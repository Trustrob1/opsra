"""STOCK-3: online stock numbers, moving stock between locations, website checkouts holding stock, low-stock alert."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.unit.test_invoices_1 import LEAD, ORG, USER, _plan_allows  # noqa: F401  (autouse fixture)
from tests.unit.test_stock_2 import (  # noqa: F401  (_no_side_effects is an autouse fixture)
    BED, OWNER, PILLOW, REP, _avail, _client, _lv, _no_side_effects, _sdb,
)
from app.services import inventory_service as stock
from app.services import invoice_service as inv
from app.services import stock_alert_service as alerts
from app.services import stock_transfer_service as tr
from app.services import web_order_stock_service as web

RITA = {"id": REP, "org_id": ORG, "roles": {"template": "sales_agent"}}


def _setup():
    """Main store: Queen bed 5, pillow 10. Lagos Store: Queen bed 2. Variants get Shopify-style ids."""
    db, main, lagos = _sdb()
    db.tables["users"][0]["roles"] = {"template": "owner"}
    db.tables["users"][0]["email"] = "ada@shop.ng"
    db.tables["users"][1]["roles"] = {"template": "sales_agent"}
    db.tables.setdefault("notifications", [])
    db.tables.setdefault("payment_links", [])
    db.tables.setdefault("stock_transfers", [])
    db.tables.setdefault("stock_transfer_lines", [])
    bed = next(p for p in db.rows("products") if p["id"] == BED)
    bed["variants"][0]["id"], bed["variants"][1]["id"] = 101, 102
    stock.refresh_all(db, ORG)
    orig = db.rpc

    def rpc(fn, params):   # the real stock_apply writes p_transfer onto the move (STOCK-1 SQL)
        out = orig(fn, params)
        if fn == "stock_apply":
            db.rows("stock_moves")[-1]["transfer_id"] = params.get("p_transfer")
        return out
    db.rpc = rpc
    return db, main, lagos


def _bed_variant(db, title="Queen"):
    bed = next(p for p in db.rows("products") if p["id"] == BED)
    return next(v for v in bed["variants"] if v["title"] == title)


# ───────────────────────────── online numbers ─────────────────────────────

def test_website_numbers_follow_the_online_location():
    db, main, lagos = _setup()
    stock.save_settings(db, ORG, USER, {"online_all": False})   # ONLINE-ALL off: one location
    q = _bed_variant(db)
    assert (q["inventory_quantity"], q["available"], q["inventory_management"]) == (5, True, "opsra")
    assert _bed_variant(db, "King")["available"] is False
    pillow = next(p for p in db.rows("products") if p["id"] == PILLOW)
    assert pillow["available"] is True
    out = stock.save_settings(db, ORG, USER, {"online_location_id": lagos["id"]})
    assert out["online_location_id"] == lagos["id"] and out["refreshed"] == 3   # its own 3 products, not the other org's
    assert _bed_variant(db)["inventory_quantity"] == 2
    assert next(p for p in db.rows("products") if p["id"] == PILLOW)["available"] is False   # none in Lagos
    stock.adjust(db, ORG, USER, {"location_id": lagos["id"], "product_id": BED, "variant": "Queen",
                                 "mode": "set", "quantity": 0, "reason": "recount"})
    assert _bed_variant(db)["available"] is False
    assert next(p for p in db.rows("products") if p["id"] == BED)["available"] is False
    with pytest.raises(stock.StockError) as e:
        stock.save_settings(db, ORG, USER, {"online_location_id": "00000000-0000-0000-0000-00000000dead"})
    assert e.value.field == "online_location_id"


def test_stock_fields_without_a_record_is_zero():
    prod = {"id": BED, "variants": [{"title": "Queen"}, {"title": "King"}]}
    out = stock.stock_fields(prod, {(BED, "Queen"): 3})
    assert [v["inventory_quantity"] for v in out["variants"]] == [3, 0] and out["available"] is True
    assert stock.stock_fields({**prod, "status": "archived"}, {(BED, "Queen"): 3})["available"] is False


# ───────────────────────────── moving stock ─────────────────────────────

def _send(db, main, lagos, lines=None, **kw):
    return tr.send(db, ORG, USER, {"from_location_id": main["id"], "to_location_id": lagos["id"],
                                   "lines": lines or [{"product_id": BED, "variant": "Queen", "quantity": 3}], **kw})


def test_send_receive_part_then_cancel_rest():
    db, main, lagos = _setup()
    t = _send(db, main, lagos, note="  for the  weekend ")
    assert t["status"] == "in_transit" and t["note"] == "for the weekend" and t["units_left"] == 3
    assert _lv(db, BED, "Queen", main)["on_hand"] == 2 and _lv(db, BED, "Queen", lagos)["in_transit_in"] == 3
    assert _lv(db, BED, "Queen", lagos)["on_hand"] == 2
    line = t["lines"][0]
    t = tr.receive(db, ORG, USER, t["id"], [{"line_id": line["id"], "quantity": 2}])
    assert t["status"] == "in_transit" and t["lines"][0]["received"] == 2 and t["units_left"] == 1
    assert _lv(db, BED, "Queen", lagos)["on_hand"] == 4 and _lv(db, BED, "Queen", lagos)["in_transit_in"] == 1
    with pytest.raises(stock.StockError) as e:
        tr.receive(db, ORG, USER, t["id"], [{"line_id": line["id"], "quantity": 2}])
    assert "Only 1" in e.value.message
    t = tr.cancel(db, ORG, USER, t["id"])
    assert t["status"] == "done" and t["lines"][0]["cancelled"] == 1 and t["units_left"] == 0
    assert _lv(db, BED, "Queen", main)["on_hand"] == 3 and _lv(db, BED, "Queen", lagos)["in_transit_in"] == 0
    with pytest.raises(stock.StockError) as e:
        tr.cancel(db, ORG, USER, t["id"])
    assert e.value.code == "INVALID_TRANSITION"
    kinds = [m["kind"] for m in db.rows("stock_moves") if m.get("transfer_id") == t["id"]]
    assert kinds == ["transfer_out", "transfer_out", "transfer_in", "transfer_cancel", "transfer_cancel"]


def test_receive_all_closes_and_cancel_before_anything_arrives():
    db, main, lagos = _setup()
    t = _send(db, main, lagos)
    t = tr.receive(db, ORG, USER, t["id"], [{"line_id": t["lines"][0]["id"], "quantity": 3}])
    assert t["status"] == "done" and _lv(db, BED, "Queen", lagos)["on_hand"] == 5
    t2 = _send(db, main, lagos, [{"product_id": PILLOW, "quantity": 4}])
    t2 = tr.receive(db, ORG, USER, t2["id"], [], cancel_rest=True)
    assert t2["status"] == "cancelled" and _lv(db, PILLOW, "", main)["on_hand"] == 10
    assert [x["id"] for x in tr.list_transfers(db, ORG, "cancelled")] == [t2["id"]]


def test_short_send_moves_nothing():
    db, main, lagos = _setup()
    with pytest.raises(stock.StockError) as e:
        _send(db, main, lagos, [{"product_id": PILLOW, "quantity": 2},
                                {"product_id": BED, "variant": "Queen", "quantity": 9}])
    assert e.value.code == "STOCK_SHORT" and "at Main store" in e.value.message
    assert _lv(db, PILLOW, "", main)["on_hand"] == 10 and _lv(db, PILLOW, "", lagos)["in_transit_in"] == 0
    assert db.rows("stock_transfers") == [] and db.rows("stock_transfer_lines") == []


def test_send_rules():
    db, main, lagos = _setup()
    q1 = {"product_id": BED, "variant": "Queen", "quantity": 1}
    for body, field in [({"to_location_id": main["id"]}, "to_location_id"), ({"lines": []}, "lines"),
                        ({"lines": [q1, q1]}, "lines.1")]:
        with pytest.raises(stock.StockError) as e:
            tr.send(db, ORG, USER, {"from_location_id": main["id"], "to_location_id": lagos["id"], "lines": [q1], **body})
        assert e.value.field == field
    off = stock.create_location(db, ORG, {"name": "Old shop"})
    stock.update_location(db, ORG, off["id"], {"is_active": False})
    with pytest.raises(stock.StockError) as e:
        tr.send(db, ORG, USER, {"from_location_id": main["id"], "to_location_id": off["id"], "lines": [q1]})
    assert "turned on" in e.value.message


def test_two_people_receiving_at_once_is_refused():
    db, main, lagos = _setup()
    t = _send(db, main, lagos)
    stale = dict(db.rows("stock_transfer_lines")[0])
    assert tr._bump(db, ORG, dict(stale), "received", 2) is True
    assert tr._bump(db, ORG, dict(stale), "received", 2) is False                # the second one sees the change
    assert db.rows("stock_transfer_lines")[0]["received"] == 2
    assert t["id"]


def test_transfer_routes_managers_only():
    db, main, lagos = _setup()
    c = _client(db, OWNER)
    r = c.post("/api/v1/inventory/transfers", json={"from_location_id": main["id"], "to_location_id": lagos["id"],
                                                     "lines": [{"product_id": BED, "variant": "Queen", "quantity": 1}]})
    t = r.json()["data"]
    assert r.status_code == 200 and t["from_name"] == "Main store" and t["sent_by_name"] == "Ada Owner"
    got = c.get("/api/v1/inventory/transfers?status=in_transit").json()["data"]
    assert [x["id"] for x in got["transfers"]] == [t["id"]] and got["can_manage"] is True
    r = c.post(f"/api/v1/inventory/transfers/{t['id']}/receive",
               json={"lines": [{"line_id": t["lines"][0]["id"], "quantity": 1}]})
    assert r.json()["data"]["status"] == "done"
    rep = _client(db, RITA)
    assert rep.post(f"/api/v1/inventory/transfers/{t['id']}/cancel").status_code == 403
    assert rep.get("/api/v1/inventory/transfers").json()["data"]["can_manage"] is False
    r = c.put("/api/v1/inventory/settings", json={"online_location_id": lagos["id"], "low_stock_alerts": False})
    assert r.json()["data"]["online_location_id"] == lagos["id"] and r.json()["data"]["low_stock_alerts"] is False


# ───────────────────────────── website checkouts ─────────────────────────────

CART = [{"pid": BED, "vid": "101", "name": "Hybrid Bed - Queen", "price": 400000, "qty": 2},
        {"pid": PILLOW, "vid": None, "name": "Pillow", "price": 15000, "qty": 1}]


def _paid_link(db, ref, amount=815000):
    db.rows("payment_links").append({"id": f"pl-{ref}", "org_id": ORG, "reference": ref, "status": "paid",
                                     "amount": amount, "paid_at": datetime.now(timezone.utc).isoformat()})


def _hold(db):
    d = web.hold(db, ORG, LEAD, CART)
    web.attach(db, ORG, d["id"], "ps_ref_1")
    return d


@pytest.fixture(autouse=True)
def _no_receipt_send():
    with patch("app.services.invoice_delivery_service.send_receipt"):
        yield


def test_checkout_holds_hidden_then_payment_makes_a_paid_invoice():
    db, main, lagos = _setup()
    stock.save_settings(db, ORG, USER, {"online_all": False})   # ONLINE-ALL off: one location
    d = _hold(db)
    assert d["total"] == 815000 and d["web_state"] == "holding"
    assert _lv(db, BED, "Queen", main)["held"] == 2 and _lv(db, PILLOW, "", main)["held"] == 1
    assert _bed_variant(db)["inventory_quantity"] == 3                       # the website shows what's left
    assert inv.list_docs(db, ORG)["items"] == [] and inv.summary(db, ORG)["drafts"] == 0
    with pytest.raises(inv.InvoiceError) as e:
        inv.update_draft(db, ORG, USER, d["id"], {"notes": "x"})
    assert "website order" in e.value.message
    from app.services import invoice_stock_service as inv_stock
    assert inv_stock.sync(db, ORG, d["id"])["changed"] == 0                  # the daily retry keeps the hold
    held = inv_stock.held_list(db, ORG)
    assert held[0]["web"] is True and held[0]["number"] == "Website order"
    _paid_link(db, "ps_ref_1")
    out = web.on_web_payment(db, ORG, "ps_ref_1")
    doc = inv.get_doc(db, ORG, d["id"])
    assert out["fully_paid"] is True and doc["status"] == "paid" and doc["number"] and doc["web_state"] == "paid"
    assert doc["web_hidden"] is False and out["receipt"]["method"] == "paystack"
    assert _lv(db, BED, "Queen", main)["held"] == 0 and _lv(db, BED, "Queen", main)["sold_pending"] == 2
    assert web.on_web_payment(db, ORG, "ps_ref_1") is None                     # Paystack sent it twice
    assert len(db.rows("receipts")) == 1
    assert web.on_web_payment(db, ORG, "inv_x") is None and web.on_web_payment(db, ORG, "other") is None


def test_short_at_checkout_holds_nothing():
    db, main, lagos = _setup()
    with pytest.raises(web.WebShort) as e:
        web.hold(db, ORG, LEAD, [{**CART[0], "qty": 6}])
    assert "right now." in e.value.message and "Main store" not in e.value.message
    assert db.rows("invoices") == [] and _lv(db, BED, "Queen", main)["held"] == 0


def test_no_stock_tracking_means_no_hold():
    db, main, lagos = _setup()
    stock.save_settings(db, ORG, USER, {"enabled": False})
    assert web.hold(db, ORG, LEAD, CART) is None and db.rows("invoices") == []


def test_no_payment_link_gives_stock_back():
    db, main, lagos = _setup()
    d = web.hold(db, ORG, LEAD, CART)
    web.drop(db, ORG, d["id"])
    assert db.rows("invoices") == [] and _lv(db, BED, "Queen", main)["held"] == 0


def test_hold_runs_out_then_late_payment_holds_again():
    db, main, lagos = _setup()
    d = _hold(db)
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    assert web.expire_holds(db, later)["released"] == 1
    row = next(x for x in db.rows("invoices") if x["id"] == d["id"])
    assert row["web_state"] == "released" and not row["stock_tracked"] and _lv(db, BED, "Queen", main)["held"] == 0
    assert web.expire_holds(db, later)["released"] == 0
    _paid_link(db, "ps_ref_1")
    out = web.on_web_payment(db, ORG, "ps_ref_1")
    assert out["fully_paid"] and _lv(db, BED, "Queen", main)["sold_pending"] == 2


def test_late_payment_when_stock_has_gone_tells_managers():
    db, main, lagos = _setup()
    stock.save_settings(db, ORG, USER, {"online_all": False})   # ONLINE-ALL off: one location
    d = _hold(db)
    web.expire_holds(db, datetime.now(timezone.utc) + timedelta(hours=3))
    stock.adjust(db, ORG, USER, {"location_id": main["id"], "product_id": BED, "variant": "Queen",
                                 "mode": "set", "quantity": 0, "reason": "recount"})
    _paid_link(db, "ps_ref_1")
    out = web.on_web_payment(db, ORG, "ps_ref_1")
    doc = inv.get_doc(db, ORG, d["id"])
    assert out["fully_paid"] and doc["status"] == "paid" and not doc["stock_tracked"]
    n = db.rows("notifications")[-1]
    assert n["type"] == "stock_web_short" and n["user_id"] == USER
    assert _lv(db, PILLOW, "", main)["held"] == 0 and _lv(db, PILLOW, "", main)["sold_pending"] == 0


def test_payment_while_release_is_stuck_asks_a_person():
    db, main, lagos = _setup()
    d = _hold(db)
    next(x for x in db.rows("invoices") if x["id"] == d["id"])["web_state"] = "releasing"
    _paid_link(db, "ps_ref_1")
    with patch("app.services.web_order_stock_service.time.sleep"):
        assert web.on_web_payment(db, ORG, "ps_ref_1") is None
    assert db.rows("notifications")[-1]["title"] == "Website payment needs a hand"
    # the worker finishes a cut-off release later
    assert web.expire_holds(db, datetime.now(timezone.utc) + timedelta(hours=3))["released"] == 1
    assert _lv(db, BED, "Queen", main)["held"] == 0


def test_old_unpaid_checkouts_are_removed():
    db, main, lagos = _setup()
    d = _hold(db)
    web.expire_holds(db, datetime.now(timezone.utc) + timedelta(hours=3))
    next(x for x in db.rows("invoices") if x["id"] == d["id"])["created_at"] = "2020-01-01T00:00:00+00:00"
    assert web.expire_holds(db)["removed"] == 1 and db.rows("invoices") == []


def test_webchat_checkout_holds_and_records_reference():
    db, main, lagos = _setup()
    from app.services import webchat_shop_service as shop
    s = {"id": "sess", "org_id": ORG, "lead_id": LEAD, "source": "site"}
    with patch.object(shop, "_reprice", return_value=([dict(l) for l in CART], [])), \
            patch.object(shop, "_save"), patch.object(shop, "view", return_value={}), \
            patch.object(shop.wc, "append_message", return_value={}), patch.object(shop.wc, "log_event"), \
            patch.object(shop.wc, "set_state"), patch.object(shop.wc, "notify_managers"), \
            patch("app.services.webchat_followup_service.send_order_link"), \
            patch("app.services.lead_service.write_timeline_event"), \
            patch("app.services.paystack_storefront_service.generate_payment_link",
                  return_value={"checkout_url": "https://pay/x", "reference": "ps_ref_9"}):
        out = shop.checkout(db, s, {})
        assert out["checkout_url"] == "https://pay/x"
        row = db.rows("invoices")[0]
        assert row["web_reference"] == "ps_ref_9" and row["web_state"] == "holding"
        with patch.object(shop, "_reprice", return_value=([{**CART[0], "qty": 9}], [])):
            bad = shop.checkout(db, s, {})
        assert "right now" in bad["error"]
        assert len(db.rows("invoices")) == 1


# ───────────────────────────── low-stock alert ─────────────────────────────

def test_low_stock_alert_notifies_emails_then_only_new_changes():
    db, main, lagos = _setup()
    stock.save_settings(db, ORG, USER, {"default_reorder_level": 5})
    sent = []
    fake = types.SimpleNamespace(api_key=None, Emails=types.SimpleNamespace(send=lambda m: sent.append(m)))
    with patch.dict(sys.modules, {"resend": fake}), patch.dict("os.environ", {"RESEND_API_KEY": "k"}):
        first = datetime(2026, 11, 25, 11, 0, tzinfo=timezone.utc)       # fake moves are stamped 10:xx
        r = alerts.alert_org(db, ORG, first)
        assert r["low"] == 2 and r["notified"] == 1 and r["emailed"] == 1   # King and the mattress (0); Queen 7, pillow 10
        assert sent[0]["to"] == ["ada@shop.ng"] and "running low" in sent[0]["subject"]
        assert db.rows("notifications")[-1]["type"] == "stock_low"
        assert alerts.alert_org(db, ORG, first + timedelta(hours=1))["low"] == 0   # nothing moved since
        stock.adjust(db, ORG, USER, {"location_id": main["id"], "product_id": BED, "variant": "Queen",
                                     "mode": "set", "quantity": 1, "reason": "recount"})
        db.rows("stock_moves")[-1]["created_at"] = "2026-11-25T12:30:00+00:00"
        r = alerts.alert_org(db, ORG, first + timedelta(hours=2))
        assert r["low"] == 1 and "Hybrid Bed - Queen: 3 left" in sent[-1]["text"]
        stock.save_settings(db, ORG, USER, {"low_stock_alerts": False})
        assert alerts.alert_all(db) == {"orgs": 0, "low": 0}


# ───────────────────────────── ONLINE-ALL: the website sells from every location ─────────────────────────────

def test_all_locations_is_the_default_and_shows_the_total():
    db, main, lagos = _setup()
    assert stock.get_settings(db, ORG)["online_all"] is True
    assert _bed_variant(db)["inventory_quantity"] == 7                     # 5 at Main store + 2 at Lagos Store
    out = stock.save_settings(db, ORG, USER, {"online_all": False})
    assert out["refreshed"] == 3 and _bed_variant(db)["inventory_quantity"] == 5
    out = stock.save_settings(db, ORG, USER, {"online_all": True})
    assert out["refreshed"] == 3 and _bed_variant(db)["inventory_quantity"] == 7


def test_all_locations_checkout_uses_one_location_when_it_has_everything():
    db, main, lagos = _setup()
    d = _hold(db)
    assert d["location_id"] == main["id"]
    assert _lv(db, BED, "Queen", main)["held"] == 2 and _lv(db, BED, "Queen", lagos)["held"] == 0
    assert _bed_variant(db)["inventory_quantity"] == 5                     # 7 - 2 held


def test_all_locations_checkout_takes_each_item_from_where_it_is():
    db, main, lagos = _setup()
    stock.adjust(db, ORG, USER, {"location_id": main["id"], "product_id": BED, "variant": "Queen",
                                 "mode": "set", "quantity": 0, "reason": "recount"})
    d = _hold(db)                                                          # Queen x2 only at Lagos, pillow only at Main
    assert _lv(db, BED, "Queen", lagos)["held"] == 2 and _lv(db, PILLOW, "", main)["held"] == 1
    lines = {i["product_id"]: i for i in db.rows("invoice_items") if i["invoice_id"] == d["id"]}
    doc_loc = next(x for x in db.rows("invoices") if x["id"] == d["id"])["location_id"]
    assert (lines[BED].get("stock_location_id") or doc_loc) == lagos["id"]
    assert (lines[PILLOW].get("stock_location_id") or doc_loc) == main["id"]
    _paid_link(db, "ps_ref_1")
    assert web.on_web_payment(db, ORG, "ps_ref_1")["fully_paid"]
    assert _lv(db, BED, "Queen", lagos)["sold_pending"] == 2 and _lv(db, PILLOW, "", main)["sold_pending"] == 1


def test_all_locations_short_when_no_location_has_enough_of_a_line():
    db, main, lagos = _setup()
    with pytest.raises(web.WebShort) as e:                                 # 7 in total, but no single place has 6
        web.hold(db, ORG, LEAD, [{**CART[0], "qty": 6}])
    assert "right now." in e.value.message and "Main store" not in e.value.message and "Lagos" not in e.value.message
    assert db.rows("invoices") == [] and _lv(db, BED, "Queen", main)["held"] == 0


def test_all_locations_late_payment_takes_stock_from_another_location():
    db, main, lagos = _setup()
    d = _hold(db)
    web.expire_holds(db, datetime.now(timezone.utc) + timedelta(hours=3))
    stock.adjust(db, ORG, USER, {"location_id": main["id"], "product_id": BED, "variant": "Queen",
                                 "mode": "set", "quantity": 0, "reason": "recount"})
    _paid_link(db, "ps_ref_1")
    out = web.on_web_payment(db, ORG, "ps_ref_1")
    doc = inv.get_doc(db, ORG, d["id"])
    assert out["fully_paid"] and doc["stock_tracked"]
    assert _lv(db, BED, "Queen", lagos)["sold_pending"] == 2 and _lv(db, PILLOW, "", main)["sold_pending"] == 1
