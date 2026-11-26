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

STOCK-2b - a line can be held at ANOTHER location (invoice_items.stock_location_id), e.g. the warehouse when the
showroom is short. A manager (owner / ops manager / admin) can do that when issuing; anyone else asks for approval:
the goods are held at once, the invoice waits as a draft with stock_approval = 'pending', and a manager approves
(it is then issued and numbered) or rejects (the hold is released and the draft can be changed again).

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


def _loc_of(doc: dict, item: dict) -> Optional[str]:
    """STOCK-2b: where a line's stock is held - its own location if set, else the invoice's."""
    return item.get("stock_location_id") or doc.get("location_id")


def _status_for_stock(doc: dict) -> str:
    """A draft waiting for stock approval holds like an issued invoice."""
    if doc.get("status") == "draft" and doc.get("stock_approval") == "pending":
        return "issued"
    if doc.get("status") == "draft" and doc.get("web_state") in ("holding", "paid"):   # STOCK-3: website checkout
        return "issued"
    return doc.get("status") or ""


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

def clean_sources(db, org_id: str, sources, lines: list, main_id: str) -> dict:
    """STOCK-2b: {item_id: location_id} for lines taken from another location. Only lines on this invoice and
    locations of this business that are turned on; the invoice's own location is dropped (nothing to approve)."""
    if not sources:
        return {}
    if not isinstance(sources, dict) or len(sources) > inv.MAX_ITEMS:
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose where each item comes from.", 422, "sources")
    ids = {i["id"] for i in lines}
    active = {l["id"] for l in stock.list_locations(db, org_id) if l.get("is_active")}
    out = {}
    for item_id, loc_id in sources.items():
        item_id, loc_id = str(item_id), str(loc_id or "")
        if item_id not in ids:
            raise inv.InvoiceError("VALIDATION_ERROR", "That line isn't on this invoice.", 422, "sources")
        if loc_id not in active:
            raise inv.InvoiceError("VALIDATION_ERROR", "Choose one of your locations that is turned on.", 422, "sources")
        if loc_id != main_id:
            out[item_id] = loc_id
    return out


def prepare_issue(db, org_id: str, user_id: Optional[str], doc: dict, number: Optional[str] = None,
                  sources: Optional[dict] = None, allow_other: bool = False) -> bool:
    """Before an invoice gets its number: hold every product line at its location, or refuse the whole issue.
    sources (STOCK-2b): {item_id: location_id} for lines held elsewhere; only managers (allow_other) may pass them
    straight in, everyone else goes through request_approval(). Returns True when the invoice is now tracked."""
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
    src = clean_sources(db, org_id, sources, lines, loc["id"])
    if src and not allow_other:
        raise inv.InvoiceError("STOCK_APPROVAL_NEEDED",
                               "Taking stock from another location needs an admin's approval. Ask for approval instead.", 403)
    db.table("invoices").update({"location_id": loc["id"], "stock_tracked": True, "updated_at": inv._now_iso()}) \
        .eq("id", doc["id"]).eq("org_id", org_id).execute()
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    for i in lines:   # where each line is held this time (a line no longer taken elsewhere goes back to the main one)
        want = src.get(i["id"])
        if (i.get("stock_location_id") or None) != want:
            db.table("invoice_items").update({"stock_location_id": want}).eq("id", i["id"]).eq("org_id", org_id).execute()
            i["stock_location_id"] = want
    held_doc = {**doc, "number": number, "location_id": loc["id"]}
    current = None
    try:
        for i in lines:
            current = _loc_of(held_doc, i)
            _move(db, org_id, user_id, held_doc, i, current, "issued",
                  reason=f"Invoice {number}" if number else "Invoice issued")
    except stock.StockError as e:
        undo_issue(db, org_id, user_id, doc["id"])
        where = names.get(current, loc["name"])
        msg = e.message.replace(" here.", f" at {where}.") if e.code == "STOCK_SHORT" else e.message
        raise inv.InvoiceError(e.code, msg, e.status, "quantity" if e.code == "STOCK_SHORT" else e.field)
    return True


def undo_issue(db, org_id: str, user_id: Optional[str], invoice_id: str) -> None:
    """Issue failed after holding: give everything back and untrack (never raises)."""
    try:
        doc = inv._one(db, "invoices", org_id, invoice_id) or {"id": invoice_id}
        for i in _items(db, org_id, invoice_id):
            loc_id = _loc_of(doc, i)
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
        status = _status_for_stock(doc)
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
                if _move(db, org_id, user_id, doc, i, _loc_of(doc, i), status):
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
    return stock.can_handle(org_ctx) or (bool(doc.get("created_by")) and doc.get("created_by") == org_ctx.get("id"))


def deliver(db, org_ctx: dict, invoice_id: str, lines: list, note: Optional[str] = None) -> dict:
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf("Invoice")
    if not can_deliver(org_ctx, doc):
        raise inv.InvoiceError("FORBIDDEN", "Only managers, the Inventory Manager or the rep who made this invoice can "
                                            "mark it delivered.", 403)
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
    from app.services import stock_request_service as move_requests   # STOCK-4: warehouse goods need the owner's OK
    move_requests.check_delivery(db, org_ctx, doc, plan)
    reason = "Delivered" + (f": {' '.join(str(note).split())[:300]}" if note and str(note).strip() else "")
    for item, qty in plan:
        try:
            stock.apply(db, org_id, user_id, item["product_id"], item.get("variant") or "", _loc_of(doc, item), "deliver",
                        on_hand=-qty, sold=-qty, invoice_id=doc["id"], invoice_item_id=item["id"],
                        reason=f"{reason} (invoice {doc.get('number') or ''})".strip(), label=_label(item))
        except stock.StockError as e:
            raise inv.InvoiceError(e.code, e.message, e.status, e.field)
    move_requests.check_delivery(db, org_ctx, doc, plan, consume=True)
    inv._audit(db, org_id, user_id, "invoice.delivered", doc["id"],
               {"lines": [{"item_id": i["id"], "quantity": q} for i, q in plan]})
    return inv.get_doc(db, org_id, doc["id"])


# ───────────────────────────── lists ─────────────────────────────

def _open_list(db, org_id: str, statuses: tuple, field: str, location_id: Optional[str], limit: int) -> list:
    q = db.table("invoices").select("id, number, customer_name, status, issue_date, total, amount_paid, location_id, "
                                    "created_by, updated_at, web_state").eq("org_id", org_id).eq("stock_tracked", True) \
        .in_("status", list(statuses))
    docs = [d for d in _rows(q.order("issue_date").limit(500).execute())   # STOCK-3: drafts only as web checkouts
            if d.get("status") != "draft" or d.get("web_state") == "holding"]
    if not docs:
        return []
    doc_loc = {d["id"]: d.get("location_id") for d in docs}
    items = _rows(db.table("invoice_items").select("id, invoice_id, description, variant, quantity, stock_held, "
                                                   "stock_sold, stock_delivered, stock_location_id").eq("org_id", org_id)
                  .in_("invoice_id", [d["id"] for d in docs]).gt(field, 0).execute())
    locs = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    by_doc: dict = {}
    for i in items:
        where = i.get("stock_location_id") or doc_loc.get(i["invoice_id"])
        if location_id and where != str(location_id):   # STOCK-2b: a location's list counts only its own lines
            continue
        if i.get("stock_location_id") and i["stock_location_id"] != doc_loc.get(i["invoice_id"]):
            i = {**i, "description": f"{i.get('description') or ''} (from {locs.get(i['stock_location_id'], 'another location')})"}
        by_doc.setdefault(i["invoice_id"], []).append(i)
    uids = list({d["created_by"] for d in docs if d.get("created_by")})
    users = {u["id"]: u.get("full_name") for u in _rows(db.table("users").select("id, full_name").eq("org_id", org_id)
                                                       .in_("id", uids).execute())} if uids else {}
    out = []
    for d in docs:
        lines = by_doc.get(d["id"])
        if not lines:
            continue
        out.append({"id": d["id"], "number": d.get("number") or ("Website order" if d.get("web_state") else None),
                    "web": bool(d.get("web_state")), "customer_name": d.get("customer_name"),
                    "status": d.get("status"), "issue_date": d.get("issue_date"), "updated_at": d.get("updated_at"),
                    "location": locs.get(d.get("location_id")), "rep_name": users.get(d.get("created_by")),
                    "balance": inv._f(inv._money(d.get("total") or 0) - inv._money(d.get("amount_paid") or 0)),
                    "units": sum(_int(i.get(field)) for i in lines),
                    "location_id": d.get("location_id"),
                    "lines": [{"description": i.get("description"), "units": _int(i.get(field)), "item_id": i["id"],
                               "location_id": i.get("stock_location_id") or d.get("location_id")} for i in lines]})
        if len(out) >= limit:
            break
    return out


def held_list(db, org_id: str, location_id: Optional[str] = None, limit: int = 200) -> list:
    """Unpaid issued invoices holding stock, oldest first."""
    return _open_list(db, org_id, UNPAID + ("draft",), "stock_held", location_id, limit)


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


# ───────────────────────────── STOCK-2b: other locations, with approval ─────────────────────────────

def can_approve(org_ctx: dict) -> bool:
    """Owner, ops manager or admin - the same people who manage stock."""
    return stock.is_manager(org_ctx)


def stock_check(db, org_ctx: dict, invoice_id: str) -> dict:
    """For a draft invoice: per product line, what it needs, what its location has, and the other locations that
    have enough. Used by the editor when issuing is refused for lack of stock."""
    org_id = org_ctx["org_id"]
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf("Invoice")
    locs = [l for l in stock.list_locations(db, org_id) if l.get("is_active")]
    main = location_for(db, org_id, doc)
    lines = [i for i in _items(db, org_id, invoice_id) if i.get("product_id")]
    pids = list({i["product_id"] for i in lines})
    avail = {l["id"]: availability(db, org_id, l["id"], pids) for l in locs} if pids else {}
    out_lines, short = [], False
    for i in lines:
        try:
            need = _whole(i.get("quantity"), _label(i))
        except inv.InvoiceError:
            need = 0
        v = i.get("variant") or ""
        here = avail.get(main["id"], {}).get(i["product_id"], {}).get(v, 0) if main else 0
        mine = _int(i.get("stock_held")) if (main and _loc_of(doc, i) == main["id"]) else 0   # already held for it
        others = sorted(({"location_id": l["id"], "name": l["name"],
                          "available": avail[l["id"]].get(i["product_id"], {}).get(v, 0)}
                         for l in locs if not main or l["id"] != main["id"]), key=lambda x: -x["available"])
        line_short = need > here + mine
        short = short or line_short
        out_lines.append({"item_id": i["id"], "description": i.get("description"), "variant": v, "needed": need,
                          "available_here": here + mine, "short": line_short,
                          "others": [o for o in others if o["available"] > 0]})
    return {"location": {"id": main["id"], "name": main["name"]} if main else None, "short": short,
            "lines": out_lines, "can_approve": can_approve(org_ctx)}


def _notify(db, org_id: str, user_ids: list, title: str, body: str, kind: str = "stock_approval") -> None:
    now = inv._now_iso()
    for uid in {u for u in user_ids if u}:
        try:
            db.table("notifications").insert({"org_id": org_id, "user_id": uid, "title": title[:200], "body": body[:1000],
                                              "type": kind, "resource_type": "invoice", "resource_id": None,
                                              "is_read": False, "created_at": now}).execute()
        except Exception as exc:
            logger.warning("invoice_stock: notify failed user=%s: %s", uid, exc)


def _manager_ids(db, org_id: str) -> list:
    try:
        rows = _rows(db.table("users").select("id, roles(template, permissions)").eq("org_id", org_id).execute())
    except Exception as exc:
        logger.warning("invoice_stock: manager lookup failed org=%s: %s", org_id, exc)
        return []
    return [r["id"] for r in rows if stock.is_manager({"roles": r.get("roles") or {}})]


def _pending_or_raise(db, org_id: str, invoice_id: str) -> dict:
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf("Invoice")
    if doc.get("status") != "draft" or doc.get("stock_approval") != "pending":
        raise inv.InvoiceError("INVALID_TRANSITION", "This invoice isn't waiting for stock approval.", 400)
    return doc


def _claim(db, org_id: str, doc: dict, to: str, user_id: Optional[str], note: Optional[str] = None) -> None:
    """Move pending -> approved / rejected only if it is still pending (two admins at once: one wins)."""
    res = db.table("invoices").update({"stock_approval": to, "stock_decided_by": user_id, "stock_decided_at": inv._now_iso(),
                                       "stock_decision_note": note}) \
        .eq("id", doc["id"]).eq("org_id", org_id).eq("status", "draft").eq("stock_approval", "pending").execute()
    if not (res and _rows(res)):
        raise inv.InvoiceError("INVALID_TRANSITION", "Someone else has already decided this. Refresh to see it.", 409)


def _where(db, org_id: str, doc: dict) -> str:
    """'2 x Hybrid Bed - Queen from Warehouse' for the lines held away from the invoice's location."""
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    parts = [f"{_int(i.get('stock_held'))} x {_label(i)} from {names.get(i['stock_location_id'], 'another location')}"
             for i in _items(db, org_id, doc["id"])
             if i.get("stock_location_id") and i["stock_location_id"] != doc.get("location_id")]
    return "; ".join(parts)


def request_approval(db, org_ctx: dict, invoice_id: str, sources: dict, note: Optional[str] = None) -> dict:
    """A rep asks to take some lines from another location. The goods are held now; a manager approves or rejects."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    doc = inv.issue_checks(db, org_id, invoice_id)
    if doc.get("doc_type") != "invoice" or not stock.stock_on(db, org_id):
        raise inv.InvoiceError("INVALID_TRANSITION", "Only invoices take stock.", 400)
    lines = [i for i in _items(db, org_id, invoice_id) if i.get("product_id")]
    main = location_for(db, org_id, doc)
    if not main:
        raise inv.InvoiceError("VALIDATION_ERROR", "Add a location in Inventory > Settings before issuing.", 422, "location_id")
    if not clean_sources(db, org_id, sources, lines, main["id"]):
        raise inv.InvoiceError("VALIDATION_ERROR", "Choose another location for at least one item.", 422, "sources")
    prepare_issue(db, org_id, user_id, doc, sources=sources, allow_other=True)
    clean_note = " ".join(str(note).split())[:300] if note and str(note).strip() else None
    db.table("invoices").update({"stock_approval": "pending", "stock_requested_by": user_id,
                                 "stock_requested_at": inv._now_iso(), "stock_request_note": clean_note,
                                 "stock_decided_by": None, "stock_decided_at": None, "stock_decision_note": None,
                                 "updated_at": inv._now_iso()}).eq("id", doc["id"]).eq("org_id", org_id).execute()
    inv._audit(db, org_id, user_id, "invoice.stock_requested", doc["id"], {"sources": sources, "note": clean_note})
    who = (_rows(db.table("users").select("full_name").eq("id", user_id).eq("org_id", org_id).limit(1).execute())
           or [{}])[0].get("full_name") if user_id else None
    _notify(db, org_id, _manager_ids(db, org_id), "Stock approval needed",
            f"{who or 'A rep'} wants to sell to {doc.get('customer_name') or 'a customer'} from another location: "
            f"{_where(db, org_id, doc)}. Open Inventory > Approvals." + (f" Note: {clean_note}" if clean_note else ""))
    return inv.get_doc(db, org_id, doc["id"])


def approve(db, org_ctx: dict, invoice_id: str) -> dict:
    """Manager approves: the invoice is issued and numbered with the goods already held."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    if not can_approve(org_ctx):
        raise inv.InvoiceError("FORBIDDEN", "Only the owner, an operations manager or an admin can approve this.", 403)
    doc = _pending_or_raise(db, org_id, invoice_id)
    _claim(db, org_id, doc, "approved", user_id)
    try:
        issued = inv._issue_numbered(db, org_id, user_id, doc)
    except Exception:
        db.table("invoices").update({"stock_approval": "pending", "stock_decided_by": None, "stock_decided_at": None}) \
            .eq("id", doc["id"]).eq("org_id", org_id).eq("status", "draft").execute()
        raise
    inv._audit(db, org_id, user_id, "invoice.stock_approved", doc["id"], {})
    _notify(db, org_id, [doc.get("stock_requested_by")], "Stock approved",
            f"Your invoice for {doc.get('customer_name') or 'the customer'} was approved and issued as {issued.get('number')}.")
    return inv.get_doc(db, org_id, doc["id"])


def reject(db, org_ctx: dict, invoice_id: str, note: Optional[str] = None) -> dict:
    """Manager rejects: the goods are released and the draft can be changed again."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    if not can_approve(org_ctx):
        raise inv.InvoiceError("FORBIDDEN", "Only the owner, an operations manager or an admin can reject this.", 403)
    doc = _pending_or_raise(db, org_id, invoice_id)
    clean_note = " ".join(str(note).split())[:300] if note and str(note).strip() else None
    _claim(db, org_id, doc, "rejected", user_id, clean_note)
    undo_issue(db, org_id, user_id, doc["id"])
    inv._audit(db, org_id, user_id, "invoice.stock_rejected", doc["id"], {"note": clean_note})
    _notify(db, org_id, [doc.get("stock_requested_by")], "Stock request not approved",
            f"Your invoice for {doc.get('customer_name') or 'the customer'} can't take stock from another location"
            + (f": {clean_note}" if clean_note else ".") + " The goods were released; the draft can be changed.")
    return inv.get_doc(db, org_id, doc["id"])


def cancel_request(db, org_ctx: dict, invoice_id: str) -> dict:
    """The rep who asked (or a manager) withdraws the request: goods released, draft editable again."""
    org_id, user_id = org_ctx["org_id"], org_ctx.get("id")
    doc = _pending_or_raise(db, org_id, invoice_id)
    if not (can_approve(org_ctx) or doc.get("stock_requested_by") == user_id):
        raise inv.InvoiceError("FORBIDDEN", "Only the person who asked or a manager can cancel this request.", 403)
    res = db.table("invoices").update({"stock_approval": None, "updated_at": inv._now_iso()}) \
        .eq("id", doc["id"]).eq("org_id", org_id).eq("status", "draft").eq("stock_approval", "pending").execute()
    if not (res and _rows(res)):
        raise inv.InvoiceError("INVALID_TRANSITION", "Someone else has already decided this. Refresh to see it.", 409)
    undo_issue(db, org_id, user_id, doc["id"])
    inv._audit(db, org_id, user_id, "invoice.stock_request_cancelled", doc["id"], {})
    return inv.get_doc(db, org_id, doc["id"])


def approvals_list(db, org_id: str, limit: int = 200) -> list:
    """Drafts waiting for stock approval, oldest first."""
    docs = _rows(db.table("invoices").select("id, customer_name, total, location_id, stock_requested_by, "
                                             "stock_requested_at, stock_request_note")
                 .eq("org_id", org_id).eq("status", "draft").eq("stock_approval", "pending")
                 .order("stock_requested_at").limit(limit).execute())
    if not docs:
        return []
    locs = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    items = _rows(db.table("invoice_items").select("invoice_id, description, stock_held, stock_location_id")
                  .eq("org_id", org_id).in_("invoice_id", [d["id"] for d in docs]).gt("stock_held", 0).execute())
    uids = list({d["stock_requested_by"] for d in docs if d.get("stock_requested_by")})
    users = {u["id"]: u.get("full_name") for u in _rows(db.table("users").select("id, full_name").eq("org_id", org_id)
                                                       .in_("id", uids).execute())} if uids else {}
    out = []
    for d in docs:
        lines = [{"description": i.get("description"), "units": _int(i.get("stock_held")),
                  "from": locs.get(i.get("stock_location_id") or d.get("location_id")),
                  "elsewhere": bool(i.get("stock_location_id")) and i["stock_location_id"] != d.get("location_id")}
                 for i in items if i["invoice_id"] == d["id"]]
        out.append({"id": d["id"], "customer_name": d.get("customer_name"), "total": d.get("total"),
                    "location": locs.get(d.get("location_id")), "rep_name": users.get(d.get("stock_requested_by")),
                    "requested_at": d.get("stock_requested_at"), "note": d.get("stock_request_note"), "lines": lines})
    return out
