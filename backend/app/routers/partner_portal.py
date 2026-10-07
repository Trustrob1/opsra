"""
app/routers/partner_portal.py
-------------------------------
PARTNER-1B — public apply / sign-in and the signed-in partner's own data. Prefix /api/v1/partner-portal.

  POST /apply/start, /apply/verify   no login (emailed code), rate limited
  POST /auth/request-link            no login; same reply whether or not the person is a partner
  GET  /me, /referrals               partner session (the builder session JWT; the builder must be a
                                     partner whose status is active). org/builder come from the JWT only.
The sign-in link is exchanged at the existing POST /api/v1/builder/auth/exchange.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.database import get_supabase
from app.models.common import ok
from app.routers.builder_portal import get_current_builder
from app.services import site_partner_apply_service as svc
from app.services import site_partner_service

router = APIRouter()

_hits: dict[str, list[float]] = defaultdict(list)


def _limited(key: str, limit: int, window: float) -> bool:
    now = time.time()
    hits = [t for t in _hits[key] if now - t < window] + [now]
    _hits[key] = hits
    if len(_hits) > 10_000:
        _hits.clear()
    return len(hits) > limit


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/apply/start")
def apply_start(payload: dict, request: Request, background_tasks: BackgroundTasks, db=Depends(get_supabase)):
    def _send(identifier: str) -> None:
        background_tasks.add_task(svc.request_login_link, identifier)
    try:
        data = svc.start(db, payload, _ip(request), send_login_link=_send)
    except svc.ApplyError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=data, message="If those details are new, a code is on its way to your email.")


@router.post("/apply/verify")
def apply_verify(payload: dict, request: Request, db=Depends(get_supabase)):
    if _limited("verify:" + _ip(request), 30, 3600.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please try again in an hour."})
    payload = payload or {}
    try:
        svc.verify(db, payload.get("request_id"), payload.get("code"))
    except svc.ApplyError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data={"applied": True}, message="Application received")


@router.post("/auth/request-link")
def request_link(payload: dict, request: Request, background_tasks: BackgroundTasks):
    ident = str((payload or {}).get("identifier") or "").strip()
    if not ident or len(ident) > 255:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Enter your email or WhatsApp number."})
    if _limited("ip:" + _ip(request), 10, 3600.0) or _limited("id:" + ident.lower(), 3, 3600.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests — please try again in an hour."})
    background_tasks.add_task(svc.request_login_link, ident)
    return ok(data={"sent": True},
              message="If that's a registered partner, a sign-in link is on its way to the email and WhatsApp on file.")


def _partner_of(builder: dict, db) -> dict:
    rows = (db.table("site_partners").select("*").eq("org_id", builder["org_id"])
            .eq("builder_id", builder["id"]).limit(1).execute()).data
    p = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else None)
    if not p or p.get("status") != "active":
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "This isn't an active partner account."})
    return p


@router.get("/me")
def me(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    p = _partner_of(builder, db)
    return ok(data={"id": p["id"], "full_name": p["full_name"], "agency_name": p.get("agency_name"),
                    "email": p.get("email"), "partner_code": p["partner_code"],
                    "link_url": site_partner_service.partner_link_url(p["link_slug"])})


@router.get("/referrals")
def referrals(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    p = _partner_of(builder, db)
    return ok(data=svc.referrals(db, p))
