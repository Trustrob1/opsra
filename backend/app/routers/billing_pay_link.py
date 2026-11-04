"""
app/routers/billing_pay_link.py
-------------------------------
BILL-4 - invoice-style Billing link.

  Public (no login; the token names the business):
    GET  /public/billing/pay/{token}            plan, credit, what renewing costs, top-up packs
    POST /public/billing/pay/{token}/renew      -> Paystack checkout url (same plan, same period)
    POST /public/billing/pay/{token}/topup      {pack_id | amount_naira} -> Paystack checkout url
    POST /public/billing/pay/{token}/verify     {reference} after coming back from Paystack
  Staff (login; owner / ops manager / admin):
    POST   /billing/pay-link   make a link (ends any earlier one); the url is shown once
    GET    /billing/pay-link   the current link's dates and use count (no url)
    DELETE /billing/pay-link   end it now
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import account_plan_billing_service as plans
from app.services import billing_pay_link_service as svc
from app.services import credit_order_service as cos
from app.services import webchat_service as wc
from app.services.site_capture_service import ip_hash

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _limit(request: Request, bucket: str, limit: int, window: int) -> None:
    if wc.rate_limited(f"bpl:{bucket}:{ip_hash(_client_ip(request))}", limit, window):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")


def _require_manager(org: dict) -> None:
    role = ((org.get("roles") or {}).get("template") or "").lower()
    if role not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or an operations manager can share a billing link.")


def _link(db, token: str) -> dict:
    try:
        return svc.resolve(db, token)
    except svc.LinkError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _callback(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/pay/{token}"


class TopupBody(BaseModel):
    pack_id: Optional[str] = Field(default=None, max_length=64)
    amount_naira: Optional[int] = Field(default=None, ge=1, le=10_000_000)


class VerifyBody(BaseModel):
    reference: str = Field(max_length=80)


# ----------------------------- public -----------------------------

@router.get("/public/billing/pay/{token}")
def public_view(token: str, request: Request, response: Response, db=Depends(get_supabase)):
    response.headers["Cache-Control"] = "no-store"
    _limit(request, "view", 120, 60)
    return ok(svc.public_view(db, _link(db, token)))


@router.post("/public/billing/pay/{token}/renew")
def public_renew(token: str, request: Request, response: Response, db=Depends(get_supabase)):
    response.headers["Cache-Control"] = "no-store"
    _limit(request, "pay", 20, 60)
    link = _link(db, token)
    try:
        return ok(svc.renew(db, link, _callback(token)))
    except plans.PlanBillingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/public/billing/pay/{token}/topup")
def public_topup(token: str, body: TopupBody, request: Request, response: Response, db=Depends(get_supabase)):
    response.headers["Cache-Control"] = "no-store"
    _limit(request, "pay", 20, 60)
    link = _link(db, token)
    if bool(body.pack_id) == bool(body.amount_naira):
        raise HTTPException(status_code=422, detail="Choose a pack or enter an amount.")
    try:
        res = cos.create_order(db, link["org_id"], link.get("payer_email") or "", pack_id=body.pack_id,
                               amount_kobo=(body.amount_naira * 100 if body.amount_naira else None), callback_url=_callback(token))
    except cos.CreditOrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok({"checkout_url": res["checkout_url"], "reference": res["reference"]})


@router.post("/public/billing/pay/{token}/verify")
def public_verify(token: str, body: VerifyBody, request: Request, response: Response, db=Depends(get_supabase)):
    response.headers["Cache-Control"] = "no-store"
    _limit(request, "verify", 60, 60)
    link = _link(db, token)
    try:
        return ok(svc.verify(db, link, body.reference))
    except (plans.PlanBillingError, cos.CreditOrderError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ----------------------------- staff -----------------------------

@router.post("/billing/pay-link")
def create_link(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    try:
        made = svc.create(db, org["org_id"], user_id=org.get("id"), label=org.get("full_name") or org.get("email") or "",
                          email=org.get("email") or "")
    except svc.LinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok({"url": f"{settings.FRONTEND_URL.rstrip('/')}/pay/{made['token']}", "expires_at": made["expires_at"]})


@router.get("/billing/pay-link")
def link_status(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok({"link": svc.status(db, org["org_id"])})


@router.delete("/billing/pay-link")
def end_link(db=Depends(get_supabase), org=Depends(get_current_org)):
    _require_manager(org)
    return ok({"ended": svc.revoke(db, org["org_id"])})
