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
  SALE-1:
  Reps (not owner / ops manager / admin) see and act on only the invoices they made and their receipts (404 else).
  GET    /payments/approvals?status=        payments waiting for an admin (admins: all; reps: their own)
  POST   /payments/approvals/{id}/approve | /reject {reason} | /cancel
  GET    /sales                             my sales (invoices I made) with any amount waiting
  POST   /sales                             make a sale: invoice + issue + payment (+ delivered)
  POST   /sales/{id}/finish                 payment + delivery after the invoice was issued another way

S1/S2: org_id comes only from get_current_org (the JWT). Ids in bodies are checked against the org in the service.
S3/S4: every body field has a length or range limit; notes/terms max 5,000 characters.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
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
    location_id: Optional[UUID] = None   # STOCK-2: where the stock comes from (checked against the business's locations)
    bank_account_id: Optional[str] = Field(None, max_length=40)   # BANK-1: blank = the region's account, else the default
    items: Optional[List[ItemIn]] = Field(None, max_length=inv.MAX_ITEMS)

    _money = field_validator("discount")(_two_places)


class DocCreate(_DocFields):
    doc_type: Literal["quote", "invoice"]


class DocPatch(_DocFields):
    pass


class VoidIn(_Strict):
    reason: str = Field(..., min_length=3, max_length=500)


class DeliverLine(_Strict):   # STOCK-2
    item_id: UUID
    quantity: int = Field(..., ge=1, le=1_000_000)


class DeliverIn(_Strict):
    lines: List[DeliverLine] = Field(..., min_length=1, max_length=inv.MAX_ITEMS)
    note: Optional[str] = Field(None, max_length=300)


class IssueIn(_Strict):   # STOCK-2b: managers may take lines from another location
    sources: Optional[Dict[UUID, UUID]] = Field(None, max_length=inv.MAX_ITEMS)


class StockRequestIn(_Strict):   # STOCK-2b
    sources: Dict[UUID, UUID] = Field(..., min_length=1, max_length=inv.MAX_ITEMS)
    note: Optional[str] = Field(None, max_length=300)


class StockRejectIn(_Strict):
    note: Optional[str] = Field(None, max_length=300)


def _src(sources) -> Optional[dict]:
    return {str(k): str(v) for k, v in sources.items()} if sources else None


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


class BankAccountIn(_Strict):   # BANK-1
    id: Optional[str] = Field(None, max_length=40)
    label: Optional[str] = Field(None, max_length=60)
    bank_name: str = Field(..., min_length=1, max_length=100)
    account_name: Optional[str] = Field(None, max_length=200)
    account_number: str = Field(..., pattern=r"^[0-9]{6,20}$")
    region: Optional[str] = Field(None, max_length=255)
    is_default: bool = False


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
    payments_need_approval: Optional[bool] = None   # SALE-1
    payment_confirm_reps: Optional[List[UUID]] = Field(None, max_length=200)   # REPORT-1
    payment_confirmers: Optional[List[UUID]] = Field(None, max_length=50)
    report_emails: Optional[List[str]] = Field(None, max_length=10)
    daily_sales_report: Optional[bool] = None
    weekly_reports: Optional[bool] = None
    bank_accounts: Optional[List[BankAccountIn]] = Field(None, max_length=10)   # BANK-1

    _money = field_validator("vat_rate")(_two_places)

    @field_validator("email", "email_reply_to")
    @classmethod
    def _email(cls, v):
        if v and ("@" not in v or " " in v.strip()):
            raise ValueError("Not a valid email address")
        return v.strip() if v else v

    @field_validator("report_emails")
    @classmethod
    def _emails(cls, v):
        from app.services.report_email_service import EMAIL_RE
        for x in v or []:
            if not EMAIL_RE.match(str(x).strip()) or len(str(x)) > 254:
                raise ValueError(f"Not a valid email address: {x}")
        return v


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


# ── SALE-1: reps see only what they made; owners, ops managers and admins see everything ──

def _mine(org: dict) -> Optional[str]:
    """None = sees everything; else the user id whose documents / receipts they may see."""
    from app.services import inventory_service as stock
    return None if stock.is_manager(org) else (org.get("id") or "-")


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"success": False, "data": None, "error": {
        "code": "NOT_FOUND", "message": f"{what} not found.", "field": None}})


async def _own_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)) -> None:
    mine = _mine(org)
    if mine is None:
        return
    res = db.table("invoices").select("created_by").eq("org_id", org["org_id"]).eq("id", str(doc_id)).limit(1).execute()
    rows = getattr(res, "data", None) or []
    if rows and rows[0].get("created_by") != mine:
        raise _not_found("Document")


async def _own_receipt(receipt_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)) -> None:
    mine = _mine(org)
    if mine is None:
        return
    res = db.table("receipts").select("owner_id").eq("org_id", org["org_id"]).eq("id", str(receipt_id)).limit(1).execute()
    rows = getattr(res, "data", None) or []
    if rows and rows[0].get("owner_id") != mine:
        raise _not_found("Receipt")


_OWN_DOC = [Depends(_own_doc)]
_OWN_RECEIPT = [Depends(_own_receipt)]


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


@router.get("/invoices/settings/people")
async def settings_people(org: dict = Depends(require_admin), db=Depends(get_supabase)):
    """REPORT-1: active staff for the payment pickers (who waits, who may confirm). Managers never wait."""
    rows = db.table("users").select("id, full_name, email, is_active, roles(template, permissions)") \
        .eq("org_id", org["org_id"]).execute().data or []
    out = []
    for u in rows:
        if u.get("is_active") is False:
            continue
        role = u.get("roles") or {}
        role = role[0] if isinstance(role, list) and role else role
        perms = (role or {}).get("permissions") or {}
        manager = (role or {}).get("template") in ("owner", "ops_manager") or perms.get("is_admin") is True
        out.append({"id": u["id"], "name": u.get("full_name") or u.get("email"), "email": u.get("email"),
                    "manager": manager})
    out.sort(key=lambda x: str(x["name"] or "").lower())
    return ok(out)


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
    out = inv.summary(db, org["org_id"], mine=_mine(org))
    out["paid_this_month"] = pay.paid_this_month(db, org["org_id"], mine=_mine(org))
    from app.services import payment_approval_service as approvals   # SALE-1
    out["payments_waiting"] = approvals.count_pending(db, org)
    out["can_confirm_payments"] = approvals.can_confirm(org, db)
    return ok(out)


@router.get("/invoices/report")
async def get_report(start: Optional[date] = None, end: Optional[date] = None,
                     org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_report_service as rep
    try:
        return ok(rep.report(db, org["org_id"], start, end, mine=_mine(org)))
    except inv.InvoiceError as e:
        return _fail(e)


# ── REPORT-1: the sales report as JSON, PDF or CSV (admins), and "send me one now" ──

def _report_file(data: bytes, name: str, media: str) -> Response:
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/reports/sales")
async def get_sales_report(start: Optional[date] = None, end: Optional[date] = None,
                           region: Optional[str] = Query(None, max_length=100), location_id: Optional[UUID] = None,
                           rep_id: Optional[UUID] = None, format: Literal["json", "pdf", "csv"] = "json",
                           org: dict = Depends(require_admin), db=Depends(get_supabase)):
    from app.services import business_report_service as biz
    from app.services import invoice_sales_service as sales_svc
    try:
        data = biz.sales_data(db, org["org_id"], start, end, region=region,
                              location_id=str(location_id) if location_id else None,
                              rep_id=str(rep_id) if rep_id else None)
    except inv.InvoiceError as e:
        return _fail(e)
    if format == "csv":
        return _report_file(biz.sales_csv(data).encode("utf-8-sig"), biz.filename("sales", data, "csv"), "text/csv")
    if format == "pdf":
        body, name = biz.sales_pdf(data, inv.get_settings(db, org["org_id"]))
        if not body:
            return _fail(inv.InvoiceError("INTEGRATION_ERROR", "The PDF could not be made. Please try again.", 503))
        return _report_file(body, name, "application/pdf")
    data["regions"] = sales_svc.regions(db, org["org_id"])
    data["reps"] = [{"id": u["id"], "name": u.get("full_name") or u.get("email")} for u in
                    (db.table("users").select("id, full_name, email, is_active").eq("org_id", org["org_id"]).execute().data or [])
                    if u.get("is_active") is not False]
    data["reps"].sort(key=lambda u: str(u["name"] or "").lower())
    data["locations"] = [{"id": l["id"], "name": l["name"]} for l in biz._locations(db, org["org_id"]).values()]
    return ok(data)


class ReportTestIn(_Strict):
    kind: Literal["daily", "weekly"] = "daily"


@router.post("/reports/send-test")
async def send_test_report(body: ReportTestIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    """Send the report now to the report emails (does not change the schedule)."""
    from datetime import timedelta
    from app.services import report_email_service as mail
    org_id = org["org_id"]
    to = mail.recipients(db, org_id)
    if not to:
        return _fail(inv.InvoiceError("VALIDATION_ERROR", "Add an email address to send reports to first.", 422,
                                      "report_emails"))
    today = mail.lagos_today()
    sent = mail.send_daily(db, org_id, today - timedelta(days=1)) if body.kind == "daily" \
        else mail.send_weekly(db, org_id, today - timedelta(days=today.isoweekday() % 7 or 7))
    if not sent:
        return _fail(inv.InvoiceError("INTEGRATION_ERROR", "The email did not go out. Please try again.", 503))
    return ok({"sent_to": to})


@router.get("/invoices/report/receipts.csv")
async def get_report_csv(start: Optional[date] = None, end: Optional[date] = None,
                         org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_report_service as rep
    try:
        text = rep.receipts_csv(db, org["org_id"], start, end, mine=_mine(org))
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
    return ok(sales.part_paid_summary(db, org_id, start, end, rep, region, mine=_mine(org)))


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
    return ok(inv.list_docs(db, org["org_id"], doc_type, status, lead_id, customer_id, q, limit, offset, mine=_mine(org)))


@router.post("/invoices", status_code=201)
async def create_doc(body: DocCreate, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.create_draft(db, org_id, user_id, _body(body)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/{doc_id}", dependencies=_OWN_DOC)
async def get_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    try:
        doc = inv.get_doc(db, org["org_id"], str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    if doc.get("doc_type") == "invoice":   # INV-4
        from app.services import invoice_payment_service as pay
        from app.services import payment_approval_service as approvals
        doc["receipts"] = pay.receipts_for_invoice(db, org["org_id"], doc["id"])
        doc["pending_payments"] = approvals.pending_for_invoice(db, org["org_id"], doc["id"])   # SALE-1
        doc["can_confirm_payments"] = approvals.can_confirm(org, db)
        doc["payments_need_approval"] = approvals.needs_approval(db, org)
        for r in doc["receipts"]:
            r.pop("public_token", None)
        if doc.get("stock_tracked"):   # STOCK-2
            from app.services import invoice_stock_service as inv_stock
            doc["can_deliver"] = inv_stock.can_deliver(org, doc)
            if doc.get("stock_approval") == "pending":   # STOCK-2b
                doc["can_approve_stock"] = inv_stock.can_approve(org)
                doc["can_cancel_stock"] = doc["can_approve_stock"] or doc.get("stock_requested_by") == org.get("id")
    return ok(doc)


@router.patch("/invoices/{doc_id}", dependencies=_OWN_DOC)
async def patch_doc(doc_id: UUID, body: DocPatch, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.update_draft(db, org_id, user_id, str(doc_id), _body(body)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.delete("/invoices/{doc_id}", dependencies=_OWN_DOC)
async def delete_doc(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        inv.delete_draft(db, org_id, user_id, str(doc_id))
        return ok({"deleted": True})
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/issue", dependencies=_OWN_DOC)
async def issue_doc(doc_id: UUID, body: Optional[IssueIn] = None, org: dict = Depends(get_current_org),
                    db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv.issue(db, org_id, user_id, str(doc_id), sources=_src(body.sources if body else None),
                            allow_other=inv_stock.can_approve(org)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/{doc_id}/stock-check", dependencies=_OWN_DOC)
async def stock_check(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2b: per product line, what is needed, what the invoice's location has, and other locations with stock."""
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.stock_check(db, org, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/stock-request", dependencies=_OWN_DOC)
async def stock_request(doc_id: UUID, body: StockRequestIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2b: ask an admin to approve taking lines from another location (goods are held meanwhile)."""
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.request_approval(db, org, str(doc_id), _src(body.sources), body.note))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/stock-approve", dependencies=_OWN_DOC)
async def stock_approve(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.approve(db, org, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/stock-reject", dependencies=_OWN_DOC)
async def stock_reject(doc_id: UUID, body: StockRejectIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.reject(db, org, str(doc_id), body.note))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/stock-cancel", dependencies=_OWN_DOC)
async def stock_cancel(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.cancel_request(db, org, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/deliver", dependencies=_OWN_DOC)
async def deliver_doc(doc_id: UUID, body: DeliverIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    """STOCK-2: mark goods delivered (paid invoices; managers or the rep who made it). Part delivery per line."""
    from app.services import invoice_stock_service as inv_stock
    try:
        return ok(inv_stock.deliver(db, org, str(doc_id), body.model_dump(mode="json")["lines"], body.note))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/void", dependencies=_OWN_DOC)
async def void_doc(doc_id: UUID, body: VoidIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.void(db, org_id, user_id, str(doc_id), body.reason.strip()))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/accept", dependencies=_OWN_DOC)
async def accept_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.set_quote_answer(db, org_id, user_id, str(doc_id), True))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/decline", dependencies=_OWN_DOC)
async def decline_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.set_quote_answer(db, org_id, user_id, str(doc_id), False))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/invoices/{doc_id}/convert", status_code=201, dependencies=_OWN_DOC)
async def convert_quote(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id, user_id = _ids(org)
    try:
        return ok(inv.convert_quote(db, org_id, user_id, str(doc_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.get("/invoices/{doc_id}/pdf", dependencies=_OWN_DOC)
async def doc_pdf(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    org_id = org["org_id"]
    try:
        doc = inv.get_doc(db, org_id, str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    settings = inv.settings_for_doc(inv.get_settings(db, org_id), doc) if not doc.get("issuer") else {}   # BANK-1
    data, name = pdf.render(doc, settings, doc["doc_type"])
    if not data:
        return _fail(inv.InvoiceError("INTEGRATION_ERROR", "Could not make the PDF. Please try again.", 503))
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


# ── INV-3: sending ──

@router.get("/invoices/{doc_id}/send-options", dependencies=_OWN_DOC)
async def send_options(doc_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    try:
        doc = inv.get_doc(db, org["org_id"], str(doc_id))
    except inv.InvoiceError as e:
        return _fail(e)
    return ok(delivery.options(db, org["org_id"], doc))


@router.post("/invoices/{doc_id}/send", dependencies=_OWN_DOC)
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

@router.post("/invoices/{doc_id}/payments", status_code=201, dependencies=_OWN_DOC)
async def record_payment(doc_id: UUID, body: PaymentIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    from app.services import payment_approval_service as approvals
    org_id, user_id = _ids(org)
    try:
        if approvals.needs_approval(db, org):   # SALE-1: waits for an admin
            pending = approvals.request_invoice_payment(db, org, str(doc_id), _body(body))
            return ok({"receipt": None, "pending_payment": pending, "invoice": inv.get_doc(db, org_id, str(doc_id)),
                       "fully_paid": False})
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
                                str(lead_id) if lead_id else None, q, limit, offset, mine=_mine(org)))


@router.post("/receipts", status_code=201)
async def new_receipt(body: ReceiptIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    from app.services import payment_approval_service as approvals
    org_id, user_id = _ids(org)
    try:
        if approvals.needs_approval(db, org):   # SALE-1: waits for an admin
            return ok({"pending_payment": approvals.request_standalone(db, org, _body(body))})
        r = pay.standalone_receipt(db, org_id, user_id, _body(body))
    except inv.InvoiceError as e:
        return _fail(e)
    r.pop("public_token", None)
    r.pop("_contact", None)
    return ok(r)


@router.post("/receipts/{receipt_id}/void", dependencies=_OWN_RECEIPT)
async def void_receipt(receipt_id: UUID, body: VoidIn, org: dict = Depends(require_admin), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id, user_id = _ids(org)
    try:
        r = pay.void_receipt(db, org_id, user_id, str(receipt_id), body.reason)
    except inv.InvoiceError as e:
        return _fail(e)
    r.pop("public_token", None)
    return ok(r)


@router.get("/receipts/{receipt_id}/pdf", dependencies=_OWN_RECEIPT)
async def receipt_pdf(receipt_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_payment_service as pay
    org_id = org["org_id"]
    try:
        data, name = pay.render_receipt(db, org_id, pay.get_receipt(db, org_id, str(receipt_id)))
    except inv.InvoiceError as e:
        return _fail(e)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/receipts/{receipt_id}/send-options", dependencies=_OWN_RECEIPT)
async def receipt_send_options(receipt_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import invoice_delivery_service as delivery
    from app.services import invoice_payment_service as pay
    org_id = org["org_id"]
    try:
        r = pay.receipt_doc(db, org_id, pay.get_receipt(db, org_id, str(receipt_id)))
    except inv.InvoiceError as e:
        return _fail(e)
    return ok(delivery.receipt_options(db, org_id, r))


@router.post("/receipts/{receipt_id}/send", dependencies=_OWN_RECEIPT)
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


# ── SALE-1: payments waiting for an admin ──

class RejectIn(_Strict):
    reason: str = Field(..., min_length=3, max_length=500)


@router.get("/payments/approvals")
async def list_payment_approvals(status: Literal["pending", "approved", "rejected", "cancelled"] = "pending",
                                 org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import payment_approval_service as approvals
    try:
        return ok(approvals.list_approvals(db, org, status))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/payments/approvals/{approval_id}/approve")
async def approve_payment(approval_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import payment_approval_service as approvals
    try:
        return ok(approvals.approve(db, org, str(approval_id)))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/payments/approvals/{approval_id}/reject")
async def reject_payment(approval_id: UUID, body: RejectIn, org: dict = Depends(get_current_org),
                         db=Depends(get_supabase)):
    from app.services import payment_approval_service as approvals
    try:
        return ok(approvals.reject(db, org, str(approval_id), body.reason))
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/payments/approvals/{approval_id}/cancel")
async def cancel_payment(approval_id: UUID, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import payment_approval_service as approvals
    try:
        return ok(approvals.cancel(db, org, str(approval_id)))
    except inv.InvoiceError as e:
        return _fail(e)


# ── SALE-1: Make a sale ──

class SalePaymentIn(_Strict):
    status: Literal["paid", "part", "unpaid"]
    amount: Optional[Decimal] = Field(None, gt=0, le=Decimal("1000000000"))
    method: Optional[Method] = None
    reference: Optional[str] = Field(None, max_length=200)
    paid_at: Optional[date] = None

    _money = field_validator("amount")(_two_places)


class SaleIn(_Strict):
    lead_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = Field(None, max_length=200)
    customer_phone: Optional[str] = Field(None, max_length=30)
    customer_email: Optional[str] = Field(None, max_length=254)
    customer_address: Optional[str] = Field(None, max_length=500)
    location_id: UUID
    region: Optional[str] = Field(None, max_length=255)
    discount: Optional[Decimal] = Field(None, ge=0, le=100_000_000_000)
    notes: Optional[str] = Field(None, max_length=5000)
    items: List[ItemIn] = Field(..., min_length=1, max_length=inv.MAX_ITEMS)
    payment: SalePaymentIn
    delivered: bool = False

    _money = field_validator("discount")(_two_places)


class SaleFinishIn(_Strict):
    payment: SalePaymentIn
    delivered: bool = False


def _sale_out(out: dict) -> dict:
    if out.get("receipt"):
        out["receipt"].pop("public_token", None)
    return out


@router.get("/sales")
async def list_sales(q: Optional[str] = Query(None, max_length=100), limit: int = Query(50, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=100_000), org: dict = Depends(get_current_org),
                     db=Depends(get_supabase)):
    from app.services import sale_service as sale
    return ok(sale.my_sales(db, org, q, limit, offset))


@router.post("/sales", status_code=201)
async def make_sale(body: SaleIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import sale_service as sale
    try:
        return ok(_sale_out(sale.create(db, org, _body(body))))
    except sale.SaleShort as e:   # the draft is kept: the screen offers another location / asks a manager
        return JSONResponse(status_code=e.status, content={
            "success": False, "data": {"doc_id": e.doc_id},
            "error": {"code": e.code, "message": e.message, "field": e.field}})
    except inv.InvoiceError as e:
        return _fail(e)


@router.post("/sales/{doc_id}/finish", dependencies=_OWN_DOC)
async def finish_sale(doc_id: UUID, body: SaleFinishIn, org: dict = Depends(get_current_org), db=Depends(get_supabase)):
    from app.services import sale_service as sale
    d = _body(body)
    try:
        return ok(_sale_out(sale.finish(db, org, str(doc_id), d["payment"], d["delivered"])))
    except inv.InvoiceError as e:
        return _fail(e)
