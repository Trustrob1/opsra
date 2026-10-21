"""
tests/integration/test_login_code_routes.py
LOGIN-1 - POST /auth/request-link with an email, and POST /auth/login/verify.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from app.services import builder_login_service as svc
from tests.funnel_fake_db import FakeDB

BUILDER = {"id": "b1", "org_id": "org-1", "email": "ada@example.com", "full_name": "Ada Okafor", "status": "active"}
URL = "/api/v1/builder/auth"


@pytest.fixture
def client():
    original = app.dependency_overrides.copy()
    for b in (builder_portal._request_link_ip_hits, builder_portal._request_link_phone_hits, builder_portal._login_verify_hits):
        b.clear()
    db = FakeDB(site_builders=[dict(BUILDER)], site_login_codes=[], site_editor_tokens=[])
    app.dependency_overrides[get_supabase] = lambda: db
    c = TestClient(app, raise_server_exceptions=False)
    c.db = db
    yield c
    app.dependency_overrides = original


def test_email_request_queues_a_code_and_gives_one_reply(client, monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "send_login_code", lambda email: sent.append(email))
    a = client.post(f"{URL}/request-link", json={"email": "Ada@Example.com"})
    b = client.post(f"{URL}/request-link", json={"email": "someone.else@example.com"})
    assert a.status_code == b.status_code == 200 and a.json()["message"] == b.json()["message"]
    assert sent == ["ada@example.com", "someone.else@example.com"]


def test_bad_email_is_422_and_phone_still_works(client, monkeypatch):
    assert client.post(f"{URL}/request-link", json={"email": "not-an-email"}).status_code == 422
    monkeypatch.setattr(svc, "send_login_link", lambda phone: None)
    assert client.post(f"{URL}/request-link", json={"phone": "08031234567"}).status_code == 200


def test_email_request_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(svc, "send_login_code", lambda email: None)
    codes = [client.post(f"{URL}/request-link", json={"email": "ada@example.com"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_correct_code_returns_a_single_use_token(client, monkeypatch):
    mailed = []
    monkeypatch.setattr(svc, "_send_code_email", lambda to, code, url, first: mailed.append(code))
    monkeypatch.setattr("app.database.get_supabase", lambda: client.db)
    svc.send_login_code("ada@example.com")
    r = client.post(f"{URL}/login/verify", json={"email": "ada@example.com", "code": mailed[0]})
    assert r.status_code == 200 and r.json()["data"]["token"] and r.json()["data"]["builder"]["id"] == "b1"
    again = client.post(f"{URL}/login/verify", json={"email": "ada@example.com", "code": mailed[0]})
    assert again.status_code == 401


def test_wrong_code_is_401_with_one_message(client):
    r = client.post(f"{URL}/login/verify", json={"email": "ada@example.com", "code": "123456"})
    n = client.post(f"{URL}/login/verify", json={"email": "nobody@example.com", "code": "123456"})
    assert r.status_code == n.status_code == 401
    assert r.json()["detail"]["message"] == n.json()["detail"]["message"]


def test_verify_is_rate_limited(client):
    codes = [client.post(f"{URL}/login/verify", json={"email": "ada@example.com", "code": "123456"}).status_code for _ in range(17)]
    assert codes[-1] == 429
