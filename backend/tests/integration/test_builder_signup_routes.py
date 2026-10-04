"""
tests/integration/test_builder_signup_routes.py
SITE-WEB-1 - POST /api/v1/builder/auth/signup/start and /verify, end to end through the HTTP routes with an
in-memory database, then the new builder's session opens the portal. Also pins the client-IP helper.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from app.services import builder_login_service, builder_signup_service as su, site_access_service
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-000000002222"
BODY = {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "08030000001", "account_type": "owner", "accept_terms": True}


def _db(open_signup=True, builders=None):
    return FakeDB(
        whatsapp_numbers=[{"id": "n1", "org_id": ORG, "wa_sales_mode": "site_builder"}],
        site_builder_settings=[{"org_id": ORG, "enabled": True, "members_only": not open_signup, "pricing": {}}],
        site_builders=builders or [], site_signup_requests=[], site_events=[], sites=[], site_editor_tokens=[],
    )


@pytest.fixture
def api(monkeypatch):
    sent = []
    monkeypatch.setattr(su, "_send_code_email", lambda email, first, code: sent.append(code) or True)

    def fake_lead(db, org, b):
        db.table("site_builders").update({"lead_id": "lead-1"}).eq("id", b["id"]).execute()
        return "lead-1"
    monkeypatch.setattr(site_access_service, "ensure_lead", fake_lead)
    holder = {"codes": sent}

    def use(db):
        holder["db"] = db
        app.dependency_overrides[get_supabase] = lambda: db
        return TestClient(app, raise_server_exceptions=False)
    holder["use"] = use
    yield holder
    app.dependency_overrides.pop(get_supabase, None)


def _sign_up(c, api):
    rid = c.post("/api/v1/builder/auth/signup/start", json=BODY).json()["data"]["request_id"]
    v = c.post("/api/v1/builder/auth/signup/verify", json={"request_id": rid, "code": api["codes"][0]})
    return v


def test_full_sign_up_then_portal_access(api):
    c = api["use"](_db())
    r = c.post("/api/v1/builder/auth/signup/start", json=BODY)
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["request_id"]
    assert r.json()["data"]["email_hint"] == "a***@example.com"
    assert "token" not in r.text

    v = c.post("/api/v1/builder/auth/signup/verify", json={"request_id": rid, "code": api["codes"][0]})
    assert v.status_code == 200, v.text
    assert "access_token" not in v.text                                   # no session until /auth/exchange
    ex = c.post("/api/v1/builder/auth/exchange", json={"token": v.json()["data"]["token"]})
    assert ex.status_code == 200, ex.text
    token = ex.json()["data"]["access_token"]
    assert token and ex.json()["data"]["builder"]["full_name"] == "Ada Obi"

    me = c.get("/api/v1/builder/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["data"]["email"] == "ada@example.com"
    acc = c.get("/api/v1/builder/access", headers={"Authorization": f"Bearer {token}"})
    assert acc.json()["data"]["used"] == 0 and acc.json()["data"]["free_sites"] == 3
    row = api["db"].rows("site_builders")[0]
    assert row["account_type"] == "owner" and row["source"] == "web_signup"


def test_the_sign_in_token_works_once(api):
    c = api["use"](_db())
    raw = _sign_up(c, api).json()["data"]["token"]
    assert c.post("/api/v1/builder/auth/exchange", json={"token": raw}).status_code == 200
    assert c.post("/api/v1/builder/auth/exchange", json={"token": raw}).status_code == 401


def test_a_new_builder_token_cannot_call_staff_routes(api):
    c = api["use"](_db())
    raw = _sign_up(c, api).json()["data"]["token"]
    token = c.post("/api/v1/builder/auth/exchange", json={"token": raw}).json()["data"]["access_token"]
    for path in ("/api/v1/sites/overview", "/api/v1/sites/builders", "/api/v1/sites/settings"):
        assert c.get(path, headers={"Authorization": f"Bearer {token}"}).status_code in (401, 403)


def test_closed_sign_up_is_a_403(api):
    c = api["use"](_db(open_signup=False))
    r = c.post("/api/v1/builder/auth/signup/start", json=BODY)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "SIGNUP_CLOSED"


def test_validation_is_a_422(api):
    c = api["use"](_db())
    assert c.post("/api/v1/builder/auth/signup/start", json={**BODY, "email": "nope"}).status_code == 422
    assert c.post("/api/v1/builder/auth/signup/start", json={**BODY, "accept_terms": False}).status_code == 422


def test_wrong_code_is_a_422_and_gives_no_session(api):
    c = api["use"](_db())
    rid = c.post("/api/v1/builder/auth/signup/start", json=BODY).json()["data"]["request_id"]
    wrong = "000000" if api["codes"][0] != "000000" else "111111"
    r = c.post("/api/v1/builder/auth/signup/verify", json={"request_id": rid, "code": wrong})
    assert r.status_code == 422 and "access_token" not in r.text
    assert api["db"].rows("site_builders") == []


def test_existing_number_gets_the_same_reply_and_a_sign_in_link(api, monkeypatch):
    sent_to = []
    monkeypatch.setattr(builder_login_service, "send_login_link", lambda phone: sent_to.append(phone))
    existing = {"id": "b-1", "org_id": ORG, "phone_number": "2348030000001", "full_name": "Old", "status": "active"}
    c = api["use"](_db(builders=[existing]))
    r = c.post("/api/v1/builder/auth/signup/start", json=BODY)
    assert r.status_code == 200 and set(r.json()["data"]) == {"request_id", "email_hint"}
    assert api["codes"] == [] and sent_to == ["2348030000001"]


def test_rate_limit_is_a_429(api):
    c = api["use"](_db())
    for i in range(su.PER_EMAIL_HOUR):
        assert c.post("/api/v1/builder/auth/signup/start", json={**BODY, "phone": f"0803000010{i}"}).status_code == 200
    assert c.post("/api/v1/builder/auth/signup/start", json={**BODY, "phone": "08030000199"}).status_code == 429


def test_client_ip_uses_the_address_the_proxy_appended():
    class Req:
        def __init__(self, xff, host="10.0.0.1"):
            self.headers = {"x-forwarded-for": xff} if xff is not None else {}
            self.client = type("C", (), {"host": host})()
    assert builder_portal._client_ip(Req("6.6.6.6, 102.89.1.1")) == "102.89.1.1"
    assert builder_portal._client_ip(Req("102.89.1.1")) == "102.89.1.1"
    assert builder_portal._client_ip(Req(None)) == "10.0.0.1"
