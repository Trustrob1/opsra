"""
tests/integration/test_builder_remember.py
HOST-4 - stay signed in: the cookie set at sign-in, POST /auth/session, POST /auth/logout, and the cookie rules.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from app.services import builder_remember_service as rem, builder_signup_service as signup
from tests.funnel_fake_db import FakeDB

BUILDER = {"id": "b1", "org_id": "org-1", "email": "ada@example.com", "full_name": "Ada Okafor", "status": "active"}
URL = "/api/v1/builder/auth"


@pytest.fixture
def client():
    original = app.dependency_overrides.copy()
    builder_portal._session_hits.clear()
    builder_portal._exchange_hits.clear()
    db = FakeDB(site_builders=[dict(BUILDER)], site_builder_sessions=[], site_editor_tokens=[])
    app.dependency_overrides[get_supabase] = lambda: db
    c = TestClient(app, raise_server_exceptions=False, base_url="https://api.opsra.test")
    c.db = db
    yield c
    app.dependency_overrides = original


def _sign_in(client):
    token = signup.mint_login_token(client.db, dict(BUILDER))
    return client.post(f"{URL}/exchange", json={"token": token}, headers={"origin": "https://opsra.test"})


def test_sign_in_sets_a_30_day_http_only_cookie_and_stores_only_a_hash(client):
    r = _sign_in(client)
    assert r.status_code == 200
    header = r.headers["set-cookie"].lower()
    assert "opsra_bsess=" in header and "httponly" in header and "secure" in header and "samesite=lax" in header
    assert f"max-age={30 * 86400}" in header
    raw = r.cookies.get("opsra_bsess")
    stored = (client.db.table("site_builder_sessions").select("*").execute()).data
    assert len(stored) == 1 and stored[0]["token_hash"] != raw and raw not in str(stored[0])


def test_cookie_restores_a_fresh_session_without_a_link(client):
    _sign_in(client)
    r = client.post(f"{URL}/session")
    assert r.status_code == 200 and r.json()["data"]["access_token"] and r.json()["data"]["builder"]["id"] == "b1"


def test_no_cookie_or_unknown_cookie_is_401(client):
    assert client.post(f"{URL}/session").status_code == 401
    client.cookies.set("opsra_bsess", "not-a-real-value")
    assert client.post(f"{URL}/session").status_code == 401


def test_logout_revokes_the_session(client):
    raw = _sign_in(client).cookies.get("opsra_bsess")
    assert client.post(f"{URL}/logout").status_code == 200
    client.cookies.clear()
    client.cookies.set("opsra_bsess", raw)
    assert client.post(f"{URL}/session").status_code == 401


def test_expired_and_suspended_are_refused():
    db = FakeDB(site_builders=[dict(BUILDER)], site_builder_sessions=[])
    raw = rem.create(db, builder_id="b1", org_id="org-1")
    assert rem.restore(db, raw)["id"] == "b1"
    db.table("site_builder_sessions").update({"expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}).eq("token_hash", rem._hash(raw)).execute()
    assert rem.restore(db, raw) is None
    raw2 = rem.create(db, builder_id="b1", org_id="org-1")
    db.table("site_builders").update({"status": "suspended"}).eq("id", "b1").execute()
    assert rem.restore(db, raw2) is None


def test_each_use_slides_the_expiry():
    db = FakeDB(site_builders=[dict(BUILDER)], site_builder_sessions=[])
    raw = rem.create(db, builder_id="b1", org_id="org-1")
    db.table("site_builder_sessions").update({"expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}).eq("token_hash", rem._hash(raw)).execute()
    rem.restore(db, raw)
    row = (db.table("site_builder_sessions").select("*").execute()).data[0]
    assert datetime.fromisoformat(row["expires_at"]) > datetime.now(timezone.utc) + timedelta(days=29)


def test_cookie_rules():
    same = rem.cookie_kwargs("https://opsra.com", "api.opsra.com")
    assert same["samesite"] == "lax" and same["secure"] and same["httponly"]
    cross = rem.cookie_kwargs("https://opsra.com", "opsra-api.onrender.com")
    assert cross["samesite"] == "none" and cross["secure"]
    ng = rem.cookie_kwargs("https://opsra.com.ng", "api.opsra.com.ng")
    assert ng["samesite"] == "lax"
    other_ng = rem.cookie_kwargs("https://a.com.ng", "b.com.ng")
    assert other_ng["samesite"] == "none"
    dev = rem.cookie_kwargs("http://localhost:5173", "localhost:8000")
    assert dev["secure"] is False and dev["samesite"] == "lax"
