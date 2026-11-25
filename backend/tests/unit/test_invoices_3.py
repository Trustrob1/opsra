"""INV-3: sending quotes/invoices (WhatsApp, web chat, email), the customer's /i/{token} page, quote accept, Get invoice button."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.test_invoices_1 import (  # noqa: F401  (_plan_allows is an autouse fixture)
    LEAD, ORG, OTHER, USER, _client, _db, _draft, _plan_allows,
)
from app.services import invoice_delivery_service as delivery
from app.services import invoice_service as inv


@pytest.fixture(autouse=True)
def _no_limits(monkeypatch):
    monkeypatch.setattr("app.services.webchat_service.rate_limited", lambda *a, **k: False)
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.ng")


def _issued(db, **kw):
    return inv.issue(db, ORG, USER, _draft(db, **kw)["id"])


def _public(db):
    from app.routers import public_invoices as r
    from app.database import get_supabase
    app = FastAPI()
    app.include_router(r.router, prefix="/api/v1")
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


# ───────────────────────────── links and wording ─────────────────────────────

def test_public_url_uses_token_only():
    db = _db()
    d = _issued(db)
    url = delivery.public_url(d)
    assert url == f"https://app.example.ng/i/{d['public_token']}"
    assert ORG not in url and d["id"] not in url


def test_message_text_quote_and_invoice():
    db = _db()
    q = _issued(db, doc_type="quote")
    assert "quote QT-0001" in delivery.message_text(q) and "accept" in delivery.message_text(q)
    i = _issued(db, due_date=str(date(2026, 12, 3)))
    t = delivery.message_text(i)
    assert t.startswith("Hello Ada,") and "INV-0001" in t and "₦30,000" in t and "3 Dec 2026" in t and "/i/" in t


def test_email_html_escapes_customer_text():
    db = _db()
    d = _issued(db, customer_name="<script>x</script> Bob")
    subject, text, body = delivery.email_bodies(d)
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert subject.startswith("Invoice INV-0001 from ")


# ───────────────────────────── send ─────────────────────────────

def test_cannot_send_a_draft_or_void():
    db = _db()
    d = _draft(db)
    with pytest.raises(inv.InvoiceError) as e:
        delivery.send(db, ORG, USER, d["id"], "email", "a@b.co")
    assert e.value.code == "INVALID_TRANSITION"
    i = _issued(db)
    inv.void(db, ORG, USER, i["id"], "wrong one")
    with pytest.raises(inv.InvoiceError):
        delivery.send(db, ORG, USER, i["id"], "email", "a@b.co")


def test_send_email_attaches_pdf_sets_reply_to_and_stamps_sent(monkeypatch):
    db = _db()
    inv.save_settings(db, ORG, {"email_reply_to": "sales@royalrest.ng"})
    d = _issued(db)
    sent = []
    monkeypatch.setitem(sys.modules, "resend", SimpleNamespace(api_key=None, Emails=SimpleNamespace(send=sent.append)))
    monkeypatch.setenv("RESEND_API_KEY", "k")
    out = delivery.send(db, ORG, USER, d["id"], "email")
    assert out["channel"] == "email" and out["link"].endswith(d["public_token"])
    (m,) = sent
    assert m["to"] == ["ada@example.com"] and m["reply_to"] == "sales@royalrest.ng"
    assert m["attachments"][0]["filename"] == "Invoice-INV-0001.pdf" and bytes(m["attachments"][0]["content"][:4]) == b"%PDF"
    assert "Royal Rest Mattress" in m["from"]
    row = [r for r in db.rows("invoices") if r["id"] == d["id"]][0]
    assert row["sent_at"]
    assert any(a["action"] == "invoice.sent" and a["new_value"]["channel"] == "email" for a in db.rows("audit_logs"))


def test_send_email_rejects_bad_address_and_header_injection(monkeypatch):
    db = _db()
    d = _issued(db)
    monkeypatch.setenv("RESEND_API_KEY", "k")
    for bad in ("not-an-email", "a@b.co\r\nBcc: x@y.z", "a@b.co, c@d.co"):
        with pytest.raises(inv.InvoiceError) as e:
            delivery.send(db, ORG, USER, d["id"], "email", bad)
        assert e.value.field == "email"


def test_send_email_failure_does_not_stamp(monkeypatch):
    db = _db()
    d = _issued(db)

    def boom(_):
        raise RuntimeError("resend down")
    monkeypatch.setitem(sys.modules, "resend", SimpleNamespace(api_key=None, Emails=SimpleNamespace(send=boom)))
    monkeypatch.setenv("RESEND_API_KEY", "k")
    with pytest.raises(inv.InvoiceError) as e:
        delivery.send(db, ORG, USER, d["id"], "email")
    assert e.value.status == 503
    assert not [r for r in db.rows("invoices") if r["id"] == d["id"]][0].get("sent_at")


def test_send_whatsapp_sends_pdf_then_link():
    db = _db()
    d = _issued(db)
    calls = {}
    with patch("app.services.whatsapp_service._is_lead_window_open", return_value=True), \
         patch("app.services.whatsapp_service.send_whatsapp_media_message", side_effect=lambda **k: calls.setdefault("media", k)), \
         patch("app.services.whatsapp_service.send_whatsapp_message", side_effect=lambda **k: calls.setdefault("text", k)):
        delivery.send(db, ORG, USER, d["id"], "whatsapp")
    assert calls["media"]["content_type"] == "application/pdf" and calls["media"]["lead_id"] == LEAD
    assert calls["media"]["org_id"] == ORG and calls["media"]["file_bytes"][:4] == b"%PDF"
    assert d["public_token"] in calls["text"]["payload"].content


def test_send_whatsapp_closed_window_is_refused_before_sending():
    db = _db()
    d = _issued(db)
    with patch("app.services.whatsapp_service._is_lead_window_open", return_value=False), \
         patch("app.services.whatsapp_service.send_whatsapp_media_message") as media:
        with pytest.raises(inv.InvoiceError) as e:
            delivery.send(db, ORG, USER, d["id"], "whatsapp")
    assert e.value.code == "WINDOW_CLOSED" and not media.called


def test_send_webchat_needs_active_chat():
    db = _db()
    d = _issued(db)
    with patch("app.services.webchat_service.latest_session_for_lead", return_value={"id": "s1", "status": "expired", "org_id": ORG}):
        with pytest.raises(inv.InvoiceError):
            delivery.send(db, ORG, USER, d["id"], "webchat")
    got = {}
    with patch("app.services.webchat_service.latest_session_for_lead", return_value={"id": "s1", "status": "active", "org_id": ORG, "lead_id": LEAD}), \
         patch("app.services.webchat_attachment_service.save_attachment", side_effect=lambda *a, **k: got.setdefault("file", (a, k))), \
         patch("app.services.webchat_service.rep_send", side_effect=lambda *a, **k: got.setdefault("text", a)):
        delivery.send(db, ORG, USER, d["id"], "webchat")
    (_db_, _s, kind, clean, data), kw = got["file"]
    assert kind == "document" and clean["mime"] == "application/pdf" and data[:4] == b"%PDF" and kw["sent_by"] == USER
    assert got["text"][1] == ORG and d["public_token"] in got["text"][3]


def test_send_options_explain_why_a_channel_is_off():
    db = _db()
    d = _issued(db)
    with patch("app.services.whatsapp_service._is_lead_window_open", return_value=False), \
         patch("app.services.webchat_service.latest_session_for_lead", return_value=None):
        o = delivery.options(db, ORG, inv.get_doc(db, ORG, d["id"]))
    assert o["link"].endswith(d["public_token"])
    assert o["channels"]["whatsapp"]["ok"] is False and "24 hours" in o["channels"]["whatsapp"]["reason"]
    assert o["channels"]["webchat"]["ok"] is False and o["channels"]["email"]["to"] == "ada@example.com"


def test_send_route_is_org_scoped_and_validates():
    db = _db()
    d = _issued(db)
    c = _client(db)
    assert c.post(f"/api/v1/invoices/{d['id']}/send", json={"channel": "fax"}).status_code == 422
    assert c.post(f"/api/v1/invoices/{d['id']}/send", json={"channel": "email", "org_id": OTHER}).status_code == 422
    for r in db.rows("invoices"):
        r["org_id"] = OTHER
    r = c.post(f"/api/v1/invoices/{d['id']}/send", json={"channel": "email", "email": "a@b.co"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


# ───────────────────────────── public page ─────────────────────────────

def test_public_view_has_no_internal_ids():
    db = _db()
    d = _issued(db)
    r = _public(db).get(f"/api/v1/public/invoices/{d['public_token']}")
    assert r.status_code == 200
    body = r.text
    for secret in (ORG, LEAD, USER, d["id"]):
        assert secret not in body
    v = r.json()["data"]
    assert v["number"] == "INV-0001" and v["total"] == 30000 and v["issuer"]["business_name"] == "Royal Rest Mattress"
    assert v["can_answer"] is False and v["items"][0]["description"] == "Pillow"


def test_public_draft_and_bad_token_are_404():
    db = _db()
    d = _draft(db)
    row = [r for r in db.rows("invoices") if r["id"] == d["id"]][0]
    row["public_token"] = "x" * 32
    c = _public(db)
    assert c.get("/api/v1/public/invoices/" + "x" * 32).status_code == 404
    assert c.get("/api/v1/public/invoices/short").status_code == 404
    assert c.get("/api/v1/public/invoices/" + "a" * 30 + "%27%20or%201=1").status_code == 404


def test_public_pdf():
    db = _db()
    d = _issued(db)
    r = _public(db).get(f"/api/v1/public/invoices/{d['public_token']}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "Invoice-INV-0001.pdf" in r.headers["content-disposition"]


def test_void_hides_bank_details():
    db = _db()
    inv.save_settings(db, ORG, {"bank_name": "GTBank", "account_number": "0123456789", "account_name": "Royal Rest"})
    d = _issued(db)
    inv.void(db, ORG, USER, d["id"], "duplicate")
    v = delivery.public_view(db, d["public_token"])
    assert v["voided"] and v["issuer"]["account_number"] is None


def test_customer_accepts_quote_once_and_team_gets_task():
    db = _db()
    q = _issued(db, doc_type="quote")
    c = _public(db)
    r = c.post(f"/api/v1/public/invoices/{q['public_token']}/accept")
    assert r.status_code == 200 and r.json()["data"]["status"] == "accepted" and r.json()["data"]["can_answer"] is False
    assert any("accepted quote QT-0001" in t["title"] and t["assigned_to"] == USER for t in db.rows("tasks"))
    r = c.post(f"/api/v1/public/invoices/{q['public_token']}/decline")
    assert r.status_code == 409
    assert inv.convert_quote(db, ORG, USER, q["id"])["status"] == "draft"


def test_customer_cannot_accept_expired_quote_or_an_invoice():
    db = _db()
    q = _issued(db, doc_type="quote")
    for r in db.rows("invoices"):
        if r["id"] == q["id"]:
            r["due_date"] = (date.today() - timedelta(days=1)).isoformat()
    c = _public(db)
    assert c.post(f"/api/v1/public/invoices/{q['public_token']}/accept").status_code == 400
    i = _issued(db)
    assert c.post(f"/api/v1/public/invoices/{i['public_token']}/accept").status_code == 400


def test_public_rate_limited(monkeypatch):
    db = _db()
    d = _issued(db)
    monkeypatch.setattr("app.services.webchat_service.rate_limited", lambda *a, **k: True)
    r = _public(db).get(f"/api/v1/public/invoices/{d['public_token']}")
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


# ───────────────────────────── Get invoice button ─────────────────────────────

def test_draft_for_lead_makes_one_draft_and_reuses_it():
    db = _db()
    a = delivery.draft_for_lead(db, ORG, LEAD)
    for r in db.rows("invoices"):            # Postgres fills created_at; the fake database does not
        r.setdefault("created_at", inv._now_iso())
    b = delivery.draft_for_lead(db, ORG, LEAD)
    assert a and a == b
    row = [r for r in db.rows("invoices") if r["id"] == a][0]
    assert row["status"] == "draft" and row["customer_name"] == "Ada Obi" and row["org_id"] == ORG


def test_draft_for_lead_respects_plan_and_never_raises():
    db = _db()
    with patch("app.services.plan_gate_service.allowed", return_value=False):
        assert delivery.draft_for_lead(db, ORG, LEAD) is None
    assert delivery.draft_for_lead(db, ORG, "not-a-lead-of-this-org") is None


def test_main_registers_public_route():
    import os
    os.environ.setdefault("SECRET_KEY", "x")
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/v1/public/invoices/{token}" in paths and "/api/v1/invoices/{doc_id}/send" in paths


def test_money_fields_allow_two_decimal_places_only():
    """Regression: Field(max_digits=...) crashed app start-up on pydantic 2.7.1 (Render, 25 Nov 2026)."""
    c = _client(_db())
    ok_line = {"description": "Pillow", "quantity": "1.50", "unit_price": "15000.25"}
    assert c.post("/api/v1/invoices", json={"doc_type": "invoice", "items": [ok_line]}).status_code == 201
    for bad in ({**ok_line, "quantity": "1.005"}, {**ok_line, "unit_price": "1.999"}):
        assert c.post("/api/v1/invoices", json={"doc_type": "invoice", "items": [bad]}).status_code == 422
    assert c.post("/api/v1/invoices", json={"doc_type": "invoice", "discount": "0.001"}).status_code == 422
    assert c.put("/api/v1/invoices/settings", json={"vat_rate": "7.125"}).status_code == 422
    assert c.put("/api/v1/invoices/settings", json={"vat_rate": "7.50"}).status_code == 200
