"""
app/services/invoice_payment_service.py
---------------------------------------
INV-4 - money received against a business's invoices, and the receipts for it.

  Record       record_payment(): staff record a transfer / cash / POS / USSD / other payment against an issued invoice.
               Part payments are allowed (many receipts per invoice). A receipt number is given from the same atomic
               counter as quotes and invoices (kind 'receipt'), and the business details are copied into it.
  Standalone   standalone_receipt(): a receipt with no invoice (a walk-in sale).
  Void         void_receipt() (admin, reason). The invoice's amount_paid and status are worked out again.
  Totals       amount_paid is always the SUM of the invoice's receipts that are not void (never added to in place), so
               two payments recorded at the same moment cannot lose one. Status: issued -> part_paid -> paid.
               Fully paid -> the lead becomes 'converted' (commerce_service.convert_lead_on_purchase).
  Paystack     can_pay() / start_checkout(): the customer's page /i/<token> gets a Pay now button when the business has
               its own Paystack connected (integrations.provider='paystack_storefront') and the invoice has a lead
               (payment_links.lead_id is required). Reference: inv_<invoice id hex>_<random>.
               on_payment_confirmed(): called by the storefront webhook after paystack_storefront_service.mark_paid; makes
               the receipt (once: receipts.payment_link_id is unique) and sends it to the customer.
               verify_return(): when the customer comes back from Paystack before the webhook, check with Paystack and
               record it the same way (idempotent).

Rules: org_id from the caller (JWT, S1) for staff calls; public calls find the org from the invoice token. Problems the
caller should see raise invoice_service.InvoiceError. Side effects (lead conversion, sending the receipt) never raise
(S14).
"""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

METHODS = ("paystack", "bank_transfer", "cash", "pos", "ussd", "other")
MANUAL_METHODS = ("bank_transfer", "cash", "pos", "ussd", "other")
PAYABLE = ("issued", "part_paid")
REF_RE = re.compile(r"^inv_([0-9a-f]{32})_[0-9a-f]{8}$")


def _rows(res) -> list:
    return (res.data or []) if res else []


def _paid_at(value) -> str:
    """A date or ISO time, not in the future (a little slack for clocks). Defaults to now."""
    now = datetime.now(timezone.utc)
    if not value:
        return now.isoformat()
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime(value.year, value.month, value.day, 12, tzinfo=inv.LAGOS)
        else:
            s = str(value)
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s else \
                datetime.fromisoformat(s[:10]).replace(hour=12, tzinfo=inv.LAGOS)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=inv.LAGOS)
    except Exception:
        raise inv.InvoiceError("VALIDATION_ERROR", "The payment date is not valid.", 422, "paid_at")
    if dt > now + timedelta(days=1):
        raise inv.InvoiceError("VALIDATION_ERROR", "The payment date cannot be in the future.", 422, "paid_at")
    if dt < now - timedelta(days=3650):
        raise inv.InvoiceError("VALIDATION_ERROR", "The payment date is too far in the past.", 422, "paid_at")
    return dt.isoformat()


# ───────────────────────────── reading ─────────────────────────────

RECEIPT_LIST_COLS = ("id, number, invoice_id, lead_id, customer_id, customer_name, amount, currency, method, reference, "
                     "description, paid_at, recorded_by, payment_link_id, voided_at, void_reason, created_at")


def get_receipt(db, org_id: str, receipt_id: str) -> dict:
    row = inv._one(db, "receipts", org_id, receipt_id)
    if not row:
        raise inv._err_nf("Receipt")
    return row


def list_receipts(db, org_id: str, invoice_id: Optional[str] = None, lead_id: Optional[str] = None,
                  q: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
    query = db.table("receipts").select(RECEIPT_LIST_COLS).eq("org_id", org_id)
    if invoice_id:
        query = query.eq("invoice_id", invoice_id)
    if lead_id:
        query = query.eq("lead_id", lead_id)
    needle = inv._needle(q)
    if needle:
        query = query.or_(f"customer_name.ilike.%{needle}%,number.ilike.%{needle}%,reference.ilike.%{needle}%")
    res = query.order("paid_at", desc=True).range(offset, offset + max(1, min(limit, 200)) - 1).execute()
    rows = _rows(res)
    numbers = {}
    inv_ids = sorted({r["invoice_id"] for r in rows if r.get("invoice_id")})
    if inv_ids:
        found = db.table("invoices").select("id, number").eq("org_id", org_id).in_("id", inv_ids).execute()
        numbers = {r["id"]: r.get("number") for r in _rows(found)}
    for r in rows:
        r["invoice_number"] = numbers.get(r.get("invoice_id"))
    return {"items": rows}


def receipts_for_invoice(db, org_id: str, invoice_id: str) -> list:
    res = db.table("receipts").select(RECEIPT_LIST_COLS + ", public_token").eq("org_id", org_id) \
        .eq("invoice_id", invoice_id).order("paid_at").execute()
    return _rows(res)


# ───────────────────────────── totals ─────────────────────────────

def _recompute(db, org_id: str, invoice_id: str) -> tuple[dict, bool]:
    """Work amount_paid and status out again from the receipts. Returns (invoice, became_fully_paid)."""
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf()
    paid = sum((inv._money(r.get("amount")) for r in receipts_for_invoice(db, org_id, invoice_id)
                if not r.get("voided_at")), Decimal("0"))
    total = inv._money(doc.get("total") or 0)
    old = doc.get("status")
    if old in ("issued", "part_paid", "paid"):
        new = "paid" if total > 0 and paid >= total else ("part_paid" if paid > 0 else "issued")
    else:
        new = old
    db.table("invoices").update({"amount_paid": inv._f(paid), "status": new, "updated_at": inv._now_iso()}) \
        .eq("id", invoice_id).eq("org_id", org_id).execute()
    if new == "paid" or old == "paid":   # INV-SALES-1: add to / take out of Sales Record (never raises)
        from app.services import invoice_sales_service as sales
        sales.sync_invoice(db, org_id, invoice_id)
    return inv.get_doc(db, org_id, invoice_id), (new == "paid" and old != "paid")


def _convert_lead(db, org_id: str, lead_id: Optional[str]) -> None:
    if not lead_id:
        return
    try:
        res = db.table("leads").select("stage").eq("id", lead_id).eq("org_id", org_id).limit(1).execute()
        rows = _rows(res)
        if rows and rows[0].get("stage") != "converted":
            from app.services import commerce_service
            commerce_service.convert_lead_on_purchase(db, org_id, lead_id)
    except Exception as exc:  # S14
        logger.warning("invoice_payment: lead conversion failed org=%s lead=%s: %s", org_id, lead_id, exc)


# ───────────────────────────── record ─────────────────────────────

def _insert_receipt(db, org_id: str, row: dict) -> dict:
    settings = inv.get_settings(db, org_id)
    row = {**row, "org_id": org_id,
           "number": inv.next_number(db, org_id, "receipt", settings.get("receipt_prefix")),
           "public_token": secrets.token_urlsafe(24), "created_at": inv._now_iso()}
    if not row.get("issuer"):
        row["issuer"] = {k: settings.get(k) for k in inv.ISSUER_FIELDS}
    res = db.table("receipts").insert(row).execute()
    out = _rows(res)
    if not out:
        raise inv.InvoiceError("INTEGRATION_ERROR", "Could not save the receipt. Please try again.", 503)
    return out[0]


def record_payment(db, org_id: str, user_id: Optional[str], invoice_id: str, data: dict,
                   payment_link_id: Optional[str] = None, allow_over: bool = False) -> dict:
    """data: amount, method, reference?, paid_at?, note?. Returns {"receipt", "invoice", "fully_paid"}."""
    doc = inv.get_doc(db, org_id, invoice_id)
    if doc["doc_type"] != "invoice":
        raise inv.InvoiceError("INVALID_TRANSITION", "Payments are recorded against invoices, not quotes.", 400)
    if doc.get("status") not in PAYABLE:
        msg = {"draft": "Issue the invoice before recording a payment.", "paid": "This invoice is already fully paid.",
               "void": "This invoice is void."}.get(doc.get("status"), "This invoice cannot take a payment.")
        raise inv.InvoiceError("INVALID_TRANSITION", msg, 400)
    method = data.get("method")
    if method not in METHODS or (method == "paystack" and not payment_link_id):
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose how the customer paid.", 422, "method")
    amount = inv._money(data.get("amount") or 0)
    if amount <= 0:
        raise inv.InvoiceError("VALIDATION_ERROR", "The amount must be more than 0.", 422, "amount")
    balance = inv._money(doc.get("total") or 0) - inv._money(doc.get("amount_paid") or 0)
    if amount > balance and not allow_over:
        raise inv.InvoiceError("VALIDATION_ERROR", f"That is more than the balance due ({inv._f(balance):,.2f}).", 422,
                               "amount")
    note = (data.get("note") or "").strip()
    row = {
        "invoice_id": doc["id"], "lead_id": doc.get("lead_id"), "customer_id": doc.get("customer_id"),
        "customer_name": doc.get("customer_name"), "amount": inv._f(amount), "currency": doc.get("currency") or "NGN",
        "method": method, "reference": (data.get("reference") or "").strip()[:200] or None,
        "description": (note or f"Payment for invoice {doc.get('number')}")[:500],
        "paid_at": _paid_at(data.get("paid_at")), "recorded_by": user_id, "payment_link_id": payment_link_id,
        "issuer": doc.get("issuer"),
    }
    receipt = _insert_receipt(db, org_id, row)
    invoice, fully = _recompute(db, org_id, doc["id"])
    inv._audit(db, org_id, user_id, "receipt.recorded", doc["id"],
               {"receipt": receipt["number"], "amount": inv._f(amount), "method": method})
    if fully:
        _convert_lead(db, org_id, doc.get("lead_id"))
    return {"receipt": receipt, "invoice": invoice, "fully_paid": invoice.get("status") == "paid"}


def standalone_receipt(db, org_id: str, user_id: Optional[str], data: dict) -> dict:
    """A receipt for a sale with no invoice. Customer from lead_id / customer_id (checked against the org) or typed."""
    method = data.get("method")
    if method not in MANUAL_METHODS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose how the customer paid.", 422, "method")
    amount = inv._money(data.get("amount") or 0)
    if amount <= 0:
        raise inv.InvoiceError("VALIDATION_ERROR", "The amount must be more than 0.", 422, "amount")
    snap = inv._customer_snapshot(db, org_id, data)
    if not (snap.get("customer_name") or "").strip():
        raise inv.InvoiceError("VALIDATION_ERROR", "Add the customer's name.", 422, "customer_name")
    description = (data.get("description") or "").strip()
    if not description:
        raise inv.InvoiceError("VALIDATION_ERROR", "Say what the payment was for.", 422, "description")
    from app.services import invoice_sales_service as sales   # INV-SALES-1
    region = sales.clean_region(db, org_id, data.get("region"))
    if not region and sales.region_required(db, org_id):
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose the region.", 422, "region")
    row = {
        "invoice_id": None, "lead_id": snap.get("lead_id"), "customer_id": snap.get("customer_id"),
        "customer_name": snap.get("customer_name"), "amount": inv._f(amount), "currency": "NGN", "method": method,
        "reference": (data.get("reference") or "").strip()[:200] or None, "description": description[:500],
        "paid_at": _paid_at(data.get("paid_at")), "recorded_by": user_id, "region": region,
    }
    receipt = _insert_receipt(db, org_id, row)
    receipt["_contact"] = {k: snap.get(k) for k in ("customer_phone", "customer_email", "customer_address")}
    sales.sync_receipt(db, org_id, receipt)
    inv._audit(db, org_id, user_id, "receipt.recorded", receipt["id"], {"receipt": receipt["number"],
                                                                        "amount": inv._f(amount), "standalone": True})
    return receipt


def void_receipt(db, org_id: str, user_id: Optional[str], receipt_id: str, reason: str) -> dict:
    r = get_receipt(db, org_id, receipt_id)
    if r.get("voided_at"):
        raise inv.InvoiceError("INVALID_TRANSITION", "This receipt is already void.", 400)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise inv.InvoiceError("VALIDATION_ERROR", "Say why the receipt is being voided.", 422, "reason")
    db.table("receipts").update({"voided_at": inv._now_iso(), "voided_by": user_id, "void_reason": reason[:500]}) \
        .eq("id", r["id"]).eq("org_id", org_id).execute()
    if r.get("invoice_id"):
        _recompute(db, org_id, r["invoice_id"])
    else:   # INV-SALES-1: a voided standalone receipt leaves Sales Record
        from app.services import invoice_sales_service as sales
        sales.sync_receipt(db, org_id, {**r, "voided_at": inv._now_iso()})
    inv._audit(db, org_id, user_id, "receipt.voided", r.get("invoice_id") or r["id"],
               {"receipt": r.get("number"), "reason": reason[:500]})
    return get_receipt(db, org_id, r["id"])


# ───────────────────────────── receipt PDF ─────────────────────────────

def receipt_doc(db, org_id: str, r: dict) -> dict:
    """What the receipt PDF needs: the receipt plus the invoice number and the balance left after this payment."""
    out = dict(r)
    if r.get("voided_at"):
        out["status"] = "void"
    if r.get("invoice_id"):
        doc = inv._one(db, "invoices", org_id, r["invoice_id"])
        if doc:
            out["invoice_number"] = doc.get("number")
            upto = [x for x in receipts_for_invoice(db, org_id, r["invoice_id"])
                    if not x.get("voided_at") and (str(x.get("paid_at") or ""), str(x.get("created_at") or ""))
                    <= (str(r.get("paid_at") or ""), str(r.get("created_at") or ""))]
            paid = sum((inv._money(x.get("amount")) for x in upto), Decimal("0"))
            out["invoice_balance"] = inv._f(max(inv._money(doc.get("total") or 0) - paid, Decimal("0")))
            for k in ("customer_phone", "customer_email", "customer_address"):
                out.setdefault(k, doc.get(k))
    return out


def render_receipt(db, org_id: str, r: dict) -> tuple[bytes, str]:
    from app.services import invoice_pdf_service as pdf
    d = receipt_doc(db, org_id, r)
    settings = inv.get_settings(db, org_id) if not d.get("issuer") else {}
    data, name = pdf.render(d, settings, "receipt")
    if not data:
        raise inv.InvoiceError("INTEGRATION_ERROR", "Could not make the PDF. Please try again.", 503)
    return data, name


# ───────────────────────────── Paystack ─────────────────────────────

def _creds(db, org_id: str) -> dict:
    try:
        from app.services import paystack_storefront_service as ps
        return ps._get_storefront_credentials(db, org_id) or {}
    except Exception as exc:
        logger.warning("invoice_payment: credentials lookup failed org=%s: %s", org_id, exc)
        return {}


def can_pay(db, doc: dict) -> bool:
    if doc.get("doc_type") != "invoice" or doc.get("status") not in PAYABLE or not doc.get("lead_id"):
        return False
    if inv._money(doc.get("total") or 0) - inv._money(doc.get("amount_paid") or 0) <= 0:
        return False
    return bool((_creds(db, doc["org_id"]).get("secret_key") or "").strip())


def start_checkout(db, doc: dict, return_url: str) -> str:
    """A Paystack checkout for the balance due, in the business's own Paystack account. Returns the checkout URL."""
    import httpx
    if not can_pay(db, doc):
        raise inv.InvoiceError("INVALID_TRANSITION", "Online payment is not available for this invoice.", 400)
    org_id = doc["org_id"]
    secret = (_creds(db, org_id).get("secret_key") or "").strip()
    balance = inv._money(doc.get("total") or 0) - inv._money(doc.get("amount_paid") or 0)
    reference = f"inv_{uuid.UUID(str(doc['id'])).hex}_{secrets.token_hex(4)}"
    email = (doc.get("customer_email") or "").strip()
    if not email or "@" not in email:
        email = f"invoice-{str(doc['id'])[:8]}@example.com"     # Paystack needs an email; same idea as PAY-LINK-1
    payload = {"email": email, "amount": int(balance * 100), "currency": "NGN", "reference": reference,
               "callback_url": return_url,
               "metadata": {"kind": "invoice", "invoice_number": doc.get("number"),
                            "cancel_action": return_url}}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{_ps_base()}/transaction/initialize",
                               headers={"Authorization": f"Bearer {secret}"}, json=payload)
        body = resp.json()
        url = (body.get("data") or {}).get("authorization_url") if resp.status_code == 200 and body.get("status") else None
    except Exception as exc:
        logger.warning("invoice_payment: Paystack initialize failed org=%s doc=%s: %s", org_id, doc.get("id"), exc)
        url = None
    if not url:
        raise inv.InvoiceError("INTEGRATION_ERROR", "Online payment is not working right now. Please pay by bank "
                               "transfer or try again later.", 503)
    now = inv._now_iso()
    link = _rows(db.table("payment_links").insert({
        "org_id": org_id, "lead_id": doc["lead_id"],
        "payment_type": "full" if inv._money(doc.get("amount_paid") or 0) == 0 else "balance",
        "amount": inv._f(balance), "currency": "NGN", "reference": reference, "checkout_url": url,
        "status": "pending", "sent_at": now, "notes": f"Invoice {doc.get('number')}"[:200],
        "created_at": now, "updated_at": now,
    }).execute())
    if link:
        try:
            db.table("invoices").update({"payment_link_id": link[0]["id"]}).eq("id", doc["id"]).eq("org_id", org_id).execute()
        except Exception as exc:  # S14
            logger.warning("invoice_payment: payment_link_id write failed doc=%s: %s", doc.get("id"), exc)
    return url


def _link(db, org_id: str, reference: str) -> Optional[dict]:
    rows = _rows(db.table("payment_links").select("*").eq("org_id", org_id).eq("reference", reference).limit(1).execute())
    return rows[0] if rows else None


def on_payment_confirmed(db, org_id: str, reference: str, user_id: Optional[str] = None) -> Optional[dict]:
    """After Paystack confirms a charge for an invoice reference: make the receipt once and send it. Never raises."""
    try:
        m = REF_RE.match(str(reference or ""))
        if not m:
            return None
        invoice_id = str(uuid.UUID(m.group(1)))
        link = _link(db, org_id, reference)
        if not link or link.get("status") != "paid":
            return None
        done = _rows(db.table("receipts").select("id").eq("org_id", org_id).eq("payment_link_id", link["id"]).limit(1).execute())
        if done:
            return None
        doc = inv._one(db, "invoices", org_id, invoice_id)
        if not doc:
            logger.warning("invoice_payment: paid reference for a missing invoice org=%s ref=%s", org_id, reference)
            return None
        if doc.get("status") not in PAYABLE:
            # paid online after the invoice was settled another way or voided. The money is in payment_links and the
            # rep got mark_paid's notification; a person has to sort out the refund or credit.
            logger.warning("invoice_payment: Paystack payment on invoice in status %s org=%s ref=%s",
                           doc.get("status"), org_id, reference)
            return None
        out = record_payment(db, org_id, user_id, invoice_id,
                             {"amount": link.get("amount"), "method": "paystack", "reference": reference,
                              "paid_at": link.get("paid_at")},
                             payment_link_id=link["id"], allow_over=True)
        try:
            from app.services import invoice_delivery_service as delivery
            delivery.send_receipt(db, org_id, None, out["receipt"]["id"])
        except Exception as exc:  # S14
            logger.warning("invoice_payment: receipt send failed org=%s ref=%s: %s", org_id, reference, exc)
        return out
    except Exception as exc:  # S14 - the webhook must always answer Paystack
        logger.error("invoice_payment: on_payment_confirmed failed org=%s ref=%s: %s", org_id, reference, exc)
        return None


def verify_return(db, doc: dict, reference: str) -> bool:
    """The customer is back from Paystack. Ask Paystack; if paid, run the same path the webhook runs. True if paid."""
    m = REF_RE.match(str(reference or ""))
    if not m or str(uuid.UUID(m.group(1))) != str(doc["id"]):
        raise inv.InvoiceError("VALIDATION_ERROR", "That payment reference is not for this invoice.", 422, "reference")
    org_id = doc["org_id"]
    link = _link(db, org_id, reference)
    if not link:
        raise inv.InvoiceError("NOT_FOUND", "We could not find that payment.", 404)
    if link.get("status") != "paid":
        from app.services import paystack_storefront_service as ps
        v = ps.verify_transaction(db, org_id, reference)
        data = v.get("data") or {}
        if not (v.get("verified") and v.get("status") == "success"
                and int(data.get("amount") or 0) >= int(inv._money(link.get("amount")) * 100)):
            return False
        ps.mark_paid(db=db, org_id=org_id, reference=reference)
    on_payment_confirmed(db, org_id, reference)
    return True


# ───────────────────────────── summary ─────────────────────────────

def paid_this_month(db, org_id: str) -> float:
    start = datetime.now(inv.LAGOS).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        res = db.table("receipts").select("amount, voided_at").eq("org_id", org_id) \
            .gte("paid_at", start.isoformat()).limit(10000).execute()
        return inv._f(sum((inv._money(r.get("amount")) for r in _rows(res) if not r.get("voided_at")), Decimal("0")))
    except Exception as exc:  # S14 - the summary still shows the rest
        logger.warning("invoice_payment: paid this month failed org=%s: %s", org_id, exc)
        return 0.0


def _ps_base() -> str:
    try:
        from app.services import paystack_storefront_service as ps
        return ps._PAYSTACK_API_BASE
    except Exception:
        return "https://api.paystack.co"
