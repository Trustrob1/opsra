"""
app/routers/public_performance.py
-----------------------------------
PIN-gated public routes for PERF-1 owner external dashboard.

No JWT dependency — auth is PIN session token only.
Redis brute-force: 5 attempts → 15-min lockout.
db via Depends(get_supabase) (Pattern 62). EXCEPTION: no get_current_org here.
Static routes before parameterised (Pattern 53).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_supabase
import app.services.performance_service as perf_svc

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Redis helpers for brute-force lockout
# ---------------------------------------------------------------------------
_LOCKOUT_ATTEMPTS = 5
_LOCKOUT_WINDOW   = 15 * 60  # 15 minutes in seconds


def _lockout_key(token: str) -> str:
    return f"owner_dashboard_lockout:{token}"


def _check_lockout(token: str) -> None:
    """Raise 429 if brute-force lockout is active."""
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        count = r.get(_lockout_key(token))
        if count and int(count) >= _LOCKOUT_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Lockout check failed: %s", exc)  # fail-open


def _record_failed_attempt(token: str) -> None:
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        key = _lockout_key(token)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOCKOUT_WINDOW)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed to record lockout attempt: %s", exc)


def _clear_lockout(token: str) -> None:
    try:
        import redis as redis_lib
        redis_url = os.environ.get("REDIS_URL", "")
        if not redis_url:
            return
        ssl = redis_url.startswith("rediss://")
        r = redis_lib.from_url(redis_url, decode_responses=True, ssl_cert_reqs=None if ssl else "required")
        r.delete(_lockout_key(token))
    except Exception as exc:
        logger.warning("Failed to clear lockout: %s", exc)


def _verify_session_token(
    token: str,
    org_id: str,
    dashboard_token: str,
    authorization: str | None,
) -> None:
    """Verify Authorization header contains a valid 24h session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="PIN session required")
    session_token = authorization.removeprefix("Bearer ").strip()
    if not perf_svc.verify_owner_session_token(session_token, org_id, dashboard_token):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PinVerifyRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6, pattern=r"^\d{4,6}$")


class ApproveLogRequest(BaseModel):
    log_id: str


class FlagLogRequest(BaseModel):
    log_id: str
    note:   str = Field(..., max_length=500)


# ---------------------------------------------------------------------------
# Routes — STATIC /verify before PARAMETERISED (Pattern 53)
# Note: all routes share /{token} prefix — static sub-paths registered first.
# ---------------------------------------------------------------------------

# POST /public/owner-dashboard/{token}/verify
@router.post("/public/owner-dashboard/{token}/verify")
def verify_pin(
    token: str,
    payload: PinVerifyRequest,
    db=Depends(get_supabase),
):
    _check_lockout(token)
    org = perf_svc.verify_owner_dashboard_pin(db, token, payload.pin)
    if not org:
        _record_failed_attempt(token)
        raise HTTPException(status_code=401, detail="Invalid PIN")
    _clear_lockout(token)
    session_token = perf_svc.generate_owner_session_token(org["id"], token)
    return {
        "session_token": session_token,
        "org_id": org["id"],
        "org_name": org.get("name", ""),
        "expires_in_seconds": 86400,
    }


# POST /public/owner-dashboard/{token}/approve
@router.post("/public/owner-dashboard/{token}/approve")
def approve_log(
    token: str,
    payload: ApproveLogRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    # Resolve org_id from token
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)
    perf_svc.approve_log(db, row["id"], payload.log_id)
    return {"data": {"ok": True}}


# POST /public/owner-dashboard/{token}/flag
@router.post("/public/owner-dashboard/{token}/flag")
def flag_log(
    token: str,
    payload: FlagLogRequest,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)

    # Find owner + ops_manager user IDs to notify (Pattern 48)
    users_res = db.table("users").select("id, roles(template)").eq("org_id", row["id"]).execute()
    notif_ids = [
        u["id"] for u in (users_res.data or [])
        if (u.get("roles") or {}).get("template", "") in ("owner", "ops_manager")
    ]
    perf_svc.flag_log(db, row["id"], payload.log_id, payload.note, notif_ids)
    return {"data": {"ok": True}}


# GET /public/owner-dashboard/{token}
@router.get("/public/owner-dashboard/{token}")
async def get_owner_dashboard(
    token: str,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id, name, health_score_weights").eq(
        "owner_dashboard_token", token
    ).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)

    panels = await perf_svc.get_owner_dashboard_panels(db, row["id"])
    health = await perf_svc.get_health_score(db, row["id"])
    return {
        "org_name": row.get("name", ""),
        "health_score": health,
        "panels": panels,
    }

@router.get("/public/owner-dashboard/{token}/goals")
async def get_owner_dashboard_goals(
    token: str,
    period_start: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db=Depends(get_supabase),
):
    org = db.table("organisations").select("id").eq("owner_dashboard_token", token).limit(1).execute()
    row = (org.data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    _verify_session_token(token, row["id"], token, authorization)
    from datetime import date
    if not period_start:
        d = date.today()
        period_start = str(date(d.year, d.month, 1))
    return {"data": perf_svc.get_business_goals(db, row["id"], period_start)}