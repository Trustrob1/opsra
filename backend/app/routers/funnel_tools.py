"""
app/routers/funnel_tools.py
----------------------------
FUNNEL-1B — dashboard tool routes for Event Funnels. Prefix: /api/v1  (paths start /funnels/{funnel_id}/…)

Same RBAC as routers/funnels.py: read = owner/admin/ops_manager, write = owner/ops_manager.
S1/S2: org_id from get_current_org only. Pattern 28/37.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.models.funnel_tools import AdSpendPut, BroadcastCreate, PreviewRequest
from app.routers.funnels import _READ_ROLES, _WRITE_ROLES, _get_funnel, _get_reg, _require
from app.services import funnel_tools_service as tools
from app.services.funnel_tools_service import FunnelToolError

logger = logging.getLogger(__name__)
router = APIRouter()


def _raise(exc: FunnelToolError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.get("/funnels/{funnel_id}/overview")
def funnel_overview(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    return ok(data=tools.get_overview(db, org["org_id"], f))


@router.get("/funnels/{funnel_id}/ad-spend")
def get_ad_spend(funnel_id: str, date_from: Optional[date] = Query(None, alias="from"),
                 date_to: Optional[date] = Query(None, alias="to"),
                 org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    rows = tools.get_ad_spend(db, org["org_id"], funnel_id,
                              date_from.isoformat() if date_from else None, date_to.isoformat() if date_to else None)
    return ok(data=rows)


@router.put("/funnels/{funnel_id}/ad-spend")
def put_ad_spend(funnel_id: str, payload: AdSpendPut, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    n = tools.put_ad_spend(db, org["org_id"], funnel_id, [r.model_dump() for r in payload.rows])
    return ok(data={"saved": n}, message="Ad spend saved")


@router.post("/funnels/{funnel_id}/preview")
def preview(funnel_id: str, payload: PreviewRequest, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    if not (payload.message_key or payload.step_key or payload.text):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Give message_key, step_key or text."})
    try:
        return ok(data=tools.render_preview(f, payload.model_dump(mode="json")))
    except FunnelToolError as exc:
        _raise(exc)


@router.delete("/funnels/{funnel_id}/registrations/{reg_id}")
def reset_test_lead(funnel_id: str, reg_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    try:
        tools.reset_registration(db, org["org_id"], funnel_id, reg)
    except FunnelToolError as exc:
        _raise(exc)
    return ok(message="Lead reset — their next message starts the funnel again")


@router.post("/funnels/{funnel_id}/duplicate-as-test", status_code=status.HTTP_201_CREATED)
def duplicate_as_test(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    return ok(data=tools.duplicate_as_test(db, org["org_id"], f), message="Test funnel created as a draft")


@router.get("/funnels/{funnel_id}/gmail-list")
def gmail_list(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    return ok(data=tools.gmail_list(db, org["org_id"], funnel_id))


@router.get("/funnels/{funnel_id}/registrations/{reg_id}/events")
def registration_events(funnel_id: str, reg_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    _get_reg(db, org["org_id"], funnel_id, reg_id)
    return ok(data=tools.registration_events(db, org["org_id"], funnel_id, reg_id))


@router.post("/funnels/{funnel_id}/registrations/{reg_id}/ask-gmail")
def ask_gmail(funnel_id: str, reg_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    reg = _get_reg(db, org["org_id"], funnel_id, reg_id)
    if not tools.ask_for_gmail(db, org["org_id"], f, reg):
        raise HTTPException(503, detail={"code": "INTEGRATION_ERROR",
                                         "message": "WhatsApp didn't accept the message (outside the 24-hour window?)."})
    return ok(message="Gmail request sent")


@router.get("/funnels/{funnel_id}/broadcasts")
def list_broadcasts(funnel_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    return ok(data=tools.list_broadcasts(db, org["org_id"], funnel_id))


@router.post("/funnels/{funnel_id}/broadcasts")
def create_broadcast(funnel_id: str, payload: BroadcastCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    f = _get_funnel(db, org["org_id"], funnel_id)
    try:
        data = tools.create_broadcast(db, org["org_id"], f, payload.model_dump(), org["id"])
    except FunnelToolError as exc:
        _raise(exc)
    return ok(data=data, message=None if payload.dry_run else "Broadcast queued — sending starts within 5 minutes")


@router.post("/funnels/{funnel_id}/broadcasts/{broadcast_id}/cancel")
def cancel_broadcast(funnel_id: str, broadcast_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _get_funnel(db, org["org_id"], funnel_id)
    try:
        return ok(data=tools.cancel_broadcast(db, org["org_id"], funnel_id, broadcast_id), message="Broadcast cancelled")
    except FunnelToolError as exc:
        _raise(exc)
