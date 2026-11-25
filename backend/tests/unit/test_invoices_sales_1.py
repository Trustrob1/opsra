"""INV-SALES-1: paid invoices into Sales Record (direct_sales), regions on invoices/receipts, part-paid card."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from tests import funnel_fake_db as fake
from tests.unit.test_invoices_1 import (  # noqa: F401  (_plan_allows is an autouse fixture)
    LEAD, ORG, OTHER, PROD, USER, _client, _db, _draft, _plan_allows,
)
from tests.unit.test_invoices_3 import _no_limits  # noqa: F401
from app.services import invoice_followup_service as fu
from app.services import invoice_payment_service as pay
from app.services import invoice_sales_service as sales
from app.services import invoice_service as inv

REGIONS = {"transactions": {"regions": [{"name": "Lagos Sales", "gid": "1"}, {"name": "Abuja Sales"}]}}
RATES = [{"product_name": "Elite Cool", "rate_per_unit": 5000}, {"product_name": "Cool", "rate_per_unit": 1},
         {"product_name": "Pillow", "rate_per_unit": 500}]


@pytest.fixture(autouse=True)
def _unique(monkeypatch):
    monkeypatch.setitem(fake.UNIQUE, "direct_sales", [("org_id", "source_ref")])
    with patch("app.services.commerce_service.convert_lead_on_purchase"):
        yield


def _sdb(regions=True, on=True):
    db = _db(users=[{"id": USER, "org_id": ORG, "full_name": "Cecilia Ade", "email": "c@x.com"}])
    org = [o for o in db.rows("organisations") if o["id"] == ORG][0]
    org["commission_rates"] = RATES
    if regions:
        org["sheet_sources"] = REGIONS
    if on:
        inv.save_settings(db, ORG, {"sales_record_enabled": True})
    return db


def _issue(db, **kw):
    kw.setdefault("region", "lagos sales")
    kw.setdefault("items", [{"description": "Premium Organic Mattress - Elite Cool", "quantity": 2, "unit_price": 100000},
                            {"description": "Pillow", "quantity": 1, "unit_price": 15000}])
    return inv.issue(db, ORG, USER, _draft(db, **kw)["id"])


def _pay(db, d, amount, method="bank_transfer", **kw):
    return pay.record_payment(db, ORG, USER, d["id"], {"amount": amount, "method": method, **kw})


def _sales(db, **f):
    return [r for r in db.rows("direct_sales") if all(r.get(k) == v for k, v in f.items())]


# ───────────────────────────── regions ─────────────────────────────

def test_regions_from_data_sources_and_saved_spelling():
    db = _sdb()
    assert sales.regions(db, ORG) == ["Lagos Sales", "Abuja Sales"]
    assert sales.clean_region(db, ORG, " LAGOS sales ") == "Lagos Sales"
    assert sales.clean_region(db, ORG, "") is None
    with pytest.raises(inv.InvoiceError) as e:
        sales.clean_region(db, ORG, "Kano")
    assert e.value.field == "region"
    assert sales.regions(db, OTHER) == []


def test_issue_needs_region_only_when_business_has_regions():
    db = _sdb()
    d = _draft(db)
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, d["id"])
    assert e.value.field == "region"
    inv.update_draft(db, ORG, USER, d["id"], {"region": "abuja sales"})
    assert inv.issue(db, ORG, USER, d["id"])["region"] == "Abuja Sales"
    db2 = _sdb(regions=False)
    assert inv.issue(db2, ORG, USER, _draft(db2)["id"])["status"] == "issued"


def test_quote_conversion_keeps_region():
    db = _sdb()
    q = _issue(db, doc_type="quote")
    newdoc = inv.convert_quote(db, ORG, USER, q["id"])
    new = newdoc.get("invoice") or newdoc
    assert new["region"] == "Lagos Sales"


# ───────────────────────────── invoice -> Sales Record ─────────────────────────────

def test_fully_paid_invoice_writes_one_row_per_line():
    db = _sdb()
    d = _issue(db, discount=15000, apply_vat=True)       # 215,000 - 15,000 = 200,000 (+ VAT only if enabled)
    total = Decimal(str(inv.get_doc(db, ORG, d["id"])["total"]))
    _pay(db, d, float(total) / 2, paid_at=date(2026, 11, 1))
    assert _sales(db) == []                                # part paid: nothing yet
    _pay(db, d, float(total - total / 2), paid_at=date(2026, 11, 3))
    rows = _sales(db, invoice_id=d["id"])
    assert len(rows) == 2
    assert sum(Decimal(str(r["amount"])) for r in rows) == total
    m = [r for r in rows if r["model"] == "Elite Cool"][0]
    assert m["units"] == 2 and m["region"] == "Lagos Sales" and m["rep_name"] == "Cecilia Ade"
    assert m["recorded_by"] == USER and m["sale_date"] == "2026-11-03" and m["reconciliation_status"] == "Pending"
    assert m["import_source"] == "invoice" and m["channel"] == "invoice" and m["notes"] == f"Invoice {d['number']}"
    assert {r["model"] for r in rows} == {"Elite Cool", "Pillow"}


def test_split_total_adds_up_and_matching():
    parts = sales.split_total([Decimal("1"), Decimal("1"), Decimal("1")], Decimal("100.00"))
    assert sum(parts) == Decimal("100.00") and parts[-1] == Decimal("33.34")
    assert sales.match_model("premium ELITE COOL 6x6", ["Cool", "Elite Cool"]) == "Elite Cool"
    assert sales.match_model("Duvet", ["Elite Cool"]) == "Duvet"
    assert sales.match_model("", ["x"]) is None


def test_paystack_payment_is_reconciled():
    db = _sdb()
    d = _issue(db)
    link = {"id": "pl1", "org_id": ORG, "reference": "r", "status": "paid"}
    db.tables.setdefault("payment_links", []).append(link)
    pay.record_payment(db, ORG, None, d["id"], {"amount": d["total"], "method": "paystack", "reference": "r"},
                       payment_link_id="pl1")
    assert {r["reconciliation_status"] for r in _sales(db, invoice_id=d["id"])} == {"Reconciled"}


def test_switch_off_writes_nothing_and_turning_on_stamps_since():
    db = _sdb(on=False)
    d = _issue(db)
    _pay(db, d, d["total"])
    assert _sales(db) == []
    s = inv.save_settings(db, ORG, {"sales_record_enabled": True})
    assert s["sales_record_enabled"] and s["sales_record_since"]
    since = s["sales_record_since"]
    assert inv.save_settings(db, ORG, {"sales_record_enabled": True})["sales_record_since"] == since   # kept
    # paid before the switch: the worker does not add it (no backfill)
    out = fu.run(db, dry_run=False, on=date(2026, 12, 20))
    assert _sales(db) == [] and out["sales_added"] == 0
    assert sales.sync_invoice(db, ORG, d["id"])["action"] == "before_switch"   # even when asked directly
    assert _sales(db) == []


def test_never_written_twice():
    db = _sdb()
    d = _issue(db)
    _pay(db, d, d["total"])
    assert sales.sync_invoice(db, ORG, d["id"])["action"] == "none"
    rows = sales.build_invoice_rows(db, ORG, inv.get_doc(db, ORG, d["id"]), [])
    assert sales._insert(db, rows) == 0                     # unique source_ref: duplicate ignored
    assert len(_sales(db, invoice_id=d["id"])) == 2


def test_void_receipt_removes_sales_even_with_switch_off():
    db = _sdb()
    d = _issue(db)
    r = _pay(db, d, d["total"])["receipt"]
    assert len(_sales(db)) == 2
    inv.save_settings(db, ORG, {"sales_record_enabled": False})
    pay.void_receipt(db, ORG, USER, r["id"], "wrong amount")
    assert _sales(db) == []
    assert inv.get_doc(db, ORG, d["id"])["status"] == "issued"


def test_sync_failure_never_blocks_payment():
    db = _sdb()
    d = _issue(db)
    with patch.object(sales, "build_invoice_rows", side_effect=RuntimeError("db down")):
        out = _pay(db, d, d["total"])
    assert out["fully_paid"] and _sales(db) == []
    res = fu.run(db, dry_run=True, on=date(2026, 12, 20))
    assert res["sales_missing"] == 1 and _sales(db) == []   # dry run: counted, not written
    res = fu.run(db, dry_run=False, on=date(2026, 12, 20))
    assert res["sales_added"] == 1 and len(_sales(db, invoice_id=d["id"])) == 2


# ───────────────────────────── standalone receipts ─────────────────────────────

def test_standalone_receipt_row_region_and_void():
    db = _sdb()
    with pytest.raises(inv.InvoiceError) as e:
        pay.standalone_receipt(db, ORG, USER, {"lead_id": LEAD, "amount": 5000, "method": "cash", "description": "Deposit"})
    assert e.value.field == "region"
    r = pay.standalone_receipt(db, ORG, USER, {"lead_id": LEAD, "amount": 5000, "method": "cash",
                                               "description": "Deposit", "region": "abuja sales"})
    row = _sales(db, receipt_id=r["id"])[0]
    assert row["amount"] == 5000 and row["region"] == "Abuja Sales" and row["model"] is None and row["units"] is None
    assert row["rep_name"] == "Cecilia Ade" and row["source_ref"] == f"rct:{r['id']}"
    pay.void_receipt(db, ORG, USER, r["id"], "duplicate")
    assert _sales(db) == []


# ───────────────────────────── part-paid card ─────────────────────────────

def test_part_paid_summary_filters():
    db = _sdb()
    a = _issue(db, issue_date="2026-12-02")
    b = _issue(db, issue_date="2026-12-05", region="Abuja Sales")
    _pay(db, a, 50000)
    _pay(db, b, 15000)
    s = sales.part_paid_summary(db, ORG, date(2026, 12, 1), date(2026, 12, 31))
    assert s["count"] == 2 and s["received"] == 65000 and s["owed"] == (215000 - 50000) + (215000 - 15000)
    assert s["items"][0]["number"] == b["number"] and s["items"][0]["rep_name"] == "Cecilia Ade"
    assert sales.part_paid_summary(db, ORG, region="Lagos Sales")["count"] == 1
    assert sales.part_paid_summary(db, ORG, rep="cecilia ade")["count"] == 2
    assert sales.part_paid_summary(db, ORG, rep="Aishat")["count"] == 0
    assert sales.part_paid_summary(db, ORG, date(2026, 12, 3), date(2026, 12, 31))["count"] == 1
    assert sales.part_paid_summary(db, OTHER)["count"] == 0


# ───────────────────────────── routes ─────────────────────────────

def test_routes_regions_part_paid_settings_and_draft_region():
    db = _sdb(on=False)
    c = _client(db)
    assert c.get("/api/v1/invoices/regions").json()["data"]["regions"] == ["Lagos Sales", "Abuja Sales"]
    r = c.put("/api/v1/invoices/settings", json={"sales_record_enabled": True})
    assert r.status_code == 200 and r.json()["data"]["sales_record_enabled"] is True
    assert c.put("/api/v1/invoices/settings", json={"sales_record_since": "2020-01-01"}).status_code == 422
    r = c.post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD, "region": "Kano",
                                         "items": [{"description": "x", "quantity": 1, "unit_price": 1}]})
    assert r.status_code == 422
    r = c.post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD, "region": "Lagos Sales",
                                         "items": [{"description": "x", "quantity": 1, "unit_price": 1}]})
    assert r.status_code == 201 and r.json()["data"]["region"] == "Lagos Sales"
    r = c.get("/api/v1/invoices/part-paid", params={"start": "2026-12-01", "end": "2026-12-31"})
    assert r.status_code == 200 and r.json()["data"]["count"] == 0
    assert c.get("/api/v1/invoices/part-paid", params={"start": "2026-12-31", "end": "2026-12-01"}).status_code == 422


def test_growth_routes_refuse_to_delete_invoice_sales():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import growth_config as g
    from app.database import get_supabase
    from app.dependencies import get_current_org
    db = _sdb()
    d = _issue(db)
    _pay(db, d, d["total"])
    app = FastAPI()
    app.include_router(g.router, prefix="/api/v1")
    owner = {"id": USER, "org_id": ORG, "roles": {"template": "owner"}, "role": "owner"}
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: owner
    c = TestClient(app)
    sid = _sales(db)[0]["id"]
    assert c.delete(f"/api/v1/growth/direct-sales/{sid}").status_code == 422
    assert c.delete("/api/v1/growth/direct-sales/import/invoice/clear").status_code == 422
    assert len(_sales(db)) == 2


# ───────────────────────────── INV-SALES-2: sizes ─────────────────────────────

SIZED = "99999999-9999-9999-9999-999999999999"


def _sized(db):
    db.tables["products"].append({
        "id": SIZED, "org_id": ORG, "title": "Premium Organic Mattress - Elite Cool", "price": 600000, "is_active": True,
        "variants": [{"title": "Default Title", "price": "1"}, {"title": "Double: 4.5/6 ft.", "price": "705000.00"},
                     {"title": "Emperor king: 7/7 ft.", "price": "825000.00"}, {"title": "double: 4.5/6 ft.", "price": "9"}]})


def test_product_sizes_skip_default_and_repeats():
    assert inv.product_sizes({"variants": [{"title": "Default Title", "price": "5"}]}) == []
    db = _sdb()
    _sized(db)
    prod = [p for p in db.rows("products") if p["id"] == SIZED][0]
    assert inv.product_sizes(prod) == [{"title": "Double: 4.5/6 ft.", "price": 705000.0},
                                       {"title": "Emperor king: 7/7 ft.", "price": 825000.0}]
    hit = [p for p in inv.search_products(db, ORG) if p["id"] == SIZED][0]
    assert [s["title"] for s in hit["sizes"]] == ["Double: 4.5/6 ft.", "Emperor king: 7/7 ft."]


def test_size_sets_price_text_and_must_be_real():
    db = _sdb()
    _sized(db)
    d = _draft(db, region="Lagos Sales", items=[{"product_id": SIZED, "quantity": 1, "variant": "emperor KING: 7/7 ft."}])
    line = d["items"][0]
    assert line["variant"] == "Emperor king: 7/7 ft." and line["unit_price"] == 825000
    assert line["description"] == "Premium Organic Mattress - Elite Cool - Emperor king: 7/7 ft."
    assert [s["title"] for s in d["items"][0]["sizes"]] == ["Double: 4.5/6 ft.", "Emperor king: 7/7 ft."]
    with pytest.raises(inv.InvoiceError) as e:
        _draft(db, items=[{"product_id": SIZED, "quantity": 1, "variant": "Queen"}])
    assert e.value.field == "variant"
    typed = _draft(db, items=[{"description": "Foam", "quantity": 1, "unit_price": 10, "variant": "6x6"}])
    assert typed["items"][0]["variant"] == "6x6" and typed["items"][0]["description"] == "Foam - 6x6"


def test_issue_needs_size_for_sized_products_and_sale_gets_variant():
    db = _sdb()
    _sized(db)
    d = _draft(db, region="Lagos Sales", items=[{"product_id": SIZED, "quantity": 2},
                                                {"description": "Pillow", "quantity": 1, "unit_price": 15000}])
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, d["id"])
    assert e.value.field == "variant" and "Elite Cool" in e.value.message
    inv.update_draft(db, ORG, USER, d["id"], {"items": [{"product_id": SIZED, "quantity": 2, "variant": "Double: 4.5/6 ft."},
                                                        {"description": "Pillow", "quantity": 1, "unit_price": 15000}]})
    doc = inv.issue(db, ORG, USER, d["id"])
    assert doc["total"] == 2 * 705000 + 15000
    _pay(db, doc, doc["total"])
    rows = {r["model"]: r for r in _sales(db, invoice_id=doc["id"])}
    assert rows["Elite Cool"]["variant"] == "Double: 4.5/6 ft." and rows["Elite Cool"]["units"] == 2
    assert rows["Pillow"]["variant"] is None


def test_route_accepts_variant():
    db = _sdb()
    _sized(db)
    r = _client(db).post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD, "region": "Lagos Sales",
                                                   "items": [{"product_id": SIZED, "quantity": 1, "variant": "Double: 4.5/6 ft."}]})
    assert r.status_code == 201 and r.json()["data"]["items"][0]["unit_price"] == 705000
