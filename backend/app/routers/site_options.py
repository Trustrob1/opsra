"""
app/routers/site_options.py
-----------------------------
SITE-OPTIONS OPT-1 - builder and staff routes for option sets (several designs for one client behind one link).

Builder (get_current_builder), prefix /api/v1/builder:
  GET    /option-sets                         my sets
  POST   /option-sets                         {client_name?, site_ids?}  make a set (the link is in the result)
  GET    /option-sets/{set_id}                one set with its designs and link
  POST   /option-sets/{set_id}/sites          {site_id, label?}          add one of my sites
  DELETE /option-sets/{set_id}/sites/{site_id}                            take a site out (free-sites limit applies again)
  POST   /option-sets/{set_id}/choose         {item_id}                  pick on the client's behalf
  POST   /option-sets/{set_id}/close                                     close a set nobody picked from

Staff (get_current_org), prefix /api/v1: same under /site-option-sets, plus builder_id on create/list.
Pattern 28: org_id from the dependency only. Read owner/admin/ops_manager, write owner/ops_manager.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.routers.builder_portal import get_current_builder
from app.routers.site_addons import _READ_ROLES, _WRITE_ROLES, _require, _require_enabled
from app.services import site_option_service as opt

logger = logging.getLogger(__name__)
builder_router = APIRouter(prefix="/builder", tags=["site-options-builder"])
staff_router = APIRouter(prefix="/site-option-sets", tags=["site-options"])


def _fail(exc: opt.OptionError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


class CreateSet(BaseModel):
    client_name: Optional[str] = Field(None, max_length=120)
    site_ids: List[str] = Field(default_factory=list, max_length=10)


class StaffCreateSet(CreateSet):
    builder_id: str


class AttachSite(BaseModel):
    site_id: str
    label: Optional[str] = Field(None, max_length=60)


class ChooseItem(BaseModel):
    item_id: str


# ─────────────────────────────── builder ───────────────────────────────

@builder_router.get("/option-sets")
def b_list(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    return ok(data=opt.list_sets(db, builder["org_id"], builder["id"]))


@builder_router.post("/option-sets", status_code=201)
def b_create(payload: CreateSet, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=opt.create_set(db, builder["org_id"], builder["id"], payload.client_name,
                                      f"builder:{builder['id']}", payload.site_ids), message="Option set created")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.get("/option-sets/{set_id}")
def b_get(set_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=opt.get_set(db, builder["org_id"], set_id, builder["id"]))
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/option-sets/{set_id}/sites")
def b_attach(set_id: str, payload: AttachSite, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=opt.attach_site(db, builder["org_id"], set_id, payload.site_id, payload.label,
                                       f"builder:{builder['id']}", builder["id"]), message="Design added")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.delete("/option-sets/{set_id}/sites/{site_id}")
def b_detach(set_id: str, site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=opt.detach_site(db, builder["org_id"], set_id, site_id, f"builder:{builder['id']}", builder["id"]),
                  message="Design removed from the set")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/option-sets/{set_id}/choose")
def b_choose(set_id: str, payload: ChooseItem, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        r = opt.choose_for_client(db, builder["org_id"], set_id, payload.item_id, f"builder:{builder['id']}", builder["id"])
        return ok(data={**r, "set": opt.get_set(db, builder["org_id"], set_id, builder["id"])}, message="Choice saved")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/option-sets/{set_id}/close")
def b_close(set_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=opt.close_set(db, builder["org_id"], set_id, f"builder:{builder['id']}", builder["id"]), message="Set closed")
    except opt.OptionError as exc:
        raise _fail(exc)


# ─────────────────────────────── staff ───────────────────────────────

@staff_router.get("")
def s_list(builder_id: Optional[str] = None, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    return ok(data=opt.list_sets(db, org["org_id"], builder_id))


@staff_router.post("", status_code=201)
def s_create(payload: StaffCreateSet, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=opt.create_set(db, org["org_id"], payload.builder_id, payload.client_name,
                                      f"user:{org.get('id')}", payload.site_ids), message="Option set created")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.get("/{set_id}")
def s_get(set_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=opt.get_set(db, org["org_id"], set_id))
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{set_id}/sites")
def s_attach(set_id: str, payload: AttachSite, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=opt.attach_site(db, org["org_id"], set_id, payload.site_id, payload.label, f"user:{org.get('id')}"),
                  message="Design added")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.delete("/{set_id}/sites/{site_id}")
def s_detach(set_id: str, site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=opt.detach_site(db, org["org_id"], set_id, site_id, f"user:{org.get('id')}"),
                  message="Design removed from the set")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{set_id}/choose")
def s_choose(set_id: str, payload: ChooseItem, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        r = opt.choose_for_client(db, org["org_id"], set_id, payload.item_id, f"user:{org.get('id')}")
        return ok(data={**r, "set": opt.get_set(db, org["org_id"], set_id)}, message="Choice saved")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{set_id}/close")
def s_close(set_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=opt.close_set(db, org["org_id"], set_id, f"user:{org.get('id')}"), message="Set closed")
    except opt.OptionError as exc:
        raise _fail(exc)
