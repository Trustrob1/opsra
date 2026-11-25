"""
app/services/web_order_stock_service.py
---------------------------------------
STOCK-3 - website (web chat shop) orders and stock.

  checkout   the cart becomes a hidden draft invoice at the online location and its stock is held for 2 hours
             (web_state 'holding'). Not enough stock: nothing is held and the visitor is told what is short.
  paid       the Paystack webhook calls on_web_payment(): the draft gets its number, the payment is recorded
             (paid -> "to deliver" -> Sales Record, all by the normal invoice code) and the invoice shows in Invoices.
  expired    the worker releases holds older than 2 hours (web_state 'released'). If the customer pays later the
             stock is held again; if it has gone meanwhile the invoice is still made, untracked, and managers are told.

ONLINE-ALL: when the website sells from every location (stock settings online_all), plan_sources() picks the location
that can fill the whole cart (main location first), else holds each line wherever it is (invoice_items.stock_location_id),
so the invoice says where each item comes from.

web_state: holding -> paid | holding -> releasing -> released -> paid. Each step is a conditional update, so the
worker and the webhook can't both act on the same order. Team-mode shops (order_mode 'team') don't hold stock here.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import inventory_service as stock
from app.services import invoice_service as inv
from app.services import invoice_stock_service as inv_stock

logger = logging.getLogger(__name__)

HOLD_HOURS = 2
PURGE_DAYS = 30


class WebShort(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _rows(res) -> list:
    data = getattr(res, "data", None)
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _drop_draft(db, org_id: str, doc_id: str) -> None:
    try:
        db.table("invoice_items").delete().eq("invoice_id", doc_id).eq("org_id", org_id).execute()
        db.table("invoices").delete().eq("id", doc_id).eq("org_id", org_id).eq("status", "draft").execute()
    except Exception as exc:
        logger.error("web_order: could not remove draft org=%s doc=%s: %s", org_id, doc_id, exc)


def _items(db, org_id: str, cart: list) -> list:
    pids = list({str(l.get("pid") or "") for l in cart if l.get("pid")})
    prods = {p["id"]: p for p in _rows(db.table("products").select("id, title, variants").eq("org_id", org_id)
                                       .in_("id", pids).execute())} if pids else {}
    out = []
    for l in cart:
        prod = prods.get(str(l.get("pid") or ""))
        if not prod:
            continue
        sizes = {s["title"].lower(): s["title"] for s in inv.product_sizes(prod)}
        v = next((x for x in (prod.get("variants") or []) if isinstance(x, dict)
                  and str(x.get("id") or x.get("variant_id") or "") == str(l.get("vid") or "")), None)
        title = str((v or {}).get("title") or (v or {}).get("option1") or "").strip()
        out.append({"product_id": prod["id"], "variant": sizes.get(title.lower()), "quantity": int(l.get("qty") or 1),
                    "unit_price": float(l.get("price") or 0)})
    return out


def _short_text(message: str) -> str:
    """'Only 2 of X left at Lekki Showroom.' -> 'Only 2 of X left right now.' (visitors don't see our locations)."""
    return re.sub(r" at [^.]+\.$", " right now.", message or "")


def plan_sources(db, org_id: str, lines: list, settings: Optional[dict] = None) -> tuple[Optional[dict], dict]:
    """ONLINE-ALL: (main location, {item_id: other location}) for a website order's product lines.
    One location fills everything if it can (the business's main location first, then the one with most of the cart);
    otherwise each line is taken from a location that has enough of it. A line no single location can fill stays on
    the main location, so holding it reports it as short."""
    settings = settings or stock.get_settings(db, org_id)
    locs = stock.online_locations(db, org_id, settings)
    if not locs:
        return None, {}
    lines = [l for l in lines if l.get("product_id")]
    if len(locs) == 1 or not lines:
        return locs[0], {}
    by = stock.available_by_location(db, org_id, [l["id"] for l in locs], list({l["product_id"] for l in lines}))
    key = lambda l: (l["product_id"], l.get("variant") or "")   # noqa: E731
    need: dict = {}
    for l in lines:
        need[key(l)] = need.get(key(l), 0) + int(float(l.get("quantity") or 0))

    def covered(loc_id: str) -> int:
        return sum(min(q, (by.get(k) or {}).get(loc_id, 0)) for k, q in need.items())

    total = sum(need.values())
    order = sorted(locs, key=lambda l: (not l.get("is_default"),))   # main location first, rest keep their order
    main = next((l for l in order if covered(l["id"]) >= total), None) \
        or max(order, key=lambda l: (covered(l["id"]), bool(l.get("is_default"))))
    left = {k: dict(v) for k, v in by.items()}
    sources: dict = {}
    for l in lines:
        k, q = key(l), int(float(l.get("quantity") or 0))
        here = left.get(k) or {}
        if here.get(main["id"], 0) >= q:
            here[main["id"]] -= q
            continue
        other = max((x for x in locs if x["id"] != main["id"] and here.get(x["id"], 0) >= q),
                    key=lambda x: here.get(x["id"], 0), default=None)
        if other:
            here[other["id"]] -= q
            sources[l["id"]] = other["id"]
    return main, sources


def _web_lines(db, org_id: str, doc_id: str) -> list:
    return _rows(db.table("invoice_items").select("id, product_id, variant, quantity").eq("org_id", org_id)
                 .eq("invoice_id", doc_id).execute())


def hold(db, org_id: str, lead_id: str, cart: list) -> Optional[dict]:
    """Hold the cart's stock for 2 hours. Returns the hidden draft, or None when stock isn't tracked for this shop.
    Raises WebShort with a visitor-friendly message when something is short."""
    if not stock.stock_on(db, org_id):
        return None
    settings = stock.get_settings(db, org_id)
    locs = stock.online_locations(db, org_id, settings)   # ONLINE-ALL
    items = _items(db, org_id, cart)
    if not locs or not items:
        return None
    loc = locs[0]
    try:
        doc = inv.create_draft(db, org_id, None, {"doc_type": "invoice", "lead_id": lead_id, "items": items,
                                                  "apply_vat": False, "location_id": loc["id"],
                                                  "notes": "Website order"})
    except inv.InvoiceError as e:
        logger.warning("web_order: draft not made org=%s: %s", org_id, e.message)
        return None
    web = {"origin": "web", "web_state": "holding", "web_hidden": True,
           "web_hold_until": _iso(_now() + timedelta(hours=HOLD_HOURS))}
    loc, sources = plan_sources(db, org_id, _web_lines(db, org_id, doc["id"]), settings)   # ONLINE-ALL
    web["location_id"] = loc["id"]
    db.table("invoices").update(web).eq("id", doc["id"]).eq("org_id", org_id).execute()
    try:
        inv_stock.prepare_issue(db, org_id, None, {**doc, **web}, number="website order",
                                sources=sources or None, allow_other=bool(sources))
    except inv.InvoiceError as e:
        _drop_draft(db, org_id, doc["id"])
        if e.code == "STOCK_SHORT":
            raise WebShort(_short_text(e.message))
        logger.warning("web_order: hold failed org=%s: %s", org_id, e.message)
        return None
    return {**doc, **web}


def attach(db, org_id: str, doc_id: str, reference: Optional[str]) -> None:
    db.table("invoices").update({"web_reference": reference}).eq("id", doc_id).eq("org_id", org_id).execute()


def drop(db, org_id: str, doc_id: str) -> None:
    """No payment link could be made: give the stock back and remove the draft."""
    inv_stock.undo_issue(db, org_id, None, doc_id)
    _drop_draft(db, org_id, doc_id)


def _claim(db, org_id: str, doc_id: str, frm: str, to: str, extra: Optional[dict] = None) -> bool:
    res = db.table("invoices").update({"web_state": to, **(extra or {})}).eq("id", doc_id).eq("org_id", org_id) \
        .eq("web_state", frm).execute()
    return bool(_rows(res))


def on_web_payment(db, org_id: str, reference: str) -> Optional[dict]:
    """Paystack confirmed a payment. If it was a website order: number the invoice and record the payment. Never raises."""
    try:
        if not reference or str(reference).startswith("inv_"):
            return None
        docs = _rows(db.table("invoices").select("*").eq("org_id", org_id).eq("web_reference", reference)
                     .eq("origin", "web").limit(1).execute())
        if not docs:
            return None
        doc = docs[0]
        link = (_rows(db.table("payment_links").select("*").eq("org_id", org_id).eq("reference", reference)
                      .limit(1).execute()) or [None])[0]
        if not link or link.get("status") != "paid":
            return None
        if doc.get("status") != "draft":
            return None   # already made into an invoice (Paystack can send the same event twice)
        held = _claim(db, org_id, doc["id"], "holding", "paid")
        if not held:
            for _ in range(5):   # the worker is releasing it right now
                state = (inv._one(db, "invoices", org_id, doc["id"]) or {}).get("web_state")
                if state != "releasing":
                    break
                time.sleep(1)
            if not _claim(db, org_id, doc["id"], "released", "paid"):
                state = (inv._one(db, "invoices", org_id, doc["id"]) or {}).get("web_state")
                if state == "releasing":   # stuck mid-release: the worker finishes it; a person records this one
                    inv_stock._notify(db, org_id, inv_stock._manager_ids(db, org_id), "Website payment needs a hand",
                                      f"{doc.get('customer_name') or 'A customer'} paid {link.get('amount')} for a "
                                      "website order (reference " + str(reference) + "). Record it on an invoice.",
                                      kind="stock_web_short")
                return None   # otherwise someone else already handled this payment
            _hold_again(db, org_id, doc)
        doc = inv._one(db, "invoices", org_id, doc["id"])
        inv._issue_numbered(db, org_id, None, doc)
        db.table("invoices").update({"web_hidden": False, "web_hold_until": None}).eq("id", doc["id"]) \
            .eq("org_id", org_id).execute()
        from app.services import invoice_payment_service as pay
        out = pay.record_payment(db, org_id, None, doc["id"],
                                 {"amount": link.get("amount"), "method": "paystack", "reference": reference,
                                  "paid_at": link.get("paid_at"), "note": "Paid on the website"},
                                 payment_link_id=link["id"], allow_over=True)
        try:
            from app.services import invoice_delivery_service as delivery
            delivery.send_receipt(db, org_id, None, out["receipt"]["id"])
        except Exception as exc:
            logger.warning("web_order: receipt send failed org=%s ref=%s: %s", org_id, reference, exc)
        return out
    except Exception as exc:  # S14 - the webhook must always answer Paystack
        logger.error("web_order: on_web_payment failed org=%s ref=%s: %s", org_id, reference, exc)
        return None


def _hold_again(db, org_id: str, doc: dict) -> None:
    """Paid after the 2-hour hold ran out: take the stock again, or make the sale untracked and tell managers."""
    fresh = inv._one(db, "invoices", org_id, doc["id"]) or doc
    try:
        loc, sources = plan_sources(db, org_id, _web_lines(db, org_id, doc["id"]))   # ONLINE-ALL: wherever it is now
        if loc and loc["id"] != fresh.get("location_id"):
            db.table("invoices").update({"location_id": loc["id"]}).eq("id", doc["id"]).eq("org_id", org_id).execute()
            fresh = {**fresh, "location_id": loc["id"]}
        inv_stock.prepare_issue(db, org_id, None, fresh, number="website order",
                                sources=sources or None, allow_other=bool(sources))
    except inv.InvoiceError as e:
        db.table("invoices").update({"stock_tracked": False}).eq("id", doc["id"]).eq("org_id", org_id).execute()
        inv_stock._notify(db, org_id, inv_stock._manager_ids(db, org_id), "Website order paid, stock short",
                          f"{doc.get('customer_name') or 'A customer'} paid after the 2-hour hold ran out and the stock "
                          f"is no longer there ({e.message}) Arrange the goods or a refund; the invoice is not taking "
                          "stock.", kind="stock_web_short")


def expire_holds(db, now: Optional[datetime] = None, limit: int = 200) -> dict:
    """Worker: release website holds older than 2 hours; remove unpaid ones after 30 days."""
    now = now or _now()
    out = {"released": 0, "removed": 0}
    due = _rows(db.table("invoices").select("id, org_id").eq("web_state", "holding")
                .lt("web_hold_until", _iso(now)).limit(limit).execute())
    for d in due:
        try:
            if not _claim(db, d["org_id"], d["id"], "holding", "releasing"):
                continue   # paid in the meantime
            inv_stock.undo_issue(db, d["org_id"], None, d["id"])
            _claim(db, d["org_id"], d["id"], "releasing", "released", {"web_hold_until": None})
            out["released"] += 1
        except Exception as exc:
            logger.error("web_order: release failed doc=%s: %s", d["id"], exc)
    stuck = _rows(db.table("invoices").select("id, org_id").eq("web_state", "releasing")
                  .lt("web_hold_until", _iso(now - timedelta(minutes=10))).limit(limit).execute())
    for d in stuck:   # a release that was cut off halfway: finish it (undo_issue is safe to run twice)
        inv_stock.undo_issue(db, d["org_id"], None, d["id"])
        _claim(db, d["org_id"], d["id"], "releasing", "released", {"web_hold_until": None})
        out["released"] += 1
    old = _rows(db.table("invoices").select("id, org_id").eq("web_state", "released").eq("status", "draft")
                .lt("created_at", _iso(now - timedelta(days=PURGE_DAYS))).limit(limit).execute())
    for d in old:
        _drop_draft(db, d["org_id"], d["id"])
        out["removed"] += 1
    return out
