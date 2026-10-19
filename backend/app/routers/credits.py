"""
app/routers/credits.py
----------------------
CREDITS-2 — a business's own credit wallet. Login required; owner / ops manager / admin only.
S1: the org always comes from the login, never from the request.

  GET  /credits/summary          balance, expiry, this month's spend
  GET  /credits/usage?days=30    spend per day and kind
  GET  /credits/ledger?before=   transaction list (newest first)
  GET  /credits/packs            packs + limits for a custom amount
  GET  /credits/orders           recent top-ups
  POST /credits/checkout         {pack_id} or {amount_naira} -> Paystack checkout url
  POST /credits/verify           {reference} after coming back from Paystack
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import credit_order_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_manager(org: dict) -> None:
    role = ((org.get("roles") or {}).get("template") or "").lower()
    if role not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner or an operations manager can see or buy credits.")


class CheckoutBody(BaseModel):
    pack_id: Optional[str] = Field(default=None, max_length=64)
    amount_naira: Optional[int] = Field(default=None, ge=1, le=10_000_000)


class VerifyBody(BaseModel):
    reference: str = Field(max_length=80)


@router.get("/credits/summary")
def get_summary(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(svc.summary(db, org["org_id"]))


@router.get("/credits/usage")
def get_usage(days: int = Query(default=30, ge=1, le=90), db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(svc.usage(db, org["org_id"], days))


@router.get("/credits/ledger")
def get_ledger(before: Optional[str] = Query(default=None, max_length=40), db=Depends(get_supabase),
               org=Depends(get_current_org)):
    _require_manager(org)
    return ok(svc.ledger(db, org["org_id"], before))


@router.get("/credits/packs")
def get_packs(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok({"packs": svc.list_packs(db), "min_custom_kobo": svc.MIN_CUSTOM_KOBO, "max_order_kobo": svc.MAX_ORDER_KOBO})


@router.get("/credits/orders")
def get_orders(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok({"orders": svc.orders(db, org["org_id"])})


@router.post("/credits/checkout")
def checkout(body: CheckoutBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    if bool(body.pack_id) == bool(body.amount_naira):
        raise HTTPException(status_code=422, detail="Choose a pack or enter an amount.")
    try:
        res = svc.create_order(db, org["org_id"], org.get("email") or "", pack_id=body.pack_id,
                               amount_kobo=(body.amount_naira * 100 if body.amount_naira else None),
                               callback_url=settings.FRONTEND_URL.rstrip("/") + "/?credits=1")
    except svc.CreditOrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(res)


@router.post("/credits/verify")
def verify(body: VerifyBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(svc.verify(db, org["org_id"], body.reference))
    except svc.CreditOrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
