"""
app/routers/performance_hub.py
--------------------------------
Authenticated routes for PERF-1 Performance & Operations Hub.

14 routes — all require JWT via get_current_org (Pattern 28).
Static routes registered BEFORE parameterised routes (Pattern 53).
db always via Depends(get_supabase) — never called directly inside body (Pattern 62).
org_id always from JWT only (S1).
Module-level service import (Pattern 54).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
import app.services.performance_service as perf_svc

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------
_MANAGER_ROLES = {"owner", "ops_manager"}


def _require_manager(org: dict) -> None:
    role = (org.get("roles") or {}).get("template", "")
    if role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Manager access required")


def _require_owner(org: dict) -> None:
    role = (org.get("roles") or {}).get("template", "")
    if role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")


def _require_manager_or_self(org: dict, user_id: str) -> None:
    role = (org.get("roles") or {}).get("template", "")
    if role not in _MANAGER_ROLES and org.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ---------------------------------------------------------------------------
# Pydantic models (S3 — explicit field constraints)
# ---------------------------------------------------------------------------

class KpiTemplateCreate(BaseModel):
    role_template: str = Field(..., max_length=50)
    kpi_name:      str = Field(..., max_length=100)
    kpi_unit:      Optional[str] = Field(None, max_length=30)
    sort_order:    int = Field(0, ge=0)


class KpiTemplateUpdate(BaseModel):
    kpi_name:   Optional[str] = Field(None, max_length=100)
    kpi_unit:   Optional[str] = Field(None, max_length=30)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active:  Optional[bool] = None


class KpiTargetItem(BaseModel):
    kpi_name:    str   = Field(..., max_length=100)
    kpi_unit:    Optional[str] = Field(None, max_length=30)
    target_value: float = Field(..., ge=0)
    notes:       Optional[str] = Field(None, max_length=1000)  # S4


class SetTargetsRequest(BaseModel):
    user_id: str
    month:   str = Field(..., pattern=r"^\d{4}-\d{2}$")
    targets: List[KpiTargetItem] = Field(..., min_items=1)


class StaffLogCreate(BaseModel):
    log_date:           Optional[str]  = None
    kpi_key:            str            = Field(..., max_length=100)
    kpi_label:          str            = Field(..., max_length=100)
    value:              float          = Field(0, ge=0)
    label_value:        Optional[str]  = Field(None, max_length=200)
    notes:              Optional[str]  = Field(None, max_length=5000)  # S4
    attendance_status:  str            = Field("present", max_length=20)
    activity_outcome:   Optional[str]  = Field(None, max_length=100)
    duration_minutes:   Optional[int]  = Field(None, ge=0)
    blocker_note:       Optional[str]  = Field(None, max_length=500)
    linked_record_type: Optional[str]  = Field(None, max_length=30)
    linked_record_id:   Optional[str]  = None


class StaffLogUpdate(BaseModel):
    value:              Optional[float] = Field(None, ge=0)
    notes:              Optional[str]   = Field(None, max_length=5000)
    attendance_status:  Optional[str]   = Field(None, max_length=20)
    activity_outcome:   Optional[str]   = Field(None, max_length=100)
    duration_minutes:   Optional[int]   = Field(None, ge=0)
    blocker_note:       Optional[str]   = Field(None, max_length=500)


class OwnerDashboardPinSet(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6, pattern=r"^\d{4,6}$")


class BusinessGoalUpsert(BaseModel):
    goal_name:     str     = Field(..., max_length=150)
    goal_category: str     = Field(..., max_length=50)
    target_value:  float   = Field(..., ge=0)
    unit:          str     = Field("count", max_length=30)
    period_type:   str     = Field("monthly", max_length=20)
    period_start:  str     = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes:         Optional[str] = Field(None, max_length=1000)


# ---------------------------------------------------------------------------
# Routes — STATIC before PARAMETERISED (Pattern 53)
# ---------------------------------------------------------------------------

# --- GET /performance/scorecard -------------------------------------------
@router.get("/performance/scorecard")
async def get_scorecard(
    month: Optional[str] = None,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    org_id = org["org_id"]
    from datetime import date
    month = month or f"{date.today().year}-{date.today().month:02d}"
    return {"data": await perf_svc.get_scorecard(db, org_id, month)}


# --- GET /performance/kpi-templates ----------------------------------------
@router.get("/performance/kpi-templates")
def get_kpi_templates(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": perf_svc.get_kpi_templates(db, org["org_id"])}


# --- POST /performance/kpi-templates ----------------------------------------
@router.post("/performance/kpi-templates", status_code=201)
def create_kpi_template(
    payload: KpiTemplateCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": perf_svc.create_kpi_template(
        db, org["org_id"],
        payload.role_template, payload.kpi_name,
        payload.kpi_unit, payload.sort_order,
    )}


# --- GET /performance/health-score ------------------------------------------
@router.get("/performance/health-score")
async def get_health_score(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": await perf_svc.get_health_score(db, org["org_id"])}


# --- GET /performance/owner-dashboard/setup ---------------------------------
@router.get("/performance/owner-dashboard/setup")
def get_owner_dashboard_setup(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_owner(org)
    return {"data": perf_svc.get_or_create_owner_dashboard_token(db, org["org_id"])}


# --- POST /performance/owner-dashboard/setup --------------------------------
@router.post("/performance/owner-dashboard/setup")
def set_owner_dashboard_pin(
    payload: OwnerDashboardPinSet,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_owner(org)
    perf_svc.set_owner_dashboard_pin(db, org["org_id"], payload.pin)
    return {"data": {"ok": True}}


# --- POST /performance/staff-log --------------------------------------------
@router.post("/performance/staff-log", status_code=201)
def create_staff_log(
    payload: StaffLogCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    user_id = org["id"]  # Pattern 61 — user UUID is at org["id"]
    return {"data": perf_svc.create_staff_log(db, org["org_id"], user_id, payload.model_dump())}


# --- POST /performance/targets ----------------------------------------------
@router.post("/performance/targets", status_code=201)
def set_targets(
    payload: SetTargetsRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    created_by = org["id"]  # Pattern 61
    return {"data": perf_svc.set_targets(
        db, org["org_id"],
        payload.user_id, payload.month,
        [t.model_dump() for t in payload.targets],
        created_by,
    )}


# ---- PARAMETERISED routes below (Pattern 53) ----

# --- PATCH /performance/kpi-templates/{id} ----------------------------------
@router.patch("/performance/kpi-templates/{template_id}")
def update_kpi_template(
    template_id: str,
    payload: KpiTemplateUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return {"data": perf_svc.update_kpi_template(db, org["org_id"], template_id, updates)}


# --- DELETE /performance/kpi-templates/{id} ----------------------------------
@router.delete("/performance/kpi-templates/{template_id}")
def delete_kpi_template(
    template_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": perf_svc.soft_delete_kpi_template(db, org["org_id"], template_id)}


# --- PATCH /performance/staff-log/{id} --------------------------------------
@router.patch("/performance/staff-log/{log_id}")
def update_staff_log(
    log_id: str,
    payload: StaffLogUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return {"data": perf_svc.update_staff_log(db, org["org_id"], log_id, updates)}


# --- GET /performance/staff/{user_id} ---------------------------------------
@router.get("/performance/staff/{user_id}")
async def get_staff_profile(
    user_id: str,
    month: Optional[str] = None,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager_or_self(org, user_id)
    from datetime import date
    month = month or f"{date.today().year}-{date.today().month:02d}"
    return {"data": await perf_svc.get_staff_profile(db, org["org_id"], user_id, month)}


# --- GET /performance/targets/{user_id}/{month} ----------------------------
@router.get("/performance/targets/{user_id}/{month}")
def get_targets(
    user_id: str,
    month: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager_or_self(org, user_id)
    return {"data": perf_svc.get_targets_for_user_month(db, org["org_id"], user_id, month)}


# --- POST /performance/targets/{id}/acknowledge -----------------------------
@router.post("/performance/targets/{target_id}/acknowledge")
def acknowledge_targets(
    target_id: str,  # not used directly — scoped by user_id from JWT
    month: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    user_id = org["id"]  # Pattern 61 — self only
    return {"data": {"ok": perf_svc.acknowledge_targets(db, org["org_id"], user_id, month)}}

# GET /performance/business-goals
@router.get("/performance/business-goals")
def get_business_goals(
    period_start: Optional[str] = None,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    from datetime import date
    if not period_start:
        d = date.today()
        period_start = str(date(d.year, d.month, 1))
    return {"data": perf_svc.get_business_goals(db, org["org_id"], period_start)}
 
 
# POST /performance/business-goals
@router.post("/performance/business-goals", status_code=201)
def upsert_business_goal(
    payload: BusinessGoalUpsert,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": perf_svc.upsert_business_goal(
        db, org["org_id"], payload.model_dump(), org["id"]
    )}
 
 
# DELETE /performance/business-goals/{goal_id}
@router.delete("/performance/business-goals/{goal_id}")
def delete_business_goal(
    goal_id: str,
    period_start: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": {"ok": perf_svc.delete_business_goal(db, org["org_id"], goal_id, period_start)}}

# PATCH /performance/issues/{issue_id}/owner-attention
@router.patch("/performance/issues/{issue_id}/owner-attention")
def toggle_owner_attention(
    issue_id: str,
    flagged: bool,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_manager(org)
    return {"data": perf_svc.toggle_owner_attention(db, org["org_id"], issue_id, flagged)}
