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
    "reminders_enabled",   # INV-5
    "sales_record_enabled", "sales_record_since",   # INV-SALES-1 (since is set by save_settings, never sent in)
)
DEFAULT_SETTINGS = {
    "business_name": None, "address": None, "phone": None, "email": None, "rc_number": None, "tin": None,
    "logo_url": None, "bank_name": None, "account_name": None, "account_number": None,
    "quote_prefix": "QT-", "invoice_prefix": "INV-", "receipt_prefix": "RCT-",
    "vat_enabled": False, "vat_rate": 7.5, "default_due_days": 7, "default_quote_valid_days": 14,
    "default_terms": None, "footer": None, "brand_colour": "#0d9488", "email_reply_to": None,
    "reminders_enabled": False,
    "sales_record_enabled": False, "sales_record_since": None,
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
    if not (out.get("business_name") or "").strip():   # INV-3: saved settings without a name also use the organisation name
        try:
            org = db.table("organisations").select("name").eq("id", org_id).limit(1).execute()
            if org and org.data:
                out["business_name"] = org.data[0].get("name")
        except Exception as exc:
            logger.warning("invoice_service: org name lookup failed org=%s: %s", org_id, exc)
    return out


def save_settings(db, org_id: str, data: dict) -> dict:
    row = {k: v for k, v in data.items() if k in SETTINGS_FIELDS and k != "sales_record_since"}
    if row.get("sales_record_enabled") is True and not get_settings(db, org_id).get("sales_record_enabled"):
        row["sales_record_since"] = _now_iso()   # INV-SALES-1: only invoices paid from now on go to Sales Record
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


def product_sizes(prod: Optional[dict]) -> list:
    """INV-SALES-2: the sizes a catalogue product is sold in ([{title, price}]), from its Shopify variants.
    A product with one 'Default Title' variant has no sizes."""
    out, seen = [], set()
    for v in ((prod or {}).get("variants") or []) if isinstance((prod or {}).get("variants"), list) else []:
        if not isinstance(v, dict):
            continue
        title = str(v.get("title") or v.get("option1") or "").strip()[:100]
        if not title or title.lower() == "default title" or title.lower() in seen:
            continue
        seen.add(title.lower())
        try:
            price = float(v.get("price")) if v.get("price") not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        out.append({"title": title, "price": price})
    return out


def _resolve_items(db, org_id: str, items: list) -> list:
    """Catalogue lines: product must be the org's; description / price default to the product's.
    INV-SALES-2: a size (variant) must be one of the product's sizes; it sets the price when none is typed and is added
    to the line text so the customer sees it. Typed lines may carry a size as free text."""
    if len(items) > MAX_ITEMS:
        raise InvoiceError("VALIDATION_ERROR", f"At most {MAX_ITEMS} lines.", 422, "items")
    out = []
    for pos, it in enumerate(items):
        it = dict(it)
        pid = it.get("product_id")
        if pid:
            prod = _one(db, "products", org_id, pid, "id, title, price, variants")
            if not prod:
                raise InvoiceError("NOT_FOUND", "Product not found.", 404, "product_id")
            it["product_id"] = prod["id"]
            if not (it.get("description") or "").strip():
                it["description"] = prod.get("title") or "Item"
            sizes = product_sizes(prod)
            want = str(it.get("variant") or "").strip()
            size = None
            if want:
                size = next((s for s in sizes if s["title"].lower() == want.lower()), None)
                if not size:
                    raise InvoiceError("VALIDATION_ERROR", f"Choose one of the sizes for {prod.get('title') or 'this product'}.",
                                       422, "variant")
            it["variant"] = size["title"] if size else None
            if it.get("unit_price") is None:
                it["unit_price"] = (size or {}).get("price") if (size or {}).get("price") is not None else (prod.get("price") or 0)
        else:
            it["variant"] = (str(it.get("variant") or "").strip()[:100]) or None
        if it.get("variant") and it["variant"].lower() not in str(it.get("description") or "").lower():
            it["description"] = f"{str(it.get('description') or '').strip()} - {it['variant']}"[:500]
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
            "line_total": _f(ln["line_total"]), "position": ln["position"], "variant": ln.get("variant"),
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
    loc_ids = {doc.get("location_id")} | {i.get("stock_location_id") for i in doc["items"]}
    loc_ids.discard(None)
    if loc_ids:   # STOCK-2 / STOCK-2b: the invoice's location, and where each line's stock is held
        locs = db.table("stock_locations").select("id, name").eq("org_id", org_id).in_("id", sorted(loc_ids)).execute()
        names = {l["id"]: l["name"] for l in ((locs.data or []) if locs else [])}
        doc["location_name"] = names.get(doc.get("location_id"))
        for i in doc["items"]:
            if i.get("stock_location_id"):
                i["stock_location_name"] = names.get(i["stock_location_id"])
    if doc.get("status") == "draft":   # INV-SALES-2: the editor offers each product line's sizes
        pids = sorted({i["product_id"] for i in doc["items"] if i.get("product_id")})
        if pids:
            prods = db.table("products").select("id, variants").eq("org_id", org_id).in_("id", pids).execute()
            by_id = {p["id"]: product_sizes(p) for p in ((prods.data or []) if prods else [])}
            for i in doc["items"]:
                if i.get("product_id"):
                    i["sizes"] = by_id.get(i["product_id"], [])
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
        needle = _needle(q)
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
    if data.get("region") is not None:   # INV-SALES-1
        from app.services import invoice_sales_service as sales
        row["region"] = sales.clean_region(db, org_id, data.get("region"))
    if data.get("location_id") is not None:   # STOCK-2
        from app.services import invoice_stock_service as inv_stock
        row["location_id"] = inv_stock.clean_location(db, org_id, data.get("location_id"))
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
    if doc.get("stock_approval") == "pending":   # STOCK-2b: goods are held while an admin decides
        raise InvoiceError("INVALID_TRANSITION",
                           "This invoice is waiting for stock approval. Cancel the request to change it.", 400)
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
    if "region" in data:   # INV-SALES-1
        from app.services import invoice_sales_service as sales
        patch["region"] = sales.clean_region(db, org_id, data.get("region"))
    if "location_id" in data:   # STOCK-2
        from app.services import invoice_stock_service as inv_stock
        patch["location_id"] = inv_stock.clean_location(db, org_id, data.get("location_id"))
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


def _sizes_picked(db, org_id: str, doc_id: str) -> None:
    """INV-SALES-2: every catalogue line whose product comes in sizes must have its size picked."""
    res = db.table("invoice_items").select("product_id, description, variant").eq("invoice_id", doc_id) \
        .eq("org_id", org_id).execute()
    lines = [i for i in ((res.data or []) if res else []) if i.get("product_id") and not i.get("variant")]
    if not lines:
        return
    prods = db.table("products").select("id, title, variants").eq("org_id", org_id) \
        .in_("id", sorted({i["product_id"] for i in lines})).execute()
    sized = {p["id"]: p.get("title") for p in ((prods.data or []) if prods else []) if product_sizes(p)}
    for i in lines:
        if i["product_id"] in sized:
            raise InvoiceError("VALIDATION_ERROR", f"Choose the size for {sized[i['product_id']] or i.get('description')}.",
                               422, "variant")


def issue(db, org_id: str, user_id: Optional[str], doc_id: str, sources: Optional[dict] = None,
          allow_other: bool = False) -> dict:
    """sources / allow_other (STOCK-2b): managers may take lines from another location while issuing."""
    doc = issue_checks(db, org_id, doc_id)
    # STOCK-2: hold the product lines' stock first; not enough anywhere -> refused before a number is used.
    from app.services import invoice_stock_service as inv_stock
    tracked = inv_stock.prepare_issue(db, org_id, user_id, doc, sources=sources, allow_other=allow_other)
    try:
        return _issue_numbered(db, org_id, user_id, doc)
    except Exception:
        if tracked:
            inv_stock.undo_issue(db, org_id, user_id, doc["id"])
        raise


def issue_checks(db, org_id: str, doc_id: str) -> dict:
    """Everything a draft needs before it can be issued (also used before asking for stock approval)."""
    doc = _draft_or_raise(db, org_id, doc_id)
    items = db.table("invoice_items").select("id").eq("invoice_id", doc["id"]).eq("org_id", org_id).execute()
    if not (items and items.data):
        raise InvoiceError("VALIDATION_ERROR", "Add at least one line before issuing.", 422, "items")
    if _money(doc.get("total") or 0) <= 0:
        raise InvoiceError("VALIDATION_ERROR", "The total must be more than 0.", 422, "total")
    if not (doc.get("customer_name") or "").strip():
        raise InvoiceError("VALIDATION_ERROR", "Add the customer's name before issuing.", 422, "customer_name")
    from app.services import invoice_sales_service as sales   # INV-SALES-1
    if not doc.get("region") and sales.region_required(db, org_id):
        raise InvoiceError("VALIDATION_ERROR", "Choose the region before issuing.", 422, "region")
    _sizes_picked(db, org_id, doc["id"])   # INV-SALES-2
    return doc


def _issue_numbered(db, org_id: str, user_id: Optional[str], doc: dict) -> dict:
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
    if doc.get("stock_tracked"):   # STOCK-2: held stock goes back to available
        from app.services import invoice_stock_service as inv_stock
        inv_stock.sync(db, org_id, doc["id"], user_id)
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
                                     "customer_email", "customer_address", "currency", "notes", "terms", "region",
                                     "location_id")},
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


# ───────────────────────────── INV-2: pickers, summary, logo ─────────────────────────────

def _needle(q: Optional[str]) -> str:
    """Search text safe to put inside a PostgREST or_() filter (no commas, brackets, wildcards or quotes)."""
    import re as _re
    return _re.sub(r"[%,()*\"'\\:]", " ", (q or "")).strip()[:60]


def search_products(db, org_id: str, q: Optional[str] = None, limit: int = 20) -> list:
    query = db.table("products").select("id, title, price, image_url, available, is_active, variants").eq("org_id", org_id)
    needle = _needle(q)
    if needle:
        query = query.ilike("title", f"%{needle}%")
    res = query.order("title").limit(200).execute()
    rows = [r for r in ((res.data or []) if res else []) if r.get("is_active") is not False]
    return [{"id": r["id"], "title": r.get("title"), "price": r.get("price"), "image_url": r.get("image_url"),
             "available": r.get("available"), "sizes": product_sizes(r)} for r in rows[:limit]]


def search_contacts(db, org_id: str, q: Optional[str] = None, limit: int = 10) -> list:
    """Leads to bill (works for every product mode; /leads itself is closed to WhatsApp-only and web-chat-only orgs)."""
    needle = _needle(q)
    query = db.table("leads").select("id, full_name, phone, whatsapp, email, location") \
        .eq("org_id", org_id).is_("deleted_at", "null")
    if needle:
        query = query.or_(f"full_name.ilike.%{needle}%,phone.ilike.%{needle}%,whatsapp.ilike.%{needle}%,email.ilike.%{needle}%")
    res = query.order("last_activity_at", desc=True).limit(limit).execute()
    return (res.data or []) if res else []


def summary(db, org_id: str) -> dict:
    """Money owed (issued + part paid invoices), how much of it is overdue, open quotes and drafts."""
    res = db.table("invoices").select("doc_type, status, total, amount_paid, due_date").eq("org_id", org_id) \
        .in_("status", ["draft", "issued", "part_paid"]).limit(5000).execute()
    out = {"drafts": 0, "open_quotes": 0, "open_quotes_amount": 0.0, "outstanding_count": 0,
           "outstanding_amount": 0.0, "overdue_count": 0, "overdue_amount": 0.0}
    owed_total = overdue_total = quotes_total = Decimal("0")
    for r in ((res.data or []) if res else []):
        if r.get("status") == "draft":
            out["drafts"] += 1
            continue
        if r.get("doc_type") == "quote":
            if display_status(r) == "issued":
                out["open_quotes"] += 1
                quotes_total += _money(r.get("total"))
            continue
        bal = _money(r.get("total")) - _money(r.get("amount_paid"))
        out["outstanding_count"] += 1
        owed_total += bal
        if display_status(r) == "overdue":
            out["overdue_count"] += 1
            overdue_total += bal
    out.update(outstanding_amount=_f(owed_total), overdue_amount=_f(overdue_total), open_quotes_amount=_f(quotes_total))
    return out


LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MAX_SIDE = 600


def save_logo(db, org_id: str, data: bytes) -> dict:
    """Checks the bytes really are a PNG/JPEG/WebP image, re-draws it as a PNG at most 600 px (drops anything hidden in the
    file), stores it in the public catalog bucket under <org>/invoice-logo/ and saves the URL in the settings."""
    import io
    if not data or len(data) > LOGO_MAX_BYTES:
        raise InvoiceError("VALIDATION_ERROR", "The logo must be an image under 2 MB.", 422, "file")
    head = data[:12]
    if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")):
        raise InvoiceError("VALIDATION_ERROR", "Use a PNG, JPG or WebP image.", 422, "file")
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 40_000_000
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        img.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
    except Exception as exc:
        logger.info("invoice_service.save_logo: unreadable image org=%s: %s", org_id, exc)
        raise InvoiceError("VALIDATION_ERROR", "That image could not be read. Try another file.", 422, "file")
    path = f"{org_id}/invoice-logo/logo-{secrets.token_hex(6)}.png"
    try:
        db.storage.from_("catalog").upload(path=path, file=png,
                                           file_options={"content-type": "image/png", "upsert": "true"})
        url = db.storage.from_("catalog").get_public_url(path)
    except Exception as exc:
        logger.error("invoice_service.save_logo: upload failed org=%s: %s", org_id, exc)
        raise InvoiceError("INTEGRATION_ERROR", "Could not save the logo. Please try again.", 503)
    url = (url or "").split("?")[0]
    return save_settings(db, org_id, {"logo_url": url})


def remove_logo(db, org_id: str) -> dict:
    db.table("invoice_settings").update({"logo_url": None, "updated_at": _now_iso()}).eq("org_id", org_id).execute()
    return get_settings(db, org_id)
