"""
app/routers/knowledge.py
------------------------
WA-AUTO-4a - what the bot knows: add a file or typed answers, preview, "Start using this", remove.
Owner, ops manager or admin. Needs the knowledge_base feature on the plan. Audit-logged (add and remove).
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import knowledge_service as ks
from app.services import knowledge_web_service as web
from app.services import plan_gate_service

router = APIRouter()


def _guard(org: dict, db) -> None:
    roles = org.get("roles") if isinstance(org.get("roles"), dict) else {}
    if (roles.get("template") or "").lower() not in ("owner", "ops_manager", "admin"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Only the owner, an ops manager or an admin can change what the bot knows."})
    if not plan_gate_service.allowed(db, org["org_id"], "knowledge_base"):
        raise plan_gate_service.http_error()


def _audit(db, org: dict, action: str, source_id, extra: dict) -> None:
    try:
        db.table("audit_logs").insert({"org_id": org["org_id"], "user_id": org["id"], "action": action, "resource_type": "knowledge_source",
                                       "resource_id": source_id, "old_value": None, "new_value": extra}).execute()
    except Exception:
        pass


class TextPayload(BaseModel):
    title: str = Field(..., max_length=200)
    content: str = Field(..., max_length=ks.MAX_SOURCE_CHARS + 1000)


@router.get("/knowledge/sources")
def list_sources(org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=ks.list_sources(db, org["org_id"]))


@router.post("/knowledge/sources/file")
async def add_file(file: UploadFile = File(...), title: str = Form(default=""), org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    data = await file.read(ks.MAX_FILE_BYTES + 1)
    out = ks.add_file(db, org["org_id"], org["id"], file.filename or "", data, title.strip() or None)
    _audit(db, org, "knowledge.added", out["id"], {"kind": "file", "chunks": out["chunk_count"]})
    return ok(data=out)


@router.post("/knowledge/sources/text")
def add_text(payload: TextPayload, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    out = ks.add_text(db, org["org_id"], org["id"], payload.title, payload.content)
    _audit(db, org, "knowledge.added", out["id"], {"kind": "text", "chunks": out["chunk_count"]})
    return ok(data=out)


class UrlPayload(BaseModel):
    url: str = Field(..., max_length=600)


def _start_web_job(kind: str, payload: UrlPayload, tasks: BackgroundTasks, org: dict, db):
    """One website or Google Doc is read at a time per business; the work runs after this call returns and the screen checks back."""
    try:
        address = web.clean_start_url(payload.url) if kind == "url" else web.gdoc_export_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": str(exc)})
    if any(s.get("status") == "processing" for s in ks.list_sources(db, org["org_id"])):
        raise HTTPException(status_code=409, detail={"code": "BUSY", "message": "We are still reading your last website or document. Please wait a moment."})
    label = web._host(address) if kind == "url" else "Google Doc"
    sid = ks.new_source(db, org["org_id"], org["id"], kind, label, source_url=(address if kind == "url" else payload.url.strip()), status="processing")
    tasks.add_task(web.run_website if kind == "url" else web.run_gdoc, db, org["org_id"], sid, address)
    _audit(db, org, "knowledge.added", sid, {"kind": kind})
    return ok(data=ks.preview(db, org["org_id"], sid))


@router.post("/knowledge/sources/url")
def add_website(payload: UrlPayload, tasks: BackgroundTasks, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return _start_web_job("url", payload, tasks, org, db)


@router.post("/knowledge/sources/gdoc")
def add_gdoc(payload: UrlPayload, tasks: BackgroundTasks, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return _start_web_job("gdoc", payload, tasks, org, db)


@router.get("/knowledge/sources/{source_id}")
def get_source(source_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=ks.preview(db, org["org_id"], source_id))


@router.post("/knowledge/sources/{source_id}/activate")
def activate(source_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    return ok(data=ks.activate(db, org["org_id"], source_id))


@router.delete("/knowledge/sources/{source_id}")
def remove(source_id: str, org=Depends(get_current_org), db=Depends(get_supabase)):
    _guard(org, db)
    out = ks.remove(db, org["org_id"], source_id)
    _audit(db, org, "knowledge.removed", source_id, {})
    return ok(data=out)
