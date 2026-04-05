"""
app/routers/ops.py
Operations Intelligence routes — Phase 6A.

Routes (prefix /api/v1 set in main.py):
  GET  /api/v1/dashboard/metrics  — executive dashboard metrics
  POST /api/v1/ask                — ask-your-data (Claude Sonnet, §12.5)

Pattern 28: get_current_org dependency on every route (never get_current_user).
S15: AI endpoint rate-limited via Upstash Redis — 30 calls per user per hour.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.models.ops import AskRequest
from app.services.ops_service import ask_your_data, get_dashboard_metrics
from app.utils.rate_limiter import check_rate_limit

router = APIRouter()


@router.get("/dashboard/metrics", tags=["ops"])
async def dashboard_metrics(
    org: dict = Depends(get_current_org),   # Pattern 28
    db=Depends(get_supabase),
):
    """
    Aggregate executive dashboard metrics scoped to the caller's org and role.
    Revenue fields (mrr_ngn, revenue_at_risk_ngn) are null unless caller is
    owner or admin (or has explicit view_revenue permission).
    """
    metrics = get_dashboard_metrics(org, db)
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
    """
    # S15: per-user AI call rate limiting — 30 per hour
    user_id = org.get("id", "unknown")
    org_id = org.get("org_id", "unknown")
    rl_key = f"rate:ai:{org_id}:{user_id}"
    if not check_rate_limit(rl_key, limit=30, window_seconds=3600):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")

    answer = ask_your_data(payload.question, org, db)
    return ok(data={"answer": answer})