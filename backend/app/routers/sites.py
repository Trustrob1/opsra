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
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

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
    SiteRecipePatch,
    generate_form_token,
    slugify_business_name,
)
# generate_form_token() is a generic (raw_token, sha256_hash) pair — reused as-is
# for editor magic links below (site_editor_tokens.token_hash is the same shape
# as site_brief_forms.token_hash, spec §18).
from app.services import site_ops_service, site_renderer

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
    "hours": [], "location": {}, "order_section": {"title": "How to order", "steps": ["Message us on WhatsApp", "Confirm your order", "We deliver"]},
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


# ── Settings ─────────────────────────────────────────────────────────────

@router.get("/sites/settings")
def get_settings(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    row = _one((db.table("site_builder_settings").select("*").eq("org_id", org["org_id"]).limit(1).execute()).data)
    return ok(data=row or {})


@router.patch("/sites/settings")
def patch_settings(payload: dict, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    updates = dict(payload or {})
    updates.pop("org_id", None)
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
    data = payload.model_dump(mode="json")
    data.update({"org_id": org["org_id"], "created_at": _now_iso(), "updated_at": _now_iso()})
    existing = (db.table("site_presets").select("id").eq("org_id", org["org_id"]).eq("key", payload.key).execute()).data
    if existing:
        raise HTTPException(409, detail={"code": "CONFLICT", "message": f"A preset with key '{payload.key}' already exists"})
    res = db.table("site_presets").insert(data).execute()
    return ok(data=_one(res.data) or data, message="Preset created")


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
    updates["updated_at"] = _now_iso()
    db.table("site_presets").update(updates).eq("id", preset_id).eq("org_id", org["org_id"]).execute()
    return ok(data=_get_preset(db, org["org_id"], preset_id), message="Preset updated")


@router.post("/sites/presets/{preset_id}/preview")
def preview_preset(preset_id: str, recipe: Recipe, org=Depends(get_current_org), db=Depends(get_supabase)):
    """Renders the preset with built-in sample data — used by the Templates tab (§13)."""
    _require(org, _READ_ROLES)
    preset = _get_preset(db, org["org_id"], preset_id)
    try:
        html = site_renderer.render_page(_SAMPLE_CONTENT, recipe.model_dump(mode="json"), preset, {})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data={"html": html})


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
    return ok(data={"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size})


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

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[file.content_type]
    storage_path = f"{site_id}/{slot}-{secrets_token()}.{ext}"
    db.storage.from_("site-assets").upload(
        path=storage_path, file=file_bytes,
        file_options={"content-type": file.content_type, "upsert": "true"},
    )
    public_url = db.storage.from_("site-assets").get_public_url(storage_path)

    row = {
        "site_id": site_id, "slot": slot, "storage_path": storage_path, "public_url": public_url,
        "mime_type": file.content_type, "bytes": len(file_bytes), "source": "editor",
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
