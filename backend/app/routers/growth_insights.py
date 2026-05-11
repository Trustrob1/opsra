"""
GPM-2 — Growth AI Insights Engine
Router: growth_insights.py

Routes:
  GET  /api/v1/analytics/growth/insights/sections   — cached section insight cards
  POST /api/v1/analytics/growth/insights/panel      — on-demand full narrative
  GET  /api/v1/analytics/growth/insights/anomalies  — current anomaly alerts

Access: owner + ops_manager only.
Pattern 53: static routes before parameterised.
Pattern 62: db via Depends(get_supabase).

GPM-2-FIX: On cache miss, GET /sections now dispatches a Celery background task
and returns 202 immediately instead of running 8 sequential Haiku calls inline.
This prevents Gunicorn worker timeouts. Frontend polls until cache is populated.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.dependencies import get_current_org, get_supabase
from app.services.growth_analytics_service import (
    get_channel_metrics,
    get_funnel_metrics,
    get_lead_velocity,
    get_overview_metrics,
    get_pipeline_at_risk,
    get_sales_rep_metrics,
    get_team_performance,
    get_win_loss_analysis,
)
from app.services.growth_insights_service import (
    generate_panel_narrative,
    get_active_anomalies,
    get_cached_insights,
    _make_cache_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/analytics/growth/insights",
    tags=["growth_insights"],
)

# ── RBAC helper ───────────────────────────────────────────────────────────────

ALLOWED_ROLES = {"owner", "ops_manager"}

def _require_growth_access(org: dict) -> None:
    role = (org.get("roles") or {}).get("template")
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="FORBIDDEN")


# ── Rate limit helper (10 panel calls / hr / org) ────────────────────────────

_panel_rate: dict[str, list] = {}

def _check_panel_rate_limit(org_id: str) -> None:
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 3600
    calls = [t for t in _panel_rate.get(org_id, []) if t > cutoff]
    if len(calls) >= 10:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: 10 panel insight requests per hour.",
        )
    calls.append(now)
    _panel_rate[org_id] = calls


# ── Section data fetcher (used by panel route only) ───────────────────────────

def _parse_date(s: str) -> date:
    """Convert ISO date string to date object for analytics service compatibility."""
    return date.fromisoformat(s)


def _fetch_all_section_data(db, org_id: str, date_from: str, date_to: str, user_id: str) -> dict:
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    fetchers = {
        "overview":         lambda: get_overview_metrics(db, org_id, df, dt),
        "team_performance": lambda: get_team_performance(db, org_id, df, dt),
        "funnel":           lambda: get_funnel_metrics(db, org_id, df, dt),
        "sales_reps":       lambda: get_sales_rep_metrics(db, org_id, df, dt, user_id, "owner"),
        "channels":         lambda: get_channel_metrics(db, org_id, df, dt),
        "velocity":         lambda: get_lead_velocity(db, org_id, df, dt),
        "pipeline_at_risk": lambda: get_pipeline_at_risk(db, org_id),
        "win_loss":         lambda: get_win_loss_analysis(db, org_id, df, dt),
    }
    results = {}
    for key, fn in fetchers.items():
        try:
            results[key] = fn()
        except Exception as exc:
            logger.warning("Section data fetch failed [%s] org %s: %s", key, org_id, exc)
            results[key] = {}
    return results


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/sections")
async def get_insight_sections(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns insight cards for all 8 dashboard sections.
    Cached per org per date range for 6 hours.

    GPM-2-FIX: On cache miss, dispatches a Celery background task and returns
    202 immediately. Frontend polls this endpoint until cache is populated.
    Cache hit path is unchanged — returns instantly with no Haiku calls.
    """
    _require_growth_access(org)
    org_id = org["org_id"]

    today = datetime.now(timezone.utc).date().isoformat()
    df = date_from or (datetime.now(timezone.utc).date().replace(day=1)).isoformat()
    dt = date_to or today
    cache_key = _make_cache_key(df, dt)

    # Cache hit — return immediately, no Haiku calls
    cached = get_cached_insights(db, org_id, cache_key)
    if cached:
        return {"success": True, "data": {"sections": cached, "from_cache": True}}

    # Cache miss — dispatch background task and return 202 immediately.
    # The Celery task runs all 8 Haiku calls and writes the result to cache.
    # Frontend polls this endpoint until cache is populated (status != generating).
    from app.workers.growth_insights_worker import run_generate_section_insights
    run_generate_section_insights.delay(str(org_id), df, dt)

    return JSONResponse(
        status_code=202,
        content={
            "success": True,
            "data": {
                "status":     "generating",
                "sections":   {},
                "from_cache": False,
            },
        },
    )


@router.post("/panel")
async def get_insight_panel(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    On-demand full narrative AI Insight Panel.
    Not cached. Rate limited: 10/hr/org.
    """
    _require_growth_access(org)
    org_id = org["org_id"]
    _check_panel_rate_limit(org_id)

    today = datetime.now(timezone.utc).date().isoformat()
    df = date_from or (datetime.now(timezone.utc).date().replace(day=1)).isoformat()
    dt = date_to or today

    section_data = _fetch_all_section_data(db, org_id, df, dt, org["id"])

    result = generate_panel_narrative(section_data)
    if not result:
        raise HTTPException(status_code=503, detail="AI insights temporarily unavailable.")

    _log_claude_usage(db, org_id, org["id"], "growth_panel_narrative", 1)

    return {"success": True, "data": result}


@router.get("/anomalies")
async def get_insight_anomalies(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Returns current active anomaly alerts for this org."""
    _require_growth_access(org)
    org_id = org["org_id"]
    alerts = get_active_anomalies(db, org_id)
    return {"success": True, "data": {"alerts": alerts}}


# ── Internal audit log ────────────────────────────────────────────────────────

def _log_claude_usage(db, org_id: str, user_id: str, action_type: str, call_count: int) -> None:
    """
    Logs one row per Claude call batch.
    Tokens and cost are unknown at call time (no streaming) — logged as 0.
    call_count tracked via action_type suffix for multi-section calls.
    """
    try:
        rows = [
            {
                "org_id":             org_id,
                "user_id":            user_id,
                "action_type":        action_type,
                "model":              "claude-haiku-4-5-20251001",
                "input_tokens":       0,
                "output_tokens":      0,
                "estimated_cost_usd": 0,
            }
            for _ in range(call_count)
        ]
        db.table("claude_usage_log").insert(rows).execute()
    except Exception as exc:
        logger.warning("claude_usage_log insert failed: %s", exc)


@router.delete("/sections/cache")
async def clear_insight_cache(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_growth_access(org)
    org_id = org["org_id"]
    db.table("organisations").update({"growth_insights": {}}).eq("id", org_id).execute()
    return {"success": True, "message": "Insight cache cleared."}
