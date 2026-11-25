"""
app/services/invoice_stock_service.py
-------------------------------------
STOCK-2 - invoices hold and take stock (status aware).

  Issued / part paid   each product line's units are HELD at the invoice's location (not sold to anyone else)
  Fully paid           HELD -> SOLD, TO DELIVER (still in the warehouse, can't be sold again)
  Delivered            out of on hand (part delivery per line allowed; managers or the rep who made the invoice)
  Void                 held / to deliver go back to available (delivered goods stay out; return them with Adjust)
  Receipt voided       paid -> part paid moves "to deliver" back to "held"

Only invoices issued while stock is on are tracked (invoices.stock_tracked). Quotes and drafts never hold.
Issuing is blocked when a line asks for more than is available at the location.

sync() works out what each line SHOULD have from the invoice status and moves only the difference, so it is safe to
run again (the daily invoice worker re-runs it for tracked invoices). The line counters (invoice_items.stock_held /
stock_sold / stock_delivered) change inside stock_apply() in the same locked step as the stock numbers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services import inventory_service as stock
from app.services import invoice_service as inv

logger = logging.getLogger(__name__)

UNPAID = ("issued", "part_paid")
TRACKED_STATUSES = ("issued", "part_paid", "paid", "void")


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _items(db, org_id: str, invoice_id: str) -> list:
    return _rows(db.table("invoice_items").select("*").eq("invoice_id", invoice_id).eq("org_id", org_id)
                 .order("position").execute())


def _whole(value, label: str) -> int:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        d = Decimal("0")
    if d <= 0 or d != d.to_integral_value():
        raise inv.InvoiceError("VALIDATION_ERROR", f"Stock is counted in whole units. Fix the quantity for {label}.",
                               422, "quantity")
    return int(d)


def _label(item: dict) -> str:
    return str(item.get("description") or "this item")[:120]


# ───────────────────────────── location ─────────────────────────────

def clean_location(db, org_id: str, location_id) -> Optional[str]:
    """A draft's chosen location: must be one of the business's locations that is turned on."""
    if location_id in (None, ""):
        return None
    rows = _rows(db.table("stock_locations").select("id, is_active").eq("org_id", org_id).eq("id", str(location_id))
                 .limit(1).execute())
    if not rows or not rows[0].get("is_active"):
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose one of your locations that is turned on.", 422, "location_id")
    return rows[0]["id"]


def location_for(db, org_id: str, doc: dict) -> Optional[dict]:
    """The invoice's own location if still on; else the first location linked to its region; else the main one."""
    locs = [l for l in stock.list_locations(db, org_id) if l.get("is_active")]
    if doc.get("location_id"):
        hit = next((l for l in locs if l["id"] == doc["location_id"]), None)
        if hit:
            return hit
    region = str(doc.get("region") or "").strip().lower()
    if region:
        hit = next((l for l in locs if str(l.get("region") or "").strip().lower() == region), None)
        if hit:
            return hit
    return next((l for l in locs if l.get("is_default")), None) or (locs[0] if locs else None)


# ───────────────────────────── the target per line ─────────────────────────────

def _target(status: str, item: dict) -> tuple[int, int]:
    """(held, to deliver) a product line should have for the invoice status."""
    qty = _int(Decimal(str(item.get("quantity") or 0)).to_integral_value())
    left = max(qty - _int(item.get("stock_delivered")), 0)
    if status in UNPAID:
        return left, 0
    if status == "paid":
        return 0, left
    return 0, 0   # void and anything else


def _move(db, org_id: str, user_id: Optional[str], doc: dict, item: dict, location_id: str, status: str,
          reason: Optional[str] = None) -> bool:
    """Move one line to its target. True if something changed. Raises StockError."""
    want_held, want_sold = _target(status, item)
    d_held = want_held - _int(item.get("stock_held"))
    d_sold = want_sold - _int(item.get("stock_sold"))
    if not d_held and not d_sold:
        return False
    if status == "void":
        kind = "release"
    elif status == "paid":
        kind = "paid"
    else:
        kind = "hold" if d_held > 0 else "release"
    stock.apply(db, org_id, user_id, item["product_id"], item.get("variant") or "", location_id, kind,
                held=d_held, sold=d_sold, invoice_id=doc["id"], invoice_item_id=item["id"],
                reason=reason or f"Invoice {doc.get('number') or ''}".strip(), label=_label(item))
    item["stock_held"] = want_held
    item["stock_sold"] = want_sold
    return True


# ───────────────────────────── issue ─────────────────────────────

def prepare_issue(db, org_id: str, user_id: Optional[str], doc: dict, number: Optional[str] = None) -> bool:
    """Before an invoice gets its number: hold every product line at its location, or refuse the whole issue.
    Returns True when the invoice is now tracked."""
    if doc.get("doc_type") != "invoice" or not stock.stock_on(db, org_id):
        return False
    lines = [i for i in _items(db, org_id, doc["id"]) if i.get("product_id")]
    if not lines:
        return False
    for i in lines:
        _whole(i.get("quantity"), _label(i))
    loc = location_for(db, org_id, doc)
    if not loc:
        raise inv.InvoiceError("VALIDATION_ERROR", "Add a location in Inventory > Settings before issuing.", 422,
                               "location_id")
    db.table("invoices").update({"location_id": loc["id"], "stock_tracked": True, "updated_at": inv._now_iso()}) \
        .eq("id", doc["id"]).eq("org_id", org_id).execute()
    held_doc = {**doc, "number": number, "location_id": loc["id"]}
    done = []
    try:
        for i in lines:
            if _move(db, org_id, user_id, held_doc, i, loc["id"], "issued",
                     reason=f"Invoice {number}" if number else "Invoice issued"):
                done.append(i)
    except stock.StockError as e:
        undo_issue(db, org_id, user_id, doc["id"])
        msg = e.message.replace(" here.", f" at {loc['name']}.") if e.code == "STOCK_SHORT" else e.message
        raise inv.InvoiceError(e.code, msg, e.status, "quantity" if e.code == "STOCK_SHORT" else e.field)
    return True


def undo_issue(db, org_id: str, user_id: Optional[str], invoice_id: str) -> None:
    """Issue failed after holding: give everything back and untrack (never raises)."""
    try:
        doc = inv._one(db, "invoices", org_id, invoice_id) or {"id": invoice_id}
        loc_id = doc.get("location_id")
        for i in _items(db, org_id, invoice_id):
            if i.get("product_id") and (_int(i.get("stock_held")) or _int(i.get("stock_sold"))) and loc_id:
                try:
                    _move(db, org_id, user_id, doc, i, loc_id, "void", reason="Issue did not go through")
                except stock.StockError as e:
                    logger.error("invoice_stock: undo failed org=%s invoice=%s item=%s: %s", org_id, invoice_id, i["id"], e.message)
        db.table("invoices").update({"stock_tracked": False}).eq("id", invoice_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.error("invoice_stock: undo_issue failed org=%s invoice=%s: %s", org_id, invoice_id, exc)


# ───────────────────────────── status changes ─────────────────────────────

def sync(db, org_id: str, invoice_id: str, user_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Bring a tracked invoice's stock in line with its status. Never raises. {tracked, changed, failed}."""
    out = {"tracked": False, "changed": 0, "failed": 0}
    try:
        doc = inv._one(db, "invoices", org_id, invoice_id)
        if not doc or not doc.get("stock_tracked") or not doc.get("location_id"):
            return out
        out["tracked"] = True
        status = doc.get("status")
        for i in _items(db, org_id, invoice_id):
            if not i.get("product_id"):
                continue
            want = _target(status, i)
            if want == (_int(i.get("stock_held")), _int(i.get("stock_sold"))):
                continue
            if dry_run:
                out["changed"] += 1
                continue
            try:
                if _move(db, org_id, user_id, doc, i, doc["location_id"], status):
                    out["changed"] += 1
            except stock.StockError as e:
                out["failed"] += 1
                logger.error("invoice_stock: sync failed org=%s invoice=%s item=%s status=%s: %s",
                             org_id, invoice_id, i["id"], status, e.message)
    except Exception as exc:
        out["failed"] += 1
        logger.error("invoice_stock: sync crashed org=%s invoice=%s: %s", org_id, invoice_id, exc)
    return out


def retry(db, dry_run: bool = False, days: int = 60) -> dict:
    """Daily worker step: re-run sync for tracked invoices changed in the last `days` days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = {"checked": 0, "fixed": 0, "failed": 0}
    try:
        docs = _rows(db.table("invoices").select("id, org_id").eq("stock_tracked", True)
                     .in_("status", list(TRACKED_STATUSES)).gte("updated_at", since).limit(2000).execute())
    except Exception as exc:
        logger.error("invoice_stock: retry query failed: %s", exc)
        return {**out, "failed": 1}
    for d in docs:
        out["checked"] += 1
        r = sync(db, d["org_id"], d["id"], dry_run=dry_run)
        out["fixed"] += r["changed"]
        out["failed"] += r["failed"]
    return out


# ───────────────────────────── delivery ─────────────────────────────

def can_deliver(org_ctx: dict, doc: dict) -> bool:
    return stock.is_manager(org_ctx) or (bool(doc.get("created_by")) and doc.get("created_by") == org_ctx.get("id"))


def deliver(db, org_ctx: dict, invoice_id: str, lines: list, note: Optional[str] = None) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf("Invoice")
    if not can_deliver(org_ctx, doc):
        raise inv.InvoiceError("FORBIDDEN", "Only managers or the rep who made this invoice can mark it delivered.", 403)
    if not doc.get("stock_tracked") or not doc.get("location_id"):
        raise inv.InvoiceError("INVALID_TRANSITION", "This invoice doesn't take stock.", 400)
    if doc.get("status") != "paid":
        raise inv.InvoiceError("INVALID_TRANSITION", "Goods can be marked delivered once the invoice is fully paid.", 400)
    if not lines or len(lines) > inv.MAX_ITEMS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose what was delivered.", 422, "lines")
    items = {i["id"]: i for i in _items(db, org_id, invoice_id) if i.get("product_id")}
    plan, seen = [], set()
    for n, ln in enumerate(lines):
        item = items.get(str(ln.get("item_id")))
        if not item or item["id"] in seen:
            raise inv.InvoiceError("VALIDATION_ERROR", "That line isn't on this invoice.", 422, f"lines.{n}.item_id")
        seen.add(item["id"])
        qty = _whole(ln.get("quantity"), _label(item))
        left = _int(item.get("stock_sold"))
        if qty > left:
            raise inv.InvoiceError("VALIDATION_ERROR", f"Only {left} of {_label(item)} left to deliver.", 422,
                                   f"lines.{n}.quantity")
        plan.append((item, qty))
    reason = "Delivered" + (f": {' '.join(str(note).split())[:300]}" if note and str(note).strip() else "")
    for item, qty in plan:
        try:
            stock.apply(db, org_id, user_id, item["product_id"], item.get("variant") or "", doc["location_id"], "deliver",
                        on_hand=-qty, sold=-qty, invoice_id=doc["id"], invoice_item_id=item["id"],
                        reason=f"{reason} (invoice {doc.get('number') or ''})".strip(), label=_label(item))
        except stock.StockError as e:
            raise inv.InvoiceError(e.code, e.message, e.status, e.field)
    inv._audit(db, org_id, user_id, "invoice.delivered", doc["id"],
               {"lines": [{"item_id": i["id"], "quantity": q} for i, q in plan]})
    return inv.get_doc(db, org_id, doc["id"])


# ───────────────────────────── lists ─────────────────────────────

def _open_list(db, org_id: str, statuses: tuple, field: str, location_id: Optional[str], limit: int) -> list:
    q = db.table("invoices").select("id, number, customer_name, status, issue_date, total, amount_paid, location_id, "
                                    "created_by, updated_at").eq("org_id", org_id).eq("stock_tracked", True) \
        .in_("status", list(statuses))
    if location_id:
        q = q.eq("location_id", str(location_id))
    docs = _rows(q.order("issue_date").limit(500).execute())
    if not docs:
        return []
    items = _rows(db.table("invoice_items").select("id, invoice_id, description, variant, quantity, stock_held, "
                                                   "stock_sold, stock_delivered").eq("org_id", org_id)
                  .in_("invoice_id", [d["id"] for d in docs]).gt(field, 0).execute())
    by_doc: dict = {}
    for i in items:
        by_doc.setdefault(i["invoice_id"], []).append(i)
    locs = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    uids = list({d["created_by"] for d in docs if d.get("created_by")})
    users = {u["id"]: u.get("full_name") for u in _rows(db.table("users").select("id, full_name").eq("org_id", org_id)
                                                       .in_("id", uids).execute())} if uids else {}
    out = []
    for d in docs:
        lines = by_doc.get(d["id"])
        if not lines:
            continue
        out.append({"id": d["id"], "number": d.get("number"), "customer_name": d.get("customer_name"),
                    "status": d.get("status"), "issue_date": d.get("issue_date"), "updated_at": d.get("updated_at"),
                    "location": locs.get(d.get("location_id")), "rep_name": users.get(d.get("created_by")),
                    "balance": inv._f(inv._money(d.get("total") or 0) - inv._money(d.get("amount_paid") or 0)),
                    "units": sum(_int(i.get(field)) for i in lines),
                    "lines": [{"description": i.get("description"), "units": _int(i.get(field))} for i in lines]})
        if len(out) >= limit:
            break
    return out


def held_list(db, org_id: str, location_id: Optional[str] = None, limit: int = 200) -> list:
    """Unpaid issued invoices holding stock, oldest first."""
    return _open_list(db, org_id, UNPAID, "stock_held", location_id, limit)


def to_deliver_list(db, org_id: str, location_id: Optional[str] = None, limit: int = 200) -> list:
    """Paid invoices with goods still in the warehouse, oldest first."""
    return _open_list(db, org_id, ("paid",), "stock_sold", location_id, limit)


def availability(db, org_id: str, location_id: str, product_ids: list) -> dict:
    """{product_id: {variant: available}} at one location (variant '' for a product with no sizes)."""
    if not product_ids:
        return {}
    items = _rows(db.table("stock_items").select("id, product_id, variant").eq("org_id", org_id)
                  .in_("product_id", [str(p) for p in product_ids[:100]]).execute())
    if not items:
        return {str(p): {} for p in product_ids[:100]}
    levels = {lv["item_id"]: lv for lv in _rows(db.table("stock_levels").select("item_id, on_hand, held, sold_pending")
                                               .eq("org_id", org_id).eq("location_id", str(location_id))
                                               .in_("item_id", [i["id"] for i in items]).execute())}
    out: dict = {str(p): {} for p in product_ids[:100]}
    for i in items:
        lv = levels.get(i["id"]) or {}
        out.setdefault(i["product_id"], {})[i["variant"] or ""] = \
            _int(lv.get("on_hand")) - _int(lv.get("held")) - _int(lv.get("sold_pending"))
    return out
