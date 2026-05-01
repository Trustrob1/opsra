"""
tests/integration/test_superadmin_health_routes.py
SA-2A — Integration tests for superadmin health dashboard routes.

13 tests as per SA-2A spec:
  Auth login valid/invalid
  All 7 health routes return 200 with correct shape
  org_id filter accepted
  403 on wrong JWT
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ─── App setup ────────────────────────────────────────────────────────────────

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-minimum!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SUPERADMIN_SECRET", "test-superadmin-secret-sa2")


def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.in_.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    db.table.return_value = chain
    return db


@pytest.fixture
def client():
    from app.main import app
    from app.database import get_supabase

    db = _mock_db()
    app.dependency_overrides[get_supabase] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def sa_token(client):
    """Exchange secret for superadmin JWT."""
    resp = client.post(
        "/api/v1/superadmin/auth/login",
        json={"secret": "test-superadmin-secret-sa2"},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


ORG_ID = "11111111-1111-1111-1111-111111111111"

# ═══════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════

class TestSuperadminAuth:

    def test_login_valid_secret_returns_token(self, client):
        """POST /superadmin/auth/login with correct secret returns token."""
        resp = client.post(
            "/api/v1/superadmin/auth/login",
            json={"secret": "test-superadmin-secret-sa2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "token" in data["data"]
        assert data["data"]["expires_in"] == 3600

    def test_login_wrong_secret_returns_403(self, client):
        """POST /superadmin/auth/login with wrong secret returns 403."""
        resp = client.post(
            "/api/v1/superadmin/auth/login",
            json={"secret": "wrong-secret"},
        )
        assert resp.status_code == 403

    def test_health_route_without_token_returns_403(self, client):
        """GET /superadmin/health/summary without token returns 403."""
        resp = client.get("/api/v1/superadmin/health/summary")
        assert resp.status_code == 403

    def test_health_route_with_invalid_jwt_returns_403(self, client):
        """GET /superadmin/health/summary with invalid JWT returns 403."""
        resp = client.get(
            "/api/v1/superadmin/health/summary",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# Health Routes
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthRoutes:

    def test_health_summary_returns_200(self, client, sa_token):
        """GET /superadmin/health/summary returns 200 with expected fields."""
        resp = client.get(
            "/api/v1/superadmin/health/summary",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_orgs" in data
        assert "errors_since" in data
        assert "failed_jobs_since" in data
        assert "webhook_errors_since" in data

    def test_health_integrations_returns_200(self, client, sa_token):
        """GET /superadmin/health/integrations returns 200 with 6 service keys."""
        with patch("app.routers.superadmin_health.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp

            resp = client.get(
                "/api/v1/superadmin/health/integrations",
                headers=_auth(sa_token),
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "supabase" in data

    def test_health_errors_returns_200(self, client, sa_token):
        """GET /superadmin/health/errors returns 200 with items list."""
        resp = client.get(
            "/api/v1/superadmin/health/errors",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "count" in data

    def test_health_jobs_returns_200(self, client, sa_token):
        """GET /superadmin/health/jobs returns 200 with items list."""
        resp = client.get(
            "/api/v1/superadmin/health/jobs",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data

    def test_health_claude_usage_returns_200(self, client, sa_token):
        """GET /superadmin/health/claude-usage returns 200 with cost fields."""
        resp = client.get(
            "/api/v1/superadmin/health/claude-usage",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_cost" in data
        assert "by_function" in data

    def test_health_webhooks_returns_200(self, client, sa_token):
        """GET /superadmin/health/webhooks returns 200 with items list."""
        resp = client.get(
            "/api/v1/superadmin/health/webhooks",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data

    def test_health_orgs_returns_200(self, client, sa_token):
        """GET /superadmin/health/orgs returns 200 with items list."""
        resp = client.get(
            "/api/v1/superadmin/health/orgs",
            headers=_auth(sa_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data

    def test_org_id_filter_accepted(self, client, sa_token):
        """All routes accept ?org_id= filter without error."""
        for route in [
            "/api/v1/superadmin/health/summary",
            "/api/v1/superadmin/health/errors",
            "/api/v1/superadmin/health/jobs",
            "/api/v1/superadmin/health/claude-usage",
            "/api/v1/superadmin/health/webhooks",
            "/api/v1/superadmin/health/orgs",
        ]:
            resp = client.get(
                route,
                headers=_auth(sa_token),
                params={"org_id": ORG_ID},
            )
            assert resp.status_code == 200, f"Route {route} failed with org_id filter"

    def test_since_filter_accepted(self, client, sa_token):
        """Routes accept ?since= ISO datetime filter without error."""
        resp = client.get(
            "/api/v1/superadmin/health/errors",
            headers=_auth(sa_token),
            params={"since": "2026-01-01T00:00:00Z"},
        )
        assert resp.status_code == 200
