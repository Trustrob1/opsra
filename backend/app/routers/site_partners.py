"""
app/routers/site_partners.py
------------------------------
PARTNER-1A — Launch Partners.

  public_router  (prefix /api/v1)          POST /partner-links/{slug}/open   — no login; the slug is the credential.
  router         (prefix /api/v1/partners) staff only: list / create / suspend / reactivate.

Pattern 28: org_id from get_current_org only (staff routes). Pattern 37: org["roles"]["template"].
Read: owner, admin, ops_manager. Write: owner, ops_manager (same convention as routers/sites.py).
The public route's rate limit is a simple in-process counter like routers/public_forms.py.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import site_partner_apply_service as apply_svc
from app.services import site_partner_service

logger = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()

_READ_ROLES = ("owner", "admin", "ops_manager")
_WRITE_ROLES = ("owner", "ops_manager")

_OPEN_LIMIT_PER_MIN = 20
_open_hits: dict[str, list[float]] = defaultdict(list)


def _role(org: dict) -> str:
    return ((org.get("roles") or {}).get("template") or "")


def _require(org: dict, roles: tuple) -> None:
    if _role(org) not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "FORBIDDEN", "message": "You don't have access to partners."})


def _rate_limited(key: str) -> bool:
    now = time.time()
    hits = [t for t in _open_hits[key] if now - t < 60]
    hits.append(now)
    _open_hits[key] = hits
    if len(_open_hits) > 10_000:
        _open_hits.clear()
    return len(hits) > _OPEN_LIMIT_PER_MIN


# ───────────────────────────── public: open a partner's permanent link ─────────────────────────────

@public_router.post("/partner-links/{slug}/open")
def open_partner_link(slug: str, request: Request, db=Depends(get_supabase)):
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED", "message": "Too many requests. Please try again in a minute."})
    try:
        result = site_partner_service.open_link(db, slug)
    except Exception:  # S14
        logger.exception("[PARTNER-1A] open_link failed")
        raise HTTPException(status_code=503, detail={"code": "UNAVAILABLE", "message": "We couldn't open this link right now. Please try again shortly."})
    kind = result["kind"]
    if kind == "ok":
        return ok(data={"url": result["url"]})
    if kind == "inactive":
        raise HTTPException(status_code=410, detail={"code": "INACTIVE", "message": "This link is not active."})
    if kind == "busy":
        raise HTTPException(status_code=429, detail={"code": "BUSY", "message": "This link is very busy right now. Please try again later."})
    raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "This link isn't valid."})


# ───────────────────────────── staff ─────────────────────────────

class PartnerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=32)
    email: Optional[str] = Field(default=None, max_length=255)
    agency_name: Optional[str] = Field(default=None, max_length=200)


@router.get("")
def list_partners(org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=site_partner_service.list_partners(db, org["org_id"]))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_partner(payload: PartnerCreate, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        partner = site_partner_service.create_partner(
            db, org["org_id"], payload.full_name, payload.phone, payload.email, payload.agency_name)
    except site_partner_service.PartnerError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=partner, message="Partner created")


def _set(partner_id: str, new_status: str, org, db):
    _require(org, _WRITE_ROLES)
    try:
        row = site_partner_service.set_status(db, org["org_id"], partner_id, new_status)
    except site_partner_service.PartnerError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Partner not found"})
    return ok(data={"id": partner_id, "status": new_status})


@router.post("/{partner_id}/suspend")
def suspend_partner(partner_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    return _set(partner_id, "suspended", org, db)


@router.post("/{partner_id}/reactivate")
def reactivate_partner(partner_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    return _set(partner_id, "active", org, db)


# ───────────────────────────── PARTNER-1B: applications ─────────────────────────────

@router.get("/applications")
def list_applications(status: Optional[str] = "applied", org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    return ok(data=apply_svc.list_applications(db, org["org_id"], status or None))


@router.post("/applications/{application_id}/approve")
def approve_application(application_id: str, background_tasks: BackgroundTasks,
                        org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        partner = apply_svc.approve(db, org["org_id"], application_id,
                                    send_login_link=lambda ident: background_tasks.add_task(apply_svc.request_login_link, ident))
    except apply_svc.ApplyError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data=partner, message="Partner approved")


@router.post("/applications/{application_id}/decline")
def decline_application(application_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    try:
        apply_svc.decline(db, org["org_id"], application_id)
    except apply_svc.ApplyError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    return ok(data={"id": application_id, "status": "declined"})
