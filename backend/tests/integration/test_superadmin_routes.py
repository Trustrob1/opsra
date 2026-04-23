"""
tests/integration/test_superadmin_routes.py
Integration tests for POST /api/v1/superadmin/organisations — ORG-ONBOARDING-A.

Classes:
  TestSuperAdminAuth          (2 tests)
  TestProvisionSuccess        (1 test)
  TestProvisionConflicts      (2 tests)
  TestProvisionValidation     (2 tests)
  TestProvisionCleanup        (1 test)

Total: 8 tests

Patterns:
  Pattern 32 — autouse fixture pops overrides in teardown
  Pattern 24 — valid UUID constants
  Pattern 38 — Supabase Auth via httpx direct REST
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi.testclient import TestClient

ORG_ID  = "00000000-0000-0000-0000-000000000010"
USER_ID = "00000000-0000-0000-0000-000000000011"
ROLE_ID = "00000000-0000-0000-0000-000000000012"

VALID_SECRET = "test-superadmin-secret"

VALID_PAYLOAD = {
    "org_name": "Acme Corp",
    "slug": "acme-corp",
    "industry": "SaaS",
    "timezone": "Africa/Lagos",
    "ticket_prefix": "ACM",
    "subscription_tier": "starter",
    "owner_email": "owner@acme.com",
    "owner_full_name": "Acme Owner",
    "owner_password": "securepassword123",
    "owner_whatsapp": "+2348012345678",
}


def _mock_db_success():
    db = MagicMock()
    call_count = {"roles": 0}

    def _table(name):
        mock = MagicMock()
        if name == "organisations":
            mock.select.return_value.eq.return_value.execute.return_value.data = []
            mock.insert.return_value.execute.return_value.data = [{"id": ORG_ID}]
            mock.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "roles":
            def _role_insert(data):
                call_count["roles"] += 1
                rid = ROLE_ID if data.get("template") == "owner" else f"role-{call_count['roles']}"
                m = MagicMock()
                m.execute.return_value.data = [{"id": rid}]
                return m
            mock.insert.side_effect = _role_insert
        elif name == "users":
            mock.insert.return_value.execute.return_value.data = [{"id": USER_ID}]
        return mock

    db.table.side_effect = _table
    return db


def _auth_list_empty():
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"users": []}
    return r


def _auth_create_success():
    r = MagicMock()
    r.status_code = 201
    r.json.return_value = {"id": USER_ID}
    return r


def _auth_create_fail():
    r = MagicMock()
    r.status_code = 500
    r.text = "Internal Server Error"
    return r


# ============================================================
# TestSuperAdminAuth
# ============================================================

class TestSuperAdminAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def test_missing_secret_header_returns_403(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        from app.main import app
        with TestClient(app) as c:
            resp = c.post("/api/v1/superadmin/organisations", json=VALID_PAYLOAD)
        assert resp.status_code == 403

    def test_wrong_secret_returns_403(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/superadmin/organisations",
                json=VALID_PAYLOAD,
                headers={"X-Superadmin-Secret": "wrong-secret"},
            )
        assert resp.status_code == 403


# ============================================================
# TestProvisionSuccess
# ============================================================

class TestProvisionSuccess:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = _mock_db_success()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def test_valid_payload_returns_200_with_org_and_user(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

        async def _mock_request(self_client, method, url, **kwargs):
            if method == "GET":
                return _auth_list_empty()
            return _auth_create_success()

        from app.main import app
        with patch("httpx.AsyncClient.request", _mock_request):
            with TestClient(app) as c:
                resp = c.post(
                    "/api/v1/superadmin/organisations",
                    json=VALID_PAYLOAD,
                    headers={"X-Superadmin-Secret": VALID_SECRET},
                )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["org_id"]      == ORG_ID
        assert data["user_id"]     == USER_ID
        assert data["slug"]        == "acme-corp"
        assert data["owner_email"] == "owner@acme.com"

        # Confirm 7 roles were inserted
        role_inserts = [
            c for c in self.mock_db.table.call_args_list
            if c[0][0] == "roles"
        ]
        assert len(role_inserts) == 7


# ============================================================
# TestProvisionConflicts
# ============================================================

class TestProvisionConflicts:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def test_duplicate_slug_returns_409(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

        def _table(name):
            mock = MagicMock()
            if name == "organisations":
                mock.select.return_value.eq.return_value.execute.return_value.data = [{"id": "existing"}]
            return mock

        self.mock_db.table.side_effect = _table

        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/superadmin/organisations",
                json=VALID_PAYLOAD,
                headers={"X-Superadmin-Secret": VALID_SECRET},
            )
        assert resp.status_code == 409
        assert "slug" in resp.json()["detail"]

    def test_duplicate_email_returns_409(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

        def _table(name):
            mock = MagicMock()
            if name == "organisations":
                mock.select.return_value.eq.return_value.execute.return_value.data = []
            return mock

        self.mock_db.table.side_effect = _table

        async def _mock_request(self_client, method, url, **kwargs):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"users": [{"email": "owner@acme.com", "id": "existing-user"}]}
            return r

        from app.main import app
        with patch("httpx.AsyncClient.request", _mock_request):
            with TestClient(app) as c:
                resp = c.post(
                    "/api/v1/superadmin/organisations",
                    json=VALID_PAYLOAD,
                    headers={"X-Superadmin-Secret": VALID_SECRET},
                )
        assert resp.status_code == 409
        assert "email" in resp.json()["detail"]


# ============================================================
# TestProvisionValidation
# ============================================================

class TestProvisionValidation:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def test_invalid_slug_uppercase_returns_422(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/superadmin/organisations",
                json={**VALID_PAYLOAD, "slug": "Acme-Corp"},
                headers={"X-Superadmin-Secret": VALID_SECRET},
            )
        assert resp.status_code == 422

    def test_invalid_ticket_prefix_lowercase_returns_422(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/superadmin/organisations",
                json={**VALID_PAYLOAD, "ticket_prefix": "acm"},
                headers={"X-Superadmin-Secret": VALID_SECRET},
            )
        assert resp.status_code == 422


# ============================================================
# TestProvisionCleanup
# ============================================================

class TestProvisionCleanup:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def test_org_row_deleted_when_auth_user_creation_fails(self, monkeypatch):
        monkeypatch.setenv("SUPERADMIN_SECRET", VALID_SECRET)
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")

        deleted_org_ids = []

        def _table(name):
            mock = MagicMock()
            if name == "organisations":
                mock.select.return_value.eq.return_value.execute.return_value.data = []
                mock.insert.return_value.execute.return_value.data = [{"id": ORG_ID}]

                def _delete():
                    m = MagicMock()
                    def _eq(field, val):
                        deleted_org_ids.append(val)
                        return MagicMock(execute=MagicMock(return_value=MagicMock()))
                    m.eq = _eq
                    return m

                mock.delete.side_effect = lambda: _delete()
            return mock

        self.mock_db.table.side_effect = _table

        async def _mock_request(self_client, method, url, **kwargs):
            if method == "GET":
                return _auth_list_empty()
            return _auth_create_fail()

        from app.main import app
        with patch("httpx.AsyncClient.request", _mock_request):
            with TestClient(app) as c:
                resp = c.post(
                    "/api/v1/superadmin/organisations",
                    json=VALID_PAYLOAD,
                    headers={"X-Superadmin-Secret": VALID_SECRET},
                )

        assert resp.status_code == 500
        assert ORG_ID in deleted_org_ids
