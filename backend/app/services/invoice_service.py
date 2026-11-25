"""
app/services/invoice_service.py
-------------------------------
INV-1 - quotations and invoices a business sends to ITS OWN customers (not Opsra's own billing).

  Money maths      compute_totals(items, discount, vat_rate) - Decimal, rounded half-up to kobo.
  Settings         get_settings / save_settings (invoice_settings, one row per org; defaults when none saved).
  Drafts           create_draft / update_draft / delete_draft. A draft has no number and can be changed freely.
  Issue            issue(): gives the number (next_invoice_number() in Postgres, atomic), copies the business details
                   into `issuer`, makes the public token, and locks the document. Issued documents are never edited:
                   void and make a new one (audit trail).
  Quotes           accept / decline (staff, INV-1; the customer's own Accept button is INV-3) and convert_quote() which
                   makes a draft invoice from the quote's lines.
  Void             void(): issued/accepted/declined only, and never once money has been recorded against an invoice.
  Lists            list_docs / get_doc. display_status adds 'overdue' (invoice past due date, not fully paid) and
                   'expired' (quote past its valid-until date) without storing them, so no worker is needed for INV-1.

Rules: org_id always comes from the caller (the JWT, S1). Every lead / customer / product id in a request is checked to
belong to that org before it is used. Problems the caller should see raise InvoiceError (code, message, status); the
audit log write never raises (S14).
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

KOBO = Decimal("0.01")
MAX_ITEMS = 100
DOC_TYPES = ("quote", "invoice")
LAGOS = timezone(timedelta(hours=1))   # Africa/Lagos has no daylight saving

SETTINGS_FIELDS = (
    "business_name", "address", "phone", "email", "rc_number", "tin", "logo_url",
    "bank_name", "account_name", "account_number",
    "quote_prefix", "invoice_prefix", "receipt_prefix",
    "vat_enabled", "vat_rate", "default_due_days", "default_quote_valid_days",
    "default_terms", "footer", "brand_colour", "email_reply_to",
)
DEFAULT_SETTINGS = {
    "business_name": None, "address": None, "phone": None, "email": None, "rc_number": None, "tin": None,
    "logo_url": None, "bank_name": None, "account_name": None, "account_number": None,
    "quote_prefix": "QT-", "invoice_prefix": "INV-", "receipt_prefix": "RCT-",
    "vat_enabled": False, "vat_rate": 7.5, "default_due_days": 7, "default_quote_valid_days": 14,
    "default_terms": None, "footer": None, "brand_colour": "#0d9488", "email_reply_to": None,
}
# What an issued document keeps of the settings (printed on it forever).
ISSUER_FIELDS = ("business_name", "address", "phone", "email", "rc_number", "tin", "logo_url",
                 "bank_name", "account_name", "account_number", "footer", "brand_colour")


class InvoiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, field: Optional[str] = None):
        super().__init__(message)
        self.code, self.message, self.status, self.field = code, message, status, field


def _err_nf(what: str = "Document") -> InvoiceError:
    return InvoiceError("NOT_FOUND", f"{what} not found.", 404)


# ───────────────────────────── money ─────────────────────────────

def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        raise InvoiceError("VALIDATION_ERROR", f"Not a number: {value!r}", 422)


def _money(value: Any) -> Decimal:
    return _d(value).quantize(KOBO, rounding=ROUND_HALF_UP)


def compute_totals(items: Iterable[dict], discount: Any = 0, vat_rate: Any = 0) -> dict:
    """Line totals, subtotal, discount, VAT (on subtotal less discount) and total. Never trusts totals sent in."""
    lines = []
    subtotal = Decimal("0")
    for it in items:
        qty, price = _d(it.get("quantity")), _money(it.get("unit_price"))
        if qty <= 0:
            raise InvoiceError("VALIDATION_ERROR", "Quantity must be more than 0.", 422, "quantity")
        if price < 0:
            raise InvoiceError("VALIDATION_ERROR", "Price cannot be below 0.", 422, "unit_price")
        line_total = _money(qty * price)
        subtotal += line_total
        lines.append({**it, "quantity": qty, "unit_price": price, "line_total": line_total})
    subtotal = _money(subtotal)
    disc = _money(discount)
    if disc < 0:
        raise InvoiceError("VALIDATION_ERROR", "Discount cannot be below 0.", 422, "discount")
    if disc > subtotal:
        raise InvoiceError("VALIDATION_ERROR", "Discount cannot be more than the subtotal.", 422, "discount")
    rate = _d(vat_rate)
    vat = _money((subtotal - disc) * rate / Decimal("100"))
    return {"lines": lines, "subtotal": subtotal, "discount": disc, "vat_rate": rate,
            "vat_amount": vat, "total": _money(subtotal - disc + vat)}


def _f(value: Decimal) -> float:
    return float(value)


# ───────────────────────────── helpers ─────────────────────────────

def today() -> date:
    return datetime.now(LAGOS).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _audit(db, org_id: str, user_id: Optional[str], action: str, doc_id: str, new_value: Optional[dict] = None,
           old_value: Optional[dict] = None) -> None:
    try:
        db.table("audit_logs").insert({
            "org_id": org_id, "user_id": user_id, "action": action, "resource_type": "invoice",
            "resource_id": doc_id, "old_value": old_value, "new_value": new_value,
        }).execute()
    except Exception as exc:  # S14
        logger.warning("invoice_service: audit write failed org=%s doc=%s: %s", org_id, doc_id, exc)


def _one(db, table: str, org_id: str, row_id: str, columns: str = "*") -> Optional[dict]:
    q = db.table(table).select(columns).eq("id", str(row_id)).eq("org_id", org_id)
    if table in ("leads", "customers"):
        q = q.is_("deleted_at", "null")
    res = q.limit(1).execute()
    rows = res.data or [] if res else []
    return rows[0] if rows else None


# ───────────────────────────── settings ─────────────────────────────

def get_settings(db, org_id: str) -> dict:
    """Saved settings, or the defaults (business name from the organisation) when none are saved yet."""
    res = db.table("invoice_settings").select("*").eq("org_id", org_id).limit(1).execute()
    rows = (res.data or []) if res else []
    out = dict(DEFAULT_SETTINGS)
    if rows:
        out.update({k: v for k, v in rows[0].items() if k in SETTINGS_FIELDS and v is not None})
        out["saved"] = True
    else:
        out["saved"] = False
        try:
            org = db.table("organisations").select("name").eq("id", org_id).limit(1).execute()
            if org and org.data:
                out["business_name"] = org.data[0].get("name")
        except Exception as exc:
            logger.warning("invoice_service: org name lookup failed org=%s: %s", org_id, exc)
    return out


def save_settings(db, org_id: str, data: dict) -> dict:
    row = {k: v for k, v in data.items() if k in SETTINGS_FIELDS}
    if "vat_rate" in row and row["vat_rate"] is not None:
        row["vat_rate"] = _f(_d(row["vat_rate"]))
    row["org_id"] = org_id
    row["updated_at"] = _now_iso()
    existing = db.table("invoice_settings").select("org_id").eq("org_id", org_id).limit(1).execute()
    if existing and existing.data:
        db.table("invoice_settings").update(row).eq("org_id", org_id).execute()
    else:
        db.table("invoice_settings").insert(row).execute()
    return get_settings(db, org_id)


# ───────────────────────────── customer + lines ─────────────────────────────

def _customer_snapshot(db, org_id: str, data: dict) -> dict:
    """Check lead_id / customer_id belong to the org; fill blank customer fields from them."""
    snap = {"lead_id": None, "customer_id": None}
    src: dict = {}
    if data.get("customer_id"):
        cust = _one(db, "customers", org_id, data["customer_id"], "id, lead_id, full_name, phone, whatsapp, email, location")
        if not cust:
            raise InvoiceError("NOT_FOUND", "Customer not found.", 404, "customer_id")
        snap["customer_id"] = cust["id"]
        snap["lead_id"] = cust.get("lead_id")
        src = cust
    if data.get("lead_id"):
        lead = _one(db, "leads", org_id, data["lead_id"], "id, full_name, phone, whatsapp, email, location")
        if not lead:
            raise InvoiceError("NOT_FOUND", "Lead not found.", 404, "lead_id")
        snap["lead_id"] = lead["id"]
        src = src or lead
    snap["customer_name"] = data.get("customer_name") or src.get("full_name")
    snap["customer_phone"] = data.get("customer_phone") or src.get("whatsapp") or src.get("phone")
    snap["customer_email"] = data.get("customer_email") or src.get("email")
    snap["customer_address"] = data.get("customer_address") or src.get("location")
    return snap


def _resolve_items(db, org_id: str, items: list) -> list:
    """Catalogue lines: product must be the org's; description / price default to the product's."""
    if len(items) > MAX_ITEMS:
        raise InvoiceError("VALIDATION_ERROR", f"At most {MAX_ITEMS} lines.", 422, "items")
    out = []
    for pos, it in enumerate(items):
        it = dict(it)
        pid = it.get("product_id")
        if pid:
            prod = _one(db, "products", org_id, pid, "id, title, price")
            if not prod:
                raise InvoiceError("NOT_FOUND", "Product not found.", 404, "product_id")
            it["product_id"] = prod["id"]
            if not (it.get("description") or "").strip():
                it["description"] = prod.get("title") or "Item"
            if it.get("unit_price") is None:
                it["unit_price"] = prod.get("price") or 0
        desc = (it.get("description") or "").strip()
        if not desc:
            raise InvoiceError("VALIDATION_ERROR", "Every line needs a description.", 422, "description")
        if it.get("unit_price") is None:
            raise InvoiceError("VALIDATION_ERROR", "Every line needs a price.", 422, "unit_price")
        it["description"] = desc
        it["position"] = pos
        out.append(it)
    return out


def _write_items(db, org_id: str, doc_id: str, lines: list) -> None:
    db.table("invoice_items").delete().eq("invoice_id", doc_id).eq("org_id", org_id).execute()
    if lines:
        db.table("invoice_items").insert([{
            "invoice_id": doc_id, "org_id": org_id, "product_id": ln.get("product_id"),
            "description": ln["description"], "quantity": _f(ln["quantity"]), "unit_price": _f(ln["unit_price"]),
            "line_total": _f(ln["line_total"]), "position": ln["position"],
        } for ln in lines]).execute()


def _totals_row(t: dict) -> dict:
    return {"subtotal": _f(t["subtotal"]), "discount": _f(t["discount"]), "vat_rate": _f(t["vat_rate"]),
            "vat_amount": _f(t["vat_amount"]), "total": _f(t["total"])}


def _vat_rate_for(settings: dict, apply_vat: Optional[bool]) -> Decimal:
    use = settings.get("vat_enabled") if apply_vat is None else apply_vat
    return _d(settings.get("vat_rate") or 0) if use else Decimal("0")


# ───────────────────────────── read ─────────────────────────────

def display_status(doc: dict, on: Optional[date] = None) -> str:
    on = on or today()
    st = doc.get("status")
    due = _as_date(doc.get("due_date"))
    if doc.get("doc_type") == "invoice" and st in ("issued", "part_paid") and due and due < on:
        return "overdue"
    if doc.get("doc_type") == "quote" and st == "issued" and due and due < on:
        return "expired"
    return st


def _decorate(doc: dict) -> dict:
    doc = dict(doc)
    doc["display_status"] = display_status(doc)
    doc["balance_due"] = _f(_money(doc.get("total") or 0) - _money(doc.get("amount_paid") or 0))
    return doc


def get_doc(db, org_id: str, doc_id: str) -> dict:
    doc = _one(db, "invoices", org_id, doc_id)
    if not doc:
        raise _err_nf()
    items = db.table("invoice_items").select("*").eq("invoice_id", doc["id"]).eq("org_id", org_id) \
        .order("position").execute()
    doc = _decorate(doc)
    doc["items"] = (items.data or []) if items else []
    return doc


def list_docs(db, org_id: str, doc_type: Optional[str] = None, status: Optional[str] = None,
              lead_id: Optional[str] = None, customer_id: Optional[str] = None, q: Optional[str] = None,
              limit: int = 50, offset: int = 0) -> dict:
    query = db.table("invoices").select(
        "id, doc_type, number, status, lead_id, customer_id, customer_name, customer_phone, currency, total, "
        "amount_paid, issue_date, due_date, created_at, issued_at, converted_from_id"
    ).eq("org_id", org_id)
    if doc_type:
        query = query.eq("doc_type", doc_type)
    if lead_id:
        query = query.eq("lead_id", str(lead_id))
    if customer_id:
        query = query.eq("customer_id", str(customer_id))
    computed = status in ("overdue", "expired")
    if status and not computed:
        query = query.eq("status", status)
    elif status == "overdue":
        query = query.eq("doc_type", "invoice").in_("status", ["issued", "part_paid"])
    elif status == "expired":
        query = query.eq("doc_type", "quote").eq("status", "issued")
    if q:
        needle = q.replace("%", "").replace(",", " ").strip()[:100]
        if needle:
            query = query.or_(f"customer_name.ilike.%{needle}%,number.ilike.%{needle}%")
    query = query.order("created_at", desc=True)
    if computed:
        rows = [_decorate(r) for r in ((query.limit(1000).execute().data) or [])]
        rows = [r for r in rows if r["display_status"] == status]
        return {"items": rows[offset: offset + limit], "total": len(rows)}
    res = query.range(offset, offset + limit - 1).execute()
    return {"items": [_decorate(r) for r in (res.data or [])]}


# ───────────────────────────── drafts ─────────────────────────────

def create_draft(db, org_id: str, user_id: Optional[str], data: dict) -> dict:
    doc_type = data.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise InvoiceError("VALIDATION_ERROR", "doc_type must be quote or invoice.", 422, "doc_type")
    settings = get_settings(db, org_id)
    snap = _customer_snapshot(db, org_id, data)
    lines = _resolve_items(db, org_id, data.get("items") or [])
    totals = compute_totals(lines, data.get("discount") or 0, _vat_rate_for(settings, data.get("apply_vat")))
    row = {
        "org_id": org_id, "doc_type": doc_type, "status": "draft", **snap, **_totals_row(totals),
        "currency": data.get("currency") or "NGN",
        "issue_date": str(data["issue_date"]) if data.get("issue_date") else None,
        "due_date": str(data["due_date"]) if data.get("due_date") else None,
        "notes": data.get("notes"),
        "terms": data.get("terms") if data.get("terms") is not None else settings.get("default_terms"),
        "created_by": user_id,
    }
    res = db.table("invoices").insert(row).execute()
    doc = res.data[0]
    _write_items(db, org_id, doc["id"], totals["lines"])
    _audit(db, org_id, user_id, f"{doc_type}.draft_created", doc["id"], {"total": row["total"]})
    return get_doc(db, org_id, doc["id"])


def _draft_or_raise(db, org_id: str, doc_id: str) -> dict:
    doc = _one(db, "invoices", org_id, doc_id)
    if not doc:
        raise _err_nf()
    if doc.get("status") != "draft":
        raise InvoiceError("INVALID_TRANSITION",
                           "This document has been issued and can't be changed. Void it and make a new one.", 400)
    return doc


def update_draft(db, org_id: str, user_id: Optional[str], doc_id: str, data: dict) -> dict:
    doc = _draft_or_raise(db, org_id, doc_id)
    settings = get_settings(db, org_id)
    patch: dict = {}
    if "lead_id" in data or "customer_id" in data or any(k in data for k in
                                                          ("customer_name", "customer_phone", "customer_email", "customer_address")):
        merged = {k: doc.get(k) for k in ("lead_id", "customer_id", "customer_name", "customer_phone",
                                          "customer_email", "customer_address")}
        merged.update({k: v for k, v in data.items() if k in merged})
        patch.update(_customer_snapshot(db, org_id, merged))
    for k in ("issue_date", "due_date"):
        if k in data:
            patch[k] = str(data[k]) if data[k] else None
    for k in ("notes", "terms", "currency"):
        if k in data:
            patch[k] = data[k]
    if "items" in data:
        lines = _resolve_items(db, org_id, data.get("items") or [])
    else:
        cur = db.table("invoice_items").select("*").eq("invoice_id", doc["id"]).eq("org_id", org_id) \
            .order("position").execute()
        lines = (cur.data or []) if cur else []
    if "apply_vat" in data:
        rate = _vat_rate_for(settings, data.get("apply_vat"))
    else:
        rate = _d(doc.get("vat_rate") or 0)
    totals = compute_totals(lines, data.get("discount", doc.get("discount")) or 0, rate)
    patch.update(_totals_row(totals))
    patch["updated_at"] = _now_iso()
    db.table("invoices").update(patch).eq("id", doc["id"]).eq("org_id", org_id).execute()
    if "items" in data:
        _write_items(db, org_id, doc["id"], totals["lines"])
    return get_doc(db, org_id, doc["id"])


def delete_draft(db, org_id: str, user_id: Optional[str], doc_id: str) -> None:
    doc = _draft_or_raise(db, org_id, doc_id)
    db.table("invoice_items").delete().eq("invoice_id", doc["id"]).eq("org_id", org_id).execute()
    db.table("invoices").delete().eq("id", doc["id"]).eq("org_id", org_id).eq("status", "draft").execute()
    _audit(db, org_id, user_id, f"{doc['doc_type']}.draft_deleted", doc["id"])


# ───────────────────────────── issue / void / quotes ─────────────────────────────

def next_number(db, org_id: str, kind: str, prefix: str) -> str:
    res = db.rpc("next_invoice_number", {"p_org": org_id, "p_kind": kind}).execute()
    value = res.data
    if isinstance(value, list):
        value = value[0] if value else None
        if isinstance(value, dict):
            value = next(iter(value.values()), None)
    if value is None:
        raise InvoiceError("INTEGRATION_ERROR", "Could not get the next number. Please try again.", 503)
    return f"{prefix or ''}{int(value):04d}"


def issue(db, org_id: str, user_id: Optional[str], doc_id: str) -> dict:
    doc = _draft_or_raise(db, org_id, doc_id)
    items = db.table("invoice_items").select("id").eq("invoice_id", doc["id"]).eq("org_id", org_id).execute()
    if not (items and items.data):
        raise InvoiceError("VALIDATION_ERROR", "Add at least one line before issuing.", 422, "items")
    if _money(doc.get("total") or 0) <= 0:
        raise InvoiceError("VALIDATION_ERROR", "The total must be more than 0.", 422, "total")
    if not (doc.get("customer_name") or "").strip():
        raise InvoiceError("VALIDATION_ERROR", "Add the customer's name before issuing.", 422, "customer_name")
    settings = get_settings(db, org_id)
    kind = doc["doc_type"]
    number = next_number(db, org_id, kind, settings.get(f"{kind}_prefix"))
    issue_day = _as_date(doc.get("issue_date")) or today()
    due = _as_date(doc.get("due_date"))
    if not due:
        days = settings.get("default_quote_valid_days" if kind == "quote" else "default_due_days") or 0
        due = issue_day + timedelta(days=int(days))
    patch = {
        "number": number, "status": "issued", "issue_date": str(issue_day), "due_date": str(due),
        "issuer": {k: settings.get(k) for k in ISSUER_FIELDS},
        "public_token": secrets.token_urlsafe(24),
        "issued_at": _now_iso(), "issued_by": user_id, "updated_at": _now_iso(),
    }
    res = db.table("invoices").update(patch).eq("id", doc["id"]).eq("org_id", org_id).eq("status", "draft").execute()
    if not (res and res.data):
        raise InvoiceError("INVALID_TRANSITION", "This document was changed by someone else. Refresh and try again.", 409)
    _audit(db, org_id, user_id, f"{kind}.issued", doc["id"], {"number": number, "total": doc.get("total")})
    return get_doc(db, org_id, doc["id"])


def void(db, org_id: str, user_id: Optional[str], doc_id: str, reason: str) -> dict:
    doc = _one(db, "invoices", org_id, doc_id)
    if not doc:
        raise _err_nf()
    if doc.get("status") not in ("issued", "accepted", "declined"):
        raise InvoiceError("INVALID_TRANSITION",
                           "Only issued documents can be voided. Delete a draft instead." if doc.get("status") == "draft"
                           else "This document can't be voided.", 400)
    if _money(doc.get("amount_paid") or 0) > 0:
        raise InvoiceError("INVALID_TRANSITION", "Money has been recorded on this invoice. Void its receipts first.", 400)
    patch = {"status": "void", "voided_at": _now_iso(), "voided_by": user_id, "void_reason": reason,
             "updated_at": _now_iso()}
    db.table("invoices").update(patch).eq("id", doc["id"]).eq("org_id", org_id).execute()
    _audit(db, org_id, user_id, f"{doc['doc_type']}.voided", doc["id"], {"reason": reason},
           {"status": doc.get("status")})
    return get_doc(db, org_id, doc["id"])


def _quote_or_raise(db, org_id: str, doc_id: str) -> dict:
    doc = _one(db, "invoices", org_id, doc_id)
    if not doc or doc.get("doc_type") != "quote":
        raise _err_nf("Quote")
    return doc


def set_quote_answer(db, org_id: str, user_id: Optional[str], doc_id: str, accepted: bool) -> dict:
    doc = _quote_or_raise(db, org_id, doc_id)
    if doc.get("status") != "issued":
        raise InvoiceError("INVALID_TRANSITION", "Only an issued quote can be accepted or declined.", 400)
    patch = {"status": "accepted" if accepted else "declined", "updated_at": _now_iso(),
             ("accepted_at" if accepted else "declined_at"): _now_iso()}
    db.table("invoices").update(patch).eq("id", doc["id"]).eq("org_id", org_id).execute()
    _audit(db, org_id, user_id, "quote.accepted" if accepted else "quote.declined", doc["id"])
    return get_doc(db, org_id, doc["id"])


def convert_quote(db, org_id: str, user_id: Optional[str], doc_id: str) -> dict:
    """A draft invoice with the quote's customer, lines, discount and VAT. The quote is marked accepted."""
    quote = _quote_or_raise(db, org_id, doc_id)
    if quote.get("status") not in ("issued", "accepted"):
        raise InvoiceError("INVALID_TRANSITION", "Only an issued or accepted quote can become an invoice.", 400)
    existing = db.table("invoices").select("id, status").eq("org_id", org_id).eq("converted_from_id", quote["id"]) \
        .neq("status", "void").limit(1).execute()
    if existing and existing.data:
        raise InvoiceError("DUPLICATE_DETECTED", "This quote already has an invoice.", 409)
    items = db.table("invoice_items").select("*").eq("invoice_id", quote["id"]).eq("org_id", org_id) \
        .order("position").execute()
    lines = (items.data or []) if items else []
    totals = compute_totals(lines, quote.get("discount") or 0, quote.get("vat_rate") or 0)
    row = {
        "org_id": org_id, "doc_type": "invoice", "status": "draft",
        **{k: quote.get(k) for k in ("lead_id", "customer_id", "customer_name", "customer_phone",
                                     "customer_email", "customer_address", "currency", "notes", "terms")},
        **_totals_row(totals), "converted_from_id": quote["id"], "created_by": user_id,
    }
    res = db.table("invoices").insert(row).execute()
    inv = res.data[0]
    _write_items(db, org_id, inv["id"], [{**ln, "position": i} for i, ln in enumerate(totals["lines"])])
    if quote.get("status") == "issued":
        db.table("invoices").update({"status": "accepted", "accepted_at": _now_iso(), "updated_at": _now_iso()}) \
            .eq("id", quote["id"]).eq("org_id", org_id).execute()
    _audit(db, org_id, user_id, "quote.converted", quote["id"], {"invoice_id": inv["id"]})
    return get_doc(db, org_id, inv["id"])
