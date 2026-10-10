"""
app/routers/site_addons.py
----------------------------
SITE-ADDONS A0-1 - staff routes for a site's tier and add-ons. Prefix: /api/v1

  GET  /site-addons/catalog                          tiers, add-ons, billing rules and the feature list (from Settings)
  GET  /sites/{site_id}/addons                       what this site has, which features are on, usage against caps
  PUT  /sites/{site_id}/addons                       staff grant a tier or add-on with no payment (optional end date)
  POST /sites/{site_id}/addons/{addon_id}/{action}   pause | resume | cancel

Pattern 28: org_id from get_current_org only. Read owner/admin/ops_manager, write owner/ops_manager (same as the rest
of the site engine). The whole feature 404s for an org without site_builder_settings.enabled (spec section 17).
Checkout, the client pay page and billing arrive in A0-2; this file only changes what a site is switched on for.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)
router = APIRouter()

_READ_ROLES = ("owner", "admin", "ops_manager")
_WRITE_ROLES = ("owner", "ops_manager")


def _require(org: dict, roles: tuple) -> None:
    if (((org.get("roles") or {}).get("template") or "").lower()) not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "You don't have access to the site engine."})


def _require_enabled(db, org_id: str) -> dict:
    data = (db.table("site_builder_settings").select("*").eq("org_id", org_id).limit(1).execute()).data
    row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
    if not row or not row.get("enabled"):
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Site engine is not enabled for this org."})
    return row


def _fail(exc: ent.EntitlementError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


class Payer(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=200)


class GrantRequest(BaseModel):
    kind: Literal["tier", "addon"]
    key: str = Field(..., min_length=1, max_length=40)
    until: Optional[datetime] = None            # None = no end date
    picks: list[str] = Field(default_factory=list, max_length=4)   # e.g. ["selling_catalog"] for Convert
    billing_mode: Literal["link", "auto"] = "link"
    payer: Optional[Payer] = None


class ResumeRequest(BaseModel):
    until: Optional[datetime] = None


@router.get("/site-addons/catalog")
def catalog(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    settings = _require_enabled(db, org["org_id"])
    cfg = ent.get_config(settings)
    return ok(data={
        "tiers": list(cfg["tiers"].values()),
        "addons": list(cfg["addons"].values()),
        "billing": cfg["billing"],
        "caps": reg.CAPS,
        "features": [{"key": k, **v} for k, v in reg.FEATURES.items()],
    })


@router.get("/sites/{site_id}/addons")
def site_addons(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        ent._site_exists(db, org["org_id"], site_id)
        return ok(data=ent.get_entitlements(db, org["org_id"], site_id))
    except ent.EntitlementError as exc:
        raise _fail(exc)


@router.put("/sites/{site_id}/addons")
def grant_addon(site_id: str, payload: GrantRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        data = ent.grant(
            db, org["org_id"], site_id, f"user:{org.get('id')}", payload.kind, payload.key,
            until=payload.until, picks=payload.picks, billing_mode=payload.billing_mode,
            payer=payload.payer.model_dump() if payload.payer else None)
    except ent.EntitlementError as exc:
        raise _fail(exc)
    return ok(data=data, message="Saved")


@router.post("/sites/{site_id}/addons/{addon_id}/{action}")
def change_addon(site_id: str, addon_id: str, action: str, payload: Optional[ResumeRequest] = None,
                 org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        data = ent.set_status(db, org["org_id"], site_id, addon_id, action, f"user:{org.get('id')}",
                              until=(payload.until if payload else None))
    except ent.EntitlementError as exc:
        raise _fail(exc)
    return ok(data=data, message="Saved")
