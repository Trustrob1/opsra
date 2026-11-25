"""
app/services/stock_transfer_service.py
--------------------------------------
STOCK-3 - moving stock from one location to another.

  send      the goods leave the sending location's on hand at once and show as "in transit" at the receiving one
            (every line is checked by stock_apply; if one line is short, the lines already moved are put back)
  receive   all or part of each line arrives: in transit -> on hand at the receiving location
  cancel    whatever hasn't arrived goes back to the sending location (closes the move)

A move is 'in_transit' until every unit is received or cancelled, then 'done' ('cancelled' when nothing arrived).
Managers only (owner, ops_manager, admin) - the router checks. Every number goes through inventory_service.apply().
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services import inventory_service as stock

logger = logging.getLogger(__name__)

StockError = stock.StockError
MAX_LINES = 100


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _get(db, org_id: str, transfer_id) -> dict:
    rows = _rows(db.table("stock_transfers").select("*").eq("org_id", org_id).eq("id", str(transfer_id)).limit(1).execute())
    if not rows:
        raise StockError("NOT_FOUND", "That stock move was not found.", 404)
    return rows[0]


def _lines(db, org_id: str, transfer_id: str) -> list:
    return _rows(db.table("stock_transfer_lines").select("*").eq("org_id", org_id).eq("transfer_id", transfer_id).execute())


def _left(line: dict) -> int:
    return int(line["quantity"]) - int(line.get("received") or 0) - int(line.get("cancelled") or 0)


def _label(prod: dict, variant: str) -> str:
    return f"{prod.get('title') or 'this item'}{f' - {variant}' if variant else ''}"[:120]


def _audit(db, org_id: str, user_id: Optional[str], action: str, transfer_id: str, new_value: dict) -> None:
    try:
        db.table("audit_logs").insert({"org_id": org_id, "user_id": user_id, "action": action,
                                       "resource_type": "stock_transfer", "resource_id": transfer_id,
                                       "new_value": new_value}).execute()
    except Exception as exc:  # S14
        logger.warning("stock_transfer: audit write failed org=%s transfer=%s: %s", org_id, transfer_id, exc)


def view(db, org_id: str, transfer_id) -> dict:
    t = _get(db, org_id, transfer_id)
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    lines = _lines(db, org_id, t["id"])
    prods = {p["id"]: p.get("title") for p in stock._products(db, org_id, list({l["product_id"] for l in lines}))} if lines else {}
    users = {}
    uids = [u for u in {t.get("sent_by"), t.get("closed_by")} if u]
    if uids:
        users = {u["id"]: u.get("full_name") for u in _rows(db.table("users").select("id, full_name").eq("org_id", org_id)
                                                           .in_("id", uids).execute())}
    return {**t, "from_name": names.get(t["from_location_id"]), "to_name": names.get(t["to_location_id"]),
            "sent_by_name": users.get(t.get("sent_by")), "closed_by_name": users.get(t.get("closed_by")),
            "lines": [{**l, "title": prods.get(l["product_id"]), "left": _left(l)} for l in lines],
            "units": sum(int(l["quantity"]) for l in lines), "units_left": sum(_left(l) for l in lines)}


def list_transfers(db, org_id: str, status: Optional[str] = None, limit: int = 100) -> list:
    q = db.table("stock_transfers").select("id").eq("org_id", org_id)
    if status:
        q = q.eq("status", status)
    ids = [r["id"] for r in _rows(q.order("sent_at", desc=True).limit(limit).execute())]
    return [view(db, org_id, i) for i in ids]


def send(db, org_id: str, user_id: Optional[str], body: dict) -> dict:
    stock._require_on(db, org_id)
    src = stock._location(db, org_id, body.get("from_location_id"))
    dst = stock._location(db, org_id, body.get("to_location_id"))
    if src["id"] == dst["id"]:
        raise StockError("VALIDATION_ERROR", "Choose two different locations.", 422, "to_location_id")
    if not src.get("is_active") or not dst.get("is_active"):
        raise StockError("VALIDATION_ERROR", "Both locations must be turned on.", 422, "to_location_id")
    raw = body.get("lines") or []
    if not raw or len(raw) > MAX_LINES:
        raise StockError("VALIDATION_ERROR", "Add what you are moving.", 422, "lines")
    plan, seen = [], set()
    for n, ln in enumerate(raw):   # every line checked before anything moves
        prod = stock._product(db, org_id, ln.get("product_id"))
        variant = stock.clean_variant(prod, ln.get("variant"))
        if (prod["id"], variant) in seen:
            raise StockError("VALIDATION_ERROR", "The same item is listed twice.", 422, f"lines.{n}")
        seen.add((prod["id"], variant))
        plan.append((prod, variant, stock._qty(ln.get("quantity"), f"lines.{n}.quantity")))
    note = " ".join(str(body.get("note") or "").split())[:300] or None
    t = _rows(db.table("stock_transfers").insert({
        "org_id": org_id, "from_location_id": src["id"], "to_location_id": dst["id"], "status": "in_transit",
        "note": note, "sent_by": user_id, "sent_at": stock._now(), "created_at": stock._now()}).execute())[0]
    done = []
    try:
        for prod, variant, qty in plan:
            label = _label(prod, variant)
            stock.apply(db, org_id, user_id, prod["id"], variant, src["id"], "transfer_out", on_hand=-qty,
                        transfer_id=t["id"], reason=f"Sent to {dst['name']}", label=label)
            done.append((prod, variant, qty, "out"))
            stock.apply(db, org_id, user_id, prod["id"], variant, dst["id"], "transfer_out", transit=qty,
                        transfer_id=t["id"], reason=f"On its way from {src['name']}", label=label)
            done.append((prod, variant, qty, "in"))
            db.table("stock_transfer_lines").insert({"org_id": org_id, "transfer_id": t["id"], "product_id": prod["id"],
                                                     "variant": variant, "quantity": qty, "received": 0,
                                                     "cancelled": 0}).execute()
    except StockError as e:
        for prod, variant, qty, side in reversed(done):   # put back what already moved
            try:
                if side == "out":
                    stock.apply(db, org_id, user_id, prod["id"], variant, src["id"], "transfer_cancel", on_hand=qty,
                                transfer_id=t["id"], reason="Move did not go through")
                else:
                    stock.apply(db, org_id, user_id, prod["id"], variant, dst["id"], "transfer_cancel", transit=-qty,
                                transfer_id=t["id"], reason="Move did not go through")
            except StockError as e2:
                logger.error("stock_transfer: undo failed org=%s transfer=%s: %s", org_id, t["id"], e2.message)
        db.table("stock_transfer_lines").delete().eq("transfer_id", t["id"]).eq("org_id", org_id).execute()
        db.table("stock_transfers").delete().eq("id", t["id"]).eq("org_id", org_id).execute()
        msg = e.message.replace(" here.", f" at {src['name']}.") if e.code == "STOCK_SHORT" else e.message
        raise StockError(e.code, msg, e.status, e.field)
    _audit(db, org_id, user_id, "stock.transfer_sent", t["id"],
           {"lines": [{"product_id": p["id"], "variant": v, "quantity": q} for p, v, q in plan]})
    return view(db, org_id, t["id"])


def _bump(db, org_id: str, line: dict, field: str, qty: int) -> bool:
    """Add to received / cancelled only if nobody changed the line meanwhile (two people receiving at once)."""
    old = int(line.get(field) or 0)
    res = db.table("stock_transfer_lines").update({field: old + qty}).eq("id", line["id"]).eq("org_id", line["org_id"]) \
        .eq(field, old).execute()
    if not _rows(res):
        return False
    line[field] = old + qty
    return True


_CHANGED = ("STOCK_CONFLICT", "Someone else updated this move. Refresh and try again.", 409)


def _close_if_finished(db, org_id: str, t: dict, user_id: Optional[str]) -> None:
    lines = _lines(db, org_id, t["id"])
    if any(_left(l) > 0 for l in lines):
        return
    status = "cancelled" if not any(int(l.get("received") or 0) for l in lines) else "done"
    db.table("stock_transfers").update({"status": status, "closed_by": user_id, "closed_at": stock._now()}) \
        .eq("id", t["id"]).eq("org_id", org_id).eq("status", "in_transit").execute()


def receive(db, org_id: str, user_id: Optional[str], transfer_id, lines: list, cancel_rest: bool = False) -> dict:
    """lines: [{line_id, quantity}] (quantity 0 = nothing of that line arrived yet). cancel_rest sends the rest back."""
    t = _get(db, org_id, transfer_id)
    if t["status"] != "in_transit":
        raise StockError("INVALID_TRANSITION", "This move is already closed.", 400)
    by_id = {l["id"]: l for l in _lines(db, org_id, t["id"])}
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    plan = []
    for n, ln in enumerate(lines or []):
        line = by_id.get(str(ln.get("line_id")))
        if not line:
            raise StockError("VALIDATION_ERROR", "That line isn't on this move.", 422, f"lines.{n}.line_id")
        qty = stock._qty(ln.get("quantity"), f"lines.{n}.quantity", allow_zero=True)
        if qty > _left(line):
            raise StockError("VALIDATION_ERROR", f"Only {_left(line)} of that line are still on the way.", 422,
                             f"lines.{n}.quantity")
        if qty:
            plan.append((line, qty))
    if not plan and not cancel_rest:
        raise StockError("VALIDATION_ERROR", "Enter how many arrived.", 422, "lines")
    for line, qty in plan:
        if not _bump(db, org_id, line, "received", qty):
            raise StockError(*_CHANGED)
        stock.apply(db, org_id, user_id, line["product_id"], line["variant"], t["to_location_id"], "transfer_in",
                    on_hand=qty, transit=-qty, transfer_id=t["id"],
                    reason=f"Arrived from {names.get(t['from_location_id'], 'another location')}")
    if cancel_rest:
        _cancel_lines(db, org_id, user_id, t, list(by_id.values()), names)
    _close_if_finished(db, org_id, t, user_id)
    _audit(db, org_id, user_id, "stock.transfer_received", t["id"],
               {"lines": [{"line_id": l["id"], "quantity": q} for l, q in plan], "cancel_rest": cancel_rest})
    return view(db, org_id, t["id"])


def _cancel_lines(db, org_id: str, user_id: Optional[str], t: dict, lines: list, names: dict) -> None:
    for line in lines:
        rest = _left(line)
        if rest <= 0:
            continue
        if not _bump(db, org_id, line, "cancelled", rest):
            raise StockError(*_CHANGED)
        stock.apply(db, org_id, user_id, line["product_id"], line["variant"], t["to_location_id"], "transfer_cancel",
                    transit=-rest, transfer_id=t["id"], reason="Move cancelled")
        stock.apply(db, org_id, user_id, line["product_id"], line["variant"], t["from_location_id"], "transfer_cancel",
                    on_hand=rest, transfer_id=t["id"],
                    reason=f"Came back: move to {names.get(t['to_location_id'], 'another location')} cancelled")


def cancel(db, org_id: str, user_id: Optional[str], transfer_id) -> dict:
    """Everything not yet received goes back to the sending location."""
    t = _get(db, org_id, transfer_id)
    if t["status"] != "in_transit":
        raise StockError("INVALID_TRANSITION", "This move is already closed.", 400)
    names = {l["id"]: l["name"] for l in stock.list_locations(db, org_id)}
    _cancel_lines(db, org_id, user_id, t, _lines(db, org_id, t["id"]), names)
    _close_if_finished(db, org_id, t, user_id)
    _audit(db, org_id, user_id, "stock.transfer_cancelled", t["id"], {})
    return view(db, org_id, t["id"])
