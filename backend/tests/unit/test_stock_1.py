"""STOCK-1: inventory - switch + one-time import, locations, receive, adjust, item settings, overview, history, routes,
Shopify sync guard. The Postgres function stock_apply is mirrored here by StockDB.rpc (same buckets, same checks,
same error texts); the real SQL is tested separately against Postgres (see the STOCK-1 session log)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import inventory_service as stock
from tests.funnel_fake_db import FakeDB

ORG = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
P_SIZED = "66666666-6666-6666-6666-666666666666"
P_PLAIN = "77777777-7777-7777-7777-777777777777"
P_OLD = "88888888-8888-8888-8888-888888888888"
P_THEIRS = "99999999-9999-9999-9999-999999999999"


class StockDB(FakeDB):
    """FakeDB + a Python copy of stock_apply()."""

    def rpc(self, fn, p):
        assert fn == "stock_apply"
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self._apply(p)))

    def _apply(self, p):
        loc = [l for l in self.rows("stock_locations") if l["id"] == p["p_location"] and l["org_id"] == p["p_org"]
               and l.get("is_active", True)]
        if not loc:
            raise Exception("STOCK_BAD_LOCATION")
        if not [r for r in self.rows("products") if r["id"] == p["p_product"] and r["org_id"] == p["p_org"]]:
            raise Exception("STOCK_BAD_PRODUCT")
        variant = (p["p_variant"] or "").strip()
        items = self.tables.setdefault("stock_items", [])
        item = next((i for i in items if i["org_id"] == p["p_org"] and i["product_id"] == p["p_product"]
                     and i["variant"] == variant), None)
        if not item:
            item = {"id": str(uuid.uuid4()), "org_id": p["p_org"], "product_id": p["p_product"], "variant": variant,
                    "sku": p.get("p_sku"), "cost_price": None, "reorder_level": None}
            items.append(item)
        levels = self.tables.setdefault("stock_levels", [])
        lv = next((x for x in levels if x["item_id"] == item["id"] and x["location_id"] == p["p_location"]), None)
        if not lv:
            lv = {"id": str(uuid.uuid4()), "org_id": p["p_org"], "item_id": item["id"], "location_id": p["p_location"],
                  "on_hand": 0, "held": 0, "sold_pending": 0, "in_transit_in": 0}
            levels.append(lv)
        d_on = (p["p_set_on_hand"] - lv["on_hand"]) if p.get("p_set_on_hand") is not None else (p.get("p_on_hand") or 0)
        on, held = lv["on_hand"] + d_on, lv["held"] + (p.get("p_held") or 0)
        sold, tr = lv["sold_pending"] + (p.get("p_sold") or 0), lv["in_transit_in"] + (p.get("p_transit") or 0)
        avail_before = lv["on_hand"] - lv["held"] - lv["sold_pending"]
        if on < 0:
            raise Exception(f"STOCK_NEGATIVE|on_hand|{avail_before}")
        if held < 0 or sold < 0 or tr < 0:
            raise Exception("STOCK_NEGATIVE|held|0")
        if held + sold > on:
            raise Exception(f"STOCK_SHORT|{avail_before}")
        lv.update(on_hand=on, held=held, sold_pending=sold, in_transit_in=tr)
        if p.get("p_unit_cost") is not None:
            item["cost_price"] = p["p_unit_cost"]
        if p.get("p_sku"):
            item["sku"] = p["p_sku"]
        move = {"id": str(uuid.uuid4()), "org_id": p["p_org"], "item_id": item["id"], "location_id": p["p_location"],
                "kind": p["p_kind"], "d_on_hand": d_on, "d_held": p.get("p_held") or 0, "d_sold": p.get("p_sold") or 0,
                "on_hand_after": on, "held_after": held, "sold_after": sold, "transit_after": tr,
                "reason": p.get("p_reason"), "ref": p.get("p_ref"), "created_by": p.get("p_user"),
                "created_at": f"2026-11-25T10:{len(self.rows('stock_moves')):02d}:00+00:00"}
        self.tables.setdefault("stock_moves", []).append(move)
        return {"item_id": item["id"], "location_id": p["p_location"], "on_hand": on, "held": held, "sold_pending": sold,
                "in_transit_in": tr, "available": on - held - sold, "change": d_on, "move_id": move["id"]}


def _variants(*pairs):
    return [{"title": t, "price": "100", "sku": f"SKU-{i}", "inventory_quantity": q} for i, (t, q) in enumerate(pairs)]


def _db(regions=("Lagos Sales", "Abuja Sales"), **extra):
    return StockDB(
        organisations=[{"id": ORG, "name": "Royal Rest", "sheet_sources": {"transactions": {"regions": [
            {"name": r, "gid": str(i)} for i, r in enumerate(regions)]}}}, {"id": OTHER, "name": "Other"}],
        users=[{"id": USER, "org_id": ORG, "full_name": "Ada Manager", "email": "ada@x.com"}],
        products=[
            {"id": P_SIZED, "org_id": ORG, "title": "Hybrid Mattress", "is_active": True, "status": "active",
             "inventory_count": 30, "variants": _variants(("Queen: 5/6 ft.", 10), ("Double: 4.5/6 ft.", 0), ("King", -3))},
            {"id": P_PLAIN, "org_id": ORG, "title": "Pillow", "is_active": True, "status": "active",
             "inventory_count": 7, "variants": [{"title": "Default Title", "inventory_quantity": 99, "sku": "PIL"}]},
            {"id": P_OLD, "org_id": ORG, "title": "Old Bed", "is_active": False, "status": "archived",
             "inventory_count": 5, "variants": []},
            {"id": P_THEIRS, "org_id": OTHER, "title": "Theirs", "is_active": True, "variants": []},
        ],
        **extra,
    )


def _on(db):
    return stock.save_settings(db, ORG, USER, {"enabled": True})


def _loc(db, name="Main store"):
    return next(l for l in stock.list_locations(db, ORG) if l["name"] == name)


def _level(db, product_id, variant, loc_id):
    item = next(i for i in db.rows("stock_items") if i["product_id"] == product_id and i["variant"] == variant)
    return next(x for x in db.rows("stock_levels") if x["item_id"] == item["id"] and x["location_id"] == loc_id)


# ───────────────────────────── switch + import ─────────────────────────────

def test_off_by_default_and_writes_refused_while_off():
    db = _db()
    assert stock.get_settings(db, ORG)["enabled"] is False and stock.stock_on(db, ORG) is False
    loc = stock.create_location(db, ORG, {"name": "Lagos Store"})
    with pytest.raises(stock.StockError) as e:
        stock.receive(db, ORG, USER, {"location_id": loc["id"], "lines": [{"product_id": P_PLAIN, "quantity": 1}]})
    assert e.value.code == "STOCK_OFF"


def test_turning_on_makes_main_store_and_copies_numbers_once():
    db = _db()
    out = _on(db)
    main = _loc(db)
    assert main["is_default"] and out["enabled"] and out["imported_at"]
    assert out["import"] == {"products": 2, "lines": 2, "units": 17}    # Queen 10 + Pillow 7; 0 / -3 / archived skipped
    assert _level(db, P_SIZED, "Queen: 5/6 ft.", main["id"])["on_hand"] == 10
    assert _level(db, P_PLAIN, "", main["id"])["on_hand"] == 7          # inventory_count wins for a product with no sizes
    assert {m["kind"] for m in db.rows("stock_moves")} == {"import"}
    assert next(i for i in db.rows("stock_items") if i["product_id"] == P_SIZED)["sku"] == "SKU-0"
    stock.save_settings(db, ORG, USER, {"enabled": False})
    stock.save_settings(db, ORG, USER, {"enabled": True})
    assert len(db.rows("stock_moves")) == 2                              # no second import
    assert stock.stock_on(db, ORG) is True


def test_turning_on_uses_existing_default_location():
    db = _db()
    lagos = stock.create_location(db, ORG, {"name": "Lagos Store", "region": "lagos sales"})
    _on(db)
    assert lagos["region"] == "Lagos Sales" and lagos["is_default"]
    assert [l["name"] for l in stock.list_locations(db, ORG)] == ["Lagos Store"]
    assert _level(db, P_PLAIN, "", lagos["id"])["on_hand"] == 7


# ───────────────────────────── locations ─────────────────────────────

def test_location_rules():
    db = _db()
    a = stock.create_location(db, ORG, {"name": "Lagos Store"})
    b = stock.create_location(db, ORG, {"name": "  Abuja   Store "})
    assert a["is_default"] and not b["is_default"] and b["name"] == "Abuja Store"
    with pytest.raises(stock.StockError) as e:
        stock.create_location(db, ORG, {"name": "lagos store"})
    assert e.value.field == "name"
    with pytest.raises(stock.StockError) as e:
        stock.create_location(db, ORG, {"name": "Kano", "region": "Kano Sales"})
    assert e.value.field == "region"
    with pytest.raises(stock.StockError) as e:
        stock.update_location(db, ORG, a["id"], {"is_active": False})          # the main one
    assert "main" in e.value.message
    stock.update_location(db, ORG, b["id"], {"is_default": True})
    assert [l["name"] for l in stock.list_locations(db, ORG) if l["is_default"]] == ["Abuja Store"]
    _on(db)                                                                   # import goes to Abuja (main)
    stock.receive(db, ORG, USER, {"location_id": a["id"], "lines": [{"product_id": P_PLAIN, "quantity": 2}]})
    with pytest.raises(stock.StockError) as e:
        stock.update_location(db, ORG, a["id"], {"is_active": False})          # still has stock
    assert "still has stock" in e.value.message
    stock.adjust(db, ORG, USER, {"location_id": a["id"], "product_id": P_PLAIN, "mode": "set", "quantity": 0,
                                 "reason": "recount"})
    assert stock.update_location(db, ORG, a["id"], {"is_active": False})["is_active"] is False
    with pytest.raises(stock.StockError):
        stock.update_location(db, OTHER, a["id"], {"name": "x"})               # other business


# ───────────────────────────── receive / adjust ─────────────────────────────

def test_receive_checks_every_line_first_and_sets_cost():
    db = _db()
    _on(db)
    main = _loc(db)
    with pytest.raises(stock.StockError) as e:
        stock.receive(db, ORG, USER, {"location_id": main["id"], "lines": [
            {"product_id": P_PLAIN, "quantity": 5},
            {"product_id": P_SIZED, "variant": "Emperor", "quantity": 1}]})   # not one of its sizes
    assert e.value.field == "variant"
    assert len(db.rows("stock_moves")) == 2                                   # nothing applied from the bad request
    with pytest.raises(stock.StockError):
        stock.receive(db, ORG, USER, {"location_id": main["id"], "lines": [{"product_id": P_THEIRS, "quantity": 1}]})
    out = stock.receive(db, ORG, USER, {"location_id": main["id"], "ref": "Waybill 12", "lines": [
        {"product_id": P_SIZED, "variant": "queen: 5/6 FT.", "quantity": 4, "unit_cost": "120000.50"}]})
    assert out["lines"][0]["variant"] == "Queen: 5/6 ft." and out["lines"][0]["on_hand"] == 14
    item = next(i for i in db.rows("stock_items") if i["variant"] == "Queen: 5/6 ft.")
    assert str(item["cost_price"]) == "120000.50"
    with pytest.raises(stock.StockError) as e:
        stock.receive(db, ORG, USER, {"location_id": main["id"], "lines": [{"product_id": P_PLAIN, "quantity": "1.5"}]})
    assert "whole" in e.value.message


def test_adjust_modes_reasons_and_short_message():
    db = _db()
    _on(db)
    main = _loc(db)
    base = {"location_id": main["id"], "product_id": P_SIZED, "variant": "Queen: 5/6 ft."}
    with pytest.raises(stock.StockError) as e:
        stock.adjust(db, ORG, USER, {**base, "mode": "remove", "quantity": 11, "reason": "damaged"})
    assert e.value.code == "STOCK_SHORT" and e.value.message == "Only 10 Hybrid Mattress Queen: 5/6 ft. available here."
    r = stock.adjust(db, ORG, USER, {**base, "mode": "remove", "quantity": 2, "reason": "damaged", "note": "water"})
    assert r["on_hand"] == 8
    assert db.rows("stock_moves")[-1]["reason"] == "Damaged: water"
    r = stock.adjust(db, ORG, USER, {**base, "mode": "set", "quantity": 12, "reason": "recount"})
    assert r["change"] == 4 and r["on_hand"] == 12
    stock.adjust(db, ORG, USER, {**base, "mode": "add", "quantity": 1, "reason": "returned"})
    assert db.rows("stock_moves")[-1]["kind"] == "return"
    with pytest.raises(stock.StockError) as e:
        stock.adjust(db, ORG, USER, {**base, "mode": "add", "quantity": 1, "reason": "other"})
    assert e.value.field == "note"
    with pytest.raises(stock.StockError) as e:
        stock.adjust(db, ORG, USER, {**base, "mode": "remove", "quantity": 0, "reason": "lost"})
    assert e.value.field == "quantity"
    # held stock can't be removed (STOCK-2 holds); the message gives what is free
    _level(db, P_SIZED, "Queen: 5/6 ft.", main["id"])["held"] = 10
    with pytest.raises(stock.StockError) as e:
        stock.adjust(db, ORG, USER, {**base, "mode": "set", "quantity": 9, "reason": "recount"})
    assert e.value.code == "STOCK_SHORT" and "Only 3" in e.value.message


def test_apply_maps_database_errors():
    db = _db()
    _on(db)
    with pytest.raises(stock.StockError) as e:
        stock.apply(db, ORG, USER, P_PLAIN, "", str(uuid.uuid4()), "receive", on_hand=1)
    assert e.value.field == "location_id"

    class Broken(StockDB):
        def rpc(self, fn, p):
            raise Exception("connection reset")
    with pytest.raises(stock.StockError) as e:
        stock.apply(Broken(), ORG, USER, P_PLAIN, "", "x", "receive", on_hand=1)
    assert e.value.code == "STOCK_FAILED" and e.value.status == 500


def test_update_item_cost_reorder_sku():
    db = _db()
    it = stock.update_item(db, ORG, {"product_id": P_SIZED, "variant": "Double: 4.5/6 ft.", "cost_price": "90000",
                                     "reorder_level": 2, "sku": " D-1 "})
    assert it["variant"] == "Double: 4.5/6 ft." and it["reorder_level"] == 2 and it["sku"] == "D-1"
    it = stock.update_item(db, ORG, {"product_id": P_SIZED, "variant": "Double: 4.5/6 ft.", "cost_price": None})
    assert it["cost_price"] is None and it["reorder_level"] == 2
    with pytest.raises(stock.StockError):
        stock.update_item(db, ORG, {"product_id": P_PLAIN, "variant": "Big"})   # pillow has no sizes
    with pytest.raises(stock.StockError):
        stock.update_item(db, ORG, {"product_id": P_SIZED, "variant": "Queen: 5/6 ft.", "cost_price": "1.234"})


# ───────────────────────────── reading ─────────────────────────────

def test_overview_totals_low_flag_cost_and_filters():
    db = _db()
    _on(db)
    main = _loc(db)
    abuja = stock.create_location(db, ORG, {"name": "Abuja Store", "region": "Abuja Sales"})
    stock.receive(db, ORG, USER, {"location_id": abuja["id"], "lines": [
        {"product_id": P_SIZED, "variant": "Queen: 5/6 ft.", "quantity": 3, "unit_cost": "100"}]})
    stock.update_item(db, ORG, {"product_id": P_PLAIN, "reorder_level": 10})
    data = stock.overview(db, ORG, manager=True)
    rows = {(r["title"], r["variant"]): r for r in data["items"]}
    assert ("Old Bed", "") not in rows                                       # archived and no stock
    assert set(rows) == {("Hybrid Mattress", "Queen: 5/6 ft."), ("Hybrid Mattress", "Double: 4.5/6 ft."),
                         ("Hybrid Mattress", "King"), ("Pillow", "")}
    q = rows[("Hybrid Mattress", "Queen: 5/6 ft.")]
    assert q["on_hand"] == 13 and q["available"] == 13 and len(q["locations"]) == 2 and q["cost_price"] == 100.0
    assert rows[("Pillow", "")]["low"] is True and rows[("Hybrid Mattress", "Double: 4.5/6 ft.")]["low"] is True
    assert data["summary"]["stock_value"] == 1300.0 and data["summary"]["missing_cost"] == 1
    staff = stock.overview(db, ORG, manager=False)
    assert "cost_price" not in staff["items"][0] and "stock_value" not in staff["summary"]
    only_abuja = stock.overview(db, ORG, manager=True, location_id=abuja["id"])
    assert {(r["variant"], r["on_hand"]) for r in only_abuja["items"] if r["on_hand"]} == {("Queen: 5/6 ft.", 3)}
    assert [r["title"] for r in stock.overview(db, ORG, True, q="pill")["items"]] == ["Pillow"]
    assert all(r["low"] for r in stock.overview(db, ORG, True, low_only=True)["items"])
    with pytest.raises(stock.StockError):
        stock.overview(db, ORG, True, location_id=str(uuid.uuid4()))
    assert main["id"] in {l["location_id"] for l in q["locations"]}


def test_overview_keeps_archived_or_removed_size_that_still_has_stock():
    db = _db()
    _on(db)
    stock.apply(db, ORG, USER, P_OLD, "", _loc(db)["id"], "receive", on_hand=2)
    stock.apply(db, ORG, USER, P_SIZED, "Gone size", _loc(db)["id"], "receive", on_hand=1)
    rows = {(r["title"], r["variant"]): r for r in stock.overview(db, ORG, True)["items"]}
    assert rows[("Old Bed", "")]["product_active"] is False
    assert rows[("Hybrid Mattress", "Gone size")]["old_size"] is True


def test_history_newest_first_with_names_and_filters():
    db = _db()
    _on(db)
    main = _loc(db)
    stock.receive(db, ORG, USER, {"location_id": main["id"], "lines": [{"product_id": P_PLAIN, "quantity": 3}]})
    h = stock.history(db, ORG, limit=2)
    assert h["more"] is True and h["items"][0]["kind_label"] == "Received" and h["items"][0]["by"] == "Ada Manager"
    assert h["items"][0]["location"] == "Main store" and h["items"][0]["change"] == 3
    only = stock.history(db, ORG, product_id=P_PLAIN)
    assert [m["kind"] for m in only["items"]] == ["receive", "import"]
    assert stock.history(db, ORG, product_id=P_THEIRS)["items"] == []


def test_search_products_lists_sizes_skips_archived():
    out = stock.search_products(_db(), ORG)
    assert [p["title"] for p in out] == ["Hybrid Mattress", "Pillow"]
    assert out[0]["sizes"] == ["Queen: 5/6 ft.", "Double: 4.5/6 ft.", "King"] and out[1]["sizes"] == []


def test_is_manager():
    assert stock.is_manager({"roles": {"template": "owner"}})
    assert stock.is_manager({"roles": {"template": "ops_manager"}})
    assert stock.is_manager({"roles": {"template": "sales_agent", "permissions": {"is_admin": True}}})
    assert not stock.is_manager({"roles": {"template": "sales_agent"}})
    assert not stock.is_manager({})


# ───────────────────────────── Shopify guard ─────────────────────────────

def _sync(db):
    from app.services import shopify_service
    product = {"id": 123, "title": "Synced", "status": "active", "images": [],
               "variants": [{"title": "Default Title", "price": "10", "inventory_quantity": 50,
                             "inventory_management": "shopify"}]}
    shopify_service.sync_product(db, ORG, product)
    return [r for r in db.rows("products") if r.get("shopify_id") == 123]


def test_shopify_sync_stops_writing_inventory_count_when_stock_is_on():
    db = _db()
    rows = _sync(db)
    assert rows and rows[0]["inventory_count"] == 50
    db2 = _db()
    _on(db2)
    rows = _sync(db2)
    assert rows and "inventory_count" not in rows[0]


# ───────────────────────────── routes ─────────────────────────────

def _client(db, template="owner"):
    from app.routers import inventory as r
    from app.database import get_supabase
    from app.dependencies import get_current_org
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    user = {"id": USER, "org_id": ORG, "roles": {"template": template}}
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _plan_allows():
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        yield


def test_routes_manager_flow_and_staff_limits():
    db = _db()
    c = _client(db)
    r = c.put("/api/v1/inventory/settings", json={"enabled": True})
    assert r.status_code == 200 and r.json()["data"]["import"]["units"] == 17
    loc = c.get("/api/v1/inventory/locations").json()["data"]
    assert loc["regions"] == ["Lagos Sales", "Abuja Sales"] and loc["locations"][0]["name"] == "Main store"
    lid = loc["locations"][0]["id"]
    r = c.post("/api/v1/inventory/receive", json={"location_id": lid, "lines": [
        {"product_id": P_SIZED, "variant": "King", "quantity": 2, "unit_cost": 5}]})
    assert r.status_code == 200 and r.json()["data"]["units"] == 2
    r = c.post("/api/v1/inventory/adjust", json={"location_id": lid, "product_id": P_SIZED, "variant": "King",
                                                 "mode": "remove", "quantity": 5, "reason": "lost"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "STOCK_SHORT"
    assert c.get("/api/v1/inventory").json()["data"]["can_manage"] is True
    assert c.get("/api/v1/inventory/history").json()["data"]["items"][0]["kind"] == "receive"
    assert c.get("/api/v1/inventory/products?q=hyb").json()["data"]["items"][0]["sizes"][0] == "Queen: 5/6 ft."
    assert c.post("/api/v1/inventory/receive", json={"location_id": lid, "lines": [
        {"product_id": P_PLAIN, "quantity": 1, "extra": 1}]}).status_code == 422          # unknown field
    assert c.post("/api/v1/inventory/receive", json={"location_id": lid, "lines": []}).status_code == 422

    staff = _client(db, "sales_agent")
    data = staff.get("/api/v1/inventory").json()["data"]
    assert data["can_manage"] is False and "cost_price" not in data["items"][0]
    assert staff.post("/api/v1/inventory/receive", json={"location_id": lid, "lines": [
        {"product_id": P_PLAIN, "quantity": 1}]}).status_code == 403
    assert staff.put("/api/v1/inventory/settings", json={"enabled": False}).status_code == 403
    assert staff.post("/api/v1/inventory/locations", json={"name": "X"}).status_code == 403
    assert staff.patch("/api/v1/inventory/items", json={"product_id": P_PLAIN, "cost_price": 1}).status_code == 403


def test_routes_plan_gate():
    with patch("app.services.plan_gate_service.allowed", return_value=False):
        r = _client(_db()).get("/api/v1/inventory")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PLAN_REQUIRED"
