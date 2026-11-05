"""
app/routers/realtor.py - REALTOR-LINE-1

Prefix: /api/v1 (set in main.py)
  GET  /leads/{lead_id}/payments   payments recorded for a lead (managers)
  POST /leads/{lead_id}/payments   record money received in the company account; creates the realtor's commission (managers)

Pattern 28: get_current_org on every route. S1: org_id from the JWT only.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import commissions_service, realtor_service

router = APIRouter(tags=["realtor"])


class PaymentBody(BaseModel):
    amount_ngn: float = Field(..., gt=0, le=10_000_000_000)
    reference: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=1000)


def _managers_only(org: dict) -> None:
    if not commissions_service._can_manage(org):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Only managers can record payments."})


@router.get("/leads/{lead_id}/payments")
def list_lead_payments(lead_id: str, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _managers_only(org)
    return ok(realtor_service.list_payments(db, org["org_id"], lead_id))


@router.post("/leads/{lead_id}/payments", status_code=201)
def record_lead_payment(lead_id: str, body: PaymentBody, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    _managers_only(org)
    out = realtor_service.record_payment(db, org["org_id"], lead_id, body.amount_ngn, body.reference, body.note, org["id"])
    return ok(out, message="Payment recorded")
