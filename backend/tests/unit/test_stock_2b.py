"""STOCK-2b: selling from another location (e.g. the warehouse when the showroom is short) with an admin's approval."""
from __future__ import annotations

import pytest

from tests.unit.test_invoices_1 import LEAD, ORG, USER, _plan_allows  # noqa: F401  (autouse fixture)
from tests.unit.test_stock_2 import (  # noqa: F401  (_no_side_effects is an autouse fixture)
    BED, OWNER, PILLOW, REP, _avail, _client, _lines, _lv, _no_side_effects, _pay, _sdb,
)
from app.services import invoice_service as inv
from app.services import invoice_stock_service as inv_stock

RITA = {"id": REP, "org_id": ORG, "roles": {"template": "sales_agent"}}
OPS = {"id": "99999999-0000-0000-0000-000000000009", "org_id": ORG, "roles": {"template": "ops_manager"}}


def _setup():
    """Main store has 5 Queen beds, Lagos Store 2; Rita sells 4 from Lagos (short by 2)."""
    db, main, lagos = _sdb()
    db.tables["users"][0]["roles"] = {"template": "owner"}
    db.tables["users"][1]["roles"] = {"template": "sales_agent"}
    db.tables.setdefault("notifications", [])
    d = inv.create_draft(db, ORG, REP, {"doc_type": "invoice", "lead_id": LEAD, "region": "Lagos Sales",
                                         "items": [{"product_id": BED, "variant": "Queen", "quantity": 4},
                                                   {"product_id": PILLOW, "quantity": 1}]})
    return db, main, lagos, d


def _bed(db, d):
    return _lines(db, d["id"])["Queen"]


def test_short_at_showroom_check_shows_the_warehouse():
    db, main, lagos, d = _setup()
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, REP, d["id"])
    assert e.value.code == "STOCK_SHORT" and "at Lagos Store" in e.value.message
    chk = inv_stock.stock_check(db, RITA, d["id"])
    assert chk["location"]["name"] == "Lagos Store" and chk["short"] and chk["can_approve"] is False
    bed = next(l for l in chk["lines"] if l["variant"] == "Queen")
    assert (bed["needed"], bed["available_here"], bed["short"]) == (4, 2, True)
    assert bed["others"] == [{"location_id": main["id"], "name": "Main store", "available": 5}]
    pillow = next(l for l in chk["lines"] if l["variant"] == "")
    assert pillow["available_here"] == 0 and pillow["others"][0]["available"] == 10


def test_rep_cannot_take_from_elsewhere_directly():
    db, main, lagos, d = _setup()
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, REP, d["id"], sources={_bed(db, d)["id"]: main["id"]}, allow_other=False)
    assert e.value.code == "STOCK_APPROVAL_NEEDED" and e.value.status == 403
    assert _lv(db, BED, "Queen", main)["held"] == 0 and not db.counters


def test_manager_issues_straight_from_the_warehouse():
    db, main, lagos, d = _setup()
    srcs = {_bed(db, d)["id"]: main["id"], _lines(db, d["id"])[""]["id"]: main["id"]}
    out = inv.issue(db, ORG, USER, d["id"], sources=srcs, allow_other=True)
    assert out["status"] == "issued" and out["location_id"] == lagos["id"]
    assert _lv(db, BED, "Queen", main)["held"] == 4 and _lv(db, BED, "Queen", lagos)["held"] == 0
    bed = next(i for i in out["items"] if i.get("variant") == "Queen")
    assert bed["stock_location_name"] == "Main store"
    # paid -> to deliver at the warehouse; delivered from there
    _pay(db, out, out["total"])
    assert _lv(db, BED, "Queen", main)["sold_pending"] == 4
    inv_stock.deliver(db, OWNER, d["id"], [{"item_id": bed["id"], "quantity": 4}])
    assert _lv(db, BED, "Queen", main)["on_hand"] == 1 and _lv(db, BED, "Queen", lagos)["on_hand"] == 2


def test_request_holds_at_warehouse_then_approve_issues():
    db, main, lagos, d = _setup()
    srcs = {_bed(db, d)["id"]: main["id"], _lines(db, d["id"])[""]["id"]: main["id"]}
    out = inv_stock.request_approval(db, RITA, d["id"], srcs, note="Customer is waiting")
    assert out["status"] == "draft" and out["stock_approval"] == "pending" and not out.get("number")
    assert _lv(db, BED, "Queen", main)["held"] == 4 and _avail(db, BED, "Queen", main) == 1
    notes = db.rows("notifications")
    assert [n["user_id"] for n in notes] == [USER] and "Main store" in notes[0]["body"] and "Rita Rep" in notes[0]["body"]
    assert inv_stock.sync(db, ORG, d["id"])["changed"] == 0                     # a re-sync keeps the hold
    assert _lv(db, BED, "Queen", main)["held"] == 4
    with pytest.raises(inv.InvoiceError):                                       # locked while waiting
        inv.update_draft(db, ORG, REP, d["id"], {"notes": "x"})
    with pytest.raises(inv.InvoiceError):
        inv.issue(db, ORG, REP, d["id"])
    with pytest.raises(inv.InvoiceError) as e:
        inv_stock.approve(db, RITA, d["id"])
    assert e.value.status == 403
    lst = inv_stock.approvals_list(db, ORG)
    assert lst[0]["rep_name"] == "Rita Rep" and lst[0]["note"] == "Customer is waiting"
    assert {(x["from"], x["elsewhere"]) for x in lst[0]["lines"]} == {("Main store", True)}
    done = inv_stock.approve(db, OPS, d["id"])
    assert done["status"] == "issued" and done["number"] and done["stock_approval"] == "approved"
    assert _lv(db, BED, "Queen", main)["held"] == 4                              # still held, not held twice
    assert inv_stock.approvals_list(db, ORG) == []
    assert db.rows("notifications")[-1]["user_id"] == REP
    with pytest.raises(inv.InvoiceError):
        inv_stock.approve(db, OPS, d["id"])                                      # already decided


def test_reject_and_cancel_release_and_unlock():
    db, main, lagos, d = _setup()
    srcs = {_bed(db, d)["id"]: main["id"], _lines(db, d["id"])[""]["id"]: main["id"]}
    inv_stock.request_approval(db, RITA, d["id"], srcs)
    out = inv_stock.reject(db, OWNER, d["id"], "Warehouse stock is promised to a dealer")
    assert out["stock_approval"] == "rejected" and out["status"] == "draft" and not out["stock_tracked"]
    assert _lv(db, BED, "Queen", main)["held"] == 0 and _lv(db, PILLOW, "", main)["held"] == 0
    assert "promised" in db.rows("notifications")[-1]["body"]
    inv.update_draft(db, ORG, REP, d["id"], {"items": [{"product_id": BED, "variant": "Queen", "quantity": 2}]})
    inv_stock.request_approval(db, RITA, d["id"], {_bed(db, d)["id"]: main["id"]})
    other = {"id": "99999999-0000-0000-0000-000000000005", "org_id": ORG, "roles": {"template": "sales_agent"}}
    with pytest.raises(inv.InvoiceError) as e:
        inv_stock.cancel_request(db, other, d["id"])
    assert e.value.status == 403
    out = inv_stock.cancel_request(db, RITA, d["id"])
    assert out["stock_approval"] is None and _lv(db, BED, "Queen", main)["held"] == 0
    issued = inv.issue(db, ORG, REP, d["id"])                                   # 2 at Lagos is enough now
    assert issued["status"] == "issued" and _lv(db, BED, "Queen", lagos)["held"] == 2
    assert _bed(db, d).get("stock_location_id") is None                         # line back on the invoice's location


def test_request_rules():
    db, main, lagos, d = _setup()
    with pytest.raises(inv.InvoiceError):                                       # same location = nothing to approve
        inv_stock.request_approval(db, RITA, d["id"], {_bed(db, d)["id"]: lagos["id"]})
    with pytest.raises(inv.InvoiceError):                                       # line from another invoice
        inv_stock.request_approval(db, RITA, d["id"], {"aaaaaaaa-0000-0000-0000-000000000000": main["id"]})
    with pytest.raises(inv.InvoiceError) as e:                                  # warehouse short too
        inv_stock.request_approval(db, RITA, d["id"], {_lines(db, d["id"])[""]["id"]: lagos["id"],
                                                       _bed(db, d)["id"]: main["id"]})
    assert e.value.code in ("STOCK_SHORT", "VALIDATION_ERROR")
    assert _lv(db, BED, "Queen", main)["held"] == 0
    assert inv.get_doc(db, ORG, d["id"]).get("stock_approval") is None


def test_location_lists_count_only_their_own_lines():
    db, main, lagos, d = _setup()
    inv.update_draft(db, ORG, REP, d["id"], {"items": [{"product_id": BED, "variant": "Queen", "quantity": 4},
                                                        {"product_id": BED, "variant": "Queen", "quantity": 1}]})
    lines = sorted(db.rows("invoice_items"), key=lambda i: i.get("position") or 0)
    lines = [i for i in lines if i["invoice_id"] == d["id"]]
    inv.issue(db, ORG, USER, d["id"], sources={lines[0]["id"]: main["id"]}, allow_other=True)
    at_lagos = inv_stock.held_list(db, ORG, location_id=lagos["id"])
    at_main = inv_stock.held_list(db, ORG, location_id=main["id"])
    assert at_lagos[0]["units"] == 1 and at_main[0]["units"] == 4
    assert "(from Main store)" in inv_stock.held_list(db, ORG)[0]["lines"][0]["description"]


def test_routes():
    db, main, lagos, d = _setup()
    rep = _client(db, RITA)
    bed_id = _bed(db, d)["id"]
    r = rep.post(f"/api/v1/invoices/{d['id']}/issue", json={"sources": {bed_id: main["id"]}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "STOCK_APPROVAL_NEEDED"
    chk = rep.get(f"/api/v1/invoices/{d['id']}/stock-check").json()["data"]
    assert chk["short"] is True
    pill = _lines(db, d["id"])[""]["id"]
    r = rep.post(f"/api/v1/invoices/{d['id']}/stock-request", json={"sources": {bed_id: main["id"], pill: main["id"]}})
    assert r.status_code == 200 and r.json()["data"]["stock_approval"] == "pending"
    got = rep.get(f"/api/v1/invoices/{d['id']}").json()["data"]
    assert got["can_approve_stock"] is False and got["can_cancel_stock"] is True
    assert rep.get("/api/v1/inventory/approvals").status_code == 403
    boss = _client(db, OWNER)
    assert len(boss.get("/api/v1/inventory/approvals").json()["data"]["items"]) == 1
    assert boss.get(f"/api/v1/invoices/{d['id']}").json()["data"]["can_approve_stock"] is True
    r = boss.post(f"/api/v1/invoices/{d['id']}/stock-approve")
    assert r.status_code == 200 and r.json()["data"]["status"] == "issued"
    d2 = inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "lead_id": LEAD, "region": "Lagos Sales",
                                          "items": [{"product_id": BED, "variant": "Queen", "quantity": 1}]})
    b2 = _lines(db, d2["id"])["Queen"]["id"]
    r = boss.post(f"/api/v1/invoices/{d2['id']}/issue", json={"sources": {b2: main["id"]}})
    assert r.status_code == 200 and _lv(db, BED, "Queen", main)["held"] == 5
    assert boss.post(f"/api/v1/invoices/{d2['id']}/stock-reject", json={}).status_code == 400
