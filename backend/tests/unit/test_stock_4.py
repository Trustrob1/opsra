"""STOCK-4: nothing leaves a warehouse without the owner's approval; the Inventory Manager role; movement records."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tests.unit.test_invoices_1 import LEAD, ORG, USER, _plan_allows  # noqa: F401  (autouse fixture)
from tests.unit.test_stock_2 import (  # noqa: F401  (_no_side_effects is an autouse fixture)
    BED, OWNER, PILLOW, REP, _avail, _client, _draft, _lines, _lv, _no_side_effects, _pay, _sdb,
)
from app.dependencies import inventory_only_blocked
from app.services import inventory_service as stock
from app.services import invoice_service as inv
from app.services import invoice_stock_service as inv_stock
from app.services import payment_approval_service as approvals
from app.services import stock_request_service as req

IM_ID = "99999999-0000-0000-0000-000000000003"
IM = {"id": IM_ID, "org_id": ORG, "full_name": "Ike Stock", "roles": {"template": "inventory_manager"}}
OPS = {"id": "99999999-0000-0000-0000-000000000004", "org_id": ORG, "roles": {"template": "ops_manager"}}
RITA = {"id": REP, "org_id": ORG, "roles": {"template": "sales_agent"}}


def _setup():
    """Main store is a WAREHOUSE (Queen bed 5, pillow 10); Lagos Store is a showroom (Queen bed 2)."""
    db, main, lagos = _sdb()
    db.tables["users"][0]["roles"] = {"template": "owner"}
    db.tables["users"][1]["roles"] = {"template": "sales_agent"}
    db.tables["users"].append({"id": IM_ID, "org_id": ORG, "full_name": "Ike Stock", "roles": {"template": "inventory_manager"}})
    for t in ("notifications", "stock_transfers", "stock_transfer_lines", "stock_move_requests", "payment_links"):
        db.tables.setdefault(t, [])
    stock.update_location(db, ORG, main["id"], {"kind": "warehouse"})
    main = stock._location(db, ORG, main["id"])
    return db, main, lagos


def _move_body(main, lagos, qty=2):
    return {"from_location_id": main["id"], "to_location_id": lagos["id"],
            "lines": [{"product_id": BED, "variant": "Queen", "quantity": qty}]}


def _notes(db, user_id):
    return [n for n in db.rows("notifications") if n["user_id"] == user_id]


# ───────────────────────────── roles and location type ─────────────────────────────

def test_roles_and_location_kind():
    assert stock.can_handle(IM) and stock.can_handle(OPS) and stock.can_handle(OWNER) and not stock.can_handle(RITA)
    assert stock.is_owner(OWNER) and not stock.is_owner(OPS) and not stock.is_owner(IM)
    assert not stock.is_manager(IM)                                   # settings and locations stay with managers
    db, main, lagos = _setup()
    assert main["kind"] == "warehouse" and lagos.get("kind", "showroom") == "showroom"
    new = stock.create_location(db, ORG, {"name": "Ikeja depot", "kind": "warehouse"})
    assert new["kind"] == "warehouse"
    with pytest.raises(stock.StockError):
        stock.create_location(db, ORG, {"name": "Bad", "kind": "garage"})


def test_inventory_manager_only_reaches_inventory_apis():
    im = {"roles": {"template": "inventory_manager"}}
    for path in ("/api/v1/inventory", "/api/v1/inventory/requests", "/api/v1/auth/me", "/api/v1/notifications",
                 "/api/v1/platform/status"):
        assert inventory_only_blocked(im, path) is False, path
    for path in ("/api/v1/leads", "/api/v1/invoices", "/api/v1/customers/1", "/api/v1/inventoryx", "/api/v1/admin/users"):
        assert inventory_only_blocked(im, path) is True, path
    assert inventory_only_blocked({"roles": {"template": "sales_agent"}}, "/api/v1/leads") is False
    assert inventory_only_blocked(im, None) is False


@pytest.mark.parametrize("path,blocked", [("/api/v1/leads", True), ("/api/v1/inventory/settings", False)])
def test_get_current_org_blocks_the_inventory_manager(path, blocked):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from app import dependencies as deps

    async def fake_load(current_user, supabase):
        return {"id": IM_ID, "org_id": ORG, "is_active": True, "roles": {"template": "inventory_manager"}}
    request = SimpleNamespace(url=SimpleNamespace(path=path))
    with patch.object(deps, "_load_current_org", fake_load):
        if blocked:
            with pytest.raises(HTTPException) as e:
                asyncio.run(deps.get_current_org(request=request, current_user=None, supabase=None))
            assert e.value.status_code == 403
        else:
            assert asyncio.run(deps.get_current_org(request=request, current_user=None, supabase=None))["id"] == IM_ID


# ───────────────────────────── moves out of a warehouse ─────────────────────────────

def test_move_from_warehouse_waits_for_owner_and_holds_the_goods():
    db, main, lagos = _setup()
    out = req.request_transfer(db, IM, _move_body(main, lagos))
    r = out["request"]
    assert "transfer" not in out and r["status"] == "pending" and r["units"] == 2
    lv = _lv(db, BED, "Queen", main)
    assert (lv["on_hand"], lv["held"]) == (5, 2) and _avail(db, BED, "Queen", main) == 3   # held, not deducted
    assert db.rows("stock_transfers") == []
    assert any("Stock move to approve" == n["title"] for n in _notes(db, USER))            # the owner is told
    with pytest.raises(stock.StockError) as e:                                            # not approved yet
        req.send_approved(db, IM, r["id"])
    assert "approved" in e.value.message
    with pytest.raises(stock.StockError) as e:                                            # only the owner decides
        req.decide(db, OPS, r["id"], True)
    assert e.value.status == 403
    v = req.decide(db, OWNER, r["id"], True, "ok")
    assert v["status"] == "approved" and v["decided_by"] == USER
    assert any(n["title"] == "Stock move approved" for n in _notes(db, IM_ID))
    sent = req.send_approved(db, IM, r["id"])
    assert sent["request"]["status"] == "done" and sent["request"]["transfer_id"] == sent["transfer"]["id"]
    lv = _lv(db, BED, "Queen", main)
    assert (lv["on_hand"], lv["held"]) == (3, 0) and _lv(db, BED, "Queen", lagos)["in_transit_in"] == 2
    with pytest.raises(stock.StockError):
        req.send_approved(db, IM, r["id"])                                                 # once only


def test_held_goods_cannot_be_sold_and_short_request_is_refused():
    db, main, lagos = _setup()
    req.request_transfer(db, IM, _move_body(main, lagos, 5))                                # all 5 queens held
    assert _avail(db, BED, "Queen", main) == 0
    with pytest.raises(stock.StockError) as e:
        req.request_transfer(db, IM, _move_body(main, lagos, 1))
    assert e.value.code == "STOCK_SHORT" and "Main store" in e.value.message
    assert len(db.rows("stock_move_requests")) == 1                                         # the failed one is gone
    with pytest.raises(inv.InvoiceError):                                                    # a sale can't take them
        inv.issue(db, ORG, USER, _draft(db, items=[{"product_id": BED, "variant": "Queen", "quantity": 1}],
                                         region=None)["id"])


def test_reject_and_cancel_release_the_hold():
    db, main, lagos = _setup()
    a = req.request_transfer(db, IM, _move_body(main, lagos))["request"]
    req.decide(db, OWNER, a["id"], False, "not now")
    assert _avail(db, BED, "Queen", main) == 5 and req.view(db, ORG, a["id"])["status"] == "rejected"
    with pytest.raises(stock.StockError):
        req.decide(db, OWNER, a["id"], True)
    b = req.request_transfer(db, IM, _move_body(main, lagos))["request"]
    with pytest.raises(stock.StockError) as e:
        req.cancel(db, RITA, b["id"])
    assert e.value.status == 403
    assert req.cancel(db, IM, b["id"])["status"] == "cancelled" and _avail(db, BED, "Queen", main) == 5


def test_owner_moves_at_once_and_showroom_moves_need_no_approval():
    db, main, lagos = _setup()
    out = req.request_transfer(db, OWNER, _move_body(main, lagos))
    assert out["transfer"]["status"] == "in_transit"
    rec = db.rows("stock_move_requests")[-1]
    assert rec["status"] == "done" and rec["decided_by"] == USER and rec["transfer_id"] == out["transfer"]["id"]
    out = req.request_transfer(db, IM, _move_body(lagos, main, 1))                          # showroom -> warehouse
    assert "transfer" in out and len(db.rows("stock_move_requests")) == 1


# ───────────────────────────── deliveries from a warehouse ─────────────────────────────

def _paid(db, user=REP):
    d = inv.issue(db, ORG, user, _draft(db, user=user)["id"])
    _pay(db, d, d["total"])
    return d, _lines(db, d["id"])


def test_delivery_from_warehouse_needs_approval_then_uses_it():
    db, main, _ = _setup()
    d, items = _paid(db)
    q = {"item_id": items["Queen"]["id"], "quantity": 2}
    with pytest.raises(inv.InvoiceError) as e:
        inv_stock.deliver(db, IM, d["id"], [q])
    assert e.value.code == "NEEDS_APPROVAL" and "Main store" in e.value.message
    assert _lv(db, BED, "Queen", main)["on_hand"] == 5                                      # still on the count
    r = req.request_delivery(db, IM, d["id"], [q])["request"]
    assert r["status"] == "pending" and r["kind"] == "delivery"
    assert req.delivery_state(db, ORG, [d["id"]])[d["id"]] == {"pending": 2, "approved": 0}
    with pytest.raises(stock.StockError):                                                    # asked already
        req.request_delivery(db, IM, d["id"], [q])
    req.decide(db, OWNER, r["id"], True)
    with pytest.raises(inv.InvoiceError) as e:                                               # pillows weren't asked for
        inv_stock.deliver(db, IM, d["id"], [q, {"item_id": items[""]["id"], "quantity": 1}])
    assert e.value.code == "NEEDS_APPROVAL"
    inv_stock.deliver(db, IM, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 1}])
    assert req.view(db, ORG, r["id"])["status"] == "approved"                                # 1 of 2 used
    inv_stock.deliver(db, IM, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 1}])
    done = req.view(db, ORG, r["id"])
    assert done["status"] == "done" and done["done_by"] == IM_ID
    assert _lv(db, BED, "Queen", main)["on_hand"] == 3


def test_owner_delivers_at_once_and_is_recorded():
    db, main, _ = _setup()
    d, items = _paid(db)
    inv_stock.deliver(db, OWNER, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 2}])
    rec = db.rows("stock_move_requests")[-1]
    assert rec["kind"] == "delivery" and rec["status"] == "done" and rec["decided_by"] == USER


def test_showroom_walk_in_delivers_at_once():
    db, main, lagos = _setup()
    stock.update_location(db, ORG, main["id"], {"kind": "showroom"})
    d, items = _paid(db)
    inv_stock.deliver(db, RITA, d["id"], [{"item_id": items["Queen"]["id"], "quantity": 2}])
    assert db.rows("stock_move_requests") == []


def test_taken_away_sale_from_warehouse_asks_the_owner_instead():
    db, main, _ = _setup()
    d, _items = _paid(db)
    assert approvals.deliver_all(db, {"org_id": ORG, "id": REP, "roles": {}}, d["id"]) is False
    r = db.rows("stock_move_requests")[-1]
    assert r["kind"] == "delivery" and r["status"] == "pending" and r["units"] == 5          # 2 queens + 3 pillows
    assert _lv(db, BED, "Queen", main)["sold_pending"] == 2


# ───────────────────────────── routes and records ─────────────────────────────

def test_routes_request_approve_send_and_records():
    db, main, lagos = _setup()
    im, owner, rep = _client(db, IM), _client(db, OWNER), _client(db, RITA)
    got = im.get("/api/v1/inventory").json()["data"]
    assert got["can_manage"] is True and got["can_settings"] is False and got["is_owner"] is False
    assert im.put("/api/v1/inventory/settings", json={"low_stock_alerts": False}).status_code == 403
    assert rep.post("/api/v1/inventory/transfers", json=_move_body(main, lagos)).status_code == 403
    r = im.post("/api/v1/inventory/transfers", json=_move_body(main, lagos)).json()["data"]["request"]
    assert owner.get("/api/v1/inventory").json()["data"]["requests"] == {"pending": 1, "approved": 0}
    assert im.post(f"/api/v1/inventory/requests/{r['id']}/approve", json={}).status_code == 403
    assert owner.post(f"/api/v1/inventory/requests/{r['id']}/approve", json={"note": "go"}).json()["data"]["status"] == "approved"
    assert rep.post(f"/api/v1/inventory/requests/{r['id']}/send").status_code == 403
    sent = im.post(f"/api/v1/inventory/requests/{r['id']}/send").json()["data"]
    assert sent["transfer"]["from_name"] == "Main store"
    lst = owner.get("/api/v1/inventory/requests?status=done").json()["data"]["requests"]
    assert [x["id"] for x in lst] == [r["id"]] and lst[0]["requested_by_name"] == "Ike Stock"
    rec = im.get("/api/v1/inventory/records?period=week").json()["data"]
    assert rec["summary"] == {"moves": 1, "deliveries": 0, "units": 2} and rec["records"][0]["decided_by_name"] == "Ada Owner"
    assert rep.get("/api/v1/inventory/records").status_code == 403
    bad = owner.get("/api/v1/inventory/records?period=custom&start=2026-11-10&end=2026-11-01")
    assert bad.status_code == 422
    # delivery from the Inventory page
    d, items = _paid(db)
    todo = im.get("/api/v1/inventory/to-deliver").json()["data"]
    row = next(x for x in todo["items"] if x["id"] == d["id"])
    assert row["warehouse_units"] == 5 and row["approval"] == {"pending": 0, "approved": 0} and todo["can_deliver"] is True
    q = [{"item_id": items["Queen"]["id"], "quantity": 2}]
    assert im.post(f"/api/v1/inventory/deliveries/{d['id']}", json={"lines": q}).status_code == 403   # needs approval
    a = im.post(f"/api/v1/inventory/deliveries/{d['id']}/request", json={"lines": q}).json()["data"]["request"]
    owner.post(f"/api/v1/inventory/requests/{a['id']}/approve", json={})
    out = im.post(f"/api/v1/inventory/deliveries/{d['id']}", json={"lines": q})
    assert out.status_code == 200 and _lv(db, BED, "Queen", main)["sold_pending"] == 0


def test_period_presets():
    today = date(2026, 11, 26)                                      # a Thursday
    assert req.period("week", None, None, today) == (date(2026, 11, 23), today)
    assert req.period("month", None, None, today) == (date(2026, 11, 1), today)
    assert req.period("custom", date(2026, 1, 1), date(2026, 1, 31), today) == (date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(stock.StockError):
        req.period("custom", None, date(2026, 1, 31), today)
    with pytest.raises(stock.StockError):
        req.period("custom", date(2025, 1, 1), date(2026, 6, 1), today)
