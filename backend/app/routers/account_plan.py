"""
app/routers/account_plan.py
---------------------------
ACCOUNT-PLANS AP-2 - an organisation's own Capture / Convert / Grow plan. Login required; owner / ops manager / admin only.
S1: the org always comes from the login, never from the request. Amounts are never accepted from the browser.

  GET    /billing/plan                 current plan, plans for sale, recent orders
  POST   /billing/plan/preview         {key, code?} what choosing a plan would cost
  POST   /billing/plan/checkout        {key, code?} -> Paystack checkout url (or {scheduled: true} for a downgrade)
  POST   /billing/plan/verify          {reference} after coming back from Paystack
  DELETE /billing/plan/pending-change  cancel a scheduled downgrade
  GET    /billing/plan/orders          recent plan payments
  GET    /billing/team                 users, included and paid seats
  POST   /billing/team/seats/preview   {add}
  POST   /billing/team/seats/checkout  {add} -> Paystack checkout url
  POST   /billing/team/seats/next      {quantity} fewer seats at next renewal
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import account_plan_billing_service as svc
from app.services import account_seat_service as seatsvc
from app.services import platform_guard
from app.services import product_mode

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_manager(org: dict) -> None:
    role = ((org.get("roles") or {}).get("template") or "").lower()
    if role not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner or an operations manager can manage the plan.")


class PlanBody(BaseModel):
    key: str = Field(max_length=40)
    code: Optional[str] = Field(default=None, max_length=60)


class VerifyBody(BaseModel):
    reference: str = Field(max_length=80)


@router.get("/billing/plan")
def get_plan(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(svc.summary(db, org["org_id"]))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/billing/plan/orders")
def get_orders(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok({"orders": svc.orders(db, org["org_id"], 30)})


@router.post("/billing/plan/preview")
def preview(body: PlanBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(svc.preview(db, org["org_id"], body.key, body.code))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/billing/plan/checkout")
def checkout(body: PlanBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        res = svc.checkout(db, org["org_id"], key=body.key, email=org.get("email") or "", user_id=org.get("id"),
                           code=body.code, callback_url=settings.FRONTEND_URL.rstrip("/") + "/?plan=1")
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(res)


@router.post("/billing/plan/verify")
def verify(body: VerifyBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(svc.verify(db, org["org_id"], body.reference))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/billing/plan/pending-change")
def clear_pending(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(svc.clear_pending_change(db, org["org_id"], org.get("id") or "owner"))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class SeatsBody(BaseModel):
    add: int = Field(ge=1, le=50)


class NextSeatsBody(BaseModel):
    quantity: int = Field(ge=0, le=500)


@router.get("/billing/team")
def get_team(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok(seatsvc.team(db, org["org_id"]))


@router.post("/billing/team/seats/preview")
def seats_preview(body: SeatsBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(seatsvc.preview_seats(db, org["org_id"], body.add))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/billing/team/seats/checkout")
def seats_checkout(body: SeatsBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        res = seatsvc.checkout_seats(db, org["org_id"], add=body.add, email=org.get("email") or "", user_id=org.get("id"),
                                     callback_url=settings.FRONTEND_URL.rstrip("/") + "/?plan=1")
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(res)


@router.post("/billing/team/seats/next")
def seats_next(body: NextSeatsBody, db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        return ok(seatsvc.set_next_seats(db, org["org_id"], body.quantity, org.get("id") or "owner"))
    except svc.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/platform/status")
def platform_status(db=Depends(get_supabase), org=Depends(get_current_org)):
    """Is the signed-in organisation Opsra's own (the platform organisation)? The app uses this to show or hide Opsra-only
    areas (Sites, Superadmin). It hides things; the server checks again on every protected route."""
    return ok({"is_platform": platform_guard.is_platform(db, org.get("org_id")),
               "product_mode": product_mode.get_mode(db, org.get("org_id"))})   # WA-AUTO-1
