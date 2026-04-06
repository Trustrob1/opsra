"""
app/routers/leads.py
All 14 lead routes from Technical Spec Section 5.2.

Phase 9B additions:
  - list_leads: scoped roles (sales_agent, affiliate_partner) see only
    leads assigned to themselves — assigned_to forced to org["id"]
  - Mutating routes (create, update, move-stage, convert, mark-lost,
    reactivate, import): blocked for affiliate_partner (read-only role)
  - Pattern 37: role derived from org["roles"]["template"] via rbac module

Conventions:
  - All routes prefixed /api/v1/leads (registered in main.py)
  - org_id from JWT only — never from request body
  - Response envelope: ok() / err() / paginated()
  - audit_log + timeline written in service layer
  - Rate limit on AI scoring: 20/60min/org (Section 11.4) — enforced via Redis
  - Static routes (/import, /import/{job_id}) declared BEFORE /{id} to avoid shadowing
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.database import get_supabase
from app.dependencies import get_current_org, require_admin
from app.models.common import ErrorCode, ok, err, paginated
from app.models.leads import (
    LeadCreate,
    LeadUpdate,
    MarkLostRequest,
    MoveStageRequest,
)
from app.services import lead_service
from app.utils.rbac import (
    get_role_template,
    is_scoped_role,
    require_not_affiliate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _org_id(org: dict) -> str:
    return org["org_id"]


def _user_id(org: dict) -> str:
    return org["id"]


# ---------------------------------------------------------------------------
# GET /api/v1/leads — list leads
# Phase 9B: scoped roles see only their own assigned leads
# ---------------------------------------------------------------------------

@router.get("")
async def list_leads(
    stage: Optional[str] = Query(None),
    score: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    # Phase 9B: force assigned_to filter for scoped roles (Pattern 37)
    effective_assigned_to = (
        _user_id(org) if is_scoped_role(org) else assigned_to
    )

    result = lead_service.list_leads(
        db=db,
        org_id=_org_id(org),
        stage=stage,
        score=score,
        assigned_to=effective_assigned_to,
        source=source,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/leads — create lead
# Phase 9B: affiliate_partner cannot create leads
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "creating leads")
    lead = lead_service.create_lead(
        db=db,
        org_id=_org_id(org),
        user_id=_user_id(org),
        payload=payload,
    )
    return ok(data=lead, message="Lead created")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/import — CSV/Excel bulk import
# Phase 9B: affiliate_partner cannot import leads
# MUST be declared before /{id} routes to avoid route shadowing
# ---------------------------------------------------------------------------

@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_leads(
    file: UploadFile = File(...),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Accept a CSV file and create leads in bulk. Returns job_id for polling."""
    require_not_affiliate(org, "importing leads")

    org_id = _org_id(org)
    user_id = _user_id(org)

    # Validate MIME type — Section 11.5
    allowed_types = {"text/csv", "application/csv", "application/vnd.ms-excel",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in allowed_types and not (
        file.filename or ""
    ).lower().endswith((".csv", ".xlsx")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "Only CSV and Excel files are accepted for bulk import",
            },
        )

    raw = await file.read()
    job_id = lead_service.create_import_job(org_id)

    try:
        text = raw.decode("utf-8-sig")  # handle BOM
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("CSV parse error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": f"Could not parse CSV file: {exc}",
            },
        ) from exc

    lead_service.process_csv_import(db=db, org_id=org_id, user_id=user_id, job_id=job_id, rows=rows)

    job = lead_service.get_import_job(org_id, job_id)
    return ok(data=job, message=f"Import completed: {job['succeeded']} succeeded, {job['failed']} failed")


# ---------------------------------------------------------------------------
# GET /api/v1/leads/import/{job_id} — poll import status
# MUST be declared before /{id} to avoid "import" being matched as an id
# ---------------------------------------------------------------------------

@router.get("/import/{job_id}")
async def get_import_status(
    job_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    job = lead_service.get_import_job(_org_id(org), job_id)
    return ok(data=job)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id} — get single lead
# Phase 9B: scoped roles can only read their own assigned leads
# The lead_service.get_lead returns 404 if not in org, so we add an
# ownership check for scoped roles after the fetch.
# ---------------------------------------------------------------------------

@router.get("/{lead_id}")
async def get_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    lead = lead_service.get_lead(db=db, org_id=_org_id(org), lead_id=lead_id)

    # Phase 9B: scoped roles can only see their own leads
    if is_scoped_role(org) and lead.get("assigned_to") != _user_id(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "You can only view leads assigned to you"},
        )

    return ok(data=lead)


# ---------------------------------------------------------------------------
# PATCH /api/v1/leads/{id} — update lead fields
# Phase 9B: affiliate_partner cannot edit leads
# ---------------------------------------------------------------------------

@router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "editing leads")
    lead = lead_service.update_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
        payload=payload,
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# DELETE /api/v1/leads/{id} — soft delete (Admin only)
# ---------------------------------------------------------------------------

@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    org: dict = Depends(require_admin),
    db=Depends(get_supabase),
):
    lead_service.soft_delete_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        admin_user_id=_user_id(org),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/score — AI scoring
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/score")
async def score_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    lead = lead_service.score_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=lead, message="Lead scored successfully")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/move-stage
# Phase 9B: affiliate_partner cannot move stages
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/move-stage")
async def move_stage(
    lead_id: str,
    payload: MoveStageRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "moving pipeline stages")
    lead = lead_service.move_stage(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        new_stage=payload.new_stage.value,
        user_id=_user_id(org),
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/convert
# Phase 9B: affiliate_partner cannot convert leads
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/convert")
async def convert_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "converting leads")
    result = lead_service.convert_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=result, message="Lead converted to customer")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/mark-lost
# Phase 9B: affiliate_partner cannot mark leads lost
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/mark-lost")
async def mark_lost(
    lead_id: str,
    payload: MarkLostRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "marking leads as lost")
    lead = lead_service.mark_lost(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        lost_reason=payload.lost_reason.value,
        user_id=_user_id(org),
        reengagement_date=str(payload.reengagement_date) if payload.reengagement_date else None,
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/reactivate
# Phase 9B: affiliate_partner cannot reactivate leads
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/reactivate", status_code=status.HTTP_201_CREATED)
async def reactivate_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "reactivating leads")
    new_lead = lead_service.reactivate_lead(
        db=db,
        org_id=_org_id(org),
        old_lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=new_lead, message="Lead reactivated")


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/timeline
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/timeline")
async def get_timeline(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    events = lead_service.get_timeline(db=db, org_id=_org_id(org), lead_id=lead_id)
    return ok(data=events)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/tasks
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/tasks")
async def get_lead_tasks(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    tasks = lead_service.get_lead_tasks(db=db, org_id=_org_id(org), lead_id=lead_id)
    return ok(data=tasks)