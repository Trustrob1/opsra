"""
app/routers/invoices.py
-----------------------
INV-1 - quotations and invoices for a business's own customers. Staff routes, prefix /api/v1.
Open to every product mode (full, wa_automation, web_chat): registered WITHOUT crm_only on purpose.
Plan feature: `invoices` (whole router, plan_gate.require).

  GET    /invoices/settings                 the business's invoice settings (defaults if none saved)
  PUT    /invoices/settings                 save them (admin)
  GET    /invoices?doc_type=&status=&lead_id=&customer_id=&q=&limit=&offset=
                                            list; status also accepts the computed 'overdue' / 'expired'
  POST   /invoices                          new draft quote or invoice
  GET    /invoices/{id}                     one document with its lines
  PATCH  /invoices/{id}                     change a draft (items, if sent, replace all lines)
  DELETE /invoices/{id}                     delete a draft
  POST   /invoices/{id}/issue               number it and lock it
  POST   /invoices/{id}/void                void an issued document (admin, reason required)
  POST   /invoices/{id}/accept | /decline   staff records the customer's answer to a quote
  POST   /invoices/{id}/convert             quote -> new draft invoice
  GET    /invoices/{id}/pdf                 the PDF (drafts carry a DRAFT mark)

S1/S2: org_id comes only from get_current_org (the JWT). Ids in bodies are checked against the org in the service.
S3/S4: every body field has a length or range limit; notes/terms max 5,000 characters.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database import get_supabase
from app.dependencies import get_current_org, require_admin
from app.models.common import ok
from app.services import invoice_pdf_service as pdf
from app.services import invoice_service as inv
from app.services import plan_gate_service as plan_gate

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(plan_gate.require("invoices"))])

Status = Literal["draft", "issued", "accepted", "declined", "part_paid", "paid", "void", "overdue", "expired"]
_COLOUR = r"^#[0-9a-fA-F]{6}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemIn(_Strict):
    product_id: Optional[UUID] = None
    description: Optional[str] = Field(None, max_length=500)
    quantity: Decimal = Field(..., gt=0, le=1_000_000, max_digits=12, decimal_places=2)
    unit_price: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000, max_digits=14, decimal_places=2)


class _DocFields(_Strict):
    lead_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = Field(None, max_length=200)
    customer_phone: Optional[str] = Field(None, max_length=30)
    customer_email: Optional[str] = Field(None, max_length=254)
    customer_address: Optional[str] = Field(None, max_length=500)
    currency: Optional[Literal["NGN"]] = None
    discount: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000, max_digits=14, decimal_places=2)
    apply_vat: Optional[bool] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    terms: Optional[str] = Field(None, max_length=5000)
    items: Optional[List[ItemIn]] = Field(None, max_length=inv.MAX_ITEMS)


class DocCreate(_DocFields):
    doc_type: Literal["quote", "invoice"]


class DocPatch(_DocFields):
    pass


class VoidIn(_Strict):
    reason: str = Field(..., min_length=3, max_length=500)


class SettingsIn(_Strict):
    business_name: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=254)
    rc_number: Optional[str] = Field(None, max_length=50)
    tin: Optional[str] = Field(None, max_length=50)
    bank_name: Optional[str] = Field(None, max_length=100)
    account_name: Optional[str] = Field(None, max_length=200)
    account_number: Optional[str] = Field(None, pattern=r"^[0-9]{6,20}$")
    quote_prefix: Optional[str] = Field(None, max_length=10, pattern=r"^[A-Za-z0-9/_-]*$")
    invoice_prefix: Optional[str] = Field(None, max_length=10, pattern=r"^[A-Za-z0-9/_-]*$")
    receipt_prefix: Optional[str] = Field(None, max_length=10, pattern=r"^[A-Za-z0-9/_-]*$")
    vat_enabled: Optional[bool] = None
    vat_rate: Optional[Decimal] = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)
    default_due_days: Optional[int] = Field(None, ge=0, le=365)
    default_quote_valid_days: Optional[int] = Field(None, ge=1, le=365)
    default_terms: Optional[str] = Field(None, max_length=5000)
    footer: Optional[str] = Field(None, max_length=300)
    brand_colour: Optional[str] = Field(None, pattern=_COLOUR)
    email_reply_to: Optional[str] = Field(None, max_length=254)

    @field_validator("email", "email_reply_to")
    @classmethod
    def _email(cls, v):
        if v and ("@" not in v or " " in v.strip()):
            raise ValueError("Not a valid email address")
        return v.strip() if v else v


def _body(model: BaseModel) -> dict:
    data = model.model_dump(exclude_unset=True, mode="json")
    if "items" in data and data["items"] is not None:
        data["items"] = [{k: v for k, v in it.items()} for it in data["items"]]
    return data


def _fail(e: inv.InvoiceError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={
        "success": False, "data": None,
        "error": {"code": e.code, "message": e.message, "field": e.field}})


def _ids(org: dict) -> tuple[str, Optional[str]]:
    return org["org_id"], org.get("id")


# ── settings (declared before /invoices/{id} so "settings" is never read as an id) ──

@router.get("/invoices/settings")
async def get_settings(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    return ok(inv.get_settings(db, org["org_id"]))


@router.put("/invoices/settings")
async def put_settings(body: SettingsIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    data = inv.save_settings(db, org_id, body.model_dump(exclude_unset=True, mode="json"))
    inv._audit(db, org_id, user_id, "invoice_settings.updated", None, {"fields": sorted(body.model_fields_set)})
    return ok(data)


# ── documents ──

@router.get("/invoices")
async def list_docs(
    doc_type: Optional[Literal["quote", "invoice"]] = None,
    status: Optional[Status] = None,
    lead_id: Optional[UUID] = None,
    customer_id: Optional[UUID] = None,
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    org: dict = Depends(get_current_org), db=Depends(get_supabase),
):
    return ok(inv.list_docs(db, org["org_id"], doc_type, status, lead_id, customer_id, q, limit, offset))


@router.post("/invoices", status_code=201)
async def create_doc(body: DocCreate, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.create_draft(db, org_id, user_id, _body(body)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/{doc_id}")
async def get_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    try:
        return ok(inv.get_doc(db, org["org_id"], str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.patch("/invoices/{doc_id}")
async def patch_doc(doc_id: UUID, body: DocPatch, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.update_draft(db, org_id, user_id, str(doc_id), _body(body)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.delete("/invoices/{doc_id}")
async def delete_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        inv.delete_draft(db, org_id, user_id, str(doc_id))
        return ok({"deleted": True})
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/issue")
async def issue_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.issue(db, org_id, user_id, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/void")
async def void_doc(doc_id: UUID, body: VoidIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.void(db, org_id, user_id, str(doc_id), body.reason.strip()))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/accept")
async def accept_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.set_quote_answer(db, org_id, user_id, str(doc_id), True))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/decline")
async def decline_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.set_quote_answer(db, org_id, user_id, str(doc_id), False))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/convert", status_code=201)
async def convert_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.convert_quote(db, org_id, user_id, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/{doc_id}/pdf")
async def doc_pdf(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id = org["org_id"]
    try:
        doc = inv.get_doc(db, org_id, str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    settings = inv.get_settings(db, org_id) if not doc.get("issuer") else {}
    data, name = pdf.render(doc, settings, doc["doc_type"])
    if not data:
        return _fail(inv.InvoiceError("INTEGRATION_ERROR", "Could not make the PDF. Please try again.", 503))
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})
