"""
app/routers/ops.py
Operations Intelligence routes — Phase 6A.

Routes (prefix /api/v1 set in main.py):
  GET  /api/v1/dashboard/metrics  — executive dashboard metrics
  POST /api/v1/ask                — ask-your-data (Claude Sonnet, §12.5)

Pattern 28: get_current_org dependency on every route (never get_current_user).
S15: AI endpoint rate-limited via Upstash Redis — 30 calls per user per hour.

PERF-1 (LOAD-TEST-1 fixes):
  - dashboard/metrics: 60-second Redis cache per org+role. S14: falls through
    to live query if Redis is unavailable.
  - /ask: 6-second asyncio timeout. Returns graceful 503 if Claude exceeds limit
    under concurrent load instead of hanging the connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.models.ops import AskRequest
from app.services.ops_service import ask_your_data, get_dashboard_metrics
from app.utils.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Redis cache helpers — PERF-1
# S14: every helper returns None / falls through on any Redis failure.
# Uses the same REDIS_URL as Celery — no new infrastructure required.
# ---------------------------------------------------------------------------

_DASHBOARD_CACHE_TTL = 60       # seconds — matches DRD §13.1 60s refresh
_ASK_TIMEOUT_SECONDS = 6.0      # slightly above DRD 5s AI threshold


def _get_redis():
    """Return a Redis client or None if unavailable (S14)."""
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return None
        return _redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
    except Exception as exc:
        logger.debug("ops._get_redis: unavailable — %s", exc)
        return None


def _cache_get(key: str):
    """Return cached value (parsed JSON) or None."""
    try:
        r = _get_redis()
        if r is None:
            return None
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("ops._cache_get %s: %s", key, exc)
        return None


def _cache_set(key: str, value, ttl: int) -> None:
    """Store value as JSON with TTL. S14: silently swallows all errors."""
    try:
        r = _get_redis()
        if r is None:
            return
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.warning("ops._cache_set FAILED %s: %s", key, exc)


@router.get("/dashboard/metrics", tags=["ops"])
async def dashboard_metrics(
    org: dict = Depends(get_current_org),   # Pattern 28
    db=Depends(get_supabase),
):
    """
    Aggregate executive dashboard metrics scoped to the caller's org and role.
    Revenue fields (mrr_ngn, revenue_at_risk_ngn) are null unless caller is
    owner or admin (or has explicit view_revenue permission).

    PERF-1: Results cached in Redis for 60 seconds per org+role.
    Cache miss falls through to live DB query (S14).
    """
    org_id  = org.get("org_id", "")
    role    = ((org.get("roles") or {}).get("template") or "default")
    cache_key = f"dashboard:metrics:{org_id}:{role}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return ok(data=cached)

    metrics = get_dashboard_metrics(org, db)
    _cache_set(cache_key, metrics, _DASHBOARD_CACHE_TTL)
    return ok(data=metrics)


@router.post("/ask", tags=["ops"])
async def ask_data(
    payload: AskRequest,
    org: dict = Depends(get_current_org),   # Pattern 28
    db=Depends(get_supabase),
):
    """
    Ask-your-data: natural language query over live business data (§12.5).
    Rate-limited: 30 AI calls per user per hour (S15).

    PERF-1: 6-second asyncio timeout. Returns 503 with a friendly message
    if Claude exceeds the limit under concurrent load rather than hanging
    the connection indefinitely.
    """
    # S15: per-user AI call rate limiting — 30 per hour
    user_id = org.get("id", "unknown")
    org_id = org.get("org_id", "unknown")
    rl_key = f"rate:ai:{org_id}:{user_id}"
    if not check_rate_limit(rl_key, limit=30, window_seconds=3600):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")

    try:
        loop = asyncio.get_event_loop()
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, ask_your_data, payload.question, org, db),
            timeout=_ASK_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("ask_data timeout for org=%s user=%s", org_id, user_id)
        raise HTTPException(
            status_code=503,
            detail="The AI assistant is taking longer than expected. Please try again in a moment.",
        )

    return ok(data={"answer": answer})