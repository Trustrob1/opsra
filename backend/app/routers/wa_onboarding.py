"""
app/routers/wa_onboarding.py
----------------------------
WA-AUTO-3 - first-login wizard routes. Only for WhatsApp-automation-only businesses (anyone else gets 404). Owner or ops manager.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import product_mode, wa_onboarding_service as svc

router = APIRouter()


def _guard(org: dict, db) -> None:
    if not product_mode.is_wa_automation(db, org["org_id"]):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Not found."})
    template = ((org.get("roles") or {}).get("template") or "").lower() if isinstance(org.get("roles"), dict) else ""
    if template not in ("owner", "ops_manager"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Only the owner or an ops manager can set this up."})


class BasicsPayload(BaseModel):
    what_you_sell: str = Field(..., max_length=2000)
    hours: str = Field(..., max_length=500)
    language: str = Field(..., max_length=40)


class SetupRequestPayload(BaseModel):
    phone: str = Field(..., max_length=60)
    note: Optional[str] = Field(None, max_length=1000)


@router.get("/wa-onboarding")
def get_state(org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=svc.state(db, org["org_id"]))


@router.put("/wa-onboarding/basics")
def put_basics(payload: BasicsPayload, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=svc.save_basics(db, org["org_id"], payload.what_you_sell, payload.hours, payload.language, org["id"]))


@router.post("/wa-onboarding/request-setup")
def post_request_setup(payload: SetupRequestPayload, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=svc.request_setup(db, org["org_id"], org["id"], payload.phone, payload.note or ""))


@router.get("/wa-onboarding/test-status")
def get_test_status(org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=svc.test_status(db, org["org_id"]))


@router.post("/wa-onboarding/complete")
def post_complete(org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=svc.complete(db, org["org_id"]))
