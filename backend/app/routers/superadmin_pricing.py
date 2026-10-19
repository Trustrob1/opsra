"""
app/routers/superadmin_pricing.py
---------------------------------
ACCOUNT-PLANS AP-8 - Opsra Pricing. The prices and plan contents every business on Opsra is sold: Capture / Convert / Grow,
add-ons (including the extra-user seat price), billing rules and discount codes. Superadmin login only (Bearer superadmin JWT).
The values live in the platform organisation's site_builder_settings row (the one PLATFORM_ORG_ID names), exactly where the
plan billing already reads them, so nothing has to be copied or migrated.

  GET    /superadmin/pricing/context               which organisation holds the values
  GET    /superadmin/pricing/settings              the pricing blob
  PATCH  /superadmin/pricing/settings              {pricing} - checked, then saved
  GET    /superadmin/pricing/catalog               plans, add-ons, billing rules, caps and every feature (for the ticks)
  GET    /superadmin/pricing/discount-codes        list
  POST   /superadmin/pricing/discount-codes        create
  PATCH  /superadmin/pricing/discount-codes/{id}   change
  DELETE /superadmin/pricing/discount-codes/{id}   remove
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase
from app.models.common import ok
from app.routers.superadmin_health import require_superadmin
from app.services import platform_guard
from app.services import site_discount_service as disc
from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg

logger = logging.getLogger(__name__)
router = APIRouter()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _platform(db) -> str:
    pid = platform_guard.platform_id(db)
    if not pid:
        raise HTTPException(status_code=422, detail="The Opsra organisation is not set up yet. Set PLATFORM_ORG_ID.")
    return pid


def _row(db, pid: str) -> dict:
    return _one((db.table("site_builder_settings").select("*").eq("org_id", pid).limit(1).execute()).data) or {}


def _bad(exc) -> HTTPException:
    return HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})


@router.get("/superadmin/pricing/context")
def context(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    pid = _platform(db)
    org = _one((db.table("organisations").select("id, name").eq("id", pid).limit(1).execute()).data) or {}
    return ok(data={"org_id": pid, "org_name": org.get("name")})


@router.get("/superadmin/pricing/settings")
def get_settings(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(data=_row(db, _platform(db)))


@router.patch("/superadmin/pricing/settings")
def patch_settings(payload: dict, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    pid = _platform(db)
    pricing = (payload or {}).get("pricing")
    if not isinstance(pricing, dict):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Send the pricing to save."})
    from app.routers import sites as sites_router
    sites_router._check_builder_access(pricing)
    sites_router._check_site_tiers(pricing)
    updates = {"pricing": pricing, "updated_at": datetime.now(timezone.utc).isoformat()}
    if _one((db.table("site_builder_settings").select("org_id").eq("org_id", pid).limit(1).execute()).data):
        db.table("site_builder_settings").update(updates).eq("org_id", pid).execute()
    else:
        db.table("site_builder_settings").insert({**updates, "org_id": pid}).execute()
    return ok(data=_row(db, pid), message="Pricing saved")


@router.get("/superadmin/pricing/catalog")
def catalog(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    cfg = ent.get_config(_row(db, _platform(db)))
    return ok(data={"tiers": list(cfg["tiers"].values()), "addons": list(cfg["addons"].values()), "billing": cfg["billing"],
                    "caps": reg.CAPS, "features": [{"key": k, **v} for k, v in reg.FEATURES.items()]})


@router.get("/superadmin/pricing/discount-codes")
def list_codes(_: None = Depends(require_superadmin), db=Depends(get_supabase)):
    return ok(data=disc.list_codes(db, _platform(db)))


@router.post("/superadmin/pricing/discount-codes")
def create_code(payload: dict, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    try:
        return ok(data=disc.create_code(db, _platform(db), payload), message="Code created")
    except disc.DiscountError as exc:
        raise _bad(exc)


@router.patch("/superadmin/pricing/discount-codes/{code_id}")
def update_code(code_id: str, payload: dict, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    try:
        return ok(data=disc.update_code(db, _platform(db), code_id, payload), message="Code saved")
    except disc.DiscountError as exc:
        raise _bad(exc)


@router.delete("/superadmin/pricing/discount-codes/{code_id}")
def delete_code(code_id: str, _: None = Depends(require_superadmin), db=Depends(get_supabase)):
    try:
        disc.delete_code(db, _platform(db), code_id)
    except disc.DiscountError as exc:
        raise _bad(exc)
    return ok(data={"id": code_id}, message="Code removed")
