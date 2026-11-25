"""INV-1: quotes and invoices backend - money maths, numbering, drafts, issue, void, quote -> invoice, PDF, routes."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import invoice_pdf_service as pdf
from app.services import invoice_service as inv
from tests.funnel_fake_db import FakeDB, Query

ORG = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
LEAD = "44444444-4444-4444-4444-444444444444"
LEAD_OTHER = "55555555-5555-5555-5555-555555555555"
PROD = "66666666-6666-6666-6666-666666666666"
PROD_OTHER = "77777777-7777-7777-7777-777777777777"
CUST = "88888888-8888-8888-8888-888888888888"


class InvQuery(Query):
    def or_(self, expr):
        needles = [p.split(".ilike.")[1].strip("%").lower() for p in expr.split(",") if ".ilike." in p]
        cols = [p.split(".ilike.")[0] for p in expr.split(",") if ".ilike." in p]
        self.filters.append(lambda r: any(n in str(r.get(c) or "").lower() for c, n in zip(cols, needles)))
        return self


class InvDB(FakeDB):
    def __init__(self, **tables):
        super().__init__(**tables)
        self.counters: dict = {}
        self.rpc_calls: list = []

    def table(self, name):
        return InvQuery(self, name)

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        assert fn == "next_invoice_number"
        key = (params["p_org"], params["p_kind"])
        self.counters[key] = self.counters.get(key, 0) + 1
        value = self.counters[key]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=value))


def _db(**extra):
    return InvDB(
        organisations=[{"id": ORG, "name": "Royal Rest Mattress"}, {"id": OTHER, "name": "Other Co"}],
        leads=[{"id": LEAD, "org_id": ORG, "full_name": "Ada Obi", "whatsapp": "2348011111111", "phone": None,
                "email": "ada@example.com", "location": "Lekki", "deleted_at": None},
               {"id": LEAD_OTHER, "org_id": OTHER, "full_name": "Not yours", "deleted_at": None}],
        customers=[{"id": CUST, "org_id": ORG, "lead_id": LEAD, "full_name": "Ada Obi Ltd", "phone": "0801",
                    "whatsapp": None, "email": None, "location": None, "deleted_at": None}],
        products=[{"id": PROD, "org_id": ORG, "title": "Orthopaedic mattress 6x6", "price": 250000},
                  {"id": PROD_OTHER, "org_id": OTHER, "title": "Theirs", "price": 1}],
        **extra,
    )


def _draft(db, **kw):
    body = {"doc_type": "invoice", "lead_id": LEAD,
            "items": [{"description": "Pillow", "quantity": 2, "unit_price": 15000}], **kw}
    return inv.create_draft(db, ORG, USER, body)


# ───────────────────────────── money maths ─────────────────────────────

def test_totals_with_discount_and_vat():
    t = inv.compute_totals([{"quantity": 2, "unit_price": "15000"}, {"quantity": "1.5", "unit_price": "1000.10"}],
                           discount=1000, vat_rate=7.5)
    assert t["subtotal"] == Decimal("31500.15")
    assert t["vat_amount"] == Decimal("2287.51")          # (31500.15 - 1000) * 7.5% = 2287.51125 -> half-up
    assert t["total"] == Decimal("32787.66")
    assert t["lines"][1]["line_total"] == Decimal("1500.15")


def test_half_kobo_rounds_up():
    assert inv.compute_totals([{"quantity": 1, "unit_price": "0.005"}])["total"] == Decimal("0.01")


def test_discount_above_subtotal_is_refused():
    with pytest.raises(inv.InvoiceError) as e:
        inv.compute_totals([{"quantity": 1, "unit_price": 100}], discount=101)
    assert e.value.field == "discount"


def test_zero_quantity_is_refused():
    with pytest.raises(inv.InvoiceError):
        inv.compute_totals([{"quantity": 0, "unit_price": 100}])


# ───────────────────────────── settings ─────────────────────────────

def test_settings_default_to_org_name():
    s = inv.get_settings(_db(), ORG)
    assert s["business_name"] == "Royal Rest Mattress" and s["saved"] is False and s["invoice_prefix"] == "INV-"


def test_settings_save_and_update():
    db = _db()
    inv.save_settings(db, ORG, {"bank_name": "GTBank", "account_number": "0123456789", "vat_enabled": True})
    s = inv.save_settings(db, ORG, {"vat_rate": 5})
    assert s["saved"] and s["bank_name"] == "GTBank" and s["vat_enabled"] is True and s["vat_rate"] == 5.0
    assert len(db.rows("invoice_settings")) == 1


# ───────────────────────────── drafts ─────────────────────────────

def test_draft_fills_customer_from_lead_and_has_no_number():
    db = _db()
    d = _draft(db)
    assert d["status"] == "draft" and d.get("number") is None
    assert d["customer_name"] == "Ada Obi" and d["customer_phone"] == "2348011111111" and d["customer_address"] == "Lekki"
    assert d["total"] == 30000.0 and len(d["items"]) == 1


def test_draft_from_customer_takes_its_lead():
    d = inv.create_draft(_db(), ORG, USER, {"doc_type": "quote", "customer_id": CUST,
                                             "items": [{"description": "x", "quantity": 1, "unit_price": 5}]})
    assert d["customer_id"] == CUST and d["lead_id"] == LEAD and d["customer_name"] == "Ada Obi Ltd"


def test_lead_of_another_org_is_refused():
    with pytest.raises(inv.InvoiceError) as e:
        _draft(_db(), lead_id=LEAD_OTHER)
    assert e.value.status == 404


def test_product_line_defaults_to_catalogue_title_and_price():
    d = inv.create_draft(_db(), ORG, USER, {"doc_type": "invoice", "lead_id": LEAD,
                                             "items": [{"product_id": PROD, "quantity": 2}]})
    assert d["items"][0]["description"] == "Orthopaedic mattress 6x6" and d["total"] == 500000.0


def test_product_of_another_org_is_refused():
    with pytest.raises(inv.InvoiceError) as e:
        inv.create_draft(_db(), ORG, USER, {"doc_type": "invoice", "items": [{"product_id": PROD_OTHER, "quantity": 1}]})
    assert e.value.status == 404


def test_vat_follows_settings_unless_overridden():
    db = _db()
    inv.save_settings(db, ORG, {"vat_enabled": True, "vat_rate": 7.5})
    assert _draft(db)["vat_amount"] == 2250.0
    assert _draft(db, apply_vat=False)["vat_amount"] == 0.0


def test_update_draft_replaces_lines_and_recalculates():
    db = _db()
    d = _draft(db)
    u = inv.update_draft(db, ORG, USER, d["id"], {"items": [{"description": "Bed frame", "quantity": 1, "unit_price": 90000}],
                                                   "discount": 10000})
    assert [i["description"] for i in u["items"]] == ["Bed frame"] and u["total"] == 80000.0
    assert len(db.rows("invoice_items")) == 1


def test_update_draft_discount_only_keeps_lines():
    db = _db()
    d = _draft(db)
    u = inv.update_draft(db, ORG, USER, d["id"], {"discount": 5000})
    assert len(u["items"]) == 1 and u["total"] == 25000.0


def test_delete_draft_removes_lines():
    db = _db()
    d = _draft(db)
    inv.delete_draft(db, ORG, USER, d["id"])
    assert not db.rows("invoices") and not db.rows("invoice_items")


def test_other_org_cannot_read_a_document():
    db = _db()
    d = _draft(db)
    with pytest.raises(inv.InvoiceError) as e:
        inv.get_doc(db, OTHER, d["id"])
    assert e.value.status == 404


# ───────────────────────────── issue ─────────────────────────────

def test_issue_numbers_locks_and_snapshots():
    db = _db()
    inv.save_settings(db, ORG, {"bank_name": "GTBank", "account_number": "0123456789", "default_due_days": 7})
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    assert d["number"] == "INV-0001" and d["status"] == "issued"
    assert d["issue_date"] == str(inv.today()) and d["due_date"] == str(inv.today() + timedelta(days=7))
    assert d["issuer"]["account_number"] == "0123456789" and len(d["public_token"]) >= 30
    with pytest.raises(inv.InvoiceError) as e:
        inv.update_draft(db, ORG, USER, d["id"], {"discount": 1})
    assert e.value.code == "INVALID_TRANSITION"
    with pytest.raises(inv.InvoiceError):
        inv.delete_draft(db, ORG, USER, d["id"])


def test_numbers_count_up_per_type_and_org():
    db = _db()
    a = inv.issue(db, ORG, USER, _draft(db)["id"])
    b = inv.issue(db, ORG, USER, _draft(db)["id"])
    q = inv.issue(db, ORG, USER, _draft(db, doc_type="quote")["id"])
    assert (a["number"], b["number"], q["number"]) == ("INV-0001", "INV-0002", "QT-0001")


def test_settings_change_after_issue_does_not_change_issuer():
    db = _db()
    inv.save_settings(db, ORG, {"bank_name": "GTBank"})
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    inv.save_settings(db, ORG, {"bank_name": "Zenith"})
    assert inv.get_doc(db, ORG, d["id"])["issuer"]["bank_name"] == "GTBank"


def test_issue_needs_lines_and_a_name():
    db = _db()
    empty = inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "customer_name": "Bola"})
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, empty["id"])
    assert e.value.field == "items"
    nameless = inv.create_draft(db, ORG, USER, {"doc_type": "invoice", "items": [{"description": "x", "quantity": 1, "unit_price": 5}]})
    with pytest.raises(inv.InvoiceError) as e:
        inv.issue(db, ORG, USER, nameless["id"])
    assert e.value.field == "customer_name"


def test_issue_writes_audit():
    db = _db()
    inv.issue(db, ORG, USER, _draft(db)["id"])
    assert any(r["action"] == "invoice.issued" and r["user_id"] == USER for r in db.rows("audit_logs"))


# ───────────────────────────── void ─────────────────────────────

def test_void_issued_invoice():
    db = _db()
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    v = inv.void(db, ORG, USER, d["id"], "Wrong price")
    assert v["status"] == "void" and v["void_reason"] == "Wrong price"


def test_draft_cannot_be_voided_and_paid_invoice_cannot_be_voided():
    db = _db()
    with pytest.raises(inv.InvoiceError):
        inv.void(db, ORG, USER, _draft(db)["id"], "x x")
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    db.table("invoices").update({"amount_paid": 1000}).eq("id", d["id"]).execute()
    with pytest.raises(inv.InvoiceError):
        inv.void(db, ORG, USER, d["id"], "x x")


# ───────────────────────────── quotes ─────────────────────────────

def test_quote_accept_decline_only_when_issued():
    db = _db()
    q = _draft(db, doc_type="quote")
    with pytest.raises(inv.InvoiceError):
        inv.set_quote_answer(db, ORG, USER, q["id"], True)
    inv.issue(db, ORG, USER, q["id"])
    assert inv.set_quote_answer(db, ORG, USER, q["id"], False)["status"] == "declined"


def test_accept_refuses_an_invoice():
    db = _db()
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    with pytest.raises(inv.InvoiceError) as e:
        inv.set_quote_answer(db, ORG, USER, d["id"], True)
    assert e.value.status == 404


def test_convert_quote_makes_draft_invoice_once():
    db = _db()
    inv.save_settings(db, ORG, {"vat_enabled": True})
    q = inv.issue(db, ORG, USER, _draft(db, doc_type="quote", discount=2000)["id"])
    i = inv.convert_quote(db, ORG, USER, q["id"])
    assert i["doc_type"] == "invoice" and i["status"] == "draft" and i["converted_from_id"] == q["id"]
    assert i["total"] == q["total"] and i["discount"] == 2000.0 and len(i["items"]) == 1
    assert inv.get_doc(db, ORG, q["id"])["status"] == "accepted"
    with pytest.raises(inv.InvoiceError) as e:
        inv.convert_quote(db, ORG, USER, q["id"])
    assert e.value.code == "DUPLICATE_DETECTED"


# ───────────────────────────── list + computed status ─────────────────────────────

def test_overdue_and_expired_are_computed():
    db = _db()
    past = inv.today() - timedelta(days=1)
    i = inv.issue(db, ORG, USER, _draft(db, due_date=str(past))["id"])
    q = inv.issue(db, ORG, USER, _draft(db, doc_type="quote", due_date=str(past))["id"])
    assert i["display_status"] == "overdue" and q["display_status"] == "expired"
    assert [r["id"] for r in inv.list_docs(db, ORG, status="overdue")["items"]] == [i["id"]]
    assert [r["id"] for r in inv.list_docs(db, ORG, status="expired")["items"]] == [q["id"]]


def test_list_is_org_scoped_and_searchable():
    db = _db()
    _draft(db)
    inv.create_draft(db, OTHER, USER, {"doc_type": "invoice", "customer_name": "Hidden"})
    assert len(inv.list_docs(db, ORG)["items"]) == 1
    assert len(inv.list_docs(db, ORG, q="ada")["items"]) == 1
    assert len(inv.list_docs(db, ORG, q="nobody")["items"]) == 0


# ───────────────────────────── PDF ─────────────────────────────

def _issued_doc():
    db = _db()
    inv.save_settings(db, ORG, {"bank_name": "GTBank", "account_number": "0123456789", "account_name": "Royal Rest"})
    return inv.issue(db, ORG, USER, _draft(db, notes="<script>alert(1)</script>")["id"])


def test_pdf_html_escapes_user_text_and_shows_bank():
    html = pdf.build_html(_issued_doc(), {}, "invoice")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "0123456789" in html and "INV-0001" in html and "₦30,000.00" in html


def test_pdf_blocks_logo_from_outside_storage(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    doc = _issued_doc()
    doc["issuer"]["logo_url"] = "http://169.254.169.254/latest/meta-data"
    assert "<img" not in pdf.build_html(doc, {}, "invoice")
    doc["issuer"]["logo_url"] = "https://proj.supabase.co/storage/v1/object/public/catalog/logo.png"
    assert "<img" in pdf.build_html(doc, {}, "invoice")
    with pytest.raises(ValueError):
        pdf._safe_fetcher("http://169.254.169.254/latest/meta-data")


def test_pdf_fetcher_works_on_new_weasyprint_and_still_blocks(monkeypatch):
    """PDF-FIX-1: WeasyPrint 68+ needs a URLFetcher object, not a function (production 503 on Preview PDF)."""
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    f = pdf.pdf_url_fetcher()
    try:
        from weasyprint.urls import URLFetcher
        assert isinstance(f, URLFetcher) and f._fail_on_errors is False
        with pytest.raises(ValueError):
            f.fetch("http://169.254.169.254/latest/meta-data")
    except ImportError:
        assert f is pdf._safe_fetcher
    import pathlib
    for name in ("invoice_pdf_service.py", "business_report_service.py"):
        src = (pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / name).read_text(encoding="utf-8")
        assert "url_fetcher=pdf_url_fetcher()" in src or "url_fetcher=pdf.pdf_url_fetcher()" in src


def test_draft_pdf_is_marked_draft_and_brand_colour_is_checked():
    db = _db()
    doc = inv.get_doc(db, ORG, _draft(db)["id"])
    html = pdf.build_html(doc, {"brand_colour": "red;} body{display:none"}, "invoice")
    assert "DRAFT" in html and "display:none" not in html


def test_receipt_html():
    html = pdf.build_html({"number": "RCT-0001", "customer_name": "Ada", "amount": 5000, "method": "cash",
                           "paid_at": "2026-11-25T10:00:00+00:00", "invoice_number": "INV-0001",
                           "invoice_balance": 25000}, {"business_name": "RR"}, "receipt")
    assert "RECEIPT" in html and "Cash" in html and "₦25,000.00" in html


def test_render_returns_pdf_bytes():
    data, name = pdf.render(_issued_doc(), {}, "invoice")
    assert data and data[:4] == b"%PDF" and name == "Invoice-INV-0001.pdf"


def test_render_never_raises():
    with patch.object(pdf, "build_html", side_effect=RuntimeError("boom")):
        assert pdf.render({"id": "x"}, {}, "invoice")[0] is None


# ───────────────────────────── routes ─────────────────────────────

def _client(db, admin=True):
    from app.routers import invoices as r
    from app.database import get_supabase
    from app.dependencies import get_current_org, require_admin
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    user = {"id": USER, "org_id": ORG, "roles": {"template": "owner" if admin else "sales_rep"}}

    async def _not_admin():
        raise HTTPException(status_code=403, detail="admin only")

    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: user
    app.dependency_overrides[require_admin] = (lambda: user) if admin else _not_admin
    return TestClient(app)


@pytest.fixture(autouse=True)
def _plan_allows():
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        yield


def test_route_full_flow():
    db = _db()
    c = _client(db)
    r = c.post("/api/v1/invoices", json={"doc_type": "quote", "lead_id": LEAD,
                                         "items": [{"description": "Pillow", "quantity": 2, "unit_price": 15000}]})
    assert r.status_code == 201, r.text
    qid = r.json()["data"]["id"]
    assert c.post(f"/api/v1/invoices/{qid}/issue").json()["data"]["number"] == "QT-0001"
    r = c.post(f"/api/v1/invoices/{qid}/convert")
    assert r.status_code == 201
    iid = r.json()["data"]["id"]
    assert c.post(f"/api/v1/invoices/{iid}/issue").json()["data"]["number"] == "INV-0001"
    listed = c.get("/api/v1/invoices", params={"doc_type": "invoice"}).json()["data"]["items"]
    assert [x["id"] for x in listed] == [iid]
    p = c.get(f"/api/v1/invoices/{iid}/pdf")
    assert p.status_code == 200 and p.headers["content-type"] == "application/pdf" and p.content[:4] == b"%PDF"


def test_route_org_id_in_body_is_rejected():
    r = _client(_db()).post("/api/v1/invoices", json={"doc_type": "invoice", "org_id": OTHER})
    assert r.status_code == 422


def test_route_validation_limits():
    c = _client(_db())
    assert c.post("/api/v1/invoices", json={"doc_type": "invoice", "notes": "x" * 5001}).status_code == 422
    assert c.post("/api/v1/invoices", json={"doc_type": "invoice", "items": [{"description": "a", "quantity": -1,
                                                                             "unit_price": 1}]}).status_code == 422
    assert c.post("/api/v1/invoices", json={"doc_type": "receipt"}).status_code == 422
    assert c.put("/api/v1/invoices/settings", json={"brand_colour": "red"}).status_code == 422
    assert c.put("/api/v1/invoices/settings", json={"account_number": "12ab"}).status_code == 422


def test_route_errors_use_envelope():
    db = _db()
    c = _client(db)
    r = c.post("/api/v1/invoices", json={"doc_type": "invoice", "lead_id": LEAD_OTHER})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND" and r.json()["success"] is False
    assert c.get(f"/api/v1/invoices/{LEAD}").status_code == 404


def test_route_settings_and_void_need_admin():
    db = _db()
    c = _client(db, admin=False)
    assert c.get("/api/v1/invoices/settings").status_code == 200
    assert c.put("/api/v1/invoices/settings", json={"bank_name": "GTBank"}).status_code == 403
    d = inv.issue(db, ORG, USER, _draft(db)["id"])
    assert c.post(f"/api/v1/invoices/{d['id']}/void", json={"reason": "wrong"}).status_code == 403
    assert _client(db).post(f"/api/v1/invoices/{d['id']}/void", json={"reason": "wrong"}).json()["data"]["status"] == "void"


def test_route_plan_gate_blocks():
    with patch("app.services.plan_gate_service.allowed", return_value=False):
        r = _client(_db()).get("/api/v1/invoices")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PLAN_REQUIRED"


def test_invoices_is_a_plan_feature():
    from app.services.site_feature_registry import FEATURES
    assert FEATURES["invoices"]["built"] is True


def test_pdf_small_formatting():
    assert pdf._qty("7.50") == "7.5" and pdf._qty(2) == "2" and pdf._qty("1.25") == "1.25"
    doc = {"status": "issued", "issuer": {"business_name": "X", "rc_number": "RC 1234567"}, "items": []}
    assert "RC RC" not in pdf.build_html(doc, {}, "invoice")
    doc["issuer"]["rc_number"] = "1234567"
    assert "RC 1234567" in pdf.build_html(doc, {}, "invoice")
