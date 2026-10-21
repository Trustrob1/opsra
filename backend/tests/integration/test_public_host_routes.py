"""tests/integration/test_public_host_routes.py - HOST-2 public routes: no sign-in needed, errors map to HTTP codes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import public_host
from app.services import host_public_service as svc
from tests.unit.test_host_public_service import db as make_db


@pytest.fixture
def client():
    original = app.dependency_overrides.copy()
    public_host._rate_store.clear()
    svc._cache.clear()
    app.dependency_overrides[get_supabase] = lambda: make_db()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def test_pricing_needs_no_login(client):
    r = client.get("/api/v1/public/host/pricing")
    assert r.status_code == 200 and r.json()["data"]["endings"][0]["tld"] == ".ng"


def test_domain_check_available(client, monkeypatch):
    from app.services import domain_check_service as dcs
    dcs._rate_hits.clear(); dcs._cache.clear()
    monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: True)
    r = client.get("/api/v1/public/host/domain-check", params={"domain": "adaezestyles.com"})
    assert r.status_code == 200 and r.json()["data"]["price"]["first_year"]["total"] > 0


def test_bad_domain_is_422(client):
    assert client.get("/api/v1/public/host/domain-check", params={"domain": "nonsense"}).status_code == 422


def test_missing_domain_is_422(client):
    assert client.get("/api/v1/public/host/domain-check").status_code == 422


def test_overall_rate_limit(client, monkeypatch):
    monkeypatch.setattr(public_host, "_LIMIT", 2)
    codes = [client.get("/api/v1/public/host/pricing").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
