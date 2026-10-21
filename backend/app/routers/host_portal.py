"""
routers/host_portal.py
HOST-1 - the builder-facing side of "Host with Opsra" (sites made outside Opsra). Mounted at /api/v1/builder/host/*,
signed in with the same builder session as the rest of the portal (get_current_builder). Logic: services/host_site_service.py.

  GET  /host/config                         switch, limits and how many hosted sites the builder has
  GET  /host/sites                          the builder's uploaded sites
  POST /host/upload                         multipart: file, name (new site) or site_id (new files for a site), dry_run
  GET  /host/sites/{id}/report              the safety report of the newest upload
  GET  /host/sites/{id}/preview             the page as HTML for a sandboxed iframe (scripts on, no portal access)

Going live is not here: the portal's normal Checkout (domain, quote, payment) handles any site, uploaded or not.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.database import get_supabase
from app.models.common import ok
from app.routers.builder_portal import get_current_builder
from app.services import host_site_service as host, site_import_service

logger = logging.getLogger(__name__)
router = APIRouter()


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, detail={"code": "VALIDATION_ERROR", "message": f"That file is over the {limit // (1024 * 1024)} MB limit."})
        chunks.append(chunk)
    return b"".join(chunks)


def _host_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except host.HostError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.get("/host/config")
def host_config(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    return ok(data=host.config(db, builder))


@router.get("/host/sites")
def host_sites(builder=Depends(get_current_builder), db=Depends(get_supabase)):
    _host_call(host.require_enabled, db, builder["org_id"])
    return ok(data=host.list_sites(db, builder))


@router.post("/host/upload")
async def host_upload(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    site_id: Optional[str] = Form(None),
    dry_run: bool = Form(False),
    builder=Depends(get_current_builder), db=Depends(get_supabase),
):
    settings = _host_call(host.require_enabled, db, builder["org_id"])
    if host.rate_limited(builder["id"]):
        raise HTTPException(429, detail={"code": "RATE_LIMITED", "message": "That's a lot of uploads in an hour. Please wait a little and try again."})
    cfg = site_import_service.settings_for(settings)
    data = await _read_capped(file, cfg["max_mb"] * 1024 * 1024)
    if not data:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "That file is empty."})
    try:
        result = host.upload(db, builder, data, file.filename or "", name=name, site_id=(site_id or None), dry_run=dry_run)
    except host.HostError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    except site_import_service.ImportRejected as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": "We could not accept those files.",
                            "errors": host.plain_errors(exc), "report": exc.report})
    except site_import_service.ImportFailed as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})
    return ok(data=result, message=("Checked only: nothing was saved." if dry_run else result.get("message", "Uploaded")))


@router.get("/host/sites/{site_id}/report")
def host_report(site_id: str, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    _host_call(host.require_enabled, db, builder["org_id"])
    return ok(data=_host_call(host.report_for, db, builder, site_id))


@router.get("/host/sites/{site_id}/preview")
def host_preview(site_id: str, design_id: Optional[str] = None, builder=Depends(get_current_builder), db=Depends(get_supabase)):
    _host_call(host.require_enabled, db, builder["org_id"])
    return ok(data={"html": _host_call(host.preview_html, db, builder, site_id, design_id)})
