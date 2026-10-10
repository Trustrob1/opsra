"""
app/routers/site_capture.py
-----------------------------
SITE-ADDONS A1-1 - staff routes for a site's lead capture. Prefix: /api/v1

  GET  /sites/{site_id}/capture              the site key, form address, workspace, 30-day counts, which features are on
  POST /sites/{site_id}/capture/rotate-key   switch the old key off and make a new one (pages with the old key stop capturing)

Pattern 28: org_id from get_current_org only. Read owner/admin/ops_manager, write owner/ops_manager. 404 if the site engine is off.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.routers.site_addons import _READ_ROLES, _WRITE_ROLES, _fail, _require, _require_enabled
from app.services import site_capture_service as cap
from app.services import site_entitlement_service as ent

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sites/{site_id}/capture")
def get_capture(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=cap.summary(db, org["org_id"], site_id))
    except ent.EntitlementError as exc:
        raise _fail(exc)


@router.post("/sites/{site_id}/capture/rotate-key")
def rotate(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        ent._site_exists(db, org["org_id"], site_id)
        cap.rotate_key(db, org["org_id"], site_id)
        ent._log_event(db, org["org_id"], site_id, f"user:{org.get('id')}", "site_key_rotated", {})
        return ok(data=cap.summary(db, org["org_id"], site_id), message="New key made")
    except ent.EntitlementError as exc:
        raise _fail(exc)
