"""
routers/public_host.py
HOST-2 - public, no sign-in: the checks a visitor makes on /host before creating an account.

  GET /api/v1/public/host/pricing                  price table per domain ending + what hosting includes
  GET /api/v1/public/host/domain-check?domain=     is this domain free, and what would it cost

Rate limited per IP (60 a minute overall; domain checks also share the 20 an hour budget in domain_check_service).
Only customer prices are returned. Logic: services/host_public_service.py.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.database import get_supabase
from app.models.common import ok
from app.services import host_public_service as svc

router = APIRouter()

_rate_store: dict = {}
_LIMIT = 60
_WINDOW = 60.0


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limit(request: Request) -> str:
    ip = _ip(request)
    now = time.monotonic()
    calls = [t for t in _rate_store.get(ip, []) if t > now - _WINDOW]
    if len(calls) >= _LIMIT:
        _rate_store[ip] = calls
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please wait a moment."})
    calls.append(now)
    _rate_store[ip] = calls
    if len(_rate_store) > 10_000:
        _rate_store.clear()
    return ip


def _call(fn, *args):
    try:
        return fn(*args)
    except svc.PublicHostError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/public/host/pricing")
def host_pricing(request: Request, db=Depends(get_supabase)):
    _limit(request)
    return ok(data=_call(svc.pricing_table, db))


@router.get("/public/host/domain-check")
def host_domain_check(request: Request, domain: str = Query(..., min_length=3, max_length=253), db=Depends(get_supabase)):
    ip = _limit(request)
    return ok(data=_call(svc.check, db, domain, ip))
