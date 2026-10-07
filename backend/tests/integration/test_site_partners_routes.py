"""
tests/integration/test_site_partners_routes.py
PARTNER-1A — routers/site_partners.py: public permanent-link route and the staff partner routes.
Hits real HTTP routes via TestClient; get_supabase and get_current_org overridden (Patterns 3, 28).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import site_partners as router_mod
from app.services import site_partner_service as svc
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-0000000000aa"


def _org(template="owner"):
    return {"id": "u1", "org_id": ORG, "role": template, "roles": {"template": template}}


@pytest.fixture
def client_db():
    db = FakeDB()
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org("owner")
    router_mod._open_hits.clear()
    yield TestClient(app), db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _make(client):
    r = client.post("/api/v1/partners", json={"full_name": "Ada Agent", "phone": "08031234567", "agency_name": "Ada Regs"})
    assert r.status_code == 201
    return r.json()["data"]


class TestStaffRoutes:
    def test_create_list_suspend_reactivate(self, client_db):
        client, db = client_db
        p = _make(client)
        assert p["link_url"].endswith("/p/" + p["link_slug"])
        listed = client.get("/api/v1/partners").json()["data"]
        assert len(listed) == 1
        assert client.post(f"/api/v1/partners/{p['id']}/suspend").status_code == 200
        assert db.rows("site_partners")[0]["status"] == "suspended"
        assert client.post(f"/api/v1/partners/{p['id']}/reactivate").status_code == 200
        assert db.rows("site_partners")[0]["status"] == "active"

    def test_duplicate_phone_422(self, client_db):
        client, _ = client_db
        _make(client)
        r = client.post("/api/v1/partners", json={"full_name": "Ada Again", "phone": "08031234567"})
        assert r.status_code == 422

    def test_unknown_partner_404(self, client_db):
        client, _ = client_db
        assert client.post("/api/v1/partners/nope/suspend").status_code == 404

    def test_read_only_role_cannot_write(self, client_db):
        client, _ = client_db
        app.dependency_overrides[get_current_org] = lambda: _org("admin")
        assert client.get("/api/v1/partners").status_code == 200
        r = client.post("/api/v1/partners", json={"full_name": "Ada Agent", "phone": "08031234567"})
        assert r.status_code == 403

    def test_no_role_forbidden(self, client_db):
        client, _ = client_db
        app.dependency_overrides[get_current_org] = lambda: _org("sales_agent")
        assert client.get("/api/v1/partners").status_code == 403

    def test_bad_body_422(self, client_db):
        client, _ = client_db
        assert client.post("/api/v1/partners", json={"full_name": "A", "phone": "1"}).status_code == 422


class TestPublicLink:
    def test_open_returns_form_url_and_needs_no_auth(self, client_db):
        client, db = client_db
        p = _make(client)
        app.dependency_overrides.pop(get_current_org, None)       # public route: no login
        r = client.post(f"/api/v1/partner-links/{p['link_slug']}/open")
        assert r.status_code == 200
        assert "/f/" in r.json()["data"]["url"]
        assert len(db.rows("site_brief_forms")) == 1

    def test_unknown_slug_404(self, client_db):
        client, _ = client_db
        assert client.post("/api/v1/partner-links/doesnotexist/open").status_code == 404

    def test_suspended_410(self, client_db):
        client, _ = client_db
        p = _make(client)
        client.post(f"/api/v1/partners/{p['id']}/suspend")
        assert client.post(f"/api/v1/partner-links/{p['link_slug']}/open").status_code == 410

    def test_busy_429(self, client_db, monkeypatch):
        client, _ = client_db
        monkeypatch.setattr(svc, "MAX_UNSUBMITTED_FORMS_PER_DAY", 0)
        p = _make(client)
        assert client.post(f"/api/v1/partner-links/{p['link_slug']}/open").status_code == 200
        assert client.post(f"/api/v1/partner-links/{p['link_slug']}/open").status_code == 429

    def test_per_ip_rate_limit_429(self, client_db):
        client, _ = client_db
        codes = [client.post("/api/v1/partner-links/abcdefgh/open").status_code for _ in range(router_mod._OPEN_LIMIT_PER_MIN + 2)]
        assert codes[-1] == 429 and codes[0] == 404

    def test_form_is_a_normal_client_form_owned_by_partner_builder(self, client_db):
        client, db = client_db
        p = _make(client)
        client.post(f"/api/v1/partner-links/{p['link_slug']}/open")
        form = db.rows("site_brief_forms")[0]
        assert form["builder_id"] == p["builder_id"] and form["audience"] == "client"
        assert form["token_hash"] and "token" not in form       # only the hash is stored
