"""
app/routers/superadmin_plans.py
-------------------------------
ACCOUNT-PLANS AP-1 - superadmin controls for account plans. Bearer superadmin JWT.

  GET   /superadmin/plans/orgs                      every business with its plan, status and enforcement
  GET   /superadmin/plans/orgs/{org_id}             one business: entitlements (features, caps, usage)
  POST  /superadmin/plans/orgs/{org_id}/grant       give a tier or add-on with no payment (staff or grandfathered)
  POST  /superadmin/plans/orgs/{org_id}/status      pause, resume or cancel a plan row
  PATCH /superadmin/plans/orgs/{org_id}/enforce     switch plan enforcement on or off for this business
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.models.common import ok
from app.routers.superadmin_health import require_superadmin
from app.services import account_entitlement_service as acc

logger = logging.getLogger(__name__)
router = APIRouter()


class GrantBody(BaseModel):
    kind: Literal["tier", "addon"]
    key: str = Field(min_length=1, max_length=40)
    until: Optional[datetime] = None
    source: Literal["staff", "grandfathered"] = "staff"
    picks: Optional[list[str]] = None


class StatusBody(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    action: Literal["pause", "resume", "cancel"]
    until: Optional[datetime] = None


class EnforceBody(BaseModel):
    enforced: bool


def _actor(sa) -> str:
    return str((sa or {}).get("email") or (sa or {}).get("sub") or "superadmin")[:120] if isinstance(sa, dict) else "superadmin"


def _fail(exc: Exception):
    if isinstance(exc, acc.EntitlementError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    logger.exception("account plans route failed")
    raise HTTPException(status_code=500, detail="Something went wrong. Try again.")


@router.get("/superadmin/plans/orgs")
def list_orgs(db=Depends(get_supabase), sa=Depends(require_superadmin)):
    try:
        return ok(acc.overview(db))
    except Exception as exc:
        _fail(exc)


@router.get("/superadmin/plans/orgs/{org_id}")
def one_org(org_id: str, db=Depends(get_supabase), sa=Depends(require_superadmin)):
    try:
        return ok(acc.get_entitlements(db, org_id))
    except Exception as exc:
        _fail(exc)


@router.post("/superadmin/plans/orgs/{org_id}/grant")
def grant(org_id: str, body: GrantBody, db=Depends(get_supabase), sa=Depends(require_superadmin)):
    try:
        return ok(acc.grant(db, org_id, _actor(sa), body.kind, body.key, until=body.until, source=body.source,
                            picks=body.picks), message="Plan updated")
    except Exception as exc:
        _fail(exc)


@router.post("/superadmin/plans/orgs/{org_id}/status")
def status(org_id: str, body: StatusBody, db=Depends(get_supabase), sa=Depends(require_superadmin)):
    try:
        return ok(acc.set_status(db, org_id, body.plan_id, body.action, _actor(sa), until=body.until), message="Plan updated")
    except Exception as exc:
        _fail(exc)


@router.patch("/superadmin/plans/orgs/{org_id}/enforce")
def enforce(org_id: str, body: EnforceBody, db=Depends(get_supabase), sa=Depends(require_superadmin)):
    try:
        return ok(acc.set_enforced(db, org_id, body.enforced, _actor(sa)),
                  message="Plans are now enforced for this business" if body.enforced else "Plans are no longer enforced for this business")
    except Exception as exc:
        _fail(exc)
