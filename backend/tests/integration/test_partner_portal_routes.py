"""
tests/integration/test_partner_portal_routes.py
PARTNER-1B — public apply/sign-in routes, partner-session routes, staff application routes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import partner_portal as portal
from app.services import builder_auth_service
from app.services import site_partner_apply_service as svc
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-0000000000aa"
GOOD = {"full_name": "Ada Obi", "email": "ada@example.com", "phone": "08030000001", "agency_name": "Ada Regs",
        "accept_terms": True}


def _org(t="owner"):
    return {"id": "u1", "org_id": ORG, "role": t, "roles": {"template": t}}


@pytest.fixture
def ctx(monkeypatch):
    db = FakeDB(whatsapp_numbers=[{"id": "n1", "org_id": ORG, "wa_sales_mode": "site_builder"}], site_builders=[],
                site_partners=[], site_partner_applications=[], sites=[], site_editor_tokens=[])
    sent = []
    monkeypatch.setattr(svc, "_send_email", lambda to, s, t: sent.append((to, s, t)) or True)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org("owner")
    portal._hits.clear()
    yield TestClient(app), db, sent
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _applied(client, sent):
    r = client.post("/api/v1/partner-portal/apply/start", json=GOOD)
    assert r.status_code == 200
    code = sent[-1][1].rsplit(": ", 1)[1]
    v = client.post("/api/v1/partner-portal/apply/verify", json={"request_id": r.json()["data"]["request_id"], "code": code})
    assert v.status_code == 200
    return client.get("/api/v1/partners/applications").json()["data"][0]


def test_full_flow_apply_approve_session_referrals(ctx):
    client, db, sent = ctx
    a = _applied(client, sent)
    assert client.post(f"/api/v1/partners/applications/{a['id']}/approve").status_code == 200
    p = db.rows("site_partners")[0]
    tok = builder_auth_service.issue_builder_session(builder_id=p["builder_id"], org_id=ORG)["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/partner-portal/me", headers=h).json()["data"]
    assert me["link_url"].endswith("/p/" + p["link_slug"])
    assert client.get("/api/v1/partner-portal/referrals", headers=h).json()["data"] == []


def test_suspended_partner_is_locked_out(ctx):
    client, db, sent = ctx
    a = _applied(client, sent)
    client.post(f"/api/v1/partners/applications/{a['id']}/approve")
    p = db.rows("site_partners")[0]
    client.post(f"/api/v1/partners/{p['id']}/suspend")
    tok = builder_auth_service.issue_builder_session(builder_id=p["builder_id"], org_id=ORG)["access_token"]
    assert client.get("/api/v1/partner-portal/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_a_plain_builder_is_not_a_partner(ctx):
    client, db, _ = ctx
    db.table("site_builders").insert({"id": "b9", "org_id": ORG, "phone_number": "2348099999999", "full_name": "B",
                                      "status": "active"}).execute()
    tok = builder_auth_service.issue_builder_session(builder_id="b9", org_id=ORG)["access_token"]
    assert client.get("/api/v1/partner-portal/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_portal_requires_a_session(ctx):
    client, _, _ = ctx
    assert client.get("/api/v1/partner-portal/me").status_code == 401
    assert client.get("/api/v1/partner-portal/referrals").status_code == 401


def test_request_link_same_reply_for_unknown_and_validates(ctx):
    client, _, _ = ctx
    r = client.post("/api/v1/partner-portal/auth/request-link", json={"identifier": "nobody@example.com"})
    assert r.status_code == 200 and r.json()["data"]["sent"] is True
    assert client.post("/api/v1/partner-portal/auth/request-link", json={"identifier": ""}).status_code == 422


def test_request_link_rate_limited_per_identifier(ctx):
    client, _, _ = ctx
    codes = [client.post("/api/v1/partner-portal/auth/request-link", json={"identifier": "x@example.com"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_wrong_verify_code_422(ctx):
    client, _, _ = ctx
    r = client.post("/api/v1/partner-portal/apply/start", json=GOOD).json()["data"]
    assert client.post("/api/v1/partner-portal/apply/verify", json={"request_id": r["request_id"], "code": "000000"}).status_code == 422


def test_staff_decline_and_role_gate(ctx):
    client, _, sent = ctx
    a = _applied(client, sent)
    app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
    assert client.post(f"/api/v1/partners/applications/{a['id']}/decline").status_code == 403
    assert client.get("/api/v1/partners/applications").status_code == 403
    app.dependency_overrides[get_current_org] = lambda: _org("owner")
    assert client.post(f"/api/v1/partners/applications/{a['id']}/decline").status_code == 200
