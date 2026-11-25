"""STOCK-2: invoices hold stock on issue, move it to "to deliver" when fully paid, take it out when delivered, and give
it back on void / receipt void. The Postgres stock_apply (with the invoice line counters) is mirrored by SDB; the real
SQL is tested against Postgres separately (see the STOCK-2 session log)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.test_invoices_1 import (  # noqa: F401  (_plan_allows is an autouse fixture)
    InvDB, LEAD, ORG, OTHER, USER, _db, _plan_allows,
)
from tests.unit.test_stock_1 import StockDB
from app.services import inventory_service as stock
from app.services import invoice_followup_service as fu
from app.services import invoice_payment_service as pay
from app.services import invoice_service as inv
from app.services import invoice_stock_service as inv_stock

REP = "99999999-0000-0000-0000-000000000001"
BED = "aaaaaaaa-1111-1111-1111-111111111111"
PILLOW = "aaaaaaaa-2222-2222-2222-222222222222"
OWNER = {"id": USER, "org_id": ORG, "roles": {"template": "owner"}}


class SDB(InvDB):
    """Invoice fake + stock_apply copy that also moves the invoice line counters (as the STOCK-2 SQL does)."""
    fail_next = 0

    def rpc(self, fn, params):
        if fn == "next_invoice_number":
            return super().rpc(fn, params)
        assert fn == "stock_apply"
        if self.fail_next:
            self.fail_next -= 1
            raise Exception("connection reset")
        p = params
        if p.get("p_invoice_item"):
            item = next((i for i in self.rows("invoice_items") if i["id"] == p["p_invoice_item"]
                         and i["org_id"] == p["p_org"] and (not p.get("p_invoice") or i["invoice_id"] == p["p_invoice"])), None)
            if not item:
                raise Exception("STOCK_BAD_INVOICE_ITEM")
        out = StockDB._apply(self, p)
        self.rows("stock_moves")[-1].update(invoice_id=p.get("p_invoice"), invoice_item_id=p.get("p_invoice_item"))
        if p.get("p_invoice_item"):
            item["stock_held"] = (item.get("stock_held") or 0) + (p.get("p_held") or 0)
            item["stock_sold"] = (item.get("stock_sold") or 0) + (p.get("p_sold") or 0)
            if p["p_kind"] == "deliver":
                item["stock_delivered"] = (item.get("stock_delivered") or 0) - out["change"]
            assert min(item["stock_held"], item["stock_sold"], item["stock_delivered"] if "stock_delivered" in item else 0) >= 0
        return type("R", (), {"execute": lambda s: type("X", (), {"data": out})()})()


@pytest.fixture(autouse=True)
def _no_side_effects():
    with patch("app.services.commerce_service.convert_lead_on_purchase"):
        yield


def _sdb(on=True, regions=True):
    db = SDB(**{k: v for k, v in _db(users=[{"id": USER, "org_id": ORG, "full_name": "Ada Owner"},
                                            {"id": REP, "org_id": ORG, "full_name": "Rita Rep"}]).tables.items()})
    org = next(o for o in db.rows("organisations") if o["id"] == ORG)
    if regions:
        org["sheet_sources"] = {"transactions": {"regions": [{"name": "Lagos Sales"}, {"name": "Abuja Sales"}]}}
    db.tables["products"] += [
        {"id": BED, "org_id": ORG, "title": "Hybrid Bed", "price": 500000, "is_active": True, "status": "active",
         "variants": [{"title": "Queen", "price": "400000", "inventory_quantity": 0},
                      {"title": "King", "price": "500000", "inventory_quantity": 0}]},
        {"id": PILLOW, "org_id": ORG, "title": "Pillow", "price": 15000, "is_active": True, "status": "active",
         "variants": [], "inventory_count": 0},
    ]
    main = stock.create_location(db, ORG, {"name": "Main store"})
    lagos = stock.create_location(db, ORG, {"name": "Lagos Store", "region": "Lagos Sales"})
    if on:
        stock.save_settings(db, ORG, USER, {"enabled": True})
        stock.receive(db, ORG, USER, {"location_id": main["id"], "lines": [
            {"product_id": BED, "variant": "Queen", "quantity": 5}, {"product_id": PILLOW, "quantity": 10}]})
        stock.receive(db, ORG, USER, {"location_id": lagos["id"], "lines": [
            {"product_id": BED, "variant": "Queen", "quantity": 2}]})
    return db, main, lagos


def _draft(db, items=None, user=USER, **kw):
    body = {"doc_type": "invoice", "lead_id": LEAD, "region": kw.pop("region", "Abuja Sales"),
            "items": items or [{"product_id": BED, "variant": "Queen", "quantity": 2},
                               {"product_id": PILLOW, "quantity": 3}], **kw}
    return inv.create_draft(db, ORG, user, body)


def _lv(db, product, variant, loc):
    item = next(i for i in db.rows("stock_items") if i["product_id"] == product and i["variant"] == variant)
    return next(x for x in db.rows("stock_levels") if x["item_id"] == item["id"] and x["location_id"] == loc["id"])


def _avail(db, product, variant, loc):
    lv = _lv(db, product, variant, loc)
    return lv["on_hand"] - lv["held"] - lv["sold_pending"]


def _lines(db, doc_id):
    return {(i.get("variant") or ""): i for i in db.rows("invoice_items") if i["invoice_id"] == doc_id}


def _pay(db, d, amount):
    return pay.record_payment(db, ORG, USER, d["id"], {"amount": amount, "method": "cash"})


# ───────────────────────────── issue ─────────────────────────────

def test_stock_off_issue_holds_nothing():
    db, main, _ = _sdb(on=False)
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    assert d["status"] == "issued" and not d.get("stock_tracked") and db.rows("stock_moves") == []


def test_issue_holds_at_main_when_region_has_no_location():
    db, main, _ = _sdb()
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    assert d["stock_tracked"] is True and d["location_id"] == main["id"] and d["location_name"] == "Main store"
    assert _lv(db, BED, "Queen", main)["held"] == 2 and _avail(db, BED, "Queen", main) == 3
    assert _avail(db, PILLOW, "", main) == 7
    assert _lines(db, d["id"])["Queen"]["stock_held"] == 2
    assert {m["kind"] for m in db.rows("stock_moves") if m.get("invoice_id") == d["id"]} == {"hold"}


def test_issue_uses_location_of_the_region_or_the_chosen_one():
    db, main, lagos = _sdb()
    d = inv.issue(db, ORG, USER, _draft(db, region="Lagos Sales", items=[{"product_id": BED, "variant": "Queen", "quantity": 1}])["id"])
    assert d["location_id"] == lagos["id"] and _avail(db, BED, "Queen", lagos) == 1
    d2 = inv.issue(db, ORG, USER, _draft(db, region="Lagos Sales", location_id=main["id"],
                                         items=[{"product_id": BED, "variant": "Queen", "quantity": 1}])["id"])
    assert d2["location_id"] == main["id"]


def test_issue_blocked_when_short_releases_earlier_lines_and_uses_no_number():
    db, main, _ = _sdb()
    draft = _draft(db, items=[{"product_id": PILLOW, "quantity": 4}, {"product_id": BED, "variant": "Queen", "quantity": 6}])
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, draft["id"])
    assert e.value.code == "STOCK_SHORT" and e.value.message.endswith("at Main store.") and "Only 5" in e.value.message
    assert _avail(db, PILLOW, "", main) == 10 and _lv(db, PILLOW, "", main)["held"] == 0
    doc = inv.get_doc(db, ORG, draft["id"])
    assert doc["status"] == "draft" and not doc["stock_tracked"] and not doc.get("number")
    assert db.counters == {}                                                  # no invoice number used
    assert all(i.get("stock_held", 0) == 0 for i in db.rows("invoice_items"))


def test_issue_refuses_part_units_and_ignores_typed_lines():
    db, main, _ = _sdb()
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, _draft(db, items=[{"product_id": PILLOW, "quantity": "1.5"}])["id"])
    assert "whole units" in e.value.message
    d = inv.issue(db, ORG, USER, _draft(db, items=[{"description": "Delivery fee", "quantity": 1, "unit_price": 5000}])["id"])
    assert d["status"] == "issued" and not d.get("stock_tracked")


def test_quotes_never_hold_and_convert_keeps_location():
    db, main, lagos = _sdb()
    q = inv.issue(db, ORG, USER, _draft(db, doc_type="quote", location_id=lagos["id"])["id"])
    assert not q.get("stock_tracked") and _lv(db, BED, "Queen", main)["held"] == 0
    d = inv.convert_quote(db, ORG, USER, q["id"])
    assert d["status"] == "draft" and d["location_id"] == lagos["id"]


def test_draft_location_must_be_the_business_and_on():
    db, main, lagos = _sdb()
    other = {"id": "aaaaaaaa-9999-9999-9999-999999999999", "org_id": OTHER, "name": "Theirs", "is_active": True}
    db.tables["stock_locations"].append(other)
    with pytest.raises(inv.InvoiceError) as e:
        _draft(db, location_id=other["id"])
    assert e.value.field == "location_id"
    d = _draft(db, location_id=main["id"])
    assert inv.update_draft(db, ORG, USER, d["id"], {"location_id": None})["location_id"] is None


def test_issue_failure_after_holding_gives_stock_back():
    db, main, _ = _sdb()
    d = _draft(db)
    with patch.object(inv, "_issue_numbered", side_effect=inv.InvoiceError("INVALID_TRANSITION", "x", 409)):
        with pytest.raises(inv.InvoiceError):
            inv.issue(db, ORG, USER, d["id"])
    assert _lv(db, BED, "Queen", main)["held"] == 0 and _lv(db, PILLOW, "", main)["held"] == 0
    assert not inv.get_doc(db, ORG, d["id"])["stock_tracked"]


# ───────────────────────────── payments, void ─────────────────────────────

def test_paid_moves_to_deliver_receipt_void_moves_back_and_void_releases():
    db, main, _ = _sdb()
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    total = d["total"]
    _pay(db, d, 1000)                                                         # part paid: still held
    assert _lv(db, BED, "Queen", main)["held"] == 2 and _lv(db, BED, "Queen", main)["sold_pending"] == 0
    r = _pay(db, d, total - 1000)
    assert r["invoice"]["status"] == "paid"
    lv = _lv(db, BED, "Queen", main)
    assert (lv["held"], lv["sold_pending"], lv["on_hand"]) == (0, 2, 5) and _avail(db, BED, "Queen", main) == 3
    assert _lines(db, d["id"])["Queen"]["stock_sold"] == 2
    pay.void_receipt(db, ORG, USER, r["receipt"]["id"], "wrong amount")      # back to part paid
    lv = _lv(db, BED, "Queen", main)
    assert (lv["held"], lv["sold_pending"]) == (2, 0)
    first = next(x for x in db.rows("receipts") if not x.get("voided_at"))
    pay.void_receipt(db, ORG, USER, first["id"], "cancelled order")
    inv.void(db, ORG, USER, d["id"], "customer cancelled")
    assert _avail(db, BED, "Queen", main) == 5 and _avail(db, PILLOW, "", main) == 10
    assert [m["kind"] for m in db.rows("stock_moves") if m.get("invoice_id") == d["id"]][-1] == "release"


# ───────────────────────────── delivery ─────────────────────────────

def test_deliver_rules_part_delivery_and_numbers():
    db, main, _ = _sdb()
    d = inv.issue(db, ORG, REP, _draft(db, user=REP)["id"])
    items = _lines(db, d["id"])
    q_line = {"item_id": items["Queen"]["id"], "quantity": 1}
    with pytest.raises(inv.InvoiceError) as e:                                 # not paid yet
        inv_stock.deliver(db, OWNER, d["id"], [q_line])
    assert "fully paid" in e.value.message
    _pay(db, d, d["total"])
    other_rep = {"id": "99999999-0000-0000-0000-000000000002", "org_id": ORG, "roles": {"template": "sales_agent"}}
    with pytest.raises(inv.InvoiceError) as e:
        inv_stock.deliver(db, other_rep, d["id"], [q_line])
    assert e.value.status == 403
    maker = {"id": REP, "org_id": ORG, "roles": {"template": "sales_agent"}}
    with pytest.raises(inv.InvoiceError) as e:
        inv_stock.deliver(db, maker, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 3}])
    assert "Only 2" in e.value.message
    out = inv_stock.deliver(db, maker, d["id"], [q_line], note="Driver Musa")
    assert out["status"] == "paid"
    lv = _lv(db, BED, "Queen", main)
    assert (lv["on_hand"], lv["sold_pending"], _avail(db, BED, "Queen", main)) == (4, 1, 3)
    line = _lines(db, d["id"])["Queen"]
    assert (line["stock_sold"], line["stock_delivered"]) == (1, 1)
    assert db.rows("stock_moves")[-1]["reason"].startswith("Delivered: Driver Musa")
    inv_stock.deliver(db, OWNER, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 1},
                                           {"item_id": items[""]["id"], "quantity": 3}])
    assert inv_stock.to_deliver_list(db, ORG) == []
    with pytest.raises(inv.InvoiceError):
        inv_stock.deliver(db, OWNER, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 1}])   # nothing left


def test_receipt_void_after_part_delivery_holds_only_what_is_left():
    db, main, _ = _sdb()
    d = inv.issue(db, ORG, USER, _draft(db, items=[{"product_id": BED, "variant": "Queen", "quantity": 2}])["id"])
    r = _pay(db, d, d["total"])
    item = _lines(db, d["id"])["Queen"]
    inv_stock.deliver(db, OWNER, d["id"], [{"item_id": item["id"], "quantity": 1}])
    pay.void_receipt(db, ORG, USER, r["receipt"]["id"], "bounced transfer")
    lv = _lv(db, BED, "Queen", main)
    assert (lv["on_hand"], lv["held"], lv["sold_pending"]) == (4, 1, 0)
    inv.void(db, ORG, USER, d["id"], "customer gone")
    assert (_lv(db, BED, "Queen", main)["held"], _avail(db, BED, "Queen", main)) == (0, 4)   # delivered one stays out


# ───────────────────────────── retry, lists, availability ─────────────────────────────

def test_failed_sync_is_put_right_by_the_daily_worker():
    db, main, _ = _sdb()
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    db.fail_next = 1
    _pay(db, d, d["total"])                                                   # paid, but the stock call failed
    assert _lv(db, BED, "Queen", main)["sold_pending"] == 0
    assert inv_stock.retry(db, dry_run=True) == {"checked": 1, "fixed": 1, "failed": 0}
    assert _lv(db, BED, "Queen", main)["sold_pending"] == 0                    # dry run writes nothing
    out = fu.run(db, dry_run=False)
    assert (out["stock_checked"], out["stock_fixed"]) == (1, 1)
    lv = _lv(db, BED, "Queen", main)
    assert (lv["held"], lv["sold_pending"]) == (0, 2)
    assert inv_stock.retry(db)["fixed"] == 0                                  # nothing more to do
    assert inv_stock.sync(db, ORG, d["id"])["changed"] == 0


def test_lists_and_availability():
    db, main, lagos = _sdb()
    a = inv.issue(db, ORG, USER, _draft(db)["id"])
    b = inv.issue(db, ORG, REP, _draft(db, user=REP, region="Lagos Sales",
                                       items=[{"product_id": BED, "variant": "Queen", "quantity": 1}])["id"])
    _pay(db, b, b["total"])
    held = inv_stock.held_list(db, ORG)
    assert [h["number"] for h in held] == [a["number"]] and held[0]["units"] == 5 and held[0]["location"] == "Main store"
    todo = inv_stock.to_deliver_list(db, ORG)
    assert [t["number"] for t in todo] == [b["number"]] and todo[0]["rep_name"] == "Rita Rep" and todo[0]["balance"] == 0
    assert inv_stock.to_deliver_list(db, ORG, location_id=main["id"]) == []
    av = inv_stock.availability(db, ORG, main["id"], [BED, PILLOW])
    assert av[BED] == {"Queen": 3} and av[PILLOW] == {"": 7}
    assert inv_stock.availability(db, ORG, lagos["id"], [BED])[BED] == {"Queen": 1}
    h = stock.history(db, ORG, product_id=PILLOW)
    assert h["items"][0]["invoice_number"] == a["number"]


# ───────────────────────────── routes ─────────────────────────────

def _client(db, user):
    from app.database import get_supabase
    from app.dependencies import get_current_org
    from app.routers import inventory as r_inv
    from app.routers import invoices as r_invoices
    app = FastAPI()
    app.include_router(r_invoices.router, prefix="/api/v1")
    app.include_router(r_inv.router, prefix="/api/v1")
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: user
    return TestClient(app)


def test_routes_deliver_flag_lists_availability():
    db, main, _ = _sdb()
    c = _client(db, OWNER)
    d = c.post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD, "region": "Abuja Sales",
                                         "location_id": main["id"],
                                         "items": [{"product_id": BED, "variant": "Queen", "quantity": 1}]}).json()["data"]
    assert d["location_id"] == main["id"]
    d = c.post(f"/api/v1/invoices/{d['id']}/issue").json()["data"]
    _pay(db, d, d["total"])
    got = c.get(f"/api/v1/invoices/{d['id']}").json()["data"]
    assert got["can_deliver"] is True and got["items"][0]["stock_sold"] == 1
    r = c.post(f"/api/v1/invoices/{d['id']}/deliver", json={"lines": [{"item_id": got["items"][0]["id"], "quantity": 1}]})
    assert r.status_code == 200 and r.json()["data"]["items"][0]["stock_delivered"] == 1
    assert c.post(f"/api/v1/invoices/{d['id']}/deliver", json={"lines": []}).status_code == 422
    staff = _client(db, {"id": "99999999-0000-0000-0000-000000000003", "org_id": ORG, "roles": {"template": "sales_agent"}})
    assert staff.get(f"/api/v1/invoices/{d['id']}").json()["data"]["can_deliver"] is False
    assert c.get("/api/v1/inventory/locations").json()["data"]["enabled"] is True
    assert c.get("/api/v1/inventory/held").json()["data"]["items"] == []
    av = c.get(f"/api/v1/inventory/availability?location_id={main['id']}&product_ids={BED},nonsense").json()["data"]
    assert av["products"][BED]["Queen"] == 4
    short = c.post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD, "region": "Abuja Sales",
                                             "items": [{"product_id": BED, "variant": "Queen", "quantity": 50}]}).json()["data"]
    r = c.post(f"/api/v1/invoices/{short['id']}/issue")
    assert r.status_code == 422 and r.json()["error"]["code"] == "STOCK_SHORT"
