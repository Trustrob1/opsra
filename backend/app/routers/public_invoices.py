"""
app/routers/public_invoices.py
------------------------------
INV-3 - the customer's own page for a quote or invoice. No login: the public token (made when the document is issued)
is the only key. Prefix /api/v1.

  GET  /public/invoices/{token}           what the page shows (no internal ids; drafts never shown)
  GET  /public/invoices/{token}/pdf       the PDF
  POST /public/invoices/{token}/accept    the customer accepts an issued quote (the team gets a task)
  POST /public/invoices/{token}/decline   or declines it

Open for every product mode and not plan-gated: a document that was sent stays readable.
Rate limited per IP (hashed). Errors use the standard envelope.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.database import get_supabase
from app.models.common import ok
from app.services import invoice_delivery_service as delivery
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _limited(request: Request, bucket: str, limit: int, window: int) -> bool:
    try:
        from app.services import webchat_service as wc
        from app.services.site_capture_service import ip_hash
        return bool(wc.rate_limited(f"pinv:{bucket}:{ip_hash(_client_ip(request))}", limit, window))
    except Exception as exc:  # S14 - a broken limiter never blocks the page
        logger.warning("public_invoices: rate limit check failed: %s", exc)
        return False


def _fail(e: inv.InvoiceError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={
        "success": False, "data": None, "error": {"code": e.code, "message": e.message, "field": e.field}})


_SLOW = inv.InvoiceError("RATE_LIMITED", "Too many requests. Please try again in a few minutes.", 429)


@router.get("/public/invoices/{token}")
async def view(token: str, request: Request, db=Depends(get_supabase)):
    if _limited(request, "view", 60, 600):
        return _fail(_SLOW)
    try:
        return ok(delivery.public_view(db, token))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/public/invoices/{token}/pdf")
async def view_pdf(token: str, request: Request, db=Depends(get_supabase)):
    if _limited(request, "pdf", 20, 600):
        return _fail(_SLOW)
    try:
        data, name = delivery.public_pdf(db, token)
    except inv.InvoiceError as e:
        return _fail(e)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex"})


@router.post("/public/invoices/{token}/accept")
async def accept(token: str, request: Request, db=Depends(get_supabase)):
    if _limited(request, "answer", 10, 600):
        return _fail(_SLOW)
    try:
        return ok(delivery.public_answer(db, token, True))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/public/invoices/{token}/decline")
async def decline(token: str, request: Request, db=Depends(get_supabase)):
    if _limited(request, "answer", 10, 600):
        return _fail(_SLOW)
    try:
        return ok(delivery.public_answer(db, token, False))
    except inv.InvoiceError as e:
        return _fail(e)
