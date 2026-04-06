"""
app/routers/commissions.py
Commission tracking router — Phase 9C.

Prefix: /api/v1/commissions (set in main.py)

ROUTE ORDERING:
  GET  /summary  ← static FIRST — prevents "summary" being matched as a commission UUID
  GET  /         ← list
  PATCH /{id}    ← parameterised AFTER static

Pattern 28: get_current_org on every route.
S1: org_id always from JWT — never from request body.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.services import commissions_service

router = APIRouter(prefix="/commissions", tags=["commissions"])


# ── Pydantic model ────────────────────────────────────────────────────────────

class CommissionUpdate(BaseModel):
    amount_ngn:  Optional[float] = Field(None, ge=0)
    status:      Optional[str]   = Field(None, max_length=20)
    notes:       Optional[str]   = Field(None, max_length=5000)


# ── GET /api/v1/commissions/summary ← STATIC — must be before /{id} ──────────

@router.get("/summary")
async def get_commission_summary(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns commission totals grouped by status.
    Affiliates see their own totals.
    Managers see org-wide totals.
    """
    summary = commissions_service.get_commission_summary(org=org, db=db)
    return ok(data=summary)


# ── GET /api/v1/commissions ───────────────────────────────────────────────────

@router.get("")
async def list_commissions(
    affiliate_user_id: Optional[str] = Query(None),
    status:            Optional[str] = Query(None),
    event_type:        Optional[str] = Query(None),
    page:              int            = Query(1,  ge=1),
    page_size:         int            = Query(20, ge=1, le=100),
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    List commissions.
    Affiliates: own commissions only (affiliate_user_id filter ignored).
    Managers: all org commissions; optionally filter by affiliate_user_id.
    """
    result = commissions_service.list_commissions(
        org=org,
        db=db,
        affiliate_user_id=affiliate_user_id,
        comm_status=status,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


# ── PATCH /api/v1/commissions/{id} ← PARAMETERISED — after static ────────────

@router.patch("/{commission_id}")
async def update_commission(
    commission_id: str,
    payload: CommissionUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Update a commission — set amount, status, or notes.
    Managers only (owner / ops_manager / is_admin).
    """
    updated = commissions_service.update_commission(
        commission_id=commission_id,
        org=org,
        db=db,
        amount_ngn=payload.amount_ngn,
        comm_status=payload.status,
        notes=payload.notes,
    )
    return ok(data=updated, message="Commission updated")
