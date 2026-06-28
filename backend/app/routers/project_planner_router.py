"""
app/routers/project_planner_router.py — PROJECT-PLANNER v2 routes.

Conventions (matching app/routers/leads.py, app/routers/whatsapp.py):
  - All routes prefixed /api/v1/project-planner (registered in main.py)
  - org_id from JWT only — never from request body (S1)
  - Response envelope: ok() / paginated()
  - RBAC: inline get_role_template(org) check, matching confirm_demo()'s
    pattern in leads.py — no generic require_role() dependency exists yet
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.models.project_planner_models import (
    DocumentLinkSet,
    PhaseCreate,
    PlanCreate,
    PlanUpdate,
    StrategyCreate,
    StrategyUpdate,
    TaskCreate,
    TaskUpdate,
)
from app.services import project_planner_service
from app.utils.rbac import get_role_template

router = APIRouter()

APPROVER_ROLES = ("owner", "ops_manager")


def _org_id(org: dict) -> str:
    return org["org_id"]


def _user_id(org: dict) -> str:
    return org["id"]


def _require_approver(org: dict) -> None:
    """Matches the inline RBAC pattern used by confirm_demo() in leads.py."""
    template = get_role_template(org)
    if template not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only owners and ops managers can approve or revert a strategy",
            },
        )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@router.get("/plans")
async def list_plans(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    plans = project_planner_service.list_plans(db=db, org_id=_org_id(org))
    return ok(data=plans)


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PlanCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    plan = project_planner_service.create_plan(db=db, org_id=_org_id(org), user_id=_user_id(org), payload=payload)
    return ok(data=plan, message="Plan created")


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    payload: PlanUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    plan = project_planner_service.update_plan(db=db, org_id=_org_id(org), user_id=_user_id(org), plan_id=plan_id, payload=payload)
    return ok(data=plan, message="Plan updated")


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    project_planner_service.delete_plan(db=db, org_id=_org_id(org), user_id=_user_id(org), plan_id=plan_id)
    return ok(data={"deleted": True})


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@router.get("/plans/{plan_id}/strategies")
async def list_strategies(
    plan_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    strategies = project_planner_service.list_strategies(db=db, org_id=_org_id(org), plan_id=plan_id)
    return ok(data=strategies)


@router.post("/strategies", status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    strategy = project_planner_service.create_strategy(
        db=db, org_id=_org_id(org), user_id=_user_id(org), payload=payload,
    )
    return ok(data=strategy, message="Strategy created")


@router.patch("/strategies/{strategy_id}")
async def update_strategy(
    strategy_id: str,
    payload: StrategyUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    strategy = project_planner_service.update_strategy(
        db=db, org_id=_org_id(org), user_id=_user_id(org), strategy_id=strategy_id, payload=payload,
    )
    return ok(data=strategy, message="Strategy updated")


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    project_planner_service.delete_strategy(db=db, org_id=_org_id(org), user_id=_user_id(org), strategy_id=strategy_id)
    return ok(data={"deleted": True})


@router.post("/strategies/{strategy_id}/approve")
async def approve_strategy(
    strategy_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Owner + ops_manager only. draft -> reviewed, or reviewed -> approved."""
    _require_approver(org)
    strategy = project_planner_service.approve_strategy(
        db=db, org_id=_org_id(org), strategy_id=strategy_id, user_id=_user_id(org),
    )
    return ok(data=strategy, message=f"Strategy moved to {strategy['approval_status']}")


@router.post("/strategies/{strategy_id}/revert")
async def revert_strategy(
    strategy_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Owner + ops_manager only. approved -> reviewed, or reviewed -> draft."""
    _require_approver(org)
    strategy = project_planner_service.revert_strategy(
        db=db, org_id=_org_id(org), strategy_id=strategy_id, user_id=_user_id(org),
    )
    return ok(data=strategy, message=f"Strategy reverted to {strategy['approval_status']}")


# ---------------------------------------------------------------------------
# Phases & Tasks
# ---------------------------------------------------------------------------

@router.post("/strategies/{strategy_id}/phases", status_code=status.HTTP_201_CREATED)
async def create_phase(
    strategy_id: str,
    payload: PhaseCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    phase = project_planner_service.create_phase(db=db, org_id=_org_id(org), strategy_id=strategy_id, payload=payload)
    return ok(data=phase, message="Phase created")


@router.post("/phases/{phase_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    phase_id: str,
    payload: TaskCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    task = project_planner_service.create_task(db=db, org_id=_org_id(org), phase_id=phase_id, payload=payload)
    return ok(data=task, message="Task created")


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    task = project_planner_service.update_task(db=db, org_id=_org_id(org), task_id=task_id, payload=payload)
    return ok(data=task, message="Task updated")


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    project_planner_service.delete_task(db=db, org_id=_org_id(org), task_id=task_id)
    return ok(data={"deleted": True})


# ---------------------------------------------------------------------------
# Strategy documents — upload (multipart) or set external link
# ---------------------------------------------------------------------------

@router.post("/strategies/{strategy_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_strategy_document(
    strategy_id: str,
    file: UploadFile = File(...),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Multipart upload. File size enforced at 25MB max (HTTP 413 if exceeded).
    Unsupported MIME type returns HTTP 415 (see Tech Spec §11.5 allow-list —
    note .docx is not on that list).
    """
    file_bytes = await file.read()
    document = project_planner_service.upload_strategy_document(
        db=db,
        org_id=_org_id(org),
        user_id=_user_id(org),
        strategy_id=strategy_id,
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
    )
    return ok(data=document, message="Document uploaded")


@router.post("/strategies/{strategy_id}/documents/link", status_code=status.HTTP_201_CREATED)
async def set_strategy_document_link(
    strategy_id: str,
    payload: DocumentLinkSet,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    document = project_planner_service.set_strategy_document_link(
        db=db, org_id=_org_id(org), user_id=_user_id(org),
        strategy_id=strategy_id, external_link=payload.external_link,
    )
    return ok(data=document, message="Link saved")


@router.get("/documents/{document_id}/download-url")
async def get_document_download_url(
    document_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Returns a fresh 1-hour signed URL (or the external link, if that's what was set)."""
    url = project_planner_service.get_document_download_url(db=db, org_id=_org_id(org), document_id=document_id)
    return ok(data={"url": url})


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    project_planner_service.delete_document(db=db, org_id=_org_id(org), document_id=document_id)
    return ok(data={"deleted": True})
