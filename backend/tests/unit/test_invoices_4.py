"""INV-4: payments against invoices, receipts (manual + standalone + void), Paystack Pay now, webhook hook, receipt send."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.unit.test_invoices_1 import (  # noqa: F401  (_plan_allows is an autouse fixture)
    CUST, LEAD, LEAD_OTHER, ORG, OTHER, USER, _client, _db, _draft, _plan_allows,
)
from tests.unit.test_invoices_3 import _issued, _no_limits, _public  # noqa: F401
from app.services import invoice_delivery_service as delivery
from app.services import invoice_payment_service as pay
from app.services import invoice_service as inv



def _row(db, table, rid):
    return [r for r in db.rows(table) if r["id"] == rid][0]


def _pay(db, d, amount, method="bank_transfer", **kw):
    return pay.record_payment(db, ORG, USER, d["id"], {"amount": amount, "method": method, **kw})


# ───────────────────────────── recording ─────────────────────────────

def test_part_then_full_payment_moves_status_and_numbers_receipts():
    db = _db()
    d = _issued(db)                                   # 30,000
    with patch("app.services.commerce_service.convert_lead_on_purchase") as conv:
        a = _pay(db, d, 10000, reference="TRF123")
        assert a["invoice"]["status"] == "part_paid" and a["invoice"]["balance_due"] == 20000
        assert a["receipt"]["number"] == "RCT-0001" and not a["fully_paid"]
        conv.assert_not_called()
        b = _pay(db, d, 20000, method="cash")
    assert b["invoice"]["status"] == "paid" and b["fully_paid"] and b["receipt"]["number"] == "RCT-0002"
    conv.assert_called_once_with(db, ORG, LEAD)
    r = _row(db, "receipts", b["receipt"]["id"])
    assert r["org_id"] == ORG and r["lead_id"] == LEAD and r["issuer"]["business_name"] == "Royal Rest Mattress"
    assert r["public_token"] and r["recorded_by"] == USER
    assert any(x["action"] == "receipt.recorded" for x in db.rows("audit_logs"))


def test_payment_rules():
    db = _db()
    d = _issued(db)
    for amount, method, code in ((40000, "cash", "VALIDATION_ERROR"), (0, "cash", "VALIDATION_ERROR"),
                                 (100, "paystack", "VALIDATION_ERROR"), (100, "cheque", "VALIDATION_ERROR")):
        with pytest.raises(inv.InvoiceError) as e:
            _pay(db, d, amount, method)
        assert e.value.code == code
    q = _issued(db, doc_type="quote")
    dr = _draft(db)
    for doc in (q, dr):
        with pytest.raises(inv.InvoiceError) as e:
            _pay(db, doc, 100)
        assert e.value.code == "INVALID_TRANSITION"
    _pay(db, d, 30000)
    with pytest.raises(inv.InvoiceError) as e:
        _pay(db, d, 1)
    assert "already fully paid" in e.value.message


def test_future_payment_date_refused():
    db = _db()
    d = _issued(db)
    with pytest.raises(inv.InvoiceError) as e:
        _pay(db, d, 100, paid_at="2099-01-01")
    assert e.value.field == "paid_at"


def test_amount_paid_is_sum_of_live_receipts_and_void_reopens():
    db = _db()
    d = _issued(db)
    with patch("app.services.commerce_service.convert_lead_on_purchase"):
        a = _pay(db, d, 10000)
        b = _pay(db, d, 20000)
    _row(db, "invoices", d["id"])["amount_paid"] = 999   # a stale number is never trusted
    pay.void_receipt(db, ORG, USER, b["receipt"]["id"], "bounced transfer")
    doc = inv.get_doc(db, ORG, d["id"])
    assert doc["amount_paid"] == 10000 and doc["status"] == "part_paid"
    pay.void_receipt(db, ORG, USER, a["receipt"]["id"], "duplicate")
    assert inv.get_doc(db, ORG, d["id"])["status"] == "issued"
    with pytest.raises(inv.InvoiceError):
        pay.void_receipt(db, ORG, USER, a["receipt"]["id"], "again")
    with pytest.raises(inv.InvoiceError) as e:
        pay.void_receipt(db, ORG, USER, b["receipt"]["id"], "")
    assert e.value.code in ("VALIDATION_ERROR", "INVALID_TRANSITION")


def test_standalone_receipt():
    db = _db()
    r = pay.standalone_receipt(db, ORG, USER, {"lead_id": LEAD, "amount": 5000, "method": "pos",
                                                "description": "Walk-in pillow"})
    assert r["invoice_id"] is None and r["customer_name"] == "Ada Obi" and r["number"] == "RCT-0001"
    with pytest.raises(inv.InvoiceError):
        pay.standalone_receipt(db, ORG, USER, {"lead_id": LEAD_OTHER, "amount": 1, "method": "cash", "description": "x"})
    with pytest.raises(inv.InvoiceError) as e:
        pay.standalone_receipt(db, ORG, USER, {"amount": 1, "method": "cash", "description": "x"})
    assert e.value.field == "customer_name"
    with pytest.raises(inv.InvoiceError):
        pay.standalone_receipt(db, ORG, USER, {"customer_name": "Bob", "amount": 1, "method": "paystack",
                                                "description": "x"})


def test_receipt_pdf_shows_invoice_and_balance_after_that_payment():
    db = _db()
    d = _issued(db)
    a = _pay(db, d, 10000, paid_at="2026-11-20")
    _pay(db, d, 5000, paid_at="2026-11-22")
    doc = pay.receipt_doc(db, ORG, a["receipt"])
    assert doc["invoice_number"] == "INV-0001" and doc["invoice_balance"] == 20000
    data, name = pay.render_receipt(db, ORG, a["receipt"])
    assert data[:4] == b"%PDF" and name == "Receipt-RCT-0001.pdf"


def test_receipts_list_and_summary_paid_this_month():
    db = _db()
    d = _issued(db)
    _pay(db, d, 10000)
    pay.standalone_receipt(db, ORG, USER, {"customer_name": "Walk in", "amount": 2500, "method": "cash",
                                           "description": "Sale"})
    items = pay.list_receipts(db, ORG)["items"]
    assert len(items) == 2 and {i.get("invoice_number") for i in items} == {"INV-0001", None}
    assert pay.paid_this_month(db, ORG) == 12500
    assert pay.paid_this_month(db, OTHER) == 0


# ───────────────────────────── routes ─────────────────────────────

def test_routes_record_list_void_and_org_scope():
    db = _db()
    d = _issued(db)
    c = _client(db)
    r = c.post(f"/api/v1/invoices/{d['id']}/payments", json={"amount": "1000.50", "method": "bank_transfer"})
    assert r.status_code == 201 and r.json()["data"]["invoice"]["status"] == "part_paid"
    assert "public_token" not in r.json()["data"]["receipt"]
    assert c.post(f"/api/v1/invoices/{d['id']}/payments", json={"amount": "1.001", "method": "cash"}).status_code == 422
    assert c.post(f"/api/v1/invoices/{d['id']}/payments",
                  json={"amount": 1, "method": "cash", "org_id": OTHER}).status_code == 422
    assert c.post(f"/api/v1/invoices/{d['id']}/payments", json={"amount": 1, "method": "paystack"}).status_code == 422
    got = c.get(f"/api/v1/invoices/{d['id']}").json()["data"]
    assert len(got["receipts"]) == 1 and "public_token" not in got["receipts"][0]
    rid = got["receipts"][0]["id"]
    assert c.get("/api/v1/receipts").json()["data"]["items"][0]["id"] == rid
    assert c.get(f"/api/v1/receipts/{rid}/pdf").content[:4] == b"%PDF"
    assert c.get("/api/v1/invoices/summary").json()["data"]["paid_this_month"] == 1000.5
    assert _client(db, admin=False).post(f"/api/v1/receipts/{rid}/void", json={"reason": "oops"}).status_code == 403
    assert c.post(f"/api/v1/receipts/{rid}/void", json={"reason": "oops"}).json()["data"]["voided_at"]
    for x in db.rows("receipts"):
        x["org_id"] = OTHER
    assert c.get(f"/api/v1/receipts/{rid}/pdf").status_code == 404


def test_route_standalone_receipt():
    db = _db()
    c = _client(db)
    r = c.post("/api/v1/receipts", json={"customer_id": CUST, "amount": 700, "method": "ussd", "description": "Deposit"})
    assert r.status_code == 201 and r.json()["data"]["customer_name"] == "Ada Obi Ltd"


# ───────────────────────────── sending receipts ─────────────────────────────

def test_send_receipt_auto_picks_whatsapp_then_email(monkeypatch):
    db = _db()
    d = _issued(db)
    a = _pay(db, d, 10000)
    calls = {}
    with patch("app.services.whatsapp_service._is_lead_window_open", return_value=True), \
         patch("app.services.whatsapp_service.send_whatsapp_media_message", side_effect=lambda **k: calls.setdefault("media", k)), \
         patch("app.services.whatsapp_service.send_whatsapp_message", side_effect=lambda **k: calls.setdefault("text", k)):
        out = delivery.send_receipt(db, ORG, None, a["receipt"]["id"])
    assert out == {"channel": "whatsapp", "sent": True}
    assert calls["media"]["filename"] == "Receipt-RCT-0001.pdf"
    text = calls["text"]["payload"].content
    assert "₦10,000" in text and "RCT-0001" in text and "Balance left on invoice INV-0001: ₦20,000" in text
    sent = []
    monkeypatch.setitem(sys.modules, "resend", SimpleNamespace(api_key=None, Emails=SimpleNamespace(send=sent.append)))
    monkeypatch.setenv("RESEND_API_KEY", "k")
    with patch("app.services.whatsapp_service._is_lead_window_open", return_value=False):
        out = delivery.send_receipt(db, ORG, None, a["receipt"]["id"])
    assert out["channel"] == "email" and sent[0]["to"] == ["ada@example.com"]
    assert sent[0]["subject"] == "Receipt RCT-0001 from Royal Rest Mattress"


def test_send_receipt_nothing_usable_returns_none_and_void_refused():
    db = _db()
    r = pay.standalone_receipt(db, ORG, USER, {"customer_name": "Walk in", "amount": 1, "method": "cash",
                                               "description": "x"})
    assert delivery.send_receipt(db, ORG, None, r["id"]) == {"channel": None, "sent": False}
    pay.void_receipt(db, ORG, USER, r["id"], "mistake")
    with pytest.raises(inv.InvoiceError):
        delivery.send_receipt(db, ORG, None, r["id"], "email", "a@b.co")


# ───────────────────────────── Paystack ─────────────────────────────

class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class _Client:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        _Client.sent.append((url, headers, json))
        return _Resp(200, {"status": True, "data": {"authorization_url": "https://checkout.paystack.com/abc"}})


def _connected(db):
    db.tables.setdefault("integrations", []).append(
        {"id": "i1", "org_id": ORG, "provider": "paystack_storefront", "status": "connected",
         "credentials": {"secret_key": "sk_test_x"}})


def test_pay_now_only_when_connected_and_linked(monkeypatch):
    db = _db()
    d = _issued(db)
    assert not pay.can_pay(db, d)
    _connected(db)
    assert pay.can_pay(db, d)
    q = _issued(db, doc_type="quote")
    assert not pay.can_pay(db, q)
    walk_in = _issued(db, lead_id=None, customer_name="Walk in")
    assert not pay.can_pay(db, walk_in)
    view = delivery.public_view(db, d["public_token"])
    assert view["can_pay"] is True and view["receipts"] == []


def test_start_checkout_makes_payment_link_for_balance(monkeypatch):
    db = _db()
    _connected(db)
    d = _issued(db)
    _pay(db, d, 10000)
    _Client.sent = []
    monkeypatch.setattr("httpx.Client", _Client)
    r = _public(db).post(f"/api/v1/public/invoices/{d['public_token']}/pay")
    assert r.status_code == 200 and r.json()["data"]["checkout_url"] == "https://checkout.paystack.com/abc"
    (url, headers, body), = _Client.sent
    assert headers["Authorization"] == "Bearer sk_test_x" and body["amount"] == 2000000
    assert body["callback_url"].endswith(f"/i/{d['public_token']}") and pay.REF_RE.match(body["reference"])
    (link,) = db.rows("payment_links")
    assert link["lead_id"] == LEAD and link["amount"] == 20000 and link["payment_type"] == "balance"
    assert _row(db, "invoices", d["id"])["payment_link_id"] == link["id"]


def _paid_link(db, d, amount):
    _connected(db)
    ref = f"inv_{d['id'].replace('-', '')}_0a1b2c3d"
    db.tables.setdefault("payment_links", []).append(
        {"id": "pl1", "org_id": ORG, "lead_id": LEAD, "amount": amount, "currency": "NGN", "reference": ref,
         "status": "paid", "paid_at": "2026-11-25T10:00:00+00:00", "payment_type": "full"})
    return ref


def test_webhook_hook_makes_one_receipt_and_sends_it():
    db = _db()
    d = _issued(db)
    ref = _paid_link(db, d, 30000)
    with patch("app.services.commerce_service.convert_lead_on_purchase") as conv, \
         patch("app.services.invoice_delivery_service.send_receipt") as send:
        out = pay.on_payment_confirmed(db, ORG, ref)
        assert pay.on_payment_confirmed(db, ORG, ref) is None          # second webhook: nothing new
    assert out["invoice"]["status"] == "paid" and out["receipt"]["method"] == "paystack"
    assert len(db.rows("receipts")) == 1 and db.rows("receipts")[0]["payment_link_id"] == "pl1"
    conv.assert_called_once()
    send.assert_called_once()


def test_webhook_hook_ignores_other_refs_other_orgs_and_never_raises():
    db = _db()
    d = _issued(db)
    ref = _paid_link(db, d, 30000)
    assert pay.on_payment_confirmed(db, ORG, "funnel_abc") is None
    assert pay.on_payment_confirmed(db, OTHER, ref) is None
    with patch("app.services.invoice_payment_service.record_payment", side_effect=RuntimeError("db")):
        assert pay.on_payment_confirmed(db, ORG, ref) is None
    assert not db.rows("receipts")


def test_mark_paid_suppresses_generic_whatsapp_for_invoice_refs():
    from app.services import paystack_storefront_service as ps
    db = _db()
    d = _issued(db)
    ref = _paid_link(db, d, 30000)
    db.rows("payment_links")[0]["status"] = "pending"
    with patch("app.services.whatsapp_service.send_payment_received_message") as msg, \
         patch("app.services.funnel_service.is_funnel_reference", return_value=False), \
         patch("app.services.site_order_service.is_site_order_reference", return_value=False), \
         patch("app.services.paystack_storefront_service.get_lead_payment_progress",
               return_value={"amount_paid": 30000, "deal_value": None, "balance_due": 0}):
        ps.mark_paid(db=db, org_id=ORG, reference=ref)
    msg.assert_not_called()
    assert db.rows("payment_links")[0]["status"] == "paid"


def test_verify_return_checks_paystack_then_records(monkeypatch):
    db = _db()
    d = _issued(db)
    ref = _paid_link(db, d, 30000)
    db.rows("payment_links")[0]["status"] = "pending"
    c = _public(db)
    tok = d["public_token"]
    assert c.post(f"/api/v1/public/invoices/{tok}/verify", json={"reference": "nope"}).status_code == 422
    wrong = "inv_" + "0" * 32 + "_0a1b2c3d"
    assert c.post(f"/api/v1/public/invoices/{tok}/verify", json={"reference": wrong}).status_code == 422
    with patch("app.services.paystack_storefront_service.verify_transaction",
               return_value={"verified": True, "status": "abandoned", "data": {"amount": 3000000}}):
        r = c.post(f"/api/v1/public/invoices/{tok}/verify", json={"reference": ref})
    assert r.json()["data"]["paid"] is False and not db.rows("receipts")
    with patch("app.services.paystack_storefront_service.verify_transaction",
               return_value={"verified": True, "status": "success", "data": {"amount": 100}}):
        r = c.post(f"/api/v1/public/invoices/{tok}/verify", json={"reference": ref})
    assert r.json()["data"]["paid"] is False                           # underpaid charge is not accepted

    def _mark(db, org_id, reference):
        db.rows("payment_links")[0]["status"] = "paid"
    with patch("app.services.paystack_storefront_service.verify_transaction",
               return_value={"verified": True, "status": "success", "data": {"amount": 3000000}}), \
         patch("app.services.paystack_storefront_service.mark_paid", side_effect=_mark), \
         patch("app.services.commerce_service.convert_lead_on_purchase"), \
         patch("app.services.invoice_delivery_service.send_receipt"):
        r = c.post(f"/api/v1/public/invoices/{tok}/verify", json={"reference": ref})
    data = r.json()["data"]
    assert data["paid"] is True and data["doc"]["status"] == "paid" and len(data["doc"]["receipts"]) == 1
    assert "id" not in data["doc"]["receipts"][0]


def test_public_receipt_pdf_by_token_only():
    db = _db()
    d = _issued(db)
    a = _pay(db, d, 100)
    tok = _row(db, "receipts", a["receipt"]["id"])["public_token"]
    c = _public(db)
    r = c.get(f"/api/v1/public/receipts/{tok}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert c.get("/api/v1/public/receipts/short/pdf").status_code == 404
    assert c.get("/api/v1/public/receipts/" + "x" * 32 + "/pdf").status_code == 404


def test_webhook_router_calls_invoice_hook():
    import inspect
    from app.routers import webhooks
    src = inspect.getsource(webhooks)
    assert "_inv_pay.on_payment_confirmed(db, org_id, reference)" in src
