"""
app/routers/growth_config.py
Growth configuration routes — GPM-1A.

Routes:
  GET    /api/v1/growth/teams
  POST   /api/v1/growth/teams
  PATCH  /api/v1/growth/teams/{team_id}
  DELETE /api/v1/growth/teams/{team_id}

  GET    /api/v1/growth/spend
  POST   /api/v1/growth/spend
  DELETE /api/v1/growth/spend/{spend_id}

  GET    /api/v1/growth/direct-sales
  POST   /api/v1/growth/direct-sales
  PATCH  /api/v1/growth/direct-sales/{sale_id}
  DELETE /api/v1/growth/direct-sales/{sale_id}

RBAC:
  Reads: owner + ops_manager
  Writes: owner only

Pattern 53: static routes before parameterised.
Pattern 62: db via Depends(get_supabase).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.routers.auth import get_current_org

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------

def _require_owner_or_ops(org: dict) -> None:
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner or ops_manager access required"},
        )


def _require_owner(org: dict) -> None:
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner access required"},
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _success(data: object, message: str = "OK") -> dict:
    return {"success": True, "data": data, "message": message, "error": None}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class SpendCreate(BaseModel):
    period_start: str          # ISO date YYYY-MM-DD
    period_end:   str          # ISO date YYYY-MM-DD
    spend_type:   str          # "team" | "channel"
    team_name:    Optional[str] = None
    channel_name: Optional[str] = None
    amount:       float = Field(..., gt=0)
    currency:     str = Field("NGN", max_length=10)
    notes:        Optional[str] = None


class DirectSaleCreate(BaseModel):
    customer_id:   Optional[str] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    amount:        float = Field(..., gt=0)
    currency:      str = Field("NGN", max_length=10)
    sale_date:     str   # ISO date YYYY-MM-DD
    channel:       str = Field("other", max_length=50)
    utm_source:    Optional[str] = Field(None, max_length=100)
    source_team:   Optional[str] = Field(None, max_length=100)
    notes:         Optional[str] = None


class DirectSaleUpdate(BaseModel):
    customer_id:   Optional[str] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    amount:        Optional[float] = Field(None, gt=0)
    currency:      Optional[str] = Field(None, max_length=10)
    sale_date:     Optional[str] = None
    channel:       Optional[str] = Field(None, max_length=50)
    utm_source:    Optional[str] = Field(None, max_length=100)
    source_team:   Optional[str] = Field(None, max_length=100)
    notes:         Optional[str] = None


# ---------------------------------------------------------------------------
# TEAM MANAGEMENT
# ---------------------------------------------------------------------------

@router.get("/growth/teams")
def list_teams(
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    result = (
        db.table("growth_teams")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("created_at", desc=False)
        .execute()
    )
    return _success(result.data or [])


@router.post("/growth/teams", status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    now = _now_iso()
    result = (
        db.table("growth_teams")
        .insert({
            "org_id":     org["org_id"],
            "name":       payload.name,
            "color":      payload.color,
            "is_active":  True,
            "created_at": now,
            "updated_at": now,
        })
        .execute()
    )
    team = result.data[0] if result.data else {}
    return _success(team, "Team created")


@router.patch("/growth/teams/{team_id}")
def update_team(
    team_id: str,
    payload: TeamUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    # Verify belongs to org
    existing = (
        db.table("growth_teams")
        .select("id")
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Team not found"})

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = _now_iso()
    result = (
        db.table("growth_teams")
        .update(updates)
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    team = result.data[0] if result.data else {}
    return _success(team, "Team updated")


@router.delete("/growth/teams/{team_id}", status_code=status.HTTP_200_OK)
def delete_team(
    team_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("growth_teams")
        .select("id")
        .eq("id", team_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Team not found"})

    # Soft delete — set is_active = false
    db.table("growth_teams").update({
        "is_active":  False,
        "updated_at": _now_iso(),
    }).eq("id", team_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Team deactivated")


# ---------------------------------------------------------------------------
# CAMPAIGN SPEND
# ---------------------------------------------------------------------------

@router.get("/growth/spend")
def list_spend(
    period_start: Optional[str] = Query(None),
    period_end:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    query = (
        db.table("campaign_spend")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("period_start", desc=True)
    )
    if period_start:
        query = query.gte("period_start", period_start)
    if period_end:
        query = query.lte("period_end", period_end)
    result = query.execute()
    return _success(result.data or [])


@router.post("/growth/spend", status_code=status.HTTP_201_CREATED)
def create_spend(
    payload: SpendCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    if payload.spend_type not in ("team", "channel"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_SPEND_TYPE", "message": "spend_type must be 'team' or 'channel'"},
        )
    if payload.spend_type == "team" and not payload.team_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "MISSING_FIELD", "message": "team_name required when spend_type is 'team'"},
        )
    if payload.spend_type == "channel" and not payload.channel_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "MISSING_FIELD", "message": "channel_name required when spend_type is 'channel'"},
        )

    result = (
        db.table("campaign_spend")
        .insert({
            "org_id":        org["org_id"],
            "period_start":  payload.period_start,
            "period_end":    payload.period_end,
            "spend_type":    payload.spend_type,
            "team_name":     payload.team_name,
            "channel_name":  payload.channel_name,
            "amount":        payload.amount,
            "currency":      payload.currency,
            "notes":         payload.notes,
            "recorded_by":   org["id"],
            "created_at":    _now_iso(),
        })
        .execute()
    )
    row = result.data[0] if result.data else {}
    return _success(row, "Spend entry recorded")


@router.delete("/growth/spend/{spend_id}", status_code=status.HTTP_200_OK)
def delete_spend(
    spend_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("campaign_spend")
        .select("id")
        .eq("id", spend_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Spend entry not found"})

    db.table("campaign_spend").delete().eq("id", spend_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Spend entry deleted")


# ---------------------------------------------------------------------------
# DIRECT SALES
# ---------------------------------------------------------------------------

@router.get("/growth/direct-sales")
def list_direct_sales(
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    offset = (page - 1) * page_size
    result = (
        db.table("direct_sales")
        .select("*", count="exact")
        .eq("org_id", org["org_id"])
        .order("sale_date", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )
    total = result.count or 0
    return _success({
        "items":     result.data or [],
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  (offset + page_size) < total,
    })


@router.post("/growth/direct-sales", status_code=status.HTTP_201_CREATED)
def create_direct_sale(
    payload: DirectSaleCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    now = _now_iso()
    result = (
        db.table("direct_sales")
        .insert({
            "org_id":        org["org_id"],
            "customer_id":   payload.customer_id,
            "customer_name": payload.customer_name,
            "amount":        payload.amount,
            "currency":      payload.currency,
            "sale_date":     payload.sale_date,
            "channel":       payload.channel,
            "utm_source":    payload.utm_source,
            "source_team":   payload.source_team,
            "notes":         payload.notes,
            "recorded_by":   org["id"],
            "created_at":    now,
            "updated_at":    now,
        })
        .execute()
    )
    row = result.data[0] if result.data else {}
    return _success(row, "Direct sale recorded")


@router.patch("/growth/direct-sales/{sale_id}")
def update_direct_sale(
    sale_id: str,
    payload: DirectSaleUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    existing = (
        db.table("direct_sales")
        .select("id")
        .eq("id", sale_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Direct sale not found"})

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = _now_iso()
    result = (
        db.table("direct_sales")
        .update(updates)
        .eq("id", sale_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    row = result.data[0] if result.data else {}
    return _success(row, "Direct sale updated")


@router.delete("/growth/direct-sales/{sale_id}", status_code=status.HTTP_200_OK)
def delete_direct_sale(
    sale_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner(org)
    existing = (
        db.table("direct_sales")
        .select("id")
        .eq("id", sale_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Direct sale not found"})

    db.table("direct_sales").delete().eq("id", sale_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Direct sale deleted")
