# tests/integration/test_sla_business_hours_routes.py
# CONFIG-3 — SLA Business Hours integration tests
# Tests GET and PATCH /api/v1/admin/sla-business-hours
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
    "id":     _USER_ID,          # Pattern 61
    "roles": {
        "template":    "owner",
        "permissions": ["manage_users"],
    },
}

_VALID_HOURS = {
    "timezone": "Africa/Lagos",
    "days": {
        "monday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "tuesday":   {"enabled": True,  "open": "08:00", "close": "18:00"},
        "wednesday": {"enabled": True,  "open": "08:00", "close": "18:00"},
        "thursday":  {"enabled": True,  "open": "08:00", "close": "18:00"},
        "friday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "saturday":  {"enabled": False, "open": None,    "close": None},
        "sunday":    {"enabled": False, "open": None,    "close": None},
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


def _override(db=None):
    if db is None:
        db = _mock_db()
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: db
    return db


def _clear():
    app.dependency_overrides.clear()


# ── GET /admin/sla-business-hours ─────────────────────────────────────────────

class TestGetSlaBusinessHours:

    def test_returns_configured_hours(self, client):
        db = _override()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"sla_business_hours": _VALID_HOURS}
            )
        r = client.get("/api/v1/admin/sla-business-hours")
        assert r.status_code == 200
        assert r.json()["data"]["sla_business_hours"]["timezone"] == "Africa/Lagos"
        assert r.json()["data"]["sla_business_hours"]["days"]["monday"]["enabled"] is True
        _clear()

    def test_returns_defaults_when_null(self, client):
        db = _override()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"sla_business_hours": None}
            )
        r = client.get("/api/v1/admin/sla-business-hours")
        assert r.status_code == 200
        bh = r.json()["data"]["sla_business_hours"]
        assert "days" in bh
        assert "monday" in bh["days"]
        _clear()

    def test_returns_defaults_when_no_row(self, client):
        db = _override()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data={})
        r = client.get("/api/v1/admin/sla-business-hours")
        assert r.status_code == 200
        assert "sla_business_hours" in r.json()["data"]
        _clear()

    def test_requires_auth(self, client):
        _clear()
        r = client.get("/api/v1/admin/sla-business-hours")
        assert r.status_code in (401, 403)


# ── PATCH /admin/sla-business-hours ──────────────────────────────────────────

class TestPatchSlaBusinessHours:

    def _patch(self, client, payload):
        return client.patch("/api/v1/admin/sla-business-hours", json=payload)

    def _setup_db_with_current(self, existing=None):
        db = _override()
        # First call = GET current config
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"sla_business_hours": existing or _VALID_HOURS}
            )
        # Second call = UPDATE
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{}])
        return db

    def test_saves_valid_hours(self, client):
        self._setup_db_with_current()
        r = self._patch(client, {"timezone": "Europe/London", "days": {
            "monday": {"enabled": True, "open": "09:00", "close": "17:00"}
        }})
        assert r.status_code == 200
        assert r.json()["data"]["sla_business_hours"]["timezone"] == "Europe/London"
        _clear()

    def test_partial_update_merges_days(self, client):
        """Sending only one day must not wipe the others."""
        self._setup_db_with_current()
        r = self._patch(client, {"days": {
            "saturday": {"enabled": True, "open": "09:00", "close": "13:00"}
        }})
        assert r.status_code == 200
        result = r.json()["data"]["sla_business_hours"]["days"]
        # Saturday updated
        assert result["saturday"]["enabled"] is True
        # Monday preserved from existing
        assert result["monday"]["enabled"] is True
        _clear()

    def test_rejects_invalid_timezone(self, client):
        _override()
        r = self._patch(client, {"timezone": "not_a_timezone"})
        assert r.status_code == 422
        _clear()

    def test_rejects_unknown_day(self, client):
        _override()
        r = self._patch(client, {"days": {
            "funday": {"enabled": True, "open": "08:00", "close": "18:00"}
        }})
        assert r.status_code == 422
        _clear()

    def test_rejects_open_after_close(self, client):
        _override()
        r = self._patch(client, {"days": {
            "monday": {"enabled": True, "open": "18:00", "close": "08:00"}
        }})
        assert r.status_code == 422
        _clear()

    def test_rejects_open_equals_close(self, client):
        _override()
        r = self._patch(client, {"days": {
            "monday": {"enabled": True, "open": "09:00", "close": "09:00"}
        }})
        assert r.status_code == 422
        _clear()

    def test_disabled_day_no_times_required(self, client):
        """Disabled days do not need open/close times."""
        self._setup_db_with_current()
        r = self._patch(client, {"days": {
            "sunday": {"enabled": False, "open": None, "close": None}
        }})
        assert r.status_code == 200
        _clear()

    def test_audit_log_written(self, client):
        self._setup_db_with_current()
        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = self._patch(client, {"timezone": "Africa/Lagos"})
            assert r.status_code == 200
            mock_audit.assert_called_once()
            assert mock_audit.call_args.kwargs["action"] == "sla_business_hours.updated"
        _clear()
