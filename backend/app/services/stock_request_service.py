"""
backend/app/services/stock_request_service.py
STOCK-4 - nothing leaves a warehouse without the owner's say-so.

  * Moving stock OUT of a warehouse (to a showroom or another location) starts as a request. The goods are held at
    the warehouse straight away (they can't be sold to anyone else), the owner approves or rejects, and only then can
    the Inventory Manager (or a manager) send them. Sending works exactly like STOCK-3 (on the way -> received).
  * Delivering a paid invoice's goods from a warehouse needs an approved delivery request too. Those goods are already
    held as "to deliver"; the request only unlocks marking them delivered, which is when they leave the count.
  * The owner's own moves and deliveries go through at once and are recorded as approved.
  * Showroom stock (walk-in sales, moves out of a showroom) works as before.
  * records(): approved moves and deliveries for a week, a month or any dates.

Statuses: pending -> approved -> done, or pending/approved -> rejected / cancelled.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from app.services import inventory_service as stock
from app.services import invoice_service as inv
from app.services import stock_transfer_service as transfers

logger = logging.getLogger(__name__)

StockError = stock.StockError
MAX_LINES = 100
OPEN = ("pending", "approved")
STATUSES = ("pending", "approved", "rejected", "cancelled", "done")


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _note(v: Any) -> Optional[str]:
    return " ".join(str(v or "").split())[:300] or None


def _uid(org_ctx: dict) -> Optional[str]:
    return org_ctx.get("id") or org_ctx.get("user_id")


def is_warehouse(loc: Optional[dict]) -> bool:
    return bool(loc) and (loc.get("kind") or "showroom") == "warehouse"


def _get(db, org_id: str, request_id: Any) -> dict:
    rows = _rows(db.table("stock_move_requests").select("*").eq("org_id", org_id).eq("id", str(request_id))
                 .limit(1).execute())
    if not rows:
        raise StockError("NOT_FOUND", "That request was not found.", 404)
    return rows[0]


def _claim(db, org_id: str, req: dict, from_status: str, patch: dict) -> bool:
    """Change a request only if it is still in from_status (two people at once: one wins)."""
    res = db.table("stock_move_requests").update(patch).eq("org_id", org_id).eq("id", req["id"]) \
        .eq("status", from_status).execute()
    return bool(_rows(res))


def _audit(db, org_id: str, user_id: Optional[str], action: str, request_id: str, new_value: dict) -> None:
    try:
        db.table("audit_logs").insert({"org_id": org_id, "user_id": user_id, "action": action,
                                       "resource_type": "stock_move_request", "resource_id": request_id,
                                       "new_value": new_value}).execute()
    except Exception as exc:  # S14
        logger.warning("stock_request: audit write failed org=%s request=%s: %s", org_id, request_id, exc)


def _notify(db, org_id: str, user_ids: list, title: str, body: str) -> None:
    from app.services import invoice_stock_service as inv_stock
    inv_stock._notify(db, org_id, user_ids, title, body, kind="stock_move_request")


def owner_ids(db, org_id: str) -> list:
    try:
        rows = _rows(db.table("users").select("id, is_active, roles(template)").eq("org_id", org_id).execute())
    except Exception as exc:
        logger.warning("stock_request: owner lookup failed org=%s: %s", org_id, exc)
        return []
    return [r["id"] for r in rows if ((r.get("roles") or {}).get("template") == "owner") and r.get("is_active", True)]


def handler_ids(db, org_id: str) -> list:
    """The Inventory Managers (who carry out approved moves), or the managers when there is none."""
    try:
        rows = _rows(db.table("users").select("id, is_active, roles(template, permissions)").eq("org_id", org_id).execute())
    except Exception as exc:
        logger.warning("stock_request: handler lookup failed org=%s: %s", org_id, exc)
        return []
    rows = [r for r in rows if r.get("is_active", True)]
    ims = [r["id"] for r in rows if stock.is_inventory_manager({"roles": r.get("roles") or {}})]
    return ims or [r["id"] for r in rows if stock.is_manager({"roles": r.get("roles") or {}})
                   and not stock.is_owner({"roles": r.get("roles") or {}})]


def _who(org_ctx: dict) -> str:
    return org_ctx.get("full_name") or "Someone"


# ───────────────────────────── moving stock ─────────────────────────────

def _plan(db, org_id: str, raw: list) -> list:
    if not raw or len(raw) > MAX_LINES:
        raise StockError("VALIDATION_ERROR", "Add what you are moving.", 422, "lines")
    plan, seen = [], set()
    for n, ln in enumerate(raw):
        prod = stock._product(db, org_id, ln.get("product_id"))
        variant = stock.clean_variant(prod, ln.get("variant"))
        if (prod["id"], variant) in seen:
            raise StockError("VALIDATION_ERROR", "The same item is listed twice.", 422, f"lines.{n}")
        seen.add((prod["id"], variant))
        plan.append({"product_id": prod["id"], "variant": variant,
                     "quantity": stock._qty(ln.get("quantity"), f"lines.{n}.quantity"),
                     "title": transfers._label(prod, variant)})
    return plan


def _hold(db, org_id: str, user_id: Optional[str], loc: dict, lines: list, sign: int, reason: str) -> None:
    """Hold (sign=1) or release (sign=-1) a request's goods at the sending location. All or nothing."""
    done = []
    try:
        for ln in lines:
            stock.apply(db, org_id, user_id, ln["product_id"], ln.get("variant") or "", loc["id"],
                        "hold" if sign > 0 else "release", held=sign * _int(ln["quantity"]), reason=reason,
                        label=ln.get("title") or "of this item")
            done.append(ln)
    except StockError as e:
        for ln in reversed(done):
            try:
                stock.apply(db, org_id, user_id, ln["product_id"], ln.get("variant") or "", loc["id"],
                            "release" if sign > 0 else "hold", held=-sign * _int(ln["quantity"]),
                            reason="Request did not go through")
            except StockError as e2:
                logger.error("stock_request: undo hold failed org=%s: %s", org_id, e2.message)
        msg = e.message.replace(" here.", f" at {loc['name']}.") if e.code == "STOCK_SHORT" else e.message
        raise StockError(e.code, msg, e.status, e.field)


def request_transfer(db, org_ctx: dict, body: dict) -> dict:
    """Move stock. Out of a warehouse by anyone but the owner -> a request (goods held). Otherwise sent at once.
    Returns {"transfer": ...} or {"request": ...}."""
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    stock._require_on(db, org_id)
    src = stock._location(db, org_id, body.get("from_location_id"))
    dst = stock._location(db, org_id, body.get("to_location_id"))
    if src["id"] == dst["id"]:
        raise StockError("VALIDATION_ERROR", "Choose two different locations.", 422, "to_location_id")
    if not src.get("is_active") or not dst.get("is_active"):
        raise StockError("VALIDATION_ERROR", "Both locations must be turned on.", 422, "to_location_id")
    if not is_warehouse(src):
        return {"transfer": transfers.send(db, org_id, user_id, body)}
    plan = _plan(db, org_id, body.get("lines") or [])
    if stock.is_owner(org_ctx):   # the owner's own move: sent now, recorded as approved
        t = transfers.send(db, org_id, user_id, body)
        now = stock._now()
        _insert(db, org_id, user_id, "transfer", "done", src, dst, None, plan, body.get("note"),
                {"decided_by": user_id, "decided_at": now, "done_by": user_id, "done_at": now, "transfer_id": t["id"]})
        return {"transfer": t}
    note = _note(body.get("note"))
    req = _insert(db, org_id, user_id, "transfer", "pending", src, dst, None, plan, note, {})
    try:
        _hold(db, org_id, user_id, src, plan, 1, f"Held for a move to {dst['name']} (waiting for approval)")
    except StockError:
        db.table("stock_move_requests").delete().eq("org_id", org_id).eq("id", req["id"]).execute()
        raise
    units = sum(l["quantity"] for l in plan)
    _audit(db, org_id, user_id, "stock.move_requested", req["id"], {"units": units, "to": dst["id"]})
    _notify(db, org_id, [u for u in owner_ids(db, org_id) if u != user_id], "Stock move to approve",
            f"{_who(org_ctx)} wants to move {units} unit{'' if units == 1 else 's'} from {src['name']} to {dst['name']}. "
            f"Approve it in Inventory > Requests.")
    return {"request": view(db, org_id, req["id"])}


def _insert(db, org_id, user_id, kind, status_, src, dst, invoice, lines, note, extra) -> dict:
    row = {"org_id": org_id, "kind": kind, "status": status_, "from_location_id": src["id"],
           "to_location_id": dst["id"] if dst else None, "invoice_id": invoice["id"] if invoice else None,
           "lines": lines, "units": sum(_int(l.get("quantity")) for l in lines), "note": _note(note),
           "requested_by": user_id, "requested_at": stock._now(), "created_at": stock._now(), **extra}
    return _rows(db.table("stock_move_requests").insert(row).execute())[0]


def send_approved(db, org_ctx: dict, request_id: Any) -> dict:
    """The Inventory Manager (or a manager) sends an approved move: hold released, goods on the way."""
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    req = _get(db, org_id, request_id)
    if req["kind"] != "transfer":
        raise StockError("INVALID_TRANSITION", "This is a delivery request. Mark the goods delivered instead.", 400)
    if req["status"] != "approved":
        raise StockError("INVALID_TRANSITION", "Only an approved move can be sent." if req["status"] == "pending"
                         else "This move is already closed.", 400)
    if not _claim(db, org_id, req, "approved", {"status": "done", "done_by": user_id, "done_at": stock._now()}):
        raise StockError("STOCK_CONFLICT", "Someone else just changed this request. Refresh and try again.", 409)
    src = stock._location(db, org_id, req["from_location_id"])
    lines = req.get("lines") or []
    try:
        _hold(db, org_id, user_id, src, lines, -1, "Approved move: hold released to send")
        try:
            t = transfers.send(db, org_id, user_id, {
                "from_location_id": req["from_location_id"], "to_location_id": req["to_location_id"],
                "note": req.get("note"),
                "lines": [{"product_id": l["product_id"], "variant": l.get("variant") or None,
                           "quantity": _int(l["quantity"])} for l in lines]})
        except StockError:
            _hold(db, org_id, user_id, src, lines, 1, "Send did not go through: held again")
            raise
    except StockError:
        db.table("stock_move_requests").update({"status": "approved", "done_by": None, "done_at": None}) \
            .eq("org_id", org_id).eq("id", req["id"]).execute()
        raise
    db.table("stock_move_requests").update({"transfer_id": t["id"]}).eq("org_id", org_id).eq("id", req["id"]).execute()
    _audit(db, org_id, user_id, "stock.move_sent", req["id"], {"transfer_id": t["id"]})
    return {"request": view(db, org_id, req["id"]), "transfer": t}


# ───────────────────────────── deliveries ─────────────────────────────

def _approved_left(db, org_id: str, invoice_id: str) -> dict:
    """{item_id: approved units not yet delivered} over the invoice's approved delivery requests."""
    left: dict = {}
    for r in _rows(db.table("stock_move_requests").select("id, lines").eq("org_id", org_id).eq("invoice_id", invoice_id)
                   .eq("kind", "delivery").eq("status", "approved").execute()):
        for l in r.get("lines") or []:
            left[l["item_id"]] = left.get(l["item_id"], 0) + _int(l.get("quantity")) - _int(l.get("used"))
    return left


def _asked(db, org_id: str, invoice_id: str) -> dict:
    """{item_id: units in pending or approved (not yet delivered) requests}."""
    out: dict = {}
    for r in _rows(db.table("stock_move_requests").select("lines").eq("org_id", org_id).eq("invoice_id", invoice_id)
                   .eq("kind", "delivery").in_("status", list(OPEN)).execute()):
        for l in r.get("lines") or []:
            out[l["item_id"]] = out.get(l["item_id"], 0) + _int(l.get("quantity")) - _int(l.get("used"))
    return out


def _warehouse_lines(db, org_id: str, doc: dict) -> tuple:
    """(items still to deliver that sit in a warehouse, {location_id: location})."""
    from app.services import invoice_stock_service as inv_stock
    locs = {l["id"]: l for l in _rows(db.table("stock_locations").select("*").eq("org_id", org_id).execute())}
    items = [i for i in inv_stock._items(db, org_id, doc["id"]) if i.get("product_id")
             and _int(i.get("stock_sold")) > 0 and is_warehouse(locs.get(inv_stock._loc_of(doc, i)))]
    return items, locs


def request_delivery(db, org_ctx: dict, invoice_id: str, lines: Optional[list] = None, note: Optional[str] = None,
                     notify: bool = True) -> dict:
    """Ask the owner to let goods on a paid invoice leave a warehouse. lines: [{item_id, quantity}] or None = all."""
    from app.services import invoice_stock_service as inv_stock
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    doc = inv._one(db, "invoices", org_id, invoice_id)
    if not doc:
        raise inv._err_nf("Invoice")
    if not (stock.can_handle(org_ctx) or (doc.get("created_by") and doc.get("created_by") == user_id)):
        raise StockError("FORBIDDEN", "Only managers, the Inventory Manager or the rep who made this invoice can ask.", 403)
    if doc.get("status") != "paid" or not doc.get("stock_tracked"):
        raise StockError("INVALID_TRANSITION", "Delivery can be asked for once the invoice is fully paid.", 400)
    items, locs = _warehouse_lines(db, org_id, doc)
    if not items:
        raise StockError("VALIDATION_ERROR", "Nothing on this invoice is waiting in a warehouse.", 422, "lines")
    asked = _asked(db, org_id, doc["id"])
    by_id = {i["id"]: i for i in items}
    wanted = lines if lines else [{"item_id": i["id"], "quantity": _int(i["stock_sold"]) - asked.get(i["id"], 0)}
                                  for i in items]
    plan, from_loc = [], None
    for n, ln in enumerate(wanted):
        item = by_id.get(str(ln.get("item_id")))
        if not item:
            raise StockError("VALIDATION_ERROR", "That line isn't waiting in a warehouse.", 422, f"lines.{n}.item_id")
        qty = _int(ln.get("quantity"))
        if qty <= 0:
            continue
        free = _int(item["stock_sold"]) - asked.get(item["id"], 0)
        if qty > free:
            raise StockError("VALIDATION_ERROR", f"Only {max(free, 0)} of {inv_stock._label(item)} can still be asked for.",
                             422, f"lines.{n}.quantity")
        loc_id = inv_stock._loc_of(doc, item)
        if from_loc and loc_id != from_loc:
            raise StockError("VALIDATION_ERROR", "Ask for one warehouse at a time.", 422, f"lines.{n}.item_id")
        from_loc = loc_id
        plan.append({"item_id": item["id"], "quantity": qty, "used": 0, "title": inv_stock._label(item),
                     "product_id": item["product_id"], "variant": item.get("variant") or ""})
    if not plan:
        raise StockError("VALIDATION_ERROR", "Everything here is already waiting for approval.", 422, "lines")
    src = locs[from_loc]
    owner = stock.is_owner(org_ctx)
    extra = {"decided_by": user_id, "decided_at": stock._now()} if owner else {}
    req = _insert(db, org_id, user_id, "delivery", "approved" if owner else "pending", src, None, doc, plan, note, extra)
    units = sum(l["quantity"] for l in plan)
    _audit(db, org_id, user_id, "stock.delivery_requested", req["id"], {"invoice_id": doc["id"], "units": units})
    if notify and not owner:
        _notify(db, org_id, [u for u in owner_ids(db, org_id) if u != user_id], "Delivery to approve",
                f"{_who(org_ctx)} wants to deliver {units} unit{'' if units == 1 else 's'} from {src['name']} for invoice "
                f"{doc.get('number') or ''} ({doc.get('customer_name') or 'customer'}). Approve it in Inventory > Requests.")
    return {"request": view(db, org_id, req["id"])}


def check_delivery(db, org_ctx: dict, doc: dict, plan: list, consume: bool = False) -> None:
    """Called by invoice_stock_service.deliver. plan: [(item, qty)]. Lines in a warehouse need approved units.
    consume=False (before anything moves): raises NEEDS_APPROVAL when the approval isn't there.
    consume=True (after the goods left): uses the approval up; the owner's own delivery is recorded as approved."""
    from app.services import invoice_stock_service as inv_stock
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    locs = {l["id"]: l for l in _rows(db.table("stock_locations").select("*").eq("org_id", org_id).execute())}
    ware = [(i, q) for i, q in plan if is_warehouse(locs.get(inv_stock._loc_of(doc, i)))]
    if not ware:
        return
    if stock.is_owner(org_ctx):
        if not consume:
            return
        by_loc: dict = {}
        for i, q in ware:
            by_loc.setdefault(inv_stock._loc_of(doc, i), []).append((i, q))
        now = stock._now()
        for loc_id, rows in by_loc.items():
            lines = [{"item_id": i["id"], "quantity": q, "used": q, "title": inv_stock._label(i),
                      "product_id": i["product_id"], "variant": i.get("variant") or ""} for i, q in rows]
            _insert(db, org_id, user_id, "delivery", "done", locs[loc_id], None, doc, lines, None,
                    {"decided_by": user_id, "decided_at": now, "done_by": user_id, "done_at": now})
        return
    left = _approved_left(db, org_id, doc["id"])
    short = [i for i, q in ware if q > left.get(i["id"], 0)]
    if short:
        name = locs.get(inv_stock._loc_of(doc, short[0]), {}).get("name") or "the warehouse"
        raise StockError("NEEDS_APPROVAL", f"Delivery from {name} needs the owner's approval first. "
                                           f"Ask for it in Inventory > To deliver.", 403)
    if not consume:
        return
    need = {i["id"]: q for i, q in ware}
    reqs = _rows(db.table("stock_move_requests").select("*").eq("org_id", org_id).eq("invoice_id", doc["id"])
                 .eq("kind", "delivery").eq("status", "approved").order("decided_at").execute())
    for r in reqs:
        lines, changed = [dict(l) for l in r.get("lines") or []], False
        for l in lines:
            take = min(need.get(l["item_id"], 0), _int(l.get("quantity")) - _int(l.get("used")))
            if take > 0:
                l["used"] = _int(l.get("used")) + take
                need[l["item_id"]] -= take
                changed = True
        if changed:
            finished = all(_int(l.get("used")) >= _int(l.get("quantity")) for l in lines)
            patch = {"lines": lines, **({"status": "done", "done_by": user_id, "done_at": stock._now()} if finished else {})}
            db.table("stock_move_requests").update(patch).eq("org_id", org_id).eq("id", r["id"]).execute()


def delivery_state(db, org_id: str, invoice_ids: list) -> dict:
    """{invoice_id: {"pending": units waiting for the owner, "approved": units approved and not yet delivered}}."""
    if not invoice_ids:
        return {}
    out: dict = {}
    for r in _rows(db.table("stock_move_requests").select("invoice_id, status, lines").eq("org_id", org_id)
                   .eq("kind", "delivery").in_("status", list(OPEN)).in_("invoice_id", invoice_ids[:500]).execute()):
        s = out.setdefault(r["invoice_id"], {"pending": 0, "approved": 0})
        s[r["status"]] += sum(_int(l.get("quantity")) - _int(l.get("used")) for l in r.get("lines") or [])
    return out


# ───────────────────────────── deciding / cancelling ─────────────────────────────

def decide(db, org_ctx: dict, request_id: Any, approve: bool, note: Optional[str] = None) -> dict:
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    if not stock.is_owner(org_ctx):
        raise StockError("FORBIDDEN", "Only the business owner can approve or reject stock moves.", 403)
    req = _get(db, org_id, request_id)
    if req["status"] != "pending":
        raise StockError("INVALID_TRANSITION", "This request isn't waiting for approval any more.", 400)
    to = "approved" if approve else "rejected"
    if not _claim(db, org_id, req, "pending", {"status": to, "decided_by": user_id, "decided_at": stock._now(),
                                               "decision_note": _note(note)}):
        raise StockError("STOCK_CONFLICT", "Someone else just changed this request. Refresh and try again.", 409)
    if not approve and req["kind"] == "transfer":
        _release(db, org_id, user_id, req, "Move rejected: hold released")
    _audit(db, org_id, user_id, f"stock.request_{to}", req["id"], {"note": _note(note)})
    v = view(db, org_id, req["id"])
    what = f"move from {v['from_name']} to {v['to_name']}" if req["kind"] == "transfer" \
        else f"delivery for invoice {v.get('invoice_number') or ''}"
    targets = {req.get("requested_by")} | (set(handler_ids(db, org_id)) if approve else set())
    _notify(db, org_id, [u for u in targets if u and u != user_id],
            f"Stock {what.split(' ')[0]} {to}",
            f"The {what} ({v['units']} unit{'' if v['units'] == 1 else 's'}) was {to}"
            + (f": {_note(note)}" if note and _note(note) else ".")
            + (" It can go now." if approve else ""))
    return v


def _release(db, org_id: str, user_id: Optional[str], req: dict, reason: str) -> None:
    try:
        src = stock._location(db, org_id, req["from_location_id"])
        _hold(db, org_id, user_id, src, req.get("lines") or [], -1, reason)
    except StockError as e:
        logger.error("stock_request: release failed org=%s request=%s: %s", org_id, req["id"], e.message)


def cancel(db, org_ctx: dict, request_id: Any) -> dict:
    """The person who asked, a manager or the Inventory Manager drops a request that hasn't gone yet."""
    org_id, user_id = org_ctx["org_id"], _uid(org_ctx)
    req = _get(db, org_id, request_id)
    if not (stock.can_handle(org_ctx) or req.get("requested_by") == user_id):
        raise StockError("FORBIDDEN", "Only the person who asked or a manager can cancel this.", 403)
    if req["status"] not in OPEN:
        raise StockError("INVALID_TRANSITION", "This request is already closed.", 400)
    if req["kind"] == "delivery" and any(_int(l.get("used")) for l in req.get("lines") or []):
        raise StockError("INVALID_TRANSITION", "Part of this delivery has gone already; it can't be cancelled.", 400)
    if not _claim(db, org_id, req, req["status"], {"status": "cancelled", "done_by": user_id, "done_at": stock._now()}):
        raise StockError("STOCK_CONFLICT", "Someone else just changed this request. Refresh and try again.", 409)
    if req["kind"] == "transfer":
        _release(db, org_id, user_id, req, "Move cancelled: hold released")
    _audit(db, org_id, user_id, "stock.request_cancelled", req["id"], {})
    return view(db, org_id, req["id"])


# ───────────────────────────── reading ─────────────────────────────

def _decorate(db, org_id: str, reqs: list) -> list:
    if not reqs:
        return []
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    uids = list({u for r in reqs for u in (r.get("requested_by"), r.get("decided_by"), r.get("done_by")) if u})
    users = {u["id"]: u.get("full_name") for u in _rows(db.table("users").select("id, full_name").eq("org_id", org_id)
                                                       .in_("id", uids).execute())} if uids else {}
    inv_ids = list({r["invoice_id"] for r in reqs if r.get("invoice_id")})
    docs = {d["id"]: d for d in _rows(db.table("invoices").select("id, number, customer_name").eq("org_id", org_id)
                                      .in_("id", inv_ids).execute())} if inv_ids else {}
    out = []
    for r in reqs:
        d = docs.get(r.get("invoice_id")) or {}
        out.append({**r, "from_name": names.get(r["from_location_id"]), "to_name": names.get(r.get("to_location_id")),
                    "invoice_number": d.get("number"), "customer_name": d.get("customer_name"),
                    "requested_by_name": users.get(r.get("requested_by")),
                    "decided_by_name": users.get(r.get("decided_by")), "done_by_name": users.get(r.get("done_by")),
                    "lines": [{**l, "left": _int(l.get("quantity")) - _int(l.get("used"))} if r["kind"] == "delivery"
                              else l for l in r.get("lines") or []]})
    return out


def view(db, org_id: str, request_id: Any) -> dict:
    return _decorate(db, org_id, [_get(db, org_id, request_id)])[0]


def list_requests(db, org_id: str, status_: Optional[str] = None, limit: int = 100) -> list:
    q = db.table("stock_move_requests").select("*").eq("org_id", org_id)
    if status_ == "open":
        q = q.in_("status", list(OPEN))
    elif status_ in STATUSES:
        q = q.eq("status", status_)
    return _decorate(db, org_id, _rows(q.order("requested_at", desc=True).limit(limit).execute()))


def counts(db, org_id: str) -> dict:
    rows = _rows(db.table("stock_move_requests").select("status").eq("org_id", org_id).in_("status", list(OPEN))
                 .limit(1000).execute())
    return {"pending": sum(1 for r in rows if r["status"] == "pending"),
            "approved": sum(1 for r in rows if r["status"] == "approved")}


def period(preset: Optional[str], start: Optional[date], end: Optional[date], today: Optional[date] = None) -> tuple:
    """(first day, last day) for week | month | custom."""
    today = today or datetime.now(timezone.utc).date()
    if preset == "custom":
        if not start or not end:
            raise StockError("VALIDATION_ERROR", "Choose both dates.", 422, "start")
        if end < start:
            raise StockError("VALIDATION_ERROR", "The end date is before the start date.", 422, "end")
        if (end - start).days > 366:
            raise StockError("VALIDATION_ERROR", "Choose up to a year at a time.", 422, "end")
        return start, end
    if preset == "month":
        return today.replace(day=1), today
    return today - timedelta(days=today.weekday()), today   # this week, from Monday


def records(db, org_id: str, start: date, end: date, location_id: Optional[str] = None) -> dict:
    """Approved moves and deliveries whose approval falls between start and end (inclusive)."""
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc).isoformat()
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc).isoformat()
    q = db.table("stock_move_requests").select("*").eq("org_id", org_id).in_("status", ["approved", "done"]) \
        .gte("decided_at", lo).lt("decided_at", hi)
    if location_id:
        q = q.eq("from_location_id", str(location_id))
    rows = _decorate(db, org_id, _rows(q.order("decided_at", desc=True).limit(2000).execute()))
    return {"start": start.isoformat(), "end": end.isoformat(), "records": rows,
            "summary": {"moves": sum(1 for r in rows if r["kind"] == "transfer"),
                        "deliveries": sum(1 for r in rows if r["kind"] == "delivery"),
                        "units": sum(_int(r.get("units")) for r in rows)}}
