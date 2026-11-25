"""
app/services/sale_service.py
----------------------------
SALE-1 - "Make a sale": one form that makes the invoice, issues it (holding the stock), records what the customer
paid and, if they took the goods away, marks them delivered.

  create(db, org_ctx, data)      the whole sale. Not enough stock -> the draft is kept and the STOCK_SHORT error
                                 carries its id, so the screen can offer another location (managers) or ask a
                                 manager to approve (reps), the same as the invoice editor.
  finish(db, org_ctx, doc_id, payment, delivered)
                                 after the invoice is issued some other way (a manager picked another location):
                                 record the payment and delivery.

payment = {status: paid | part | unpaid, amount?, method?, reference?, paid_at?}
  paid   the full total (amount ignored)
  part   0 < amount < total
  unpaid nothing recorded
When the business wants payments confirmed and the user isn't an admin, the payment waits (payment_approval_service);
a "taken away" sale is then delivered when the admin approves it.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from app.services import inventory_service as stock
from app.services import invoice_payment_service as pay
from app.services import invoice_service as inv
from app.services import payment_approval_service as approvals

logger = logging.getLogger(__name__)

PAY_STATUSES = ("paid", "part", "unpaid")


class SaleShort(inv.InvoiceError):
    """Not enough stock; the draft invoice is kept (doc_id) so the screen can carry on."""

    def __init__(self, err: inv.InvoiceError, doc_id: str):
        super().__init__(err.code, err.message, err.status, err.field)
        self.doc_id = doc_id


def _check_payment(payment: Optional[dict]) -> dict:
    p = dict(payment or {})
    status = p.get("status")
    if status not in PAY_STATUSES:
        raise inv.InvoiceError("VALIDATION_ERROR", "Say whether the customer paid.", 422, "payment.status")
    if status == "unpaid":
        return {"status": "unpaid"}
    if p.get("method") not in pay.MANUAL_METHODS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose how the customer paid.", 422, "payment.method")
    if status == "part" and inv._money(p.get("amount") or 0) <= 0:
        raise inv.InvoiceError("VALIDATION_ERROR", "Enter how much the customer paid.", 422, "payment.amount")
    return p


def create(db, org_ctx: dict, data: dict) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    payment = _check_payment(data.get("payment"))
    if not data.get("items"):
        raise inv.InvoiceError("VALIDATION_ERROR", "Add at least one product.", 422, "items")
    if not data.get("location_id"):
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose where the stock comes from.", 422, "location_id")
    if data.get("delivered") and payment["status"] != "paid":
        raise inv.InvoiceError("VALIDATION_ERROR", "Goods can be handed over once the sale is fully paid.", 422,
                               "delivered")
    region = data.get("region")
    if not region:   # the location's region, when the rep didn't choose one
        try:
            res = db.table("stock_locations").select("region").eq("org_id", org_id) \
                .eq("id", str(data["location_id"])).limit(1).execute()
            rows = getattr(res, "data", None) or []
            region = rows[0].get("region") if rows else None
        except Exception as exc:  # S14
            logger.warning("sale: location region lookup failed org=%s: %s", org_id, exc)
    draft = {k: data.get(k) for k in ("lead_id", "customer_id", "customer_name", "customer_phone", "customer_email",
                                      "customer_address", "location_id", "items", "discount", "notes")
             if data.get(k) is not None}
    draft.update({"doc_type": "invoice", "region": region})
    doc = inv.create_draft(db, org_id, user_id, draft)
    try:
        inv.issue(db, org_id, user_id, doc["id"])
    except inv.InvoiceError as e:
        if e.code == "STOCK_SHORT":
            raise SaleShort(e, doc["id"])
        try:
            inv.delete_draft(db, org_id, user_id, doc["id"])
        except inv.InvoiceError:
            pass
        raise
    inv._audit(db, org_id, user_id, "sale.made", doc["id"], {"payment": payment["status"]})
    return finish(db, org_ctx, doc["id"], payment, bool(data.get("delivered")), checked=True)


def finish(db, org_ctx: dict, doc_id: str, payment: Optional[dict], delivered: bool = False,
           checked: bool = False) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    p = payment if checked else _check_payment(payment)
    doc = inv.get_doc(db, org_id, doc_id)
    if doc.get("doc_type") != "invoice":
        raise inv._err_nf("Invoice")
    if not stock.is_manager(org_ctx) and doc.get("created_by") != user_id:
        raise inv._err_nf("Invoice")
    if delivered and p["status"] != "paid":
        raise inv.InvoiceError("VALIDATION_ERROR", "Goods can be handed over once the sale is fully paid.", 422,
                               "delivered")
    out = {"receipt": None, "pending_payment": None, "delivered": False}
    if p["status"] != "unpaid":
        balance = inv._money(doc.get("total") or 0) - inv._money(doc.get("amount_paid") or 0)
        amount = balance if p["status"] == "paid" else inv._money(p.get("amount") or 0)
        if p["status"] == "part" and amount >= balance:
            raise inv.InvoiceError("VALIDATION_ERROR", "That is the whole amount - choose Paid in full instead.", 422,
                                   "payment.amount")
        data = {"amount": str(amount), "method": p.get("method"), "reference": p.get("reference"),
                "paid_at": p.get("paid_at")}
        if approvals.needs_approval(db, org_ctx):
            out["pending_payment"] = approvals.request_invoice_payment(db, org_ctx, doc["id"], data, deliver=delivered)
        else:
            res = pay.record_payment(db, org_id, user_id, doc["id"], data)
            receipt = res["receipt"]
            receipt.pop("public_token", None)
            out["receipt"] = receipt
            if delivered and res.get("fully_paid") and doc.get("stock_tracked"):
                out["delivered"] = approvals.deliver_all(db, org_ctx, doc["id"])
    out["invoice"] = inv.get_doc(db, org_id, doc["id"])
    return out


def my_sales(db, org_ctx: dict, q: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
    """The invoices this user made (admins: everyone's), newest first, with what is waiting for an admin."""
    mine = None if stock.is_manager(org_ctx) else org_ctx.get("id")
    out = inv.list_docs(db, org_ctx["org_id"], "invoice", None, None, None, q, limit, offset, mine=mine)
    ids = [d["id"] for d in out.get("items", [])]
    waiting: dict = {}
    if ids:
        res = db.table("payment_approvals").select("invoice_id, amount").eq("org_id", org_ctx["org_id"]) \
            .in_("invoice_id", ids).eq("status", "pending").execute()
        for r in getattr(res, "data", None) or []:
            waiting[r["invoice_id"]] = waiting.get(r["invoice_id"], Decimal("0")) + inv._money(r.get("amount"))
    for d in out.get("items", []):
        d["waiting_amount"] = inv._f(waiting.get(d["id"], Decimal("0")))
    return out
