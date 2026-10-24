"""
app/routers/wa_signup.py
------------------------
WA-AUTO-5 - PUBLIC sign-up for WhatsApp-automation-only businesses, and the Superadmin switches for it.
Public (no login): GET /wa-signup/info, POST /wa-signup/start, POST /wa-signup/verify.
Superadmin: GET/PUT /superadmin/wa-signup/settings.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_supabase
from app.models.common import ok
from app.routers.superadmin_health import require_superadmin
from app.services import wa_signup_service as svc

router = APIRouter()
_verify_hits: dict = defaultdict(list)


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")) or "unknown"


def _limited(ip: str, limit: int, window: float) -> bool:
    now = time.time()
    hits = [t for t in _verify_hits[ip] if now - t < window]
    _verify_hits[ip] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def _http(exc: svc.SignupError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/wa-signup/info")
def signup_info(db=Depends(get_supabase)):
    return ok(data=svc.info(db))


@router.post("/wa-signup/start")
def signup_start(payload: dict, request: Request, db=Depends(get_supabase)):
    try:
        data = svc.start(db, payload, _ip(request))
    except svc.SignupError as exc:
        raise _http(exc)
    return ok(data=data, message="If those details are new, a code is on its way to your email.")


@router.post("/wa-signup/verify")
def signup_verify(payload: dict, request: Request, db=Depends(get_supabase)):
    if _limited(_ip(request), 30, 3600.0):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many attempts. Please try again in an hour."})
    payload = payload or {}
    try:
        data = svc.verify(db, payload.get("request_id"), payload.get("code"), payload.get("password"))
    except svc.SignupError as exc:
        raise _http(exc)
    return ok(data=data, message="Your account is ready. Sign in to set up your bot.")


@router.get("/superadmin/wa-signup/settings")
def get_signup_settings(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(data=svc.get_settings(db))


@router.put("/superadmin/wa-signup/settings")
def put_signup_settings(payload: dict, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    try:
        return ok(data=svc.save_settings(db, payload or {}))
    except svc.SignupError as exc:
        raise _http(exc)
