"""
app/routers/site_giveaways.py
-------------------------------
GIVEAWAY-1 — group giveaways with a slot counter.
  public_router (prefix /api/v1)            GET  /giveaways/{slug}        slots left, fee, renewal + edit terms
                                            POST /giveaways/{slug}/open   {name, phone, email, consent:true} -> {url} to the brief form
                                            GET  /giveaway-winner/{token}               the winner's private page
                                            POST /giveaway-winner/{token}/domain-check  {domain}
                                            POST /giveaway-winner/{token}/checkout      pay the giveaway fee (amount is server-side)
  router        (prefix /api/v1/giveaways)  staff: list / create / close / reopen / entries / void a slot
Pattern 28: org_id from get_current_org only (staff). Read owner/admin/ops_manager, write owner/ops_manager.
"""
from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import site_giveaway_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()

_READ_ROLES = ("owner", "admin", "ops_manager")
_WRITE_ROLES = ("owner", "ops_manager")
_hits: dict[str, list[float]] = defaultdict(list)


def _limited(key: str, limit: int) -> bool:
    now = time.time()
    hits = [t for t in _hits[key] if now - t < 60] + [now]
    _hits[key] = hits
    if len(_hits) > 10_000:
        _hits.clear()
    return len(hits) > limit


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require(org: dict, roles: tuple) -> None:
    if ((org.get("roles") or {}).get("template") or "") not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "You don't have access to giveaways."})


@public_router.get("/giveaways/{slug}")
def public_status(slug: str, request: Request, db=Depends(get_supabase)):
    if _limited("get:" + _ip(request), 60):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    data = svc.get_public(db, slug)
    if not data:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "This giveaway link isn't valid."})
    return ok(data=data)


@public_router.post("/giveaways/{slug}/open")
def public_open(slug: str, payload: dict, request: Request, db=Depends(get_supabase)):
    if _limited("open:" + _ip(request), 15):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    try:
        p = payload or {}
        result = svc.open_entry(db, slug, p.get("consent") is True,
                                {"name": p.get("name"), "phone": p.get("phone"), "email": p.get("email")})
    except Exception:  # S14
        logger.exception("[GIVEAWAY-1] open failed")
        raise HTTPException(503, detail={"code": "UNAVAILABLE", "message": "We couldn't open the form right now. Please try again shortly."})
    kind = result["kind"]
    if kind == "ok":
        return ok(data={"url": result["url"]})
    msgs = {
        "full": (409, "FULL", "All the free slots have been taken."),
        "closed": (410, "CLOSED", "This giveaway is closed."),
        "busy": (429, "BUSY", "This giveaway is very busy right now. Please try again later."),
        "consent_required": (422, "CONSENT_REQUIRED", "Please agree that your finished site can be shown in the group."),
        "not_found": (404, "NOT_FOUND", "This giveaway link isn't valid."),
        "duplicate": (409, "ALREADY_ENTERED", "This WhatsApp number has already won a slot in this giveaway. Each person can take one."),
        "invalid": (422, "VALIDATION_ERROR", result.get("message") or "Please check your details."),
    }
    code, c, m = msgs[kind]
    raise HTTPException(code, detail={"code": c, "message": m})


@public_router.get("/giveaways/{slug}/qr.svg")
def public_qr(slug: str, request: Request, db=Depends(get_supabase)):
    """GIVEAWAY-4: the giveaway page's QR code, for the flier. Only ever encodes this giveaway's own public link."""
    if _limited("qr:" + _ip(request), 60):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    if not svc.get_public(db, slug):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "This giveaway link isn't valid."})
    import segno
    buf = io.BytesIO()
    segno.make(svc.giveaway_url(slug), error="m").save(buf, kind="svg", scale=10, border=2, dark="#0F1733", xmldecl=False)
    return Response(content=buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


@public_router.post("/giveaways/{slug}/lost-link")
def public_lost_link(slug: str, payload: dict, request: Request, db=Depends(get_supabase)):
    """A winner asks for a new private link with their WhatsApp number. The answer is the same whether or not it matched."""
    if _limited("lost:" + _ip(request), 5):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    if not svc.request_link(db, slug, str((payload or {}).get("phone") or "")):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "This giveaway link isn't valid."})
    return ok(data={"requested": True}, message="If that number won a slot, a new link is on its way to the email and WhatsApp number used to enter.")


class GiveawayCreate(BaseModel):
    partner_id: str = Field(min_length=10, max_length=64)
    title: str = Field(min_length=3, max_length=120)
    total_slots: int = Field(default=5, ge=1, le=100)
    fee_ngn: int | None = Field(default=None, ge=1000, le=10_000_000)        # domain + hosting fee the winner pays; blank = 24,500
    renewal_ngn: int | None = Field(default=None, ge=1000, le=10_000_000)    # yearly renewal from year two; blank = 25,000
    pay_by_days: int | None = Field(default=None, ge=1, le=30)                # days to pay after the preview is ready; blank = 3
    campaign_name: str | None = Field(default=None, max_length=60)            # headline on the flier and page; blank = the title
    ends_at: datetime | None = None                                           # closing time; blank = open until full or closed


@router.get("")
def list_all(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=svc.list_giveaways(db, org["org_id"]))


@router.post("", status_code=status.HTTP_201_CREATED)
def create(payload: GiveawayCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        row = svc.create_giveaway(db, org["org_id"], payload.partner_id, payload.title, payload.total_slots,
                                  payload.fee_ngn, payload.renewal_ngn, payload.pay_by_days,
                                  payload.campaign_name, payload.ends_at)
    except svc.GiveawayError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=row, message="Giveaway created")


def _set(gid: str, new: str, org, db):
    _require(org, _WRITE_ROLES)
    row = svc.set_status(db, org["org_id"], gid, new)
    if not row:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Giveaway not found"})
    return ok(data={"id": gid, "status": new})


@router.post("/{giveaway_id}/close")
def close(giveaway_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    return _set(giveaway_id, "closed", org, db)


@router.post("/{giveaway_id}/reopen")
def reopen(giveaway_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    return _set(giveaway_id, "active", org, db)


@router.get("/{giveaway_id}/entries")
def entries(giveaway_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=svc.entries(db, org["org_id"], giveaway_id))


@router.post("/{giveaway_id}/entries/{position}/void")
def void_slot(giveaway_id: str, position: int, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        return ok(data=svc.void_slot(db, org["org_id"], giveaway_id, position), message="Slot voided")
    except svc.GiveawayError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


@router.post("/{giveaway_id}/entries/{position}/resend-link")
def resend_link(giveaway_id: str, position: int, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        return ok(data=svc.resend_link(db, org["org_id"], giveaway_id, position), message="New link sent")
    except svc.GiveawayError as exc:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


# ───────────────────────────── the winner's private page ─────────────────────────────

def _winner_call(request: Request, bucket: str, limit: int, fn, *args):
    if _limited(f"{bucket}:" + _ip(request), limit):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    try:
        return fn(*args)
    except svc.WinnerError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    except HTTPException:
        raise
    except Exception:  # S14
        logger.exception("[GIVEAWAY-1] winner call failed")
        raise HTTPException(503, detail={"code": "UNAVAILABLE", "message": "Something went wrong. Please try again shortly."})


@public_router.get("/giveaway-winner/{token}")
def winner_page(token: str, request: Request, db=Depends(get_supabase)):
    return ok(data=_winner_call(request, "wv", 60, svc.winner_view, db, token))


@public_router.post("/giveaway-winner/{token}/domain-check")
def winner_domain(token: str, payload: dict, request: Request, db=Depends(get_supabase)):
    return ok(data=_winner_call(request, "wd", 30, svc.winner_domain_check, db, token, str((payload or {}).get("domain") or "")))


@public_router.post("/giveaway-winner/{token}/catalog-checkout")
def winner_catalog(token: str, request: Request, db=Depends(get_supabase)):
    return ok(data=_winner_call(request, "wk", 10, svc.winner_catalog_checkout, db, token), message="Payment link created")


@public_router.post("/giveaway-winner/{token}/checkout")
def winner_pay(token: str, payload: dict, request: Request, db=Depends(get_supabase)):
    return ok(data=_winner_call(request, "wc", 10, svc.winner_checkout, db, token, payload or {}), message="Payment link created")
