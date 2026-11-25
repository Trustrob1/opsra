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
  INV-2:
  POST   /invoices/settings/logo            upload the logo (admin; PNG/JPG/WebP <= 2 MB, re-drawn as PNG)
  DELETE /invoices/settings/logo            remove it (admin)
  GET    /invoices/summary                  money owed, overdue, open quotes, drafts
  GET    /invoices/products?q=              catalogue items for the line picker
  GET    /invoices/contacts?q=              leads to bill (open to every product mode)
  INV-3:
  GET    /invoices/{id}/send-options        the customer's link and which channels can be used now
  POST   /invoices/{id}/send                {channel: whatsapp|webchat|email, email?} send the PDF + link

S1/S2: org_id comes only from get_current_org (the JWT). Ids in bodies are checked against the org in the service.
S3/S4: every body field has a length or range limit; notes/terms max 5,000 characters.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
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


def _two_places(v: Optional[Decimal]) -> Optional[Decimal]:
    """At most 2 decimal places (kobo). Done here, not with Field(max_digits=...), because pydantic 2.7 (pinned in
    requirements.txt) cannot apply max_digits to an Optional[Decimal] and the app then fails to start."""
    if v is not None and v.as_tuple().exponent < -2 and v != v.quantize(Decimal("0.01")):
        raise ValueError("Use at most 2 decimal places.")
    return v


class ItemIn(_Strict):
    product_id: Optional[UUID] = None
    description: Optional[str] = Field(None, max_length=500)
    quantity: Decimal = Field(..., gt=0, le=1_000_000)
    unit_price: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000)
    variant: Optional[str] = Field(None, max_length=100)   # INV-SALES-2 size

    _money = field_validator("quantity", "unit_price")(_two_places)


class _DocFields(_Strict):
    lead_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = Field(None, max_length=200)
    customer_phone: Optional[str] = Field(None, max_length=30)
    customer_email: Optional[str] = Field(None, max_length=254)
    customer_address: Optional[str] = Field(None, max_length=500)
    currency: Optional[Literal["NGN"]] = None
    discount: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000)
    apply_vat: Optional[bool] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    terms: Optional[str] = Field(None, max_length=5000)
    region: Optional[str] = Field(None, max_length=255)   # INV-SALES-1 (checked against the business's regions)
    items: Optional[List[ItemIn]] = Field(None, max_length=inv.MAX_ITEMS)

    _money = field_validator("discount")(_two_places)


class DocCreate(_DocFields):
    doc_type: Literal["quote", "invoice"]


class DocPatch(_DocFields):
    pass


class VoidIn(_Strict):
    reason: str = Field(..., min_length=3, max_length=500)


class SendIn(_Strict):
    channel: Literal["whatsapp", "webchat", "email"]
    email: Optional[str] = Field(default=None, max_length=254)


Method = Literal["bank_transfer", "cash", "pos", "ussd", "other"]


class PaymentIn(_Strict):
    amount: Decimal = Field(..., gt=0, le=Decimal("1000000000"))
    method: Method
    reference: Optional[str] = Field(None, max_length=200)
    paid_at: Optional[date] = None
    note: Optional[str] = Field(None, max_length=500)

    _money = field_validator("amount")(_two_places)


class ReceiptIn(_Strict):
    lead_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = Field(None, max_length=200)
    amount: Decimal = Field(..., gt=0, le=Decimal("1000000000"))
    method: Method
    reference: Optional[str] = Field(None, max_length=200)
    paid_at: Optional[date] = None
    description: str = Field(..., min_length=1, max_length=500)
    region: Optional[str] = Field(None, max_length=255)   # INV-SALES-1

    _money = field_validator("amount")(_two_places)


class AiDraftIn(_Strict):
    lead_id: UUID


class ReceiptSendIn(_Strict):
    channel: Literal["whatsapp", "webchat", "email"]
    email: Optional[str] = Field(default=None, max_length=254)


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
    vat_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    default_due_days: Optional[int] = Field(None, ge=0, le=365)
    default_quote_valid_days: Optional[int] = Field(None, ge=1, le=365)
    default_terms: Optional[str] = Field(None, max_length=5000)
    footer: Optional[str] = Field(None, max_length=300)
    brand_colour: Optional[str] = Field(None, pattern=_COLOUR)
    email_reply_to: Optional[str] = Field(None, max_length=254)
    reminders_enabled: Optional[bool] = None   # INV-5
    sales_record_enabled: Optional[bool] = None   # INV-SALES-1

    _money = field_validator("vat_rate")(_two_places)

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


@router.post("/invoices/settings/logo")
async def upload_logo(file: UploadFile = File(...), org: dict = Depends(require_admin), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    data = await file.read(inv.LOGO_MAX_BYTES + 1)
    try:
        out = inv.save_logo(db, org_id, data)
    except inv.InvoiceError as e:
        return _fail(e)
    inv._audit(db, org_id, user_id, "invoice_settings.logo_uploaded", None)
    return ok(out)


@router.delete("/invoices/settings/logo")
async def delete_logo(org: dict = Depends(require_admin), db=Depends(get_supabase)):
    return ok(inv.remove_logo(db, org["org_id"]))


# ── INV-2 pickers + summary (static paths, before /invoices/{id}) ──

@router.get("/invoices/summary")
async def get_summary(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    out = inv.summary(db, org["org_id"])
    out["paid_this_month"] = pay.paid_this_month(db, org["org_id"])
    return ok(out)


@router.get("/invoices/report")
async def get_report(start: Optional[date] = None, end: Optional[date] = None,
                     org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_report_service as rep
    try:
        return ok(rep.report(db, org["org_id"], start, end))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/report/receipts.csv")
async def get_report_csv(start: Optional[date] = None, end: Optional[date] = None,
                         org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_report_service as rep
    try:
        text = rep.receipts_csv(db, org["org_id"], start, end)
        s, e = rep.check_period(start, end)
    except inv.InvoiceError as e:
        return _fail(e)
    return Response(content=text.encode("utf-8-sig"), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="receipts-{s}-to-{e}.csv"', "Cache-Control": "no-store"})


@router.post("/invoices/ai-draft")
async def ai_draft(body: AiDraftIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_ai_service as ai
    from app.services import webchat_service as wc
    org_id = org["org_id"]
    if wc.rate_limited(f"invai:{org_id}", 30, 3600):
        return _fail(inv.InvoiceError("RATE_LIMITED", "That is a lot of AI drafts. Please wait a few minutes.", 429))
    try:
        return ok(ai.suggest_lines(db, org_id, str(body.lead_id)))
    except inv.InvoiceError as e:
        return _fail(e)


# INV-SALES-1 ─ declared before /invoices/{doc_id}
@router.get("/invoices/regions")
async def get_regions(org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_sales_service as sales
    org_id, _ = _ids(org)
    return ok({"regions": sales.regions(db, org_id)})


@router.get("/invoices/part-paid")
async def get_part_paid(start: Optional[date] = None, end: Optional[date] = None,
                        rep: Optional[str] = Query(None, max_length=200), region: Optional[str] = Query(None, max_length=255),
                        org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_sales_service as sales
    org_id, _ = _ids(org)
    if start and end and start > end:
        return _fail(inv.InvoiceError("VALIDATION_ERROR", "The start date is after the end date.", 422, "start"))
    return ok(sales.part_paid_summary(db, org_id, start, end, rep, region))


@router.get("/invoices/products")
async def pick_products(q: Optional[str] = Query(None, max_length=100), org: dict = Depends(get_current_org),
                        db=Depends(get_supabase)):
    return ok(inv.search_products(db, org["org_id"], q))


@router.get("/invoices/contacts")
async def pick_contacts(q: Optional[str] = Query(None, max_length=100), org: dict = Depends(get_current_org),
                        db=Depends(get_supabase)):
    return ok(inv.search_contacts(db, org["org_id"], q))


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
        doc = inv.get_doc(db, org["org_id"], str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    if doc.get("doc_type") == "invoice":   # INV-4
        from app.services import invoice_payment_service as pay
        doc["receipts"] = pay.receipts_for_invoice(db, org["org_id"], doc["id"])
        for r in doc["receipts"]:
            r.pop("public_token", None)
    return ok(doc)


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


# ── INV-3: sending ──

@router.get("/invoices/{doc_id}/send-options")
async def send_options(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    try:
        doc = inv.get_doc(db, org["org_id"], str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    return ok(delivery.options(db, org["org_id"], doc))


@router.post("/invoices/{doc_id}/send")
async def send_doc(doc_id: UUID, body: SendIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    from app.services import webchat_service as wc
    org_id, user_id = _ids(org)
    if wc.rate_limited(f"invsend:{org_id}", 120, 3600):
        return _fail(inv.InvoiceError("RATE_LIMITED", "That is a lot of sending. Please wait a few minutes.", 429))
    try:
        return ok(delivery.send(db, org_id, user_id, str(doc_id), body.channel, body.email))
    except inv.InvoiceError as e:
        return _fail(e)


# ── INV-4: payments and receipts ──

@router.post("/invoices/{doc_id}/payments", status_code=201)
async def record_payment(doc_id: UUID, body: PaymentIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id, user_id = _ids(org)
    try:
        out = pay.record_payment(db, org_id, user_id, str(doc_id), _body(body))
    except inv.InvoiceError as e:
        return _fail(e)
    out["receipt"].pop("public_token", None)
    return ok(out)


@router.get("/receipts")
async def list_receipts(
    invoice_id: Optional[UUID] = None,
    lead_id: Optional[UUID] = None,
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
    org: dict = Depends(get_current_org), db=Depends(get_supabase),
):
    from app.services import invoice_payment_service as pay
    return ok(pay.list_receipts(db, org["org_id"], str(invoice_id) if invoice_id else None,
                                str(lead_id) if lead_id else None, q, limit, offset))


@router.post("/receipts", status_code=201)
async def new_receipt(body: ReceiptIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id, user_id = _ids(org)
    try:
        r = pay.standalone_receipt(db, org_id, user_id, _body(body))
    except inv.InvoiceError as e:
        return _fail(e)
    r.pop("public_token", None)
    r.pop("_contact", None)
    return ok(r)


@router.post("/receipts/{receipt_id}/void")
async def void_receipt(receipt_id: UUID, body: VoidIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id, user_id = _ids(org)
    try:
        r = pay.void_receipt(db, org_id, user_id, str(receipt_id), body.reason)
    except inv.InvoiceError as e:
        return _fail(e)
    r.pop("public_token", None)
    return ok(r)


@router.get("/receipts/{receipt_id}/pdf")
async def receipt_pdf(receipt_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id = org["org_id"]
    try:
        data, name = pay.render_receipt(db, org_id, pay.get_receipt(db, org_id, str(receipt_id)))
    except inv.InvoiceError as e:
        return _fail(e)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/receipts/{receipt_id}/send-options")
async def receipt_send_options(receipt_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    from app.services import invoice_payment_service as pay
    org_id = org["org_id"]
    try:
        r = pay.receipt_doc(db, org_id, pay.get_receipt(db, org_id, str(receipt_id)))
    except inv.InvoiceError as e:
        return _fail(e)
    return ok(delivery.receipt_options(db, org_id, r))


@router.post("/receipts/{receipt_id}/send")
async def send_receipt(receipt_id: UUID, body: ReceiptSendIn, org: dict = Depends(get_current_org),
                       db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    from app.services import webchat_service as wc
    org_id, user_id = _ids(org)
    if wc.rate_limited(f"invsend:{org_id}", 120, 3600):
        return _fail(inv.InvoiceError("RATE_LIMITED", "That is a lot of sending. Please wait a few minutes.", 429))
    try:
        return ok(delivery.send_receipt(db, org_id, user_id, str(receipt_id), body.channel, body.email))
    except inv.InvoiceError as e:
        return _fail(e)
