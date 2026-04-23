# tests/integration/test_drip_business_type_routes.py
# CONFIG-2 — Drip Business Types integration tests
# Tests GET and PATCH /api/v1/admin/drip-business-types
# via FastAPI TestClient with mocked Supabase + auth dependencies.

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org, get_supabase

# ── Fixtures ──────────────────────────────────────────────────────────────────

_ORG_ID  = "00000000-0000-0000-0000-000000000001"
_USER_ID = "00000000-0000-0000-0000-000000000002"

_ORG_PAYLOAD = {
    "org_id": _ORG_ID,
    "id":     _USER_ID,          # Pattern 61 — "id" not "user_id"
    "roles": {
        "template":    "owner",
        "permissions": ["manage_users"],
    },
}


def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    db.table.return_value = chain
    chain.select.return_value  = chain
    chain.update.return_value  = chain
    chain.eq.return_value      = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data={})
    return db


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


# ── Helper ────────────────────────────────────────────────────────────────────

def _override(db=None):
    if db is None:
        db = _mock_db()
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: db
    return db


def _clear():
    app.dependency_overrides.clear()


# ── GET /admin/drip-business-types ────────────────────────────────────────────

class TestGetDripBusinessTypes:

    def test_returns_configured_types(self, client):
        db = _override()
        stored = [
            {"key": "pharmacy",    "label": "Pharmacy",    "enabled": True},
            {"key": "supermarket", "label": "Supermarket", "enabled": True},
        ]
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"drip_business_types": stored}
            )
        r = client.get("/api/v1/admin/drip-business-types")
        assert r.status_code == 200
        assert r.json()["data"]["business_types"] == stored
        _clear()

    def test_returns_empty_list_when_null(self, client):
        """Null column → falls back to empty list (unrestricted)."""
        db = _override()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"drip_business_types": None}
            )
        r = client.get("/api/v1/admin/drip-business-types")
        assert r.status_code == 200
        assert r.json()["data"]["business_types"] == []
        _clear()

    def test_returns_empty_list_when_no_row(self, client):
        db = _override()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data={})
        r = client.get("/api/v1/admin/drip-business-types")
        assert r.status_code == 200
        assert r.json()["data"]["business_types"] == []
        _clear()

    def test_requires_auth(self, client):
        _clear()  # no overrides → real dependency → 401/403
        r = client.get("/api/v1/admin/drip-business-types")
        assert r.status_code in (401, 403)


# ── PATCH /admin/drip-business-types ─────────────────────────────────────────

class TestPatchDripBusinessTypes:

    def _patch(self, client, payload):
        return client.patch("/api/v1/admin/drip-business-types", json=payload)

    def test_saves_valid_types(self, client):
        db = _override()
        updated = [{"key": "pharmacy", "label": "Pharmacy", "enabled": True}]
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{"drip_business_types": updated}])

        r = self._patch(client, {"business_types": updated})
        assert r.status_code == 200
        assert r.json()["data"]["business_types"] == updated
        _clear()

    def test_saves_empty_list(self, client):
        """Empty list (all types unrestricted) must be accepted."""
        db = _override()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{}])

        r = self._patch(client, {"business_types": []})
        assert r.status_code == 200
        _clear()

    def test_rejects_duplicate_keys(self, client):
        _override()
        r = self._patch(client, {"business_types": [
            {"key": "pharmacy", "label": "Pharmacy",  "enabled": True},
            {"key": "pharmacy", "label": "Pharmacy 2","enabled": True},
        ]})
        assert r.status_code == 422
        _clear()

    def test_rejects_invalid_key_chars(self, client):
        _override()
        r = self._patch(client, {"business_types": [
            {"key": "has space", "label": "Has Space", "enabled": True}
        ]})
        assert r.status_code == 422
        _clear()

    def test_rejects_label_over_80_chars(self, client):
        _override()
        r = self._patch(client, {"business_types": [
            {"key": "x", "label": "A" * 81, "enabled": True}
        ]})
        assert r.status_code == 422
        _clear()

    def test_audit_log_written(self, client):
        db = _override()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{}])

        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = self._patch(client, {"business_types": [
                {"key": "retail", "label": "Retail", "enabled": True}
            ]})
            assert r.status_code == 200
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args.kwargs
            assert call_kwargs["action"] == "drip_business_types.updated"
        _clear()

    def test_mixed_enabled_disabled_accepted(self, client):
        db = _override()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{}])

        r = self._patch(client, {"business_types": [
            {"key": "pharmacy",    "label": "Pharmacy",    "enabled": True},
            {"key": "supermarket", "label": "Supermarket", "enabled": False},
        ]})
        assert r.status_code == 200
        _clear()
