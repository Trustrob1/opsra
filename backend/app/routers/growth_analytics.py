"""
app/routers/growth_analytics.py
Growth & Performance Dashboard analytics routes — GPM-1A.

Routes:
  GET /api/v1/analytics/growth/overview
  GET /api/v1/analytics/growth/teams
  GET /api/v1/analytics/growth/funnel
  GET /api/v1/analytics/growth/sales-reps
  GET /api/v1/analytics/growth/channels
  GET /api/v1/analytics/growth/velocity
  GET /api/v1/analytics/growth/pipeline-at-risk
  GET /api/v1/analytics/growth/win-loss

RBAC:
  All routes: owner + ops_manager only.
  /sales-reps: additionally permits sales_agent (response scoped in service layer).

Pattern 53: static routes registered before parameterised.
Pattern 54: service imported at module level.
Pattern 62: db via Depends(get_supabase) in route signature.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_supabase
from app.routers.auth import get_current_org
from app.services import growth_analytics_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------

def _require_growth_access(org: dict) -> None:
    """Allow owner and ops_manager only."""
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner or ops_manager access required"},
        )


def _require_growth_or_rep(org: dict) -> str:
    """
    Allow owner, ops_manager, and sales_agent.
    Returns the role template string for scoping in the service layer.
    """
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager", "sales_agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions"},
        )
    return template


def _parse_dates(
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[Optional[date], Optional[date]]:
    """Parse ISO date strings. Raises 422 on invalid format."""
    parsed_from: Optional[date] = None
    parsed_to: Optional[date] = None
    try:
        if date_from:
            parsed_from = date.fromisoformat(date_from)
        if date_to:
            parsed_to = date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_DATE", "message": "date_from and date_to must be ISO date strings (YYYY-MM-DD)"},
        )
    return parsed_from, parsed_to


def _success(data: object) -> dict:
    return {"success": True, "data": data, "error": None}


# ---------------------------------------------------------------------------
# GET /analytics/growth/overview
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/overview")
def get_overview(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_overview_metrics(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/teams
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/teams")
def get_teams(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_team_performance(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/funnel
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/funnel")
def get_funnel(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    team:      Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_funnel_metrics(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
        team=team,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/sales-reps
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/sales-reps")
def get_sales_reps(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    role = _require_growth_or_rep(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_sales_rep_metrics(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
        requesting_user_id=org["id"],        # Pattern 61: org["id"] is the user UUID
        requesting_user_role=role,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/channels
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/channels")
def get_channels(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_channel_metrics(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/velocity
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/velocity")
def get_velocity(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_lead_velocity(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/pipeline-at-risk
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/pipeline-at-risk")
def get_pipeline_at_risk(
    stuck_days: int = Query(7, ge=1, le=365),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    data = growth_analytics_service.get_pipeline_at_risk(
        db=db,
        org_id=org["org_id"],
        stuck_days_threshold=stuck_days,
    )
    return _success(data)


# ---------------------------------------------------------------------------
# GET /analytics/growth/win-loss
# ---------------------------------------------------------------------------

@router.get("/analytics/growth/win-loss")
def get_win_loss(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_growth_access(org)
    df, dt = _parse_dates(date_from, date_to)
    data = growth_analytics_service.get_win_loss_analysis(
        db=db,
        org_id=org["org_id"],
        date_from=df,
        date_to=dt,
    )
    return _success(data)

@router.get("/analytics/growth/debug")
def debug_fetch(
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    org_id = org["org_id"]
    try:
        result = db.table("leads").select("id, stage, deleted_at").eq("org_id", org_id).execute()
        rows = result.data or []
        return {
            "org_id": org_id,
            "row_count": len(rows),
            "sample": rows[:3],
        }
    except Exception as e:
        return {"error": str(e)}