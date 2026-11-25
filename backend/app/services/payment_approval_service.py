"""
app/services/payment_approval_service.py
----------------------------------------
SALE-1 - payments that wait for an admin's OK.

When the business turns on invoice_settings.payments_need_approval, a payment recorded by anyone who isn't an owner,
ops manager or admin is saved here as "pending" instead of becoming a receipt. It doesn't count as paid, makes no
receipt and sends nothing to the customer. An admin then approves it (the receipt is made then, recorded by the rep
and marked approved_by the admin) or rejects it with a reason. The rep can cancel their own while it waits.
Paystack payments never come through here.

kind "invoice"    payload = PaymentIn fields; the amount counts against the balance while it waits
kind "standalone" payload = ReceiptIn fields (a receipt with no invoice)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from app.services import inventory_service as stock
from app.services import invoice_payment_service as pay
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

STATUSES = ("pending", "approved", "rejected", "cancelled")
COLS = ("id, invoice_id, kind, amount, payload, deliver, status, owner_id, requested_by, requested_at, decided_by, "
        "decided_at, decision_note, receipt_id")


def _rows(res) -> list:
    data = getattr(res, "data", None)
    return data if isinstance(data, list) else []


def can_confirm(org_ctx: Optional[dict]) -> bool:
    """Owner, ops manager or admin."""
    return stock.is_manager(org_ctx)


def needs_approval(db, org_ctx: dict) -> bool:
    if can_confirm(org_ctx):
        return False
    return bool(inv.get_settings(db, org_ctx["org_id"]).get("payments_need_approval"))


def waiting_total(db, org_id: str, invoice_id: str) -> Decimal:
    res = db.table("payment_approvals").select("amount").eq("org_id", org_id).eq("invoice_id", invoice_id) \
        .eq("status", "pending").execute()
    return sum((inv._money(r.get("amount")) for r in _rows(res)), Decimal("0"))


def pending_for_invoice(db, org_id: str, invoice_id: str) -> list:
    res = db.table("payment_approvals").select(COLS).eq("org_id", org_id).eq("invoice_id", invoice_id) \
        .eq("status", "pending").order("requested_at").execute()
    return _decorate(db, org_id, _rows(res))


def _get(db, org_id: str, approval_id: str) -> dict:
    res = db.table("payment_approvals").select(COLS).eq("org_id", org_id).eq("id", str(approval_id)).limit(1).execute()
    rows = _rows(res)
    if not rows:
        raise inv._err_nf("Payment")
    return rows[0]


def _names(db, org_id: str, ids) -> dict:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    try:
        res = db.table("users").select("id, full_name").eq("org_id", org_id).in_("id", ids).execute()
        return {r["id"]: r.get("full_name") for r in _rows(res)}
    except Exception as exc:  # S14 - names are only a nicety
        logger.warning("payment_approval: name lookup failed org=%s: %s", org_id, exc)
        return {}


def _decorate(db, org_id: str, rows: list) -> list:
    inv_ids = sorted({r["invoice_id"] for r in rows if r.get("invoice_id")})
    docs = {}
    if inv_ids:
        res = db.table("invoices").select("id, number, customer_name, total, amount_paid").eq("org_id", org_id) \
            .in_("id", inv_ids).execute()
        docs = {d["id"]: d for d in _rows(res)}
    names = _names(db, org_id, [r.get("requested_by") for r in rows] + [r.get("decided_by") for r in rows])
    for r in rows:
        p = r.get("payload") or {}
        d = docs.get(r.get("invoice_id")) or {}
        r["invoice_number"] = d.get("number")
        r["customer_name"] = d.get("customer_name") or p.get("customer_name")
        r["method"] = p.get("method")
        r["reference"] = p.get("reference")
        r["paid_at"] = p.get("paid_at")
        r["description"] = p.get("note") or p.get("description")
        r["requested_by_name"] = names.get(r.get("requested_by"))
        r["decided_by_name"] = names.get(r.get("decided_by"))
    return rows


def _notify(db, org_id: str, user_ids: list, title: str, body: str) -> None:
    from app.services import invoice_stock_service as inv_stock
    inv_stock._notify(db, org_id, user_ids, title, body, kind="payment_approval")


def _money_text(v) -> str:
    return f"NGN {inv._f(inv._money(v)):,.2f}"


# ───────────────────────────── asking ─────────────────────────────

def request_invoice_payment(db, org_ctx: dict, invoice_id: str, data: dict, deliver: bool = False) -> dict:
    """A rep's payment on an invoice, held for an admin. Runs every check record_payment would."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    checked = pay.record_payment(db, org_id, user_id, invoice_id, data, check_only=True,
                                 waiting=waiting_total(db, org_id, invoice_id))
    doc = checked["invoice"]
    payload = {k: data.get(k) for k in ("amount", "method", "reference", "paid_at", "note") if data.get(k) is not None}
    payload["amount"] = checked["amount"]
    row = {"org_id": org_id, "invoice_id": doc["id"], "kind": "invoice", "amount": checked["amount"],
           "payload": payload, "deliver": bool(deliver and doc.get("stock_tracked")), "status": "pending",
           "owner_id": doc.get("created_by") or user_id, "requested_by": user_id, "requested_at": inv._now_iso()}
    saved = _rows(db.table("payment_approvals").insert(row).execute())
    out = saved[0] if saved else row
    inv._audit(db, org_id, user_id, "payment.requested", doc["id"], {"amount": checked["amount"],
                                                                     "method": payload.get("method")})
    from app.services import invoice_stock_service as inv_stock
    _notify(db, org_id, [m for m in inv_stock._manager_ids(db, org_id) if m != user_id], "Payment to confirm",
            f"{org_ctx.get('full_name') or 'A rep'} recorded {_money_text(checked['amount'])} on invoice "
            f"{doc.get('number') or ''} ({doc.get('customer_name') or 'customer'}). Please confirm it.")
    return _decorate(db, org_id, [out])[0]


def request_standalone(db, org_ctx: dict, data: dict) -> dict:
    """A rep's receipt with no invoice, held for an admin."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    row_checked = pay.standalone_receipt(db, org_id, user_id, data, check_only=True)
    payload = {k: v for k, v in data.items() if v is not None}
    payload["customer_name"] = row_checked.get("customer_name")
    payload["amount"] = row_checked["amount"]
    row = {"org_id": org_id, "invoice_id": None, "kind": "standalone", "amount": row_checked["amount"],
           "payload": payload, "deliver": False, "status": "pending", "owner_id": user_id, "requested_by": user_id,
           "requested_at": inv._now_iso()}
    saved = _rows(db.table("payment_approvals").insert(row).execute())
    out = saved[0] if saved else row
    inv._audit(db, org_id, user_id, "payment.requested", None, {"amount": row_checked["amount"], "standalone": True})
    from app.services import invoice_stock_service as inv_stock
    _notify(db, org_id, [m for m in inv_stock._manager_ids(db, org_id) if m != user_id], "Payment to confirm",
            f"{org_ctx.get('full_name') or 'A rep'} recorded {_money_text(row_checked['amount'])} from "
            f"{row_checked.get('customer_name') or 'a customer'}. Please confirm it.")
    return _decorate(db, org_id, [out])[0]


# ───────────────────────────── lists ─────────────────────────────

def list_approvals(db, org_ctx: dict, status: str = "pending", limit: int = 100) -> dict:
    """Admins see everyone's; a rep sees the ones they recorded."""
    org_id = org_ctx["org_id"]
    if status not in STATUSES:
        raise inv.InvoiceError("VALIDATION_ERROR", "Unknown status.", 422, "status")
    q = db.table("payment_approvals").select(COLS).eq("org_id", org_id).eq("status", status)
    if not can_confirm(org_ctx):
        q = q.eq("requested_by", org_ctx.get("id"))
    res = q.order("requested_at", desc=status != "pending").limit(max(1, min(limit, 200))).execute()
    return {"items": _decorate(db, org_id, _rows(res)), "can_confirm": can_confirm(org_ctx)}


def count_pending(db, org_ctx: dict) -> int:
    q = db.table("payment_approvals").select("id").eq("org_id", org_ctx["org_id"]).eq("status", "pending")
    if not can_confirm(org_ctx):
        q = q.eq("requested_by", org_ctx.get("id"))
    return len(_rows(q.limit(500).execute()))


# ───────────────────────────── deciding ─────────────────────────────

def _claim(db, org_id: str, approval_id: str, status: str, user_id: Optional[str], note: Optional[str]) -> dict:
    """Move pending -> status only if it is still pending (two admins clicking at once: one wins)."""
    patch = {"status": status, "decided_by": user_id, "decided_at": inv._now_iso(),
             "decision_note": (note or "").strip()[:500] or None}
    res = db.table("payment_approvals").update(patch).eq("org_id", org_id).eq("id", str(approval_id)) \
        .eq("status", "pending").execute()
    rows = _rows(res)
    if not rows:
        raise inv.InvoiceError("INVALID_TRANSITION", "This payment has already been dealt with.", 409)
    return rows[0]


def approve(db, org_ctx: dict, approval_id: str) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    if not can_confirm(org_ctx):
        raise inv.InvoiceError("FORBIDDEN", "Only an owner, ops manager or admin can confirm payments.", 403)
    a = _get(db, org_id, approval_id)
    if a.get("status") != "pending":
        raise inv.InvoiceError("INVALID_TRANSITION", "This payment has already been dealt with.", 409)
    a = _claim(db, org_id, a["id"], "approved", user_id, None)
    data = {**(a.get("payload") or {}), "approved_by": user_id}
    try:
        if a["kind"] == "invoice":
            out = pay.record_payment(db, org_id, a.get("requested_by"), a["invoice_id"], data)
            receipt = out["receipt"]
        else:
            receipt = pay.standalone_receipt(db, org_id, a.get("requested_by"), data)
            out = {"receipt": receipt, "invoice": None, "fully_paid": False}
    except inv.InvoiceError:
        db.table("payment_approvals").update({"status": "pending", "decided_by": None, "decided_at": None}) \
            .eq("org_id", org_id).eq("id", a["id"]).execute()
        raise
    db.table("payment_approvals").update({"receipt_id": receipt["id"]}).eq("org_id", org_id).eq("id", a["id"]).execute()
    delivered = False
    if a.get("deliver") and out.get("fully_paid"):
        delivered = deliver_all(db, org_ctx, a["invoice_id"])
    inv._audit(db, org_id, user_id, "payment.approved", a.get("invoice_id"),
               {"approval": a["id"], "receipt": receipt.get("number"), "amount": a.get("amount")})
    _notify(db, org_id, [a.get("requested_by")] if a.get("requested_by") != user_id else [], "Payment confirmed",
            f"Your payment of {_money_text(a.get('amount'))} was confirmed. Receipt {receipt.get('number') or ''} "
            f"is ready to send.")
    receipt.pop("public_token", None)
    receipt.pop("_contact", None)
    return {"approval": {**a, "receipt_id": receipt["id"]}, "receipt": receipt, "invoice": out.get("invoice"),
            "fully_paid": out.get("fully_paid"), "delivered": delivered}


def reject(db, org_ctx: dict, approval_id: str, reason: str) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    if not can_confirm(org_ctx):
        raise inv.InvoiceError("FORBIDDEN", "Only an owner, ops manager or admin can reject payments.", 403)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise inv.InvoiceError("VALIDATION_ERROR", "Say why the payment is rejected.", 422, "reason")
    a = _claim(db, org_id, approval_id, "rejected", user_id, reason)
    inv._audit(db, org_id, user_id, "payment.rejected", a.get("invoice_id"), {"approval": a["id"], "reason": reason})
    _notify(db, org_id, [a.get("requested_by")] if a.get("requested_by") != user_id else [], "Payment rejected",
            f"Your payment of {_money_text(a.get('amount'))} was not confirmed: {reason}")
    return _decorate(db, org_id, [a])[0]


def cancel(db, org_ctx: dict, approval_id: str) -> dict:
    """The rep who recorded it (or an admin) takes it back while it waits."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    a = _get(db, org_id, approval_id)
    if not can_confirm(org_ctx) and a.get("requested_by") != user_id:
        raise inv._err_nf("Payment")
    a = _claim(db, org_id, a["id"], "cancelled", user_id, None)
    inv._audit(db, org_id, user_id, "payment.cancelled", a.get("invoice_id"), {"approval": a["id"]})
    return _decorate(db, org_id, [a])[0]


def drop_for_invoice(db, org_id: str, user_id: Optional[str], invoice_id: str, reason: str) -> None:
    """The invoice was voided: anything still waiting on it is rejected (never raises)."""
    try:
        rows = _rows(db.table("payment_approvals").update({
            "status": "rejected", "decided_by": user_id, "decided_at": inv._now_iso(), "decision_note": reason[:500],
        }).eq("org_id", org_id).eq("invoice_id", invoice_id).eq("status", "pending").execute())
        for a in rows:
            _notify(db, org_id, [a.get("requested_by")], "Payment rejected",
                    f"Your payment of {_money_text(a.get('amount'))} was not confirmed: {reason}")
    except Exception as exc:  # S14
        logger.warning("payment_approval: drop failed org=%s invoice=%s: %s", org_id, invoice_id, exc)


# ───────────────────────────── delivery ─────────────────────────────

def deliver_all(db, org_ctx: dict, invoice_id: str) -> bool:
    """Mark every product line delivered (a paid sale the customer took away). Never raises."""
    from app.services import invoice_stock_service as inv_stock
    org_id = org_ctx["org_id"]
    try:
        lines = [{"item_id": i["id"], "quantity": int(i.get("stock_sold") or 0)}
                 for i in inv_stock._items(db, org_id, invoice_id)
                 if i.get("product_id") and int(i.get("stock_sold") or 0) > 0]
        if not lines:
            return False
        inv_stock.deliver(db, org_ctx, invoice_id, lines, "Taken by the customer at the sale")
        return True
    except (inv.InvoiceError, stock.StockError) as e:
        logger.warning("payment_approval: deliver failed org=%s invoice=%s: %s", org_id, invoice_id, e.message)
        return False
