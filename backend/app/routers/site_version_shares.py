"""
app/routers/site_version_shares.py
------------------------------------
SITE-OPTIONS OPT-3 - builder and staff routes for sharing several versions of one Premium site behind one link.

Builder (get_current_builder), prefix /api/v1/builder:
  GET    /version-shares                          my links
  GET    /version-shares/sites                    my Premium sites with 2+ saved versions
  GET    /version-shares/sites/{site_id}/versions the saved versions of one site
  POST   /version-shares                          {site_id, client_name?, design_ids}  (the link is in the result)
  GET    /version-shares/{share_id}               one link with its versions
  POST   /version-shares/{share_id}/versions      {design_id, label?}
  DELETE /version-shares/{share_id}/versions/{item_id}
  POST   /version-shares/{share_id}/choose        {item_id}   record the client's pick (makes it the live preview)
  POST   /version-shares/{share_id}/close
Staff (get_current_org), prefix /api/v1: same under /site-version-shares; list/sites take builder_id.
Static routes are declared before /{share_id} (Pattern 53). Pattern 28: org_id from the dependency only.
Read owner/admin/ops_manager, write owner/ops_manager.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.routers.builder_portal import get_current_builder
from app.routers.site_addons import _READ_ROLES, _WRITE_ROLES, _require, _require_enabled
from app.services import site_option_service as opt
from app.services import site_version_share_service as ver

builder_router = APIRouter(prefix="/builder", tags=["site-versions-builder"])
staff_router = APIRouter(prefix="/site-version-shares", tags=["site-versions"])


def _fail(exc: opt.OptionError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


class CreateShare(BaseModel):
    site_id: str
    client_name: Optional[str] = Field(None, max_length=120)
    design_ids: List[str] = Field(default_factory=list, max_length=10)


class AddVersion(BaseModel):
    design_id: str
    label: Optional[str] = Field(None, max_length=60)


class ChooseItem(BaseModel):
    item_id: str


# ─────────────────────────────── builder ───────────────────────────────

@builder_router.get("/version-shares")
def b_list(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    return ok(data=ver.list_shares(db, builder["org_id"], builder["id"]))


@builder_router.get("/version-shares/sites")
def b_sites(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    return ok(data=ver.premium_sites(db, builder["org_id"], builder["id"]))


@builder_router.get("/version-shares/sites/{site_id}/versions")
def b_site_versions(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.site_versions(db, builder["org_id"], site_id, builder["id"]))
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/version-shares", status_code=201)
def b_create(payload: CreateShare, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.create_share(db, builder["org_id"], payload.site_id, payload.client_name, payload.design_ids,
                                        f"builder:{builder['id']}", builder["id"]), message="Version link created")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.get("/version-shares/{share_id}")
def b_get(share_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.get_share(db, builder["org_id"], share_id, builder["id"]))
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/version-shares/{share_id}/versions")
def b_add(share_id: str, payload: AddVersion, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.add_version(db, builder["org_id"], share_id, payload.design_id, payload.label,
                                       f"builder:{builder['id']}", builder["id"]), message="Version added")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.delete("/version-shares/{share_id}/versions/{item_id}")
def b_remove(share_id: str, item_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.remove_version(db, builder["org_id"], share_id, item_id, f"builder:{builder['id']}", builder["id"]),
                  message="Version removed")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/version-shares/{share_id}/choose")
def b_choose(share_id: str, payload: ChooseItem, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        r = ver.choose_for_client(db, builder["org_id"], share_id, payload.item_id, f"builder:{builder['id']}", builder["id"])
        return ok(data={**r, "set": ver.get_share(db, builder["org_id"], share_id, builder["id"])}, message="Choice saved")
    except opt.OptionError as exc:
        raise _fail(exc)


@builder_router.post("/version-shares/{share_id}/close")
def b_close(share_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    try:
        return ok(data=ver.close_share(db, builder["org_id"], share_id, f"builder:{builder['id']}", builder["id"]), message="Link closed")
    except opt.OptionError as exc:
        raise _fail(exc)


# ─────────────────────────────── staff ───────────────────────────────

@staff_router.get("")
def s_list(builder_id: Optional[str] = None, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    return ok(data=ver.list_shares(db, org["org_id"], builder_id))


@staff_router.get("/sites")
def s_sites(builder_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    return ok(data=ver.premium_sites(db, org["org_id"], builder_id))


@staff_router.get("/sites/{site_id}/versions")
def s_site_versions(site_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.site_versions(db, org["org_id"], site_id))
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("", status_code=201)
def s_create(payload: CreateShare, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.create_share(db, org["org_id"], payload.site_id, payload.client_name, payload.design_ids,
                                        f"user:{org.get('id')}"), message="Version link created")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.get("/{share_id}")
def s_get(share_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _READ_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.get_share(db, org["org_id"], share_id))
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{share_id}/versions")
def s_add(share_id: str, payload: AddVersion, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.add_version(db, org["org_id"], share_id, payload.design_id, payload.label, f"user:{org.get('id')}"),
                  message="Version added")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.delete("/{share_id}/versions/{item_id}")
def s_remove(share_id: str, item_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.remove_version(db, org["org_id"], share_id, item_id, f"user:{org.get('id')}"), message="Version removed")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{share_id}/choose")
def s_choose(share_id: str, payload: ChooseItem, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        r = ver.choose_for_client(db, org["org_id"], share_id, payload.item_id, f"user:{org.get('id')}")
        return ok(data={**r, "set": ver.get_share(db, org["org_id"], share_id)}, message="Choice saved")
    except opt.OptionError as exc:
        raise _fail(exc)


@staff_router.post("/{share_id}/close")
def s_close(share_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _require(org, _WRITE_ROLES)
    _require_enabled(db, org["org_id"])
    try:
        return ok(data=ver.close_share(db, org["org_id"], share_id, f"user:{org.get('id')}"), message="Link closed")
    except opt.OptionError as exc:
        raise _fail(exc)
