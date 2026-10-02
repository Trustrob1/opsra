"""
app/routers/builder_portal.py
-------------------------------
SITE-2B — the builder web editor/portal API. Prefix: /api/v1/builder

Two auth shapes in one file, per spec §10:

  • POST /auth/exchange — NO auth dependency. The magic link's raw token
    (from `/b/login?t=<token>`) is the only credential, exactly like
    routers/public_forms.py's token-in-path pattern. Single-use: the
    site_editor_tokens row is marked used (revoked_at set) in the same
    request that reads it, so a captured/replayed link can't be exchanged
    twice. Issues a builder session JWT (services/builder_auth_service).

  • Every other route — `get_current_builder` below, which verifies the
    builder JWT (separate secret + aud="builder", never the staff
    get_current_user/get_current_org) and re-checks the builder is still
    `active` in site_builders on every request (so a suspended builder's
    still-valid 12h token stops working immediately, mirroring the staff
    is_active check in dependencies.py).

Pattern 28 analogue: builder_id/org_id come from the verified JWT only,
never from the request path or body — every query below is scoped to both.

Safety (spec §10): every content/recipe edit goes through the identical
Pydantic models + `site_renderer.validate_recipe` as the staff editor
(routers/sites.py) and the WhatsApp path (site_chat_service.py) — the
builder can only ever produce a value those already accept.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Request, UploadFile, status

from app.database import get_supabase
from app.models.common import ok
from app.models.sites import (
    CheckoutRequest,
    DomainCheckRequest,
    QuoteRequest,
    Recipe,
    SiteAssetCreate,
    SiteContentPatch,
    SiteRecipePatch,
    hash_form_token,
)
from app.services import (
    builder_auth_service,
    domain_check_service,
    pricing_service,
    site_care_plan_service,
    site_design_service,
    site_image_service,
    site_order_service,
    site_renewal_service,
    site_premium_service,
    site_renderer,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_ASSET_BYTES = 8 * 1024 * 1024
_MAX_ASSETS_PER_SITE = 20
_MAX_REVISIONS_PER_SITE = 20   # spec §10 — "undo the last 20 changes"

_MAGIC_BYTES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}

# In-process rate limit on the exchange route — a magic link is already
# single-use, but this blunts a brute-force guessing loop against the
# 32-byte token space. Same non-durable pattern as public_sites.py/
# public_forms.py (resets on deploy/restart — acceptable here).
_EXCHANGE_LIMIT_PER_MIN = 10
_exchange_hits: dict[str, list[float]] = defaultdict(list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _rate_limited(bucket: dict, key: str, limit: int, window_s: float) -> bool:
    now = time.time()
    hits = [t for t in bucket[key] if now - t < window_s]
    hits.append(now)
    bucket[key] = hits
    return len(hits) > limit


# ─────────────────────────────── Auth ───────────────────────────────

@router.post("/auth/exchange")
def exchange_token(payload: dict, request: Request, db=Depends(get_supabase)):
    raw_token = str((payload or {}).get("token") or "").strip()
    if not raw_token:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "token is required"})

    limit_key = request.client.host if request.client else "unknown"
    if _rate_limited(_exchange_hits, limit_key, _EXCHANGE_LIMIT_PER_MIN, 60.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many attempts — please wait a moment."})

    token_hash = hash_form_token(raw_token)   # same sha256 helper as site_brief_forms — generic by design
    row = _one((db.table("site_editor_tokens").select("*").eq("token_hash", token_hash).limit(1).execute()).data)
    if not row or row.get("revoked_at"):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "This link isn't valid — ask for a new one."})

    expires_at = row.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "This link has expired — ask for a new one."})
        except (ValueError, AttributeError):
            pass

    builder = _one((db.table("site_builders").select("*").eq("id", row["builder_id"]).eq("org_id", row["org_id"]).execute()).data)
    if not builder or builder.get("status") != "active":
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "This account isn't available right now."})

    # Single-use: revoke immediately so a captured link can't be replayed.
    db.table("site_editor_tokens").update({"revoked_at": _now_iso(), "last_used_at": _now_iso(),
                                            "updated_at": _now_iso()}).eq("id", row["id"]).execute()

    session = builder_auth_service.issue_builder_session(builder_id=builder["id"], org_id=builder["org_id"])
    return ok(data={
        "access_token": session["access_token"],
        "expires_at": session["expires_at"],
        "builder": {"id": builder["id"], "full_name": builder["full_name"],
                    "business_name": builder.get("business_name"), "email": builder.get("email")},
    }, message="Signed in")


_REQUEST_LINK_PER_IP_HOUR = 10
_REQUEST_LINK_PER_PHONE_HOUR = 3
_request_link_ip_hits: dict[str, list[float]] = defaultdict(list)
_request_link_phone_hits: dict[str, list[float]] = defaultdict(list)


@router.post("/auth/request-link")
def request_login_link(payload: dict, request: Request, background_tasks: BackgroundTasks):
    """Public landing-page sign-in. The reply is the same whether or not the number is a
    registered builder; the link goes only to the builder's own WhatsApp/email (never the browser)."""
    from app.services import builder_login_service
    variants = builder_login_service.phone_variants(str((payload or {}).get("phone") or ""))
    if not variants:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Enter the WhatsApp number you registered with."})

    ip = request.client.host if request.client else "unknown"
    if (_rate_limited(_request_link_ip_hits, ip, _REQUEST_LINK_PER_IP_HOUR, 3600.0)
            or _rate_limited(_request_link_phone_hits, variants[1], _REQUEST_LINK_PER_PHONE_HOUR, 3600.0)):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests — please try again in an hour."})

    background_tasks.add_task(builder_login_service.send_login_link, variants[1])
    return ok(data={"sent": True},
              message="If that number is registered, a sign-in link is on its way to your WhatsApp and email.")


# ─────────────────────────────── get_current_builder ───────────────────────────────

async def get_current_builder(
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Please sign in again."})
    token = authorization[7:].strip()
    claims = builder_auth_service.decode_builder_session(token)
    if not claims:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Your session has expired — please sign in again."})

    builder = _one((db.table("site_builders").select("*").eq("id", claims["builder_id"])
                     .eq("org_id", claims["org_id"]).execute()).data)
    if not builder or builder.get("status") != "active":
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "This account isn't available right now."})
    return builder


def _get_site(db, org_id: str, builder_id: str, site_id: str) -> dict:
    """Scoped to BOTH org_id and builder_id from the verified JWT — a builder
    can never reach another builder's site even inside the same org."""
    row = _one((db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).eq("builder_id", builder_id)
                .is_("deleted_at", "null").limit(1).execute()).data)
    if not row:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Site not found"})
    return row


def _get_preset(db, org_id: str, preset_id: str) -> dict:
    row = _one((db.table("site_presets").select("*").eq("id", preset_id).eq("org_id", org_id).limit(1).execute()).data)
    if not row:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Preset not found"})
    return row


def _log_event(db, org_id: str, site_id: str, builder_id: str, event: str, detail: Optional[dict] = None) -> None:
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "actor": f"builder:{builder_id}",
            "event": event, "detail": detail or {}, "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("builder_portal: site_events insert failed site=%s event=%s: %s", site_id, event, exc)


def _snapshot_for_undo(db, org_id: str, site: dict) -> None:
    """Called BEFORE a content/recipe change is applied — pushes the
    pre-change state onto the undo stack, then trims to the newest 20
    (spec §10: 'undo the last 20 changes')."""
    try:
        db.table("site_revisions").insert({
            "org_id": org_id, "site_id": site["id"],
            "content": site.get("content"), "recipe": site.get("recipe"),
            "created_at": _now_iso(),
        }).execute()
        old = (db.table("site_revisions").select("id").eq("site_id", site["id"])
               .order("created_at", desc=True).range(_MAX_REVISIONS_PER_SITE, _MAX_REVISIONS_PER_SITE + 200)
               .execute()).data or []
        for row in old:
            db.table("site_revisions").delete().eq("id", row["id"]).execute()
    except Exception as exc:
        logger.warning("builder_portal: revision snapshot failed site=%s: %s", site.get("id"), exc)


def _render_and_store(db, org_id: str, site: dict) -> dict:
    preset = _get_preset(db, org_id, site["preset_id"])
    assets_r = db.table("site_assets").select("id, public_url").eq("site_id", site["id"]).execute()
    assets_by_id = {a["id"]: {"public_url": a["public_url"]} for a in (assets_r.data or [])}
    try:
        html = site_premium_service.render_if_premium(db, site, assets_by_id)   # SITE-PREMIUM P1
        if html is None:
            html = site_renderer.render_page(site["content"], site["recipe"], preset, assets_by_id)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    updates = {"rendered_html": html, "updated_at": _now_iso()}
    db.table("sites").update(updates).eq("id", site["id"]).eq("org_id", org_id).execute()
    site.update(updates)
    return site


# ─────────────────────────────── Account ───────────────────────────────

@router.get("/me")
def get_me(builder=Depends(get_current_builder)):
    return ok(data={"id": builder["id"], "full_name": builder["full_name"],
                     "business_name": builder.get("business_name"), "email": builder.get("email"),
                     "phone_number": builder["phone_number"], "status": builder["status"]})


@router.patch("/me")
def patch_me(payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    allowed = {"full_name", "business_name", "email"}
    updates = {k: str(v).strip()[:255] for k, v in (payload or {}).items() if k in allowed and v is not None}
    if "full_name" in updates and not updates["full_name"]:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "full_name can't be empty"})
    if not updates:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "No editable fields given"})
    updates["updated_at"] = _now_iso()
    db.table("site_builders").update(updates).eq("id", builder["id"]).eq("org_id", builder["org_id"]).execute()
    row = _one((db.table("site_builders").select("*").eq("id", builder["id"]).execute()).data)
    return ok(data=row, message="Account updated")


# ─────────────────────────────── My sites ───────────────────────────────

@router.get("/sites")
def list_my_sites(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    rows = (db.table("sites")
            .select("id, client_business_name, slug, status, live_url, preview_expires_at, created_at, updated_at")
            .eq("org_id", builder["org_id"]).eq("builder_id", builder["id"])
            .is_("deleted_at", "null").order("created_at", desc=True).execute()).data or []
    domains = (db.table("site_domains").select("site_id, renews_on, hosting_renews_on, status")
               .eq("org_id", builder["org_id"]).execute()).data or []
    domains_by_site = {d["site_id"]: d for d in domains}
    today = site_renewal_service.lagos_today()
    for r in rows:
        d = domains_by_site.get(r["id"])
        r["hosting_status"] = d["status"] if d else None
        r["renews_on"] = d["renews_on"] if d else None
        r.update(site_renewal_service.builder_view(d, today))
    try:
        views = site_care_plan_service.summaries(db, builder["org_id"], [r["id"] for r in rows])
        for r in rows:
            r.update(site_care_plan_service.list_fields(views[r["id"]]))
    except Exception as exc:  # S14
        logger.warning("care plan: list summaries failed: %s", exc)
    return ok(data=rows)


@router.get("/sites/{site_id}")
def get_my_site(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    site = _get_site(db, builder["org_id"], builder["id"], site_id)
    assets = (db.table("site_assets").select("id, slot, public_url").eq("site_id", site_id).execute()).data or []
    site["assets"] = assets
    # SITE-1C-1c: only the design choices the template allows (so the visual look picker can
    # narrow itself); never the rest of the preset. Fails open: no options = everything shown.
    try:
        preset = _get_preset(db, builder["org_id"], site["preset_id"])
        site["design_options"] = {
            "allowed_themes": preset.get("allowed_themes") or [],
            "allowed_fonts": preset.get("allowed_fonts") or [],
            "token_options": preset.get("token_options") or {},
            "allowed_variants": preset.get("allowed_variants") or {},
            "sections": preset.get("sections") or [],
        }
    except Exception as exc:
        logger.warning("builder_portal: design options unavailable site=%s: %s", site_id, exc)
    return ok(data=site)


# ─────────────────────────────── Editor ───────────────────────────────

@router.patch("/sites/{site_id}/content")
def patch_my_content(site_id: str, payload: SiteContentPatch, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    try:
        site_care_plan_service.consume_edit(db, org_id, site)
    except site_care_plan_service.EditLimitReached as exc:
        raise HTTPException(402, detail={"code": "EDIT_LIMIT_REACHED", "message": str(exc), "offer": exc.offer})
    except Exception as exc:  # fail open — a bug in the allowance code must never stop a builder saving
        logger.warning("care plan: consume_edit failed site=%s: %s", site_id, exc)
    _snapshot_for_undo(db, org_id, site)
    updates = {"content": payload.content.model_dump(mode="json"), "updated_at": _now_iso(),
               "revision_count": (site.get("revision_count") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, builder["id"], "content_updated")
    return ok(data=site, message="Saved — call render to refresh the preview")


@router.patch("/sites/{site_id}/recipe")
def patch_my_recipe(site_id: str, payload: SiteRecipePatch, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    preset = _get_preset(db, org_id, site["preset_id"])
    try:
        site_renderer.validate_recipe(preset, payload.recipe.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    _snapshot_for_undo(db, org_id, site)
    updates = {"recipe": payload.recipe.model_dump(mode="json"), "updated_at": _now_iso(),
               "design_rolls": (site.get("design_rolls") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, builder["id"], "recipe_updated")
    return ok(data=site, message="Saved — call render to refresh the preview")


# ─────────────────── Suggest another design (SITE-1C-2b) ───────────────────
# Before the site goes live: DESIGN_SUGGESTION_CAP free suggestion rounds. Once live (a counting
# status), browsing suggestions is free but APPLYING one counts as an edit, exactly like a content save.

def _is_live_site(site: dict) -> bool:
    return site.get("status") in site_care_plan_service.COUNTING_SITE_STATUSES


@router.post("/sites/{site_id}/design/suggest")
def suggest_my_designs(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    preset = _get_preset(db, org_id, site["preset_id"])
    live = _is_live_site(site)
    used = site_design_service.suggestions_used(db, org_id, site_id)
    cap = site_design_service.DESIGN_SUGGESTION_CAP
    if not live and used >= cap:
        raise HTTPException(429, detail={"code": "DESIGN_SUGGEST_LIMIT",
                                          "message": f"You've used the {cap} free design suggestions for this preview. You can still change the design yourself."})
    suggestions = site_design_service.suggest_for_site(db, org_id, site, preset, used)
    _log_event(db, org_id, site_id, builder["id"], "design_suggested", {"round": used + 1, "shown": len(suggestions)})
    return ok(data={"suggestions": suggestions, "used": used + 1, "cap": None if live else cap,
                    "remaining": None if live else max(0, cap - used - 1), "counts_as_edit": live})


@router.post("/sites/{site_id}/design/apply")
def apply_my_design(site_id: str, payload: SiteRecipePatch, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    preset = _get_preset(db, org_id, site["preset_id"])
    recipe = payload.recipe.model_dump(mode="json")
    try:
        site_renderer.validate_recipe(preset, recipe)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    counted = False
    if _is_live_site(site):
        try:
            counted = bool(site_care_plan_service.consume_edit(db, org_id, site).get("counted"))
        except site_care_plan_service.EditLimitReached as exc:
            raise HTTPException(402, detail={"code": "EDIT_LIMIT_REACHED", "message": str(exc), "offer": exc.offer})
        except Exception as exc:  # fail open, same as a content save
            logger.warning("care plan: consume_edit failed (design apply) site=%s: %s", site_id, exc)
    _snapshot_for_undo(db, org_id, site)
    updates = {"recipe": recipe, "updated_at": _now_iso(), "design_rolls": (site.get("design_rolls") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, builder["id"], "design_applied", {"fingerprint": site_design_service.fingerprint(recipe), "counted_as_edit": counted})
    return ok(data=site, message="Design applied — call render to refresh the preview")


@router.post("/sites/{site_id}/render")
def render_my_site(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    site = _render_and_store(db, org_id, site)
    return ok(data=site, message="Preview rendered")


@router.post("/sites/{site_id}/undo")
def undo_my_site(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    last = _one((db.table("site_revisions").select("*").eq("site_id", site_id)
                 .order("created_at", desc=True).limit(1).execute()).data)
    if not last:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Nothing to undo"})
    updates = {"content": last["content"], "recipe": last["recipe"], "updated_at": _now_iso()}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    db.table("site_revisions").delete().eq("id", last["id"]).execute()
    site.update(updates)
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "undo")
    return ok(data=site, message="Undone")


@router.post("/sites/{site_id}/assets", status_code=status.HTTP_201_CREATED)
async def upload_my_asset(
    site_id: str,
    slot: str = Query(..., max_length=40),
    file: UploadFile = File(...),
    builder=Depends(get_current_builder), db=Depends(get_supabase),
):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    SiteAssetCreate(slot=slot)   # 422-shaped ValueError on a bad slot format

    count = len((db.table("site_assets").select("id").eq("site_id", site_id).execute()).data or [])
    if count >= _MAX_ASSETS_PER_SITE:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": f"A site can have at most {_MAX_ASSETS_PER_SITE} photos"})

    if file.content_type not in _ALLOWED_IMAGE_MIME:
        raise HTTPException(400, detail="Unsupported file type '%s'. Allowed: JPEG, PNG, WebP." % file.content_type)
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_ASSET_BYTES:
        raise HTTPException(400, detail="File exceeds the 8 MB limit.")
    if not _sniff_image(file_bytes, file.content_type):
        raise HTTPException(400, detail="File content doesn't match its declared type.")

    file_bytes, mime = site_image_service.optimise(file_bytes, file.content_type)  # SITE-1C-3d
    storage_path = f"{site_id}/{slot}-{_token_hex()}.{site_image_service.extension_for(mime)}"
    db.storage.from_("site-assets").upload(path=storage_path, file=file_bytes,
                                            file_options={"content-type": mime, "upsert": "true"})
    public_url = db.storage.from_("site-assets").get_public_url(storage_path)

    row = {
        "site_id": site_id, "slot": slot, "storage_path": storage_path, "public_url": public_url,
        "mime_type": mime, "bytes": len(file_bytes), "source": "builder_portal",
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = db.table("site_assets").insert(row).execute()
    _log_event(db, org_id, site_id, builder["id"], "asset_uploaded", detail={"slot": slot})
    return ok(data=_one(res.data) or row, message="Photo uploaded")


def _sniff_image(file_bytes: bytes, declared_mime: str) -> bool:
    sigs = _MAGIC_BYTES.get(declared_mime)
    if not sigs or not any(file_bytes.startswith(s) for s in sigs):
        return False
    if declared_mime == "image/webp" and file_bytes[8:12] != b"WEBP":
        return False
    return True


def _token_hex() -> str:
    import secrets
    return secrets.token_hex(4)


# ─────────────────────────────── Hosting checkout — domains & quotes (SITE-3) ───────────────

@router.post("/domains/check")
def check_domain(payload: DomainCheckRequest, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        result = domain_check_service.check_domain(db, builder["org_id"], builder["id"], payload.domain)
    except domain_check_service.RateLimited as exc:
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": str(exc)})
    except domain_check_service.InvalidDomain as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result)


@router.post("/quotes")
def get_quote(payload: QuoteRequest, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        result = pricing_service.quote_both_routes(db, builder["org_id"], payload.domain, payload.kind)
    except pricing_service.PricingError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    # SITE-DISCOUNT — codes apply to initial orders only; a bad code never breaks pricing.
    if payload.discount_code and payload.kind == "initial":
        from app.services import site_discount_service
        try:
            site_discount_service.apply_to_quotes(db, builder["org_id"], builder["id"], payload.discount_code, result)
        except Exception:
            logger.exception("quote: discount code check failed")
            result["discount_error"] = "We couldn't check that code. Try again."
    return ok(data=result)


@router.post("/checkout")
def checkout(payload: CheckoutRequest, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        result = site_order_service.create_checkout(db, builder["org_id"], builder, payload)
    except site_order_service.SiteNotFound as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except site_order_service.CheckoutBlocked as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except pricing_service.PricingError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result, message="Payment link created")


@router.post("/sites/{site_id}/renewal-checkout")
def renewal_checkout(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        result = site_renewal_service.builder_renewal_checkout(db, builder["org_id"], builder, site_id)
    except site_renewal_service.RenewalNotFound as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except site_renewal_service.RenewalError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    except pricing_service.PricingError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result, message="Renewal link created")


# ─────────────────────────────── Care plans & extra edits (SITE-4B) ───────────────────────────────

def _care_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except site_care_plan_service.CarePlanNotFound as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except site_care_plan_service.CarePlanError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


@router.get("/sites/{site_id}/care-plan")
def get_care_plan(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    _get_site(db, builder["org_id"], builder["id"], site_id)
    return ok(data=site_care_plan_service.site_allowance(db, builder["org_id"], site_id))


@router.post("/sites/{site_id}/care-plan/checkout")
def care_plan_checkout(site_id: str, payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    what = (payload or {}).get("what")
    result = _care_errors(site_care_plan_service.create_checkout, db, builder["org_id"], builder, site_id, what)
    result.pop("order", None)
    return ok(data=result, message="Payment link created")


@router.post("/sites/{site_id}/care-plan/cancel")
def care_plan_cancel(site_id: str, payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    cancel = bool((payload or {}).get("cancel", True))
    view = _care_errors(site_care_plan_service.set_cancel, db, builder["org_id"], builder, site_id, cancel)
    return ok(data=view, message="Cancellation saved" if cancel else "Cancellation withdrawn")

