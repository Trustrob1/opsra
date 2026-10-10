"""
app/routers/sites.py
----------------------
SITE-1A — internal, authenticated Site Engine routes. Prefix: /api/v1/sites

Pattern 28: org_id from get_current_org only. Pattern 37: org["roles"]["template"].
Pattern 53: static routes registered before parameterised ones.
Read: owner, admin, ops_manager. Write: owner, ops_manager (same convention as
routers/funnels.py). The whole feature 404s for any org where site_builder_settings
isn't enabled — SITE-1A ships this only for Trust's own org (spec L1).

SITE-1A covers: settings, presets, builders, and by-hand site creation/edit/render/
assets so Trust can build and preview sites before the WhatsApp flow (SITE-1B) exists.
Hosting/checkout/orders (SITE-3), the builder portal (SITE-2B) and AI copy (SITE-2) are
later phases and are not in this file.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.models.sites import (
    HostingJobPatch,
    MarkLiveRequest,
    OrderDomainChoice,
    OrderRejectRequest,
    Recipe,
    RefundRecordedRequest,
    SiteAssetCreate,
    SiteBriefFormCreate,
    SiteContentPatch,
    SiteContentV1,
    SiteCreate,
    SitePresetCreate,
    SitePresetUpdate,
    PremiumImportRequest,
    PremiumUseDesign,
    SiteRecipePatch,
    generate_form_token,
    slugify_business_name,
)
# generate_form_token() is a generic (raw_token, sha256_hash) pair — reused as-is
# for editor magic links below (site_editor_tokens.token_hash is the same shape
# as site_brief_forms.token_hash, spec §18).
from app.services import site_care_plan_service, site_discount_service, site_design_registry, site_design_service, site_image_service, site_ops_service, site_publish_service, site_cloudflare_service, site_zone_service, site_renderer, site_premium_service, site_premium_generation_service, site_premium_billing_service, site_import_service, site_import_render, site_import_resolve, site_import_editable_service, site_library_service

logger = logging.getLogger(__name__)
router = APIRouter()

_READ_ROLES = ("owner", "admin", "ops_manager")
_WRITE_ROLES = ("owner", "ops_manager")

_ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_ASSET_BYTES = 8 * 1024 * 1024   # spec §18
_MAX_ASSETS_PER_SITE = 20            # spec §18

_MAGIC_BYTES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),  # WEBP also needs "WEBP" at offset 8 — checked separately
}

_SAMPLE_CONTENT = {
    "business": {"name": "Sample Business", "city": "Lagos", "tagline": "Quality you can trust",
                 "whatsapp_e164": "+2348000000000", "phone_display": "0800 000 0000",
                 "instagram": "samplebusiness", "delivery_note": "Nationwide delivery"},
    "hero": {"headline": "Welcome to Sample Business", "subhead": "This is a sample preview.", "image_asset_id": None},
    "about": {"title": "Our story", "body": ["A short sample paragraph about the business."],
              "owner": "The Founder", "pull_quote": "We put our customers first.", "image_asset_id": None},
    "items": [
        {"name": "Sample item one", "desc": "A short description.", "price_ngn": 15000, "price_style": "exact", "tag": "New"},
        {"name": "Sample item two", "desc": "Another short description.", "price_ngn": 25000, "price_style": "from"},
    ],
    "categories": [{"name": "Category A", "teaser": "Browse category A"}],
    "reviews": [{"text": "Great service, will order again!", "who": "A happy customer"}],
    "hours": [{"days": "Mon - Fri", "time": "9am - 6pm"}, {"days": "Sat", "time": "10am - 4pm"}],
    "location": {"address": "12 Sample Street, Lagos", "landmark": "Opposite the market"},
    "announcement": {"text": "Free delivery on orders above N50,000 this week"},
    "faqs": [{"q": "How long does delivery take?", "a": "Within Lagos, same or next day. Other states take 2 to 4 days."},
             {"q": "Can I pay on delivery?", "a": "Yes for Lagos. Other states are paid before dispatch."}],
    "menu": [{"name": "Popular", "lines": [{"name": "Sample service one", "desc": "A short description.", "price_ngn": 5000, "price_style": "exact"},
                                            {"name": "Sample service two", "desc": "", "price_ngn": 12000, "price_style": "from"}]},
             {"name": "Extras", "lines": [{"name": "Sample extra", "desc": "", "price_ngn": 2000, "price_style": "exact"}]}],
    "process": {"title": "How we work", "steps": [{"title": "Tell us what you need", "text": "Message us on WhatsApp."},
                                                   {"title": "We confirm the details", "text": "Price and timing, agreed upfront."},
                                                   {"title": "We deliver", "text": "On time, every time."}]},
    "team": [{"name": "Amaka Obi", "role": "Founder", "bio": "Started the business to serve customers better."},
             {"name": "Tunde Bello", "role": "Operations", "bio": "Keeps every order on schedule."}],
    "gallery": [{"caption": "Recent work"}, {"caption": "Behind the scenes"}, {"caption": "Happy customers"}],
    "banner": {"eyebrow": "Your next order", "headline": "Ready when you are.", "text": "Message us and we will help you choose.",
               "button_text": "Chat with us"},
    "order_section": {"title": "How to order", "steps": ["Message us on WhatsApp", "Confirm your order", "We deliver"]},
    "seo": {"title": "Sample Business", "description": "A sample preview page."},
}


def _role(org: dict) -> str:
    return ((org.get("roles") or {}).get("template") or "").lower()


def _require(org: dict, roles: tuple) -> None:
    if _role(org) not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "You don't have access to the site engine."})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _require_enabled(db, org_id: str) -> dict:
    """The whole feature 404s for an org that hasn't got site_builder_settings.enabled — spec §17."""
    row = _one((db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data)
    if not row or not row.get("enabled"):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Site engine is not enabled for this org."})
    return row


def _get_preset(db, org_id: str, preset_id: str) -> dict:
    row = _one((db.table("site_presets").select("*").eq("id", preset_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Preset not found"})
    return row


def _get_site(db, org_id: str, site_id: str) -> dict:
    row = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
                .limit(1).execute()).data)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Site not found"})
    return row


def _log_event(db, org_id: str, site_id: str, actor: str, event: str, detail: Optional[dict] = None, order_id: Optional[str] = None) -> None:
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "order_id": order_id,
            "actor": actor, "event": event, "detail": detail or {}, "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("site_events insert failed site=%s event=%s: %s", site_id, event, exc)


def _sniff_image(file_bytes: bytes, declared_mime: str) -> bool:
    """Magic-byte check (spec §18) — never trust the Content-Type header alone."""
    sigs = _MAGIC_BYTES.get(declared_mime)
    if not sigs:
        return False
    if not any(file_bytes.startswith(s) for s in sigs):
        return False
    if declared_mime == "image/webp" and file_bytes[8:12] != b"WEBP":
        return False
    return True


def _render_and_store(db, org_id: str, site: dict) -> dict:
    preset = _get_preset(db, org_id, site["preset_id"])
    assets_r = db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}
    try:
        html = site_premium_service.render_if_premium(db, site, assets_by_id)   # SITE-PREMIUM P1
        if html is None:
            html = site_renderer.render_page(site["content"], site["recipe"], preset, assets_by_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    updates = {
        "rendered_html": html,
        "updated_at": _now_iso(),
    }
    if site["status"] not in ("live",):
        updates["preview_expires_at"] = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    if site["status"] in ("brief_in_progress", "brief_complete", "generating"):
        updates["status"] = "preview_ready"
    db.table("sites").update(updates).eq("id", site["id"]).eq("org_id", org_id).execute()
    site.update(updates)
    return site


# ── Overview (basic — full KPIs are SITE-1A part 2 / SITE-3) ────────────────

@router.get("/sites/overview")
def sites_overview(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    org_id = org["org_id"]
    _require_enabled(db, org_id)
    sites = (db.table("sites").select("id, status").eq("org_id", org_id).is_("deleted_at", "null").execute()).data or []
    by_status: dict[str, int] = {}
    for s in sites:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    builders_count = len((db.table("site_builders").select("id").eq("org_id", org_id).execute()).data or [])
    try:  # orders / revenue / renewals / hosting jobs (spec §13 Overview) — never let these break the overview
        orders_kpis = site_ops_service.order_kpis(db, org_id, len(sites))
    except Exception:
        logger.exception("sites_overview: order KPIs failed org=%s", org_id)
        orders_kpis = None
    return ok(data={
        "orders": orders_kpis,
        "sites_total": len(sites),
        "sites_by_status": by_status,
        "previews_shared": by_status.get("preview_ready", 0) + by_status.get("revising", 0),
        "builders_total": builders_count,
    })


# ── Discount codes (SITE-DISCOUNT) ───────────────────────────────────────

def _discount_call(fn, *args):
    try:
        return fn(*args)
    except site_discount_service.DiscountError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


@router.get("/sites/discount-codes")
def list_discount_codes(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=site_discount_service.list_codes(db, org["org_id"]))


@router.post("/sites/discount-codes")
def create_discount_code(payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    row = _discount_call(site_discount_service.create_code, db, org["org_id"], payload)
    return ok(data=row, message="Code created")


@router.patch("/sites/discount-codes/{code_id}")
def update_discount_code(code_id: str, payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    row = _discount_call(site_discount_service.update_code, db, org["org_id"], code_id, payload)
    return ok(data=row, message="Code saved")


@router.delete("/sites/discount-codes/{code_id}")
def delete_discount_code(code_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _discount_call(site_discount_service.delete_code, db, org["org_id"], code_id)
    return ok(data={"id": code_id}, message="Code removed")


# ── Settings ─────────────────────────────────────────────────────────────

@router.get("/sites/settings")
def get_settings(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    row = _one((db.table("site_builder_settings").select("*").eq("org_id", org["org_id"]).limit(1).execute()).data)
    return ok(data=row or {})


# SITE-WEB-2: pricing.builder_access limits (free sites, subscription price and length, daily sign-up cap).
_ACCESS_LIMITS = {
    "free_sites": (0, 1000, "Free sites"),
    "price_ngn": (0, 10_000_000, "Subscription price"),
    "days": (1, 366, "Subscription length (days)"),
    "signup_daily_cap": (0, 100_000, "Daily sign-up limit"),
}


def _check_builder_access(pricing) -> None:
    """Rejects a nonsense builder_access block with a plain 422; fills nothing in (the reader falls back to defaults)."""
    if not isinstance(pricing, dict) or "builder_access" not in pricing:
        return
    ba = pricing["builder_access"]
    if not isinstance(ba, dict):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Builder access settings must be a set of numbers."})
    for key, (low, high, label) in _ACCESS_LIMITS.items():
        if key not in ba:
            continue
        v = ba[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not (low <= int(v) <= high):
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR",
                                             "message": f"{label} must be a whole number from {low} to {high:,}."})
        ba[key] = int(v)


def _check_site_tiers(pricing) -> None:
    """SITE-ADDONS A0-1: rejects a nonsense pricing.tiers / addons / tier_billing block with a plain 422."""
    from app.services import site_entitlement_service as _ent
    try:
        _ent.validate_pricing(pricing)
    except _ent.EntitlementError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


# SITE-TOOLS: on/off switches for the design tools. Only the owner may flip them; each must be true or false.
_DESIGN_TOOL_FLAGS = {
    "premium_enabled": "Premium designs",
    "site_import_enabled": "Import a finished site",
    "site_library_enabled": "Design library",
}


def _check_design_tools(updates: dict, org: dict) -> None:
    present = [k for k in _DESIGN_TOOL_FLAGS if k in updates]
    if not present:
        return
    if _role(org) not in _OWNER_ONLY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "Only the owner can switch design tools on or off."})
    for k in present:
        if not isinstance(updates[k], bool):
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR",
                                             "message": f"{_DESIGN_TOOL_FLAGS[k]} must be on or off."})


@router.patch("/sites/settings")
def patch_settings(payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    updates = dict(payload or {})
    updates.pop("org_id", None)
    _check_design_tools(updates, org)
    _check_builder_access(updates.get("pricing"))
    _check_site_tiers(updates.get("pricing"))
    updates["updated_at"] = _now_iso()
    existing = _one((db.table("site_builder_settings").select("org_id").eq("org_id", org["org_id"]).limit(1).execute()).data)
    if existing:
        db.table("site_builder_settings").update(updates).eq("org_id", org["org_id"]).execute()
    else:
        updates["org_id"] = org["org_id"]
        db.table("site_builder_settings").insert(updates).execute()
    row = _one((db.table("site_builder_settings").select("*").eq("org_id", org["org_id"]).limit(1).execute()).data)
    return ok(data=row, message="Settings saved")


# ── Presets ──────────────────────────────────────────────────────────────

@router.get("/sites/presets")
def list_presets(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    rows = (db.table("site_presets").select("*").eq("org_id", org["org_id"]).order("name").execute()).data or []
    return ok(data=rows)


@router.post("/sites/presets", status_code=status.HTTP_201_CREATED)
def create_preset(payload: SitePresetCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    for theme in payload.allowed_themes:
        if theme not in site_renderer.THEMES:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": f"Unknown theme: {theme}"})
    try:
        site_design_registry.validate_preset_design_fields(
            payload.allowed_fonts, payload.token_options, payload.default_palettes, payload.allowed_variants)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    data = payload.model_dump(mode="json")
    data.update({"org_id": org["org_id"], "created_at": _now_iso(), "updated_at": _now_iso()})
    existing = (db.table("site_presets").select("id").eq("org_id", org["org_id"]).eq("key", payload.key).execute()).data
    if existing:
        raise HTTPException(409, detail={"code": "CONFLICT", "message": f"A preset with key '{payload.key}' already exists"})
    res = db.table("site_presets").insert(data).execute()
    return ok(data=_one(res.data) or data, message="Preset created")


@router.get("/sites/presets/look-stats")
def preset_look_stats(org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-1C-2: recent sites per template and how many distinct looks they used (thin-pool warning in the Templates tab)."""
    _require(org, _READ_ROLES)
    try:
        return ok(data=site_design_service.look_stats(db, org["org_id"]))
    except Exception as exc:  # informational only
        logger.warning("look stats failed: %s", exc)
        return ok(data={})


@router.get("/sites/presets/{preset_id}")
def get_preset(preset_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=_get_preset(db, org["org_id"], preset_id))


@router.patch("/sites/presets/{preset_id}")
def update_preset(preset_id: str, payload: SitePresetUpdate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _get_preset(db, org["org_id"], preset_id)
    updates = payload.model_dump(exclude_unset=True, mode="json")
    if "allowed_themes" in updates:
        for theme in updates["allowed_themes"]:
            if theme not in site_renderer.THEMES:
                raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": f"Unknown theme: {theme}"})
    try:
        site_design_registry.validate_preset_design_fields(
            updates.get("allowed_fonts"), updates.get("token_options"), updates.get("default_palettes"),
            updates.get("allowed_variants"))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    updates["updated_at"] = _now_iso()
    db.table("site_presets").update(updates).eq("id", preset_id).eq("org_id", org["org_id"]).execute()
    return ok(data=_get_preset(db, org["org_id"], preset_id), message="Preset updated")


@router.post("/sites/presets/{preset_id}/preview")
def preview_preset(preset_id: str, recipe: Recipe, seed: Optional[str] = Query(None, max_length=60),
                   org=Depends(get_current_org), db=Depends(get_supabase)):
    """Renders the preset with built-in sample data — used by the Templates tab (§13).
    With ?seed=..., the look is chosen by the same seeded picker new sites use (SITE-1C-1), so
    staff can shuffle through what this preset's settings will produce; the recipe is returned."""
    _require(org, _READ_ROLES)
    preset = _get_preset(db, org["org_id"], preset_id)
    recipe_dict = site_design_service.pick_recipe(preset, seed) if seed else recipe.model_dump(mode="json")
    try:
        html = site_renderer.render_page(_SAMPLE_CONTENT, recipe_dict, preset, {})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data={"html": html, "recipe": recipe_dict})


# ── Builders ─────────────────────────────────────────────────────────────

@router.get("/sites/builders")
def list_builders(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    rows = (db.table("site_builders").select("*").eq("org_id", org["org_id"]).order("joined_at", desc=True).execute()).data or []
    return ok(data=rows)


@router.post("/sites/builders", status_code=status.HTTP_201_CREATED)
def create_builder(payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    phone = re.sub(r"[^\d+]", "", str(payload.get("phone_number") or ""))
    if not phone:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "phone_number is required"})
    full_name = (payload.get("full_name") or "").strip()
    if not full_name:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "full_name is required"})
    existing = (db.table("site_builders").select("id").eq("org_id", org_id).eq("phone_number", phone).execute()).data
    if existing:
        raise HTTPException(409, detail={"code": "CONFLICT", "message": "A builder with this phone number already exists"})

    # One CRM lead per builder (spec §5.2) — best-effort; a builder record must still be
    # created even if lead creation fails, so this never blocks builder onboarding.
    lead_id = None
    try:
        from app.services import lead_service
        from app.models.leads import LeadCreate, LeadSource
        lead = lead_service.create_lead(
            db=db, org_id=org_id, user_id=org.get("id"),
            payload=LeadCreate(full_name=full_name, phone=phone, whatsapp=phone,
                                source=LeadSource.manual_referral.value),
            entry_path="site_builder",
        )
        lead_id = lead.get("id")
    except Exception as exc:
        logger.warning("create_builder: lead creation failed for %s: %s", phone, exc)

    row = {
        "org_id": org_id, "phone_number": phone, "full_name": full_name,
        "email": payload.get("email"), "business_name": payload.get("business_name"),
        "lead_id": lead_id, "status": payload.get("status") or "active",
        "source": payload.get("source") or "manual",
        "access_paid_until": payload.get("access_paid_until"),
        "max_active_sites": payload.get("max_active_sites"),
        "approved_orders_count": 0, "joined_at": _now_iso(),
    }
    res = db.table("site_builders").insert(row).execute()
    return ok(data=_one(res.data) or row, message="Builder added")


@router.post("/sites/builders/import")
async def import_builders(file: UploadFile = File(...), org=Depends(get_current_org), db=Depends(get_supabase)):
    """CSV columns: phone_number, full_name, email (optional), business_name (optional)."""
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    created, skipped = [], []
    existing_phones = {r["phone_number"] for r in (db.table("site_builders").select("phone_number").eq("org_id", org_id).execute()).data or []}
    for row in reader:
        phone = re.sub(r"[^\d+]", "", str(row.get("phone_number") or ""))
        full_name = (row.get("full_name") or "").strip()
        if not phone or not full_name or phone in existing_phones:
            skipped.append(row)
            continue
        db.table("site_builders").insert({
            "org_id": org_id, "phone_number": phone, "full_name": full_name,
            "email": row.get("email") or None, "business_name": row.get("business_name") or None,
            "status": "active", "source": "csv_import", "approved_orders_count": 0, "joined_at": _now_iso(),
        }).execute()
        existing_phones.add(phone)
        created.append(phone)
    return ok(data={"created": len(created), "skipped": len(skipped)}, message=f"Imported {len(created)} builders")


@router.patch("/sites/builders/{builder_id}")
def update_builder(builder_id: str, payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    existing = _one((db.table("site_builders").select("id").eq("id", builder_id).eq("org_id", org_id).execute()).data)
    if not existing:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Builder not found"})
    allowed = {"status", "full_name", "email", "business_name", "max_active_sites", "access_paid_until"}
    updates = {k: v for k, v in (payload or {}).items() if k in allowed}
    if not updates:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "No editable fields given"})
    updates["updated_at"] = _now_iso()
    db.table("site_builders").update(updates).eq("id", builder_id).eq("org_id", org_id).execute()
    row = _one((db.table("site_builders").select("*").eq("id", builder_id).execute()).data)
    return ok(data=row, message="Builder updated")


# ── Sites (by-hand creation/edit for SITE-1A; the bot flow is SITE-1B) ──────

@router.get("/sites")
def list_sites(
    builder_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    _require(org, _READ_ROLES)
    org_id = org["org_id"]
    q = (db.table("sites").select("id, builder_id, preset_id, client_business_name, slug, status, live_url, created_at, updated_at")
         .eq("org_id", org_id).is_("deleted_at", "null"))
    if builder_id:
        q = q.eq("builder_id", builder_id)
    if status_filter:
        q = q.eq("status", status_filter)
    rows = q.order("created_at", desc=True).execute().data or []
    if search:  # Pattern 33 — Python-side filter
        s = search.lower().strip()
        rows = [r for r in rows if s in (r.get("client_business_name") or "").lower() or s in (r.get("slug") or "")]
    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    try:
        views = site_care_plan_service.summaries(db, org_id, [r["id"] for r in items])
        for r in items:
            r.update(site_care_plan_service.list_fields(views[r["id"]]))
    except Exception as exc:  # S14 — the list still works without the care-plan columns
        logger.warning("care plan: staff list summaries failed: %s", exc)
    return ok(data={"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("/sites", status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    _require_enabled(db, org_id)
    preset = _get_preset(db, org_id, payload.preset_id)
    try:
        site_renderer.validate_recipe(preset, payload.recipe.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})

    base_slug = slugify_business_name(payload.client_business_name)
    slug = site_renderer.generate_slug(payload.client_business_name)
    # Extremely unlikely collision guard (random 6-hex suffix) — retry once.
    if (db.table("sites").select("id").eq("slug", slug).execute()).data:
        slug = f"{base_slug}-{site_renderer.generate_slug('')}"

    row = {
        "org_id": org_id, "builder_id": payload.builder_id, "preset_id": payload.preset_id,
        "client_business_name": payload.client_business_name, "slug": slug,
        "status": "brief_complete", "content": payload.content.model_dump(mode="json"),
        "recipe": payload.recipe.model_dump(mode="json"), "content_source": payload.content_source,
        "revision_count": 0, "ai_generation_count": 0, "design_rolls": 0,
        "preview_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("sites").insert(row).execute()
    site = _one(res.data) or row
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site["id"], f"user:{org.get('id')}", "site_created")
    return ok(data=site, message="Site created")


# ── SITE-3: staff dashboard — orders, hosting queue, domains (spec §13, §17) ──
# Static paths (/sites/orders, /sites/hosting-jobs, /sites/domains) must be declared before
# /sites/{site_id} (Pattern 53). Logic lives in services/site_ops_service.py.

_OWNER_ONLY = ("owner",)   # spec §17: approve / reject / refund-recorded are "org, owner"


def _ops(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _ops_org(org, db, roles):
    _require(org, roles)
    _require_enabled(db, org["org_id"])
    return org["org_id"]


@router.get("/sites/orders")
def list_orders(
    status_filter: Optional[str] = Query(None, alias="status", max_length=30),
    search: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    org_id = _ops_org(org, db, _READ_ROLES)
    return ok(data=site_ops_service.list_orders(db, org_id, status_filter, search, page, page_size))


@router.post("/sites/orders/{order_id}/approve")
def approve_order(order_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _OWNER_ONLY)
    return ok(data=_ops(site_ops_service.approve_order, db, org_id, order_id, org["id"]), message="Order approved")


@router.post("/sites/orders/{order_id}/reject")
def reject_order(order_id: str, payload: OrderRejectRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _OWNER_ONLY)
    return ok(data=_ops(site_ops_service.reject_order, db, org_id, order_id, org["id"], payload.reason),
              message="Order rejected — a refund task was created")


@router.post("/sites/orders/{order_id}/refund-recorded")
def refund_recorded(order_id: str, payload: RefundRecordedRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _OWNER_ONLY)
    return ok(data=_ops(site_ops_service.record_refund, db, org_id, order_id, org["id"], payload.amount),
              message="Refund recorded")


@router.post("/sites/orders/{order_id}/set-domain")
def set_order_domain(order_id: str, payload: OrderDomainChoice, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.resolve_domain_choice, db, org_id, order_id, org["id"], payload.domain),
              message="Domain updated — the job is back in the queue")


@router.get("/sites/hosting-jobs")
def list_hosting_jobs(
    mine: bool = Query(False),
    include_done: bool = Query(False),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    org_id = _ops_org(org, db, _READ_ROLES)
    return ok(data=site_ops_service.list_hosting_jobs(db, org_id, assigned_to=org["id"] if mine else None,
                                                      include_done=include_done))


@router.patch("/sites/hosting-jobs/{job_id}")
def patch_hosting_job(job_id: str, payload: HostingJobPatch, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.patch_hosting_job, db, org_id, job_id, org["id"],
                        payload.model_dump(exclude_unset=True)))


@router.post("/sites/hosting-jobs/{job_id}/recheck-domain")
def recheck_job_domain(job_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.recheck_domain, db, org_id, job_id, org["id"]))


@router.post("/sites/hosting-jobs/{job_id}/use-backup")
def use_job_backup_domain(job_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.use_backup_domain, db, org_id, job_id, org["id"]))


@router.post("/sites/hosting-jobs/{job_id}/mark-live")
def mark_job_live(job_id: str, payload: MarkLiveRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.mark_live, db, org_id, job_id, org["id"], payload.live_url),
              message="Marked live — the builder has been told")


@router.post("/sites/hosting-jobs/{job_id}/mark-renewed")
def mark_job_renewed(job_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.mark_renewed, db, org_id, job_id, org["id"]),
              message="Marked renewed — the builder has been told")


@router.post("/sites/domains/{domain_id}/renewal-link")
def send_domain_renewal_link(domain_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    return ok(data=_ops(site_ops_service.send_renewal_link, db, org_id, domain_id, org["id"]))


@router.post("/sites/{site_id}/care-link")
def send_care_link(site_id: str, payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _ops_org(org, db, _WRITE_ROLES)
    try:
        result = site_care_plan_service.send_care_link(db, org_id, site_id, (payload or {}).get("what"))
    except site_care_plan_service.CarePlanNotFound as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except site_care_plan_service.CarePlanError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result, message="Link sent to the builder" if result["sent"] else "Link created — WhatsApp could not deliver it, copy it below")


@router.get("/sites/domains")
def list_site_domains(
    expiring_within: Optional[int] = Query(None, ge=0, le=365),
    status_filter: Optional[str] = Query(None, alias="status", max_length=20),
    search: Optional[str] = Query(None, max_length=100),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    org_id = _ops_org(org, db, _READ_ROLES)
    return ok(data=site_ops_service.list_domains(db, org_id, expiring_within, status_filter, search))


@router.patch("/sites/{site_id}/content")
def patch_content(site_id: str, payload: SiteContentPatch, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    site = _get_site(db, org_id, site_id)
    updates = {"content": payload.content.model_dump(mode="json"), "updated_at": _now_iso(),
               "revision_count": (site.get("revision_count") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "content_updated")
    return ok(data=site, message="Content updated — call render to refresh the preview")


@router.patch("/sites/{site_id}/recipe")
def patch_recipe(site_id: str, payload: SiteRecipePatch, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    site = _get_site(db, org_id, site_id)
    preset = _get_preset(db, org_id, site["preset_id"])
    try:
        site_renderer.validate_recipe(preset, payload.recipe.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    updates = {"recipe": payload.recipe.model_dump(mode="json"), "updated_at": _now_iso(),
               "design_rolls": (site.get("design_rolls") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "recipe_updated")
    return ok(data=site, message="Design updated — call render to refresh the preview")


@router.post("/sites/{site_id}/design/suggest")
def suggest_designs(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-1C-2b: a fresh set of looks for this site (staff: uncapped, applying is the normal free Save design)."""
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    site = _get_site(db, org_id, site_id)
    preset = _get_preset(db, org_id, site["preset_id"])
    used = site_design_service.suggestions_used(db, org_id, site_id)
    suggestions = site_design_service.suggest_for_site(db, org_id, site, preset, used)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "design_suggested", {"round": used + 1, "shown": len(suggestions)})
    return ok(data={"suggestions": suggestions, "used": used + 1, "cap": None, "remaining": None, "counts_as_edit": False})


# ── SITE-PREMIUM P1: bespoke Premium designs (staff import, list, undo, back to Standard) ──────────────

def _premium_org(org, db, roles):
    """Role check + the site engine switch + the Premium switch (off except for the test org)."""
    _require(org, roles)
    org_id = org["org_id"]
    settings = _require_enabled(db, org_id)
    try:
        site_premium_service.require_enabled(settings)
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return org_id


@router.get("/sites/{site_id}/premium/designs")
def premium_designs(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _premium_org(org, db, _READ_ROLES)
    site = _get_site(db, org_id, site_id)
    return ok(data={"tier": site.get("tier") or "standard", "current_design_id": site.get("current_design_id"),
                    "designs": site_premium_service.list_designs(db, org_id, site_id),
                    "charge_at_golive": bool(site.get("premium_charge_at_golive")),
                    "fee_paid": site_premium_billing_service.design_fee_paid(db, org_id, site_id),
                    "golive_balance": site_premium_billing_service.go_live_balance(db, org_id, site_id)["balance"],
                    "total_fee": site_premium_billing_service.get_config(site_premium_generation_service.settings_for(db, org_id))["total_fee_ngn"]})


@router.post("/sites/{site_id}/premium/charge-at-golive")
def premium_charge_at_golive(site_id: str, payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Staff: charge the whole Premium price at go-live for a Premium site made before payment existed."""
    org_id = _premium_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    enabled = bool((payload or {}).get("enabled"))
    try:
        data = site_premium_billing_service.set_charge_at_golive(db, org_id, site, enabled, f"user:{org.get('id')}")
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=data, message="Premium will be charged at go-live." if enabled else "Premium will not be charged at go-live.")


@router.get("/sites/{site_id}/premium/designs/{design_id}/preview")
def premium_design_preview(site_id: str, design_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-PREMIUM P2b: the rendered page for one finished design version (nothing is changed or made live)."""
    org_id = _premium_org(org, db, _READ_ROLES)
    site = _get_site(db, org_id, site_id)
    assets_r = db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}
    html = _ops(site_premium_service.preview_design, db, org_id, site, design_id, assets_by_id)
    return ok(data={"design_id": design_id, "html": html})


@router.post("/sites/{site_id}/premium/generate", status_code=status.HTTP_202_ACCEPTED)
def premium_generate(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-PREMIUM P2: Claude designs this site. Returns at once; a worker does the 1 to 4 minute job.
    Poll GET /premium/designs: the new version's status goes generating -> checking -> ready (or failed, and the
    site keeps its Standard design). Guards: Premium on, content present, one in flight per site, per-builder and
    org daily caps."""
    org_id = _premium_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    actor = f"user:{org.get('id')}"
    try:
        row = site_premium_generation_service.start_generation(db, org_id, site, actor)
    except site_premium_generation_service.CapReached as exc:
        if "paused" in str(exc):
            site_premium_generation_service.alert_cost_cap(db, org_id, site_id)
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    try:
        from app.workers.site_premium_worker import run_premium_generation
        run_premium_generation.apply_async(args=[row["id"]], retry=False)
    except Exception as exc:  # S14 - the queue is down: do not leave the site blocked
        logger.warning("premium generate: could not queue design=%s: %s", row["id"], exc)
        db.table("site_designs").update({"status": "failed", "checks": {"outcome": "fallback_standard", "errors": ["The design could not be queued."]}}) \
            .eq("id", row["id"]).eq("org_id", org_id).execute()
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": "The design service is busy. Please try again in a few minutes."})
    _log_event(db, org_id, site_id, actor, "premium_generation_started", {"design_id": row["id"], "version": row["version"]})
    return ok(data={"design_id": row["id"], "version": row["version"], "status": "generating"},
              message="Designing your Premium site. This takes a few minutes.")


@router.post("/sites/{site_id}/premium/import", status_code=status.HTTP_201_CREATED)
def premium_import(site_id: str, payload: PremiumImportRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _premium_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    assets_r = db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}
    result = _ops(site_premium_service.import_skeleton, db, org_id, site, f"user:{org.get('id')}", payload.html,
                  payload.headline_font, payload.body_font, assets_by_id)
    site["tier"], site["current_design_id"] = "premium", result["id"]
    _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "premium_design_imported",
               {"design_id": result["id"], "version": result["version"], "removed": len(result["removed"])})
    return ok(data={"design_id": result["id"], "version": result["version"], "removed": result["removed"]},
              message="Premium design saved - open the preview to review it")


@router.post("/sites/{site_id}/premium/use-design")
def premium_use_design(site_id: str, payload: PremiumUseDesign, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _premium_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    row = _ops(site_premium_service.use_design, db, org_id, site, payload.design_id)
    site["tier"], site["current_design_id"] = "premium", row["id"]
    _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "premium_design_selected",
               {"design_id": row["id"], "version": row["version"]})
    return ok(data={"design_id": row["id"], "version": row["version"]}, message="Design version restored")


@router.post("/sites/{site_id}/premium/standard")
def premium_force_standard(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _premium_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    site_premium_service.force_standard(db, org_id, site)
    site["tier"] = "standard"
    _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "premium_switched_to_standard")
    return ok(data={"tier": "standard"}, message="Site is back on the Standard design")


# ── SITE-IMPORT 1a: upload a finished single-page site made outside Opsra (staff only) ──────────────

def _import_org(org, db, roles):
    """Role check + the site engine switch + the import switch (off except where staff turn it on)."""
    _require(org, roles)
    org_id = org["org_id"]
    settings = _require_enabled(db, org_id)
    if not settings.get("site_import_enabled"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Site import is not switched on for this account yet."})
    return org_id, settings


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """Reads an upload in chunks and stops as soon as it is over the limit (never holds more than limit + 1 chunk)."""
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail={"code": "VALIDATION_ERROR",
                                "message": f"The upload is over the {limit // (1024 * 1024)} MB limit."})
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/sites/{site_id}/import")
async def import_site_upload(
    site_id: str,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    accepted: str = Form(""),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    """A .zip (or one .html file). dry_run=true analyses and saves nothing. `accepted` is optional JSON,
    e.g. {"js/vendor.js": ["eval"]}: staff accept a named overridable finding for that file."""
    org_id, settings = _import_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    cfg = site_import_service.settings_for(settings)
    try:
        accepted_map = json.loads(accepted) if accepted.strip() else {}
        if not isinstance(accepted_map, dict) or not all(isinstance(k, str) and isinstance(v, list) for k, v in accepted_map.items()):
            raise ValueError("shape")
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR",
                            "message": "accepted must be JSON like {\"js/app.js\": [\"eval\"]}."})
    data = await _read_capped(file, cfg["max_mb"] * 1024 * 1024)
    actor = f"user:{org.get('id')}"
    try:
        result = site_import_service.import_site(db, org_id, site, actor, data, file.filename or "", settings,
                                                 accepted=accepted_map, dry_run=dry_run)
    except site_import_service.ImportRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc),
                            "errors": exc.errors, "report": exc.report})
    except site_import_service.ImportFailed as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    if result["saved"]:
        report = result["report"]
        _log_event(db, org_id, site_id, actor, "site_imported",
                   {"design_id": result["design_id"], "version": result["version"], "files": result["files"],
                    "warnings": len(report["warnings"]), "accepted": report["accepted"],
                    "scripts": len(report["scripts"]) + report["page"].get("inline_scripts", 0)})
        return ok(data=result, message="Import saved. It is not live yet: open the report to review it.")
    return ok(data=result, message="Checked only: nothing was saved.")


@router.get("/sites/{site_id}/import/report")
def import_report(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id, _settings = _import_org(org, db, _READ_ROLES)
    _get_site(db, org_id, site_id)
    latest = site_import_service.latest_report(db, org_id, site_id)
    if not latest:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This site has no imported design yet."})
    return ok(data=latest)


class ImportDesignRef(BaseModel):
    design_id: str = Field(min_length=1, max_length=64)
    adopt_content: bool = False        # SITE-IMPORT 2: make the page's own text the site's content when activating a Level 2 design


def _import_render_call(fn, *args):
    try:
        return fn(*args)
    except (site_import_render.ImportRenderError, site_import_service.ImportRejected) as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except site_import_service.ImportFailed as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/sites/{site_id}/import/designs")
def import_designs(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id, _settings = _import_org(org, db, _READ_ROLES)
    site = _get_site(db, org_id, site_id)
    return ok(data={"tier": site.get("tier"), "current_design_id": site.get("current_design_id"),
                    "designs": site_import_render.designs(db, org_id, site)})


@router.get("/sites/{site_id}/import/designs/{design_id}/preview")
def import_design_preview(site_id: str, design_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """The page of one imported design, ready to show in a sandboxed iframe (scripts on, no access to the dashboard)."""
    org_id, _settings = _import_org(org, db, _READ_ROLES)
    site = _get_site(db, org_id, site_id)
    assets_r = db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}
    html = _import_render_call(site_import_render.preview_design, db, org_id, site, design_id, assets_by_id)
    return ok(data={"html": html})


@router.post("/sites/{site_id}/import/resolve")
def import_resolve(payload: ImportDesignRef, site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Copy the pictures / stylesheets / fonts the page loads from unlisted websites into the site's own files."""
    org_id, settings = _import_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    cfg = site_import_service.settings_for(settings)
    marked = (db.table("site_designs").select("id, editable").eq("id", payload.design_id).eq("site_id", site_id)
              .eq("org_id", org_id).limit(1).execute()).data
    if marked and marked[0].get("editable"):
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message":
                            "This design is already editable, and copying files would change its page. Copy the files first, then make it editable "
                            "(upload the site again if needed)."})
    result = _import_render_call(site_import_resolve.resolve, db, org_id, site, payload.design_id, cfg["allowed_hosts"])
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "site_import_resolved",
               {"design_id": payload.design_id, "resolved": len(result["resolved"]), "failed": len(result["failed"])})
    return ok(data=result, message=f"{len(result['resolved'])} file(s) copied")


@router.post("/sites/{site_id}/import/activate")
def import_activate(payload: ImportDesignRef, site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Make an imported design the site's page (preview). Publishing to the domain stays a separate step."""
    org_id, _settings = _import_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    actor = f"user:{org.get('id')}"
    row = _import_render_call(site_import_render.activate, db, org_id, site, payload.design_id, payload.adopt_content, actor)
    site["tier"], site["current_design_id"] = "imported", row["id"]
    _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, actor, "site_import_activated", {"design_id": row["id"], "adopt_content": bool(payload.adopt_content)})
    return ok(data={"design_id": row["id"], "tier": "imported", "editable": bool(row.get("editable"))},
              message="The imported design is now the site's page")


@router.post("/sites/{site_id}/import/make-editable", status_code=status.HTTP_202_ACCEPTED)
def import_make_editable(payload: ImportDesignRef, site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-IMPORT 2: Claude maps the uploaded page onto the editor's content fields (a plan, never page code). Returns at once;
    a worker does the 1 to 3 minute job. Poll GET /import/designs: level2.status goes running -> working -> ready (or failed,
    and the design stays a plain Level 1 import)."""
    org_id, _settings = _import_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    actor = f"user:{org.get('id')}"
    try:
        started = site_import_editable_service.start(db, org_id, site, actor, payload.design_id)
    except site_premium_generation_service.CapReached as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
    try:
        from app.workers.site_import_worker import run_make_editable
        run_make_editable.apply_async(args=[started["design_id"]], retry=False)
    except Exception as exc:  # S14 - the queue is down: do not leave the design 'running'
        logger.warning("import make-editable: could not queue design=%s: %s", started["design_id"], exc)
        row = (db.table("site_designs").select("*").eq("id", started["design_id"]).eq("org_id", org_id).limit(1).execute()).data
        if row:
            site_import_editable_service._write_meta(db, row[0], status="failed", errors=["The job could not be queued."], finished_at=site_import_editable_service._now_iso())
        raise HTTPException(status_code=503, detail={"code": "SERVICE_UNAVAILABLE", "message": "The service is busy. Please try again in a few minutes."})
    _log_event(db, org_id, site_id, actor, "import_editable_started", {"design_id": started["design_id"]})
    return ok(data={"design_id": started["design_id"], "status": "running"}, message="Making the page editable. This takes a few minutes.")


# ── SITE-IMPORT 3: library designs (staff only; switched on per account by site_builder_settings.site_library_enabled) ──────────

def _library_org(org, db, roles):
    _require(org, roles)
    org_id = org["org_id"]
    settings = _require_enabled(db, org_id)
    if not settings.get("site_library_enabled"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "The design library is not switched on for this account yet."})
    return org_id


def _library_call(fn, *args):
    try:
        return fn(*args)
    except site_ops_service.SiteOpsError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


class LibrarySaveRequest(BaseModel):
    site_id: str = Field(min_length=1, max_length=64)
    design_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    niche: str = Field(min_length=1, max_length=80)
    note: str = Field("", max_length=300)


class LibraryAttachRequest(BaseModel):
    library_id: Optional[str] = Field(None, max_length=64)    # omitted: the rotation picks one


@router.get("/site-library")
def library_list(niche: Optional[str] = Query(None, max_length=80), org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _library_org(org, db, _READ_ROLES)
    return ok(data=site_library_service.list_designs(db, org_id, niche))


@router.post("/site-library/save", status_code=status.HTTP_201_CREATED)
def library_save(payload: LibrarySaveRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Copy a site's design (an editable import or a ready Premium design) into the library after the fit checks."""
    org_id = _library_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, payload.site_id)
    actor = f"user:{org.get('id')}"
    result = _library_call(site_library_service.save, db, org_id, site, payload.design_id, actor, payload.name, payload.niche, payload.note)
    _log_event(db, org_id, payload.site_id, actor, "library_design_saved", {"library_id": result["id"], "niche": payload.niche, "kind": result["source_kind"]})
    return ok(data=result, message="Saved to the library")


@router.get("/site-library/{library_id}/preview")
def library_preview(library_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _library_org(org, db, _READ_ROLES)
    return ok(data={"library_id": library_id, "html": _library_call(site_library_service.preview, db, org_id, library_id)})


@router.get("/site-library/{library_id}")
def library_detail(library_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _library_org(org, db, _READ_ROLES)
    row = _library_call(site_library_service.get, db, org_id, library_id)
    return ok(data={k: row.get(k) for k in ("id", "name", "niche", "note", "source_kind", "status", "uses_count", "has_scripts", "fit", "created_at")})


@router.post("/site-library/{library_id}/retire")
def library_retire(library_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _library_org(org, db, _WRITE_ROLES)
    return ok(data=_library_call(site_library_service.set_status, db, org_id, library_id, "retired"), message="Retired. Sites already using it are not changed.")


@router.post("/site-library/{library_id}/restore")
def library_restore(library_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    org_id = _library_org(org, db, _WRITE_ROLES)
    return ok(data=_library_call(site_library_service.set_status, db, org_id, library_id, "active"), message="Restored")


@router.post("/sites/{site_id}/library/attach")
def library_attach(payload: LibraryAttachRequest, site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Give this site a copy of a library design (the named one, or the next one in the rotation). The site's own content fills it."""
    org_id = _library_org(org, db, _WRITE_ROLES)
    site = _get_site(db, org_id, site_id)
    actor = f"user:{org.get('id')}"
    if payload.library_id:
        result = _library_call(site_library_service.attach, db, org_id, site, payload.library_id, actor)
    else:
        result = _library_call(site_library_service.attach_best, db, org_id, site, actor)
    _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, actor, "library_design_attached", {"library_id": result["library_id"], "design_id": result["design_id"]})
    return ok(data=result, message="The design is now this site's page")


@router.post("/sites/{site_id}/render")
def render_site(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    site = _get_site(db, org_id, site_id)
    site = _render_and_store(db, org_id, site)
    return ok(data=site, message="Preview rendered")


@router.post("/sites/{site_id}/assets", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    site_id: str,
    slot: str = Query(..., max_length=40),
    file: UploadFile = File(...),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    site = _get_site(db, org_id, site_id)
    SiteAssetCreate(slot=slot)  # raises 422-shaped ValueError via Pydantic if the slot format is bad

    count = len((db.table("site_assets").select("id").eq("site_id", site_id).execute()).data or [])
    if count >= _MAX_ASSETS_PER_SITE:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": f"A site can have at most {_MAX_ASSETS_PER_SITE} photos"})

    if file.content_type not in _ALLOWED_IMAGE_MIME:
        raise HTTPException(400, detail=f"Unsupported file type '{file.content_type}'. Allowed: JPEG, PNG, WebP.")
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_ASSET_BYTES:
        raise HTTPException(400, detail="File exceeds the 8 MB limit.")
    if not _sniff_image(file_bytes, file.content_type):
        raise HTTPException(400, detail="File content doesn't match its declared type.")

    file_bytes, mime = site_image_service.optimise(file_bytes, file.content_type)  # SITE-1C-3d: web-sized, EXIF stripped
    storage_path = f"{site_id}/{slot}-{secrets_token()}.{site_image_service.extension_for(mime)}"
    db.storage.from_("site-assets").upload(
        path=storage_path, file=file_bytes,
        file_options={"content-type": mime, "upsert": "true"},
    )
    public_url = db.storage.from_("site-assets").get_public_url(storage_path)

    row = {
        "site_id": site_id, "slot": slot, "storage_path": storage_path, "public_url": public_url,
        "mime_type": mime, "bytes": len(file_bytes), "source": "editor",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("site_assets").insert(row).execute()
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "asset_uploaded", detail={"slot": slot})
    return ok(data=_one(res.data) or row, message="Photo uploaded")


def secrets_token() -> str:
    import secrets
    return secrets.token_hex(4)


# ── Brief forms (internal by-hand creation — SITE-1B) ────────────────────
# The WhatsApp-driven creation (builder replies FORM / NEW → option 1 or 2)
# lives in services/site_chat_service.py and inserts the same row shape
# directly; these routes are for Trust creating a link by hand ahead of a
# closed deal, or re-listing/cancelling links from the (future) portal.

import os as _os


def _form_public_url(raw_token: str) -> str:
    frontend_base = _os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{frontend_base}/f/{raw_token}"


@router.get("/sites/forms")
def list_forms(
    builder_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    org=Depends(get_current_org), db=Depends(get_supabase),
):
    _require(org, _READ_ROLES)
    org_id = org["org_id"]
    q = (db.table("site_brief_forms")
         .select("id, builder_id, site_id, audience, preset_id, status, expires_at, opened_at, last_saved_at, submitted_at, submit_count, client_label, created_at")
         .eq("org_id", org_id))
    if builder_id:
        q = q.eq("builder_id", builder_id)
    if status_filter:
        q = q.eq("status", status_filter)
    rows = q.order("created_at", desc=True).execute().data or []
    return ok(data=rows)


@router.post("/sites/forms", status_code=status.HTTP_201_CREATED)
def create_form(payload: SiteBriefFormCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    builder = _one((db.table("site_builders").select("id, phone_number").eq("id", payload.builder_id).eq("org_id", org_id).execute()).data)
    if not builder:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Builder not found"})
    if payload.preset_id:
        _get_preset(db, org_id, payload.preset_id)

    raw_token, token_hash = generate_form_token()
    row = {
        "org_id": org_id, "builder_id": payload.builder_id, "audience": payload.audience,
        "token_hash": token_hash, "preset_id": payload.preset_id, "answers": {},
        "status": "open", "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        "client_label": payload.client_label, "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("site_brief_forms").insert(row).execute()
    form = _one(res.data) or row
    return ok(data={**form, "url": _form_public_url(raw_token)}, message="Form link created — this is the only time the link is shown in full.")


@router.post("/sites/forms/{form_id}/revoke")
def revoke_form(form_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    existing = _one((db.table("site_brief_forms").select("id").eq("id", form_id).eq("org_id", org_id).execute()).data)
    if not existing:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Form not found"})
    db.table("site_brief_forms").update({"status": "revoked", "updated_at": _now_iso()}).eq("id", form_id).eq("org_id", org_id).execute()
    return ok(data={"id": form_id, "status": "revoked"}, message="Link cancelled")


# ── Builder editor magic links (SITE-2B) ───────────────────────────────
# Internal, by-hand link creation — mirrors the "Get form link" pattern above.
# Normally the builder gets this by replying EDIT on WhatsApp (see
# site_chat_service.py), but D4 (the site_builder WhatsApp number) isn't
# supplied yet, so this button is today's only way to mint one for testing.


def _editor_public_url(raw_token: str) -> str:
    frontend_base = _os.environ.get("FRONTEND_URL", "https://opsra-frontend.onrender.com").rstrip("/")
    return f"{frontend_base}/b/login?t={raw_token}"


@router.post("/sites/builders/{builder_id}/edit-link", status_code=status.HTTP_201_CREATED)
def create_edit_link(builder_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    org_id = org["org_id"]
    builder = _one((db.table("site_builders").select("id, full_name, status").eq("id", builder_id).eq("org_id", org_id).execute()).data)
    if not builder:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Builder not found"})
    if builder.get("status") != "active":
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "This builder isn't active"})

    raw_token, token_hash = generate_form_token()   # spec §10: 7-day, single-use, hashed — never stored raw
    row = {
        "org_id": org_id, "builder_id": builder_id, "token_hash": token_hash,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    db.table("site_editor_tokens").insert(row).execute()
    return ok(data={"url": _editor_public_url(raw_token), "expires_at": row["expires_at"]},
               message="Edit link created — this is the only time the link is shown in full.")


@router.get("/sites/{site_id}")
def get_site(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=_get_site(db, org["org_id"], site_id))


@router.get("/sites/{site_id}/export.zip")
def export_site_zip(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """spec §8.6 — internal only; built in memory, never stored."""
    org_id = _ops_org(org, db, _READ_ROLES)
    data, filename = _ops(site_ops_service.build_export_zip, db, org_id, site_id)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "export_downloaded")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class PublishRequest(BaseModel):
    """Optional body for publish. dns_mode picks the flow for the domain: 'cloudflare_zone' (we manage its
    DNS on Cloudflare — for domains we bought) or 'client_cname' (the client adds a CNAME). Omitted = auto."""
    dns_mode: Optional[Literal["cloudflare_zone", "client_cname"]] = None


@router.post("/sites/{site_id}/publish")
def publish_site(site_id: str, body: Optional[PublishRequest] = None, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-PUBLISH — uploads the site's files to Cloudflare R2 under the client's domain; the
    `opsra-sites` Worker serves them. Safe to repeat (replaces the live copy)."""
    org_id = _ops_org(org, db, _WRITE_ROLES)
    result = _ops(site_publish_service.publish_site, db, org_id, site_id)
    # SITE-AUTOTICK — tick the "Click Publish to Cloudflare" step on this site's open hosting job.
    result["hosting_step_ticked"] = site_ops_service.tick_publish_step(db, org_id, site_id)
    # Connect the domain to the Worker. A problem here never undoes the publish: the files are already up.
    result["hostnames"], result["hostnames_error"] = None, None
    try:
        mode = site_zone_service.resolve_mode(db, org_id, result["domain"], body.dns_mode if body else None)
        if mode == site_zone_service.MODE_ZONE:
            result["hostnames"] = site_zone_service.connect_domain(result["domain"])
            site_zone_service.save_state(db, org_id, result["domain"], result["hostnames"])
        else:
            result["hostnames"] = site_cloudflare_service.register_domain(result["domain"])
            result["hostnames"]["mode"] = site_zone_service.MODE_CNAME
            # SITE-FAILOVER — also register it in the backup Cloudflare account. Never blocks the publish.
            try:
                site_cloudflare_service.register_standby(result["domain"])
                result["standby_registered"] = True
            except site_cloudflare_service.HostnamesNotConfigured:
                pass
            except Exception as exc:  # S14
                result["standby_registered"] = False
                logger.warning("[sites] standby registration failed for %s: %s", result["domain"], exc)
    except site_cloudflare_service.HostnamesNotConfigured:
        pass
    except site_ops_service.SiteOpsError as exc:
        result["hostnames_error"] = str(exc)
    _log_event(db, org_id, site_id, f"user:{org.get('id')}", "published_to_cloudflare",
               {k: result[k] for k in ("domain", "files", "bytes", "removed")})
    return ok(data=result)


@router.get("/sites/{site_id}/hostnames")
def site_hostnames(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    """SITE-HOSTNAMES — DNS records the client must add, and whether Cloudflare has connected the domain."""
    org_id = _ops_org(org, db, _READ_ROLES)

    def _status():
        domain = site_publish_service.site_domain(db, org_id, site_id)
        if site_zone_service.resolve_mode(db, org_id, domain) == site_zone_service.MODE_ZONE:
            info = site_zone_service.connect_domain(domain, create=False)
            site_zone_service.save_state(db, org_id, domain, info)
            return info
        info = site_cloudflare_service.status_domain(domain)
        info["mode"] = site_zone_service.MODE_CNAME
        return info

    return ok(data=_ops(_status))
