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
    PremiumLookRequest,
    Recipe,
    SiteAssetCreate,
    SiteContentPatch,
    SiteRecipePatch,
    hash_form_token,
)
from app.services import (
    builder_auth_service,
    builder_phone_service,
    builder_signup_service,
    site_access_service,
    site_chat_service,
    domain_check_service,
    pricing_service,
    site_care_plan_service,
    site_catalog_service,
    site_design_service,
    site_image_service,
    site_order_service,
    site_renewal_service,
    site_premium_billing_service,
    site_premium_history,
    site_premium_service,
    site_import_editable_service,
    site_premium_tweaks,
    site_renderer,
)
from app.services.site_ops_service import SiteOpsError

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


def _client_ip(request: Request) -> str:
    """The caller's IP. Behind Render's proxy request.client is the proxy, so use the address the proxy appended
    to X-Forwarded-For (the LAST entry; anything earlier is whatever the caller claimed)."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    return forwarded or (request.client.host if request.client else "unknown")


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

    limit_key = _client_ip(request)
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

    ip = _client_ip(request)
    if (_rate_limited(_request_link_ip_hits, ip, _REQUEST_LINK_PER_IP_HOUR, 3600.0)
            or _rate_limited(_request_link_phone_hits, variants[1], _REQUEST_LINK_PER_PHONE_HOUR, 3600.0)):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests — please try again in an hour."})

    background_tasks.add_task(builder_login_service.send_login_link, variants[1])
    return ok(data={"sent": True},
              message="If that number is registered, a sign-in link is on its way to your WhatsApp and email.")


# ─────────────── Web sign-up (SITE-WEB-1): emailed code, then straight into the portal ───────────────

_verify_hits: dict[str, list[float]] = defaultdict(list)


@router.post("/auth/signup/start")
def signup_start(payload: dict, request: Request, background_tasks: BackgroundTasks, db=Depends(get_supabase)):
    """Public. Emails a 6-digit code. The reply is the same whether or not the number already has an account
    (an existing account is sent a normal sign-in link instead)."""
    from app.services import builder_login_service

    def _send_link(phone: str) -> None:
        background_tasks.add_task(builder_login_service.send_login_link, phone)

    try:
        data = builder_signup_service.start(db, payload, _client_ip(request), send_login_link=_send_link)
    except builder_signup_service.SignupError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=data, message="If those details are new, a code is on its way to your email.")


@router.post("/auth/signup/verify")
def signup_verify(payload: dict, request: Request, db=Depends(get_supabase)):
    """Public. A correct code creates the account and returns a single-use portal sign-in token; the page opens
    /b/login?t=<token>, which exchanges it for a session exactly like a link from WhatsApp."""
    if _rate_limited(_verify_hits, _client_ip(request), 30, 3600.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please try again in an hour."})
    payload = payload or {}
    try:
        builder = builder_signup_service.verify(db, payload.get("request_id"), payload.get("code"))
        token = builder_signup_service.mint_login_token(db, builder)
    except builder_signup_service.SignupError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data={"token": token, "builder": {"id": builder["id"], "full_name": builder["full_name"]}},
              message="Welcome to Opsra")


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

def _whatsapp_state(db, builder: dict) -> dict:
    """Has this builder ever messaged the Site Builder WhatsApp, and within the last 24 hours (Meta's reply window)?
    Never raises: the portal just hides the 'message us' prompt if this can't be worked out."""
    try:
        digits = "".join(ch for ch in (builder.get("phone_number") or "") if ch.isdigit())
        rows = (db.table("site_chats").select("last_inbound_at").eq("org_id", builder["org_id"])
                .in_("phone_number", [digits, "+" + digits]).limit(5).execute()).data or []
        times = [t for t in (builder_signup_service._parse(r.get("last_inbound_at")) for r in rows) if t]
        if not times:
            return {"ever": False, "open": False}
        return {"ever": True, "open": (datetime.now(timezone.utc) - max(times)).total_seconds() < 24 * 3600}
    except Exception:
        return {"ever": True, "open": True}


@router.get("/me")
def get_me(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    wa = _whatsapp_state(db, builder)
    return ok(data={"id": builder["id"], "full_name": builder["full_name"],
                     "business_name": builder.get("business_name"), "email": builder.get("email"),
                     "phone_number": builder["phone_number"], "status": builder["status"],
                     "account_type": builder.get("account_type") or "builder",
                     "whatsapp_ever": wa["ever"], "whatsapp_open": wa["open"]})


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


_phone_change_hits: dict[str, list[float]] = defaultdict(list)


@router.post("/me/phone/start")
def phone_change_start(payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Signed-in builder asks to move to a new WhatsApp number. A code goes to the email already on the account."""
    try:
        data = builder_phone_service.start(db, builder, (payload or {}).get("phone"))
    except builder_signup_service.SignupError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=data, message="A code is on its way to your email.")


@router.post("/me/phone/verify")
def phone_change_verify(payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    if _rate_limited(_phone_change_hits, builder["id"], 20, 3600.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please try again in an hour."})
    payload = payload or {}
    try:
        row = builder_phone_service.verify(db, builder, payload.get("request_id"), payload.get("code"))
    except builder_signup_service.SignupError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=row, message="Your WhatsApp number is updated")


# ─────────────────────────────── My sites ───────────────────────────────

# ─────────────── Access: free sites and subscription (SITE-ACCESS-1) ───────────────

@router.get("/access")
def get_access(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """How many sites the builder has used, the free cap, and whether a subscription is running."""
    return ok(data=site_access_service.view(db, builder["org_id"], builder))


@router.post("/access/checkout")
def access_checkout(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        result = site_access_service.create_checkout(db, builder["org_id"], builder)
    except site_access_service.AccessError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result, message="Payment link created")


# ─────────────── New site from the web: pick a type, get a form link (SITE-WEB-1) ───────────────

_MAX_OPEN_FORMS = 25


@router.get("/presets")
def list_my_presets(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """The business types a builder can start a site for (only what's needed to choose one)."""
    rows = (db.table("site_presets").select("id, key, name").eq("org_id", builder["org_id"])
            .eq("is_active", True).order("name").execute()).data or []
    return ok(data=rows)


@router.get("/forms")
def list_my_forms(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    rows = (db.table("site_brief_forms")
            .select("id, audience, status, client_label, preset_id, site_id, expires_at, submitted_at, created_at")
            .eq("org_id", builder["org_id"]).eq("builder_id", builder["id"])
            .order("created_at", desc=True).limit(50).execute()).data or []
    return ok(data=rows)


@router.post("/forms", status_code=status.HTTP_201_CREATED)
def create_my_form(payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Start a new site: a brief-form link the builder fills in or sends to their client. The link is shown once."""
    org_id = builder["org_id"]
    payload = payload or {}
    audience = payload.get("audience") or "builder"
    if audience not in ("builder", "client"):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "audience must be builder or client"})
    label = str(payload.get("client_label") or "").strip()[:120] or None
    preset_id = payload.get("preset_id") or None
    if preset_id:
        _get_preset(db, org_id, str(preset_id))

    try:
        site_access_service.check_can_create(db, org_id, builder)
    except site_access_service.AccessBlocked as exc:
        raise HTTPException(403, detail={"code": "ACCESS_LIMIT", "message": str(exc), "access": exc.view})

    open_forms = (db.table("site_brief_forms").select("id").eq("org_id", org_id).eq("builder_id", builder["id"])
                  .eq("status", "open").execute()).data or []
    if len(open_forms) >= _MAX_OPEN_FORMS:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR",
                                         "message": f"You have {_MAX_OPEN_FORMS} open links. Cancel the ones you no longer need first."})

    form, url = site_chat_service.create_form_link(db, org_id, builder, audience, preset_id=preset_id, client_label=label)
    return ok(data={"id": form.get("id"), "audience": audience, "url": url, "expires_at": form.get("expires_at"),
                    "client_label": label}, message="Link created. Copy it now: it is only shown once.")


@router.post("/forms/{form_id}/revoke")
def revoke_my_form(form_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    form = _one((db.table("site_brief_forms").select("id, status").eq("id", form_id).eq("org_id", org_id)
                 .eq("builder_id", builder["id"]).limit(1).execute()).data)
    if not form:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Link not found"})
    if form.get("status") != "open":
        raise HTTPException(409, detail={"code": "CONFLICT", "message": "Only open links can be cancelled"})
    db.table("site_brief_forms").update({"status": "revoked", "updated_at": _now_iso()}) \
        .eq("id", form_id).eq("org_id", org_id).execute()
    return ok(data={"id": form_id, "status": "revoked"}, message="Link cancelled")


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


# ── SITE-ADDONS A0-2: the builder sees what plans a site can have and sends the client the payment link ──

@router.get("/sites/{site_id}/addons")
def my_site_addons(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    from app.services import site_entitlement_service as ent
    from app.services import site_feature_registry as reg
    _get_site(db, builder["org_id"], builder["id"], site_id)
    cfg = ent.get_config(ent._settings(db, builder["org_id"]))

    def plan(d):
        return {"key": d["key"], "label": d["label"], "monthly_ngn": d["monthly_ngn"],
                "setup_fee_ngn": d.get("setup_fee_ngn", 0), "pick_one": d.get("pick_one", []),
                "includes": [reg.FEATURES[k]["label"] for k in d["features"] if k in reg.FEATURES]}
    data = ent.get_entitlements(db, builder["org_id"], site_id)
    data["plans"] = [plan(d) for d in cfg["tiers"].values() if d["sellable"]]
    data["addon_plans"] = [plan(d) for d in cfg["addons"].values() if d["sellable"]]
    data["billing"] = cfg["billing"]
    return ok(data=data)


@router.post("/sites/{site_id}/addons/checkout")
def my_site_addons_checkout(site_id: str, payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    from app.routers.site_addons import PurchaseRequest
    from app.services import site_addon_billing_service as billing
    from app.services import site_entitlement_service as ent
    from pydantic import ValidationError
    _get_site(db, builder["org_id"], builder["id"], site_id)
    try:
        req = PurchaseRequest(**(payload or {}))
        data = billing.start_purchase(
            db, builder["org_id"], site_id, f"builder:{builder['id']}", req.kind, req.key, picks=req.picks,
            billing_mode=req.billing_mode, payer=req.payer.model_dump() if req.payer else None)
        if req.send and not data["scheduled"]:
            data["sent"] = billing.send_link(db, builder["org_id"], site_id, data["addon_id"], f"builder:{builder['id']}")["sent"]
    except ValidationError:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Please check the plan and the client's details."})
    except ent.EntitlementError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=data)


@router.get("/sites/{site_id}")
def get_my_site(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    site = _get_site(db, builder["org_id"], builder["id"], site_id)
    assets = (db.table("site_assets").select("id, slot, public_url").eq("site_id", site_id).execute()).data or []
    site["assets"] = assets
    try:
        site["item_limit"] = site_catalog_service.offer_for(db, builder["org_id"], site)    # GIVEAWAY-2
    except Exception as exc:
        logger.warning("builder_portal: item limit unavailable site=%s: %s", site_id, exc)
    # SITE-PREMIUM P4-1: tells the editor this is a Premium design and which content it shows.
    site["premium"] = site_premium_service.editor_info(db, builder["org_id"], site)
    # SITE-IMPORT 2: an uploaded site made editable: the editor shows only the content groups the page shows.
    site["imported"] = site_import_editable_service.editor_info(db, builder["org_id"], site)
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

def _refuse_if_premium(db, org_id: str, site: dict) -> None:
    """SITE-PREMIUM P4-1: a Premium site is drawn by its own design, so the Standard design controls
    (recipe, suggested looks) would save something that changes nothing. Refuse plainly instead."""
    if site_premium_service.editor_info(db, org_id, site):
        raise HTTPException(409, detail={"code": "PREMIUM_DESIGN",
                                         "message": "This site has a Premium design, so the standard design options do not apply to it."})
    if site_import_editable_service.editor_info(db, org_id, site):
        raise HTTPException(409, detail={"code": "IMPORTED_DESIGN",
                                         "message": "This site is an uploaded page, so the standard design options do not apply to it."})


@router.patch("/sites/{site_id}/content")
def patch_my_content(site_id: str, payload: SiteContentPatch, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    new_content = payload.content.model_dump(mode="json")
    try:                                    # GIVEAWAY-2: a template holds a set number of items; more is a paid pack
        site_catalog_service.check_growth(db, org_id, site, new_content)
    except site_catalog_service.CatalogLimitReached as exc:
        raise HTTPException(402, detail={"code": "CATALOG_LIMIT", "message": str(exc), "offer": exc.offer})
    except Exception as exc:  # fail open - a lookup problem must never stop a builder saving
        logger.warning("catalog limit check failed site=%s: %s", site_id, exc)
    try:
        items_changed = site_care_plan_service.count_item_changes(site.get("content"), new_content)
        site_care_plan_service.consume_edit(db, org_id, site, items_changed=items_changed)
    except site_care_plan_service.EditLimitReached as exc:
        raise HTTPException(402, detail={"code": "EDIT_LIMIT_REACHED", "message": str(exc), "offer": exc.offer})
    except Exception as exc:  # fail open — a bug in the allowance code must never stop a builder saving
        logger.warning("care plan: consume_edit failed site=%s: %s", site_id, exc)
    _snapshot_for_undo(db, org_id, site)
    updates = {"content": new_content, "updated_at": _now_iso(),
               "revision_count": (site.get("revision_count") or 0) + 1}
    db.table("sites").update(updates).eq("id", site_id).eq("org_id", org_id).execute()
    site.update(updates)
    _log_event(db, org_id, site_id, builder["id"], "content_updated")
    return ok(data=site, message="Saved — call render to refresh the preview")


@router.patch("/sites/{site_id}/recipe")
def patch_my_recipe(site_id: str, payload: SiteRecipePatch, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    _refuse_if_premium(db, org_id, site)
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
    _refuse_if_premium(db, org_id, site)
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
    _refuse_if_premium(db, org_id, site)
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


# ─────────────── Premium look: colour and font (SITE-PREMIUM P4-2) ───────────────
# Buttons and pickers only. A look change is free before go-live and counts as 1 edit once the site is live
# (same session dedupe as a content save). Going back one step never counts.
def _premium_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SiteOpsError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _niche_of(db, org_id: str, site: dict) -> Optional[str]:
    try:
        return _get_preset(db, org_id, site["preset_id"]).get("key")
    except HTTPException:
        return None


def _assets_map(db, site_id: str) -> dict:
    rows = (db.table("site_assets").select("id, public_url").eq("site_id", site_id).execute()).data or []
    return {a["id"]: {"public_url": a["public_url"]} for a in rows}


def _layout_dict(payload) -> Optional[dict]:
    """P4-3b: the section show/hide/size changes as plain dicts ({section: {show?, size?}})."""
    if not payload.section_layout:
        return None
    return {name: change.model_dump(exclude_none=True) for name, change in payload.section_layout.items()}


def _look_payload(db, org_id: str, site: dict) -> dict:
    design = _premium_errors(site_premium_tweaks.current_design, db, org_id, site)
    return {"look": site_premium_tweaks.look_options(design, _niche_of(db, org_id, site)),
            "can_go_back": design.get("kind") == "patch" and bool(design.get("parent_id")),
            "counts_as_edit": _is_live_site(site)}


@router.get("/sites/{site_id}/premium/look")
def premium_look_options(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    return ok(data=_look_payload(db, org_id, site))


@router.post("/sites/{site_id}/premium/look/preview")
def premium_look_preview(site_id: str, payload: PremiumLookRequest, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Shows the page with the chosen look. Saves nothing and costs nothing."""
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    design = _premium_errors(site_premium_tweaks.current_design, db, org_id, site)
    plan = _premium_errors(site_premium_tweaks.plan_tweak, design, site.get("content") or {}, _assets_map(db, site_id),
                           _niche_of(db, org_id, site), payload.accent, payload.headline_font, payload.body_font,
                           payload.sections, _layout_dict(payload))
    return ok(data={"html": plan["html"], "changes": plan["changes"]})


@router.post("/sites/{site_id}/premium/look")
def premium_look_apply(site_id: str, payload: PremiumLookRequest, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    design = _premium_errors(site_premium_tweaks.current_design, db, org_id, site)
    # Validate first, so a refused look never uses up an edit.
    plan = _premium_errors(site_premium_tweaks.plan_tweak, design, site.get("content") or {}, _assets_map(db, site_id),
                           _niche_of(db, org_id, site), payload.accent, payload.headline_font, payload.body_font,
                           payload.sections, _layout_dict(payload))
    counted = False
    if _is_live_site(site):
        try:
            counted = bool(site_care_plan_service.consume_edit(db, org_id, site).get("counted"))
        except site_care_plan_service.EditLimitReached as exc:
            raise HTTPException(402, detail={"code": "EDIT_LIMIT_REACHED", "message": str(exc), "offer": exc.offer})
        except Exception as exc:  # fail open, same as a content save
            logger.warning("care plan: consume_edit failed (premium look) site=%s: %s", site_id, exc)
    saved = _premium_errors(site_premium_tweaks.apply_tweak, db, org_id, site, f"builder:{builder['id']}", design, plan)
    site["current_design_id"] = saved["id"]   # the stored row now points at the new version; keep this copy in step before rendering
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "premium_look_changed", {"changes": saved["changes"], "version": saved["version"], "counted_as_edit": counted})
    return ok(data={"site": site, "premium": site_premium_service.editor_info(db, org_id, site), **_look_payload(db, org_id, site)},
              message="Look updated")


@router.post("/sites/{site_id}/premium/look/undo")
def premium_look_undo(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _get_site(db, org_id, builder["id"], site_id)
    row = _premium_errors(site_premium_tweaks.restore_previous, db, org_id, site)
    site["current_design_id"] = row["id"]
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "premium_look_undone", {"version": row.get("version")})
    return ok(data={"site": site, "premium": site_premium_service.editor_info(db, org_id, site), **_look_payload(db, org_id, site)},
              message="Back to your previous look")


# ── SITE-PREMIUM P4-4: design history, restore and "Try another design" ──────────────────────────────

def _premium_site(db, org_id: str, builder_id: str, site_id: str) -> dict:
    """The builder's own site, which must have a Premium design (404 otherwise, like the look routes)."""
    site = _get_site(db, org_id, builder_id, site_id)
    if not site_premium_service.editor_info(db, org_id, site):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "This site does not have a Premium design."})
    return site


def _history_payload(db, org_id: str, site: dict) -> dict:
    return {"history": site_premium_history.history(db, org_id, site),
            "redesign": site_premium_history.redesign_status(db, org_id, site)}


def _site_result(db, org_id: str, site: dict) -> dict:
    """What the editor needs after the live design changes: the site, premium info, look options, history, redesign status."""
    return {"site": site, "premium": site_premium_service.editor_info(db, org_id, site),
            **_look_payload(db, org_id, site), **_history_payload(db, org_id, site)}


@router.get("/sites/{site_id}/premium/history")
def premium_history(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    return ok(data=_history_payload(db, org_id, site))


@router.get("/sites/{site_id}/premium/history/{design_id}/preview")
def premium_history_preview(site_id: str, design_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """The page for one saved version with the site's current content. Saves nothing."""
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    html = _premium_errors(site_premium_history.version_preview, db, org_id, site, design_id, _assets_map(db, site_id))
    return ok(data={"design_id": design_id, "html": html})


@router.post("/sites/{site_id}/premium/history/{design_id}/restore")
def premium_history_restore(site_id: str, design_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Go back to a saved version. Never counts as an edit; the version being replaced stays in the history."""
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    row = _premium_errors(site_premium_history.restore, db, org_id, site, design_id)
    site["current_design_id"] = row["id"]
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "premium_design_restored", {"version": row.get("version")})
    return ok(data=_site_result(db, org_id, site), message="Design restored")


# ─────────────── Buying Premium (SITE-PREMIUM P5) ───────────────

def _billing_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SiteOpsError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/sites/{site_id}/premium/offer")
def premium_offer(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """The 'Make it Premium' card for a Standard site before go-live (price, payment state, failure options)."""
    site = _get_site(db, builder["org_id"], builder["id"], site_id)
    return ok(data={"offer": site_premium_billing_service.offer(db, builder["org_id"], site), "tier": site.get("tier") or "standard"})


@router.post("/sites/{site_id}/premium/checkout")
def premium_checkout(site_id: str, payload: dict, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """what = 'design' (the design fee, before the design is made) or 'redesign' (one extra new design)."""
    what = (payload or {}).get("what")
    result = _billing_errors(site_premium_billing_service.create_checkout, db, builder["org_id"], builder, site_id, what)
    return ok(data={k: v for k, v in result.items() if k != "order"}, message="Payment link created")


@router.post("/sites/{site_id}/premium/retry", status_code=status.HTTP_202_ACCEPTED)
def premium_retry(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """A paid design that failed is tried again at no charge (up to the allowed number of failed attempts)."""
    _billing_errors(site_premium_billing_service.retry, db, builder["org_id"], builder, site_id)
    site = _get_site(db, builder["org_id"], builder["id"], site_id)
    return ok(data={"offer": site_premium_billing_service.offer(db, builder["org_id"], site)}, message="Designing your site again.")


@router.post("/sites/{site_id}/premium/refund")
def premium_refund(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """The builder asks for the design fee back when no design could be made."""
    _billing_errors(site_premium_billing_service.request_refund, db, builder["org_id"], builder, site_id)
    site = _get_site(db, builder["org_id"], builder["id"], site_id)
    return ok(data={"offer": site_premium_billing_service.offer(db, builder["org_id"], site)}, message="Your refund has been requested.")


@router.get("/sites/{site_id}/premium/redesign")
def premium_redesign_status(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    return ok(data=site_premium_history.redesign_status(db, org_id, site))


@router.post("/sites/{site_id}/premium/redesign", status_code=status.HTTP_202_ACCEPTED)
def premium_redesign_start(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Claude designs a completely new look from the same content and photos. Returns at once; a worker does the
    1 to 4 minute job into a held-back slot, and the live site is not touched until the customer keeps it."""
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    try:
        row = site_premium_history.start_redesign(db, org_id, site, f"builder:{builder['id']}")
    except site_premium_history.RedesignNotAllowed as exc:
        raise HTTPException(402, detail={"code": exc.code, "message": str(exc)})
    except site_premium_history.gen.CapReached as exc:
        raise HTTPException(429, detail={"code": exc.code, "message": str(exc)})
    except SiteOpsError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    try:
        from app.workers.site_premium_worker import run_premium_generation
        run_premium_generation.apply_async(args=[row["id"]], retry=False)
    except Exception as exc:  # S14 - the queue is down: do not leave the site blocked, and do not use up a redesign
        logger.warning("premium redesign: could not queue design=%s: %s", row["id"], exc)
        db.table("site_designs").update({"status": "failed", "checks": {"stage": "service", "outcome": "fallback_standard",
                                         "errors": ["The design could not be queued."]}}).eq("id", row["id"]).eq("org_id", org_id).execute()
        raise HTTPException(503, detail={"code": "SERVICE_UNAVAILABLE", "message": "The design service is busy. Please try again in a few minutes."})
    _log_event(db, org_id, site_id, builder["id"], "premium_redesign_started", {"design_id": row["id"], "version": row["version"]})
    return ok(data={"design_id": row["id"], "redesign": site_premium_history.redesign_status(db, org_id, site)},
              message="Designing a new look. This takes a few minutes.")


@router.get("/sites/{site_id}/premium/redesign/preview")
def premium_redesign_preview(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    html = _premium_errors(site_premium_history.redesign_preview, db, org_id, site, _assets_map(db, site_id))
    return ok(data={"html": html})


@router.post("/sites/{site_id}/premium/redesign/keep")
def premium_redesign_keep(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """Make the new design the live one. The design it replaces stays in the history, so going back is one tap."""
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    row = _premium_errors(site_premium_history.keep_redesign, db, org_id, site)
    site["current_design_id"] = row["id"]
    site = _render_and_store(db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "premium_redesign_kept", {"version": row.get("version")})
    return ok(data=_site_result(db, org_id, site), message="Your new design is live in the preview")


@router.post("/sites/{site_id}/premium/redesign/discard")
def premium_redesign_discard(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    org_id = builder["org_id"]
    site = _premium_site(db, org_id, builder["id"], site_id)
    _premium_errors(site_premium_history.discard_redesign, db, org_id, site)
    _log_event(db, org_id, site_id, builder["id"], "premium_redesign_discarded")
    return ok(data=_history_payload(db, org_id, site), message="New design discarded")


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
    # SITE-PREMIUM P5 - what is still owed of the Premium price is one extra line on the go-live total.
    if payload.site_id and payload.kind == "initial":
        try:
            site = _get_site(db, builder["org_id"], builder["id"], payload.site_id)
            line = site_premium_billing_service.go_live_balance(db, builder["org_id"], site["id"])
            if line["balance"]:
                for q in result.values():
                    if isinstance(q, dict) and isinstance(q.get("price"), dict) and not q.get("error"):
                        base = q["amount_due"] if q.get("amount_due") is not None else q["price"]["total"]
                        q["premium_balance"] = line["balance"]
                        q["premium_paid"] = line["paid"]
                        q["amount_due"] = round(float(base) + float(line["balance"]), 2)
        except HTTPException:
            raise
        except Exception:
            logger.exception("quote: premium balance failed")
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


@router.post("/sites/{site_id}/catalog/checkout")
def catalog_checkout(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    """GIVEAWAY-2: buy a pack of extra items for this site."""
    try:
        result = site_catalog_service.create_checkout(db, builder["org_id"], builder, site_id)
    except site_catalog_service.CatalogNotFound as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except site_catalog_service.CatalogError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=result, message="Payment link created")


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

