# tests/integration/test_business_gates.py
# 9E-D — Integration tests for GET/PATCH /api/v1/admin/messaging-limits
#
# Pattern: app.dependency_overrides — same as test_commerce_routes.py.
# Pattern 32: _clear_overrides autouse fixture calls .clear() (not pop).
# Pattern 62: get_supabase overridden via dependency_overrides.
# T2: db.table.side_effect used — never mix with return_value.

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase


# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID  = "org-test-gates-001"
USER_ID = "user-test-gates-002"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_org(role="owner"):
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "roles":  {"template": role, "permissions": {}},
    }


def _make_db(org_row=None):
    """
    Build a Supabase mock using table side_effect (T2 pattern).
    Handles select, update, and insert chains for organisations + audit_logs.
    """
    effective_org = org_row if org_row is not None else {
        "daily_customer_message_limit": 5,
        "quiet_hours_start":            "22:00",
        "quiet_hours_end":              "06:00",
        "timezone":                     "Africa/Lagos",
    }

    db = MagicMock()

    def table_side(name):
        tbl = MagicMock()

        # ── select chain ──────────────────────────────────────────────────────
        sel = MagicMock()
        sel.select        = MagicMock(return_value=sel)
        sel.eq            = MagicMock(return_value=sel)
        sel.maybe_single  = MagicMock(return_value=sel)
        sel.execute       = MagicMock(
            return_value=MagicMock(
                data=effective_org if name == "organisations" else None
            )
        )
        tbl.select.return_value = sel

        # ── update chain ─────────────────────────────────────────────────────
        upd = MagicMock()
        upd.eq.return_value      = upd
        upd.execute.return_value = MagicMock(data=effective_org)
        tbl.update.return_value  = upd

        # ── insert chain (audit_logs) ─────────────────────────────────────────
        ins = MagicMock()
        ins.execute.return_value = None
        tbl.insert.return_value  = ins

        return tbl

    db.table.side_effect = table_side
    return db


# ── Autouse fixture — Pattern 32 ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── GET /api/v1/admin/messaging-limits ───────────────────────────────────────

class TestGetMessagingLimits:

    def test_returns_configured_values(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).get("/api/v1/admin/messaging-limits")

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["daily_customer_message_limit"] == 5
        assert data["quiet_hours_start"] == "22:00"
        assert data["quiet_hours_end"]   == "06:00"
        assert data["timezone"]          == "Africa/Lagos"
        assert data["system_ceiling"]    == 20

    def test_returns_defaults_when_null(self):
        db = _make_db(org_row={
            "daily_customer_message_limit": None,
            "quiet_hours_start":            None,
            "quiet_hours_end":              None,
            "timezone":                     None,
        })
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).get("/api/v1/admin/messaging-limits")

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["daily_customer_message_limit"] == 3
        assert data["timezone"] == "Africa/Lagos"
        assert data["quiet_hours_start"] is None
        assert data["quiet_hours_end"]   is None


# ── PATCH /api/v1/admin/messaging-limits ─────────────────────────────────────

class TestPatchMessagingLimits:

    def test_valid_limit_saves_successfully(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"daily_customer_message_limit": 10},
        )

        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_limit_above_ceiling_returns_422(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"daily_customer_message_limit": 25},
        )

        assert r.status_code == 422
        # Confirm response contains a human-readable explanation mentioning the ceiling
        detail_str = str(r.json().get("detail", {}))
        assert "20" in detail_str

    def test_limit_at_ceiling_saves_successfully(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"daily_customer_message_limit": 20},
        )

        assert r.status_code == 200

    def test_valid_quiet_hours_saves(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={
                "quiet_hours_start": "22:00",
                "quiet_hours_end":   "06:00",
                "timezone":          "Africa/Lagos",
            },
        )

        assert r.status_code == 200

    def test_invalid_time_format_returns_422(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"quiet_hours_start": "10pm", "quiet_hours_end": "6am"},
        )

        assert r.status_code == 422

    def test_only_start_without_end_returns_422(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"quiet_hours_start": "22:00"},
        )

        assert r.status_code == 422

    def test_same_start_and_end_returns_422(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"quiet_hours_start": "22:00", "quiet_hours_end": "22:00"},
        )

        assert r.status_code == 422

    def test_invalid_timezone_returns_422(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"timezone": "notavalidtimezone"},
        )

        assert r.status_code == 422

    def test_empty_payload_returns_no_changes(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={},
        )

        assert r.status_code == 200
        assert r.json()["message"] == "No changes to save"

    def test_403_for_non_admin(self):
        db = _make_db()
        app.dependency_overrides[get_current_org] = lambda: _mock_org("sales_agent")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"daily_customer_message_limit": 5},
        )

        assert r.status_code == 403

    def test_audit_log_written_on_save(self):
        """Verify audit_logs insert fires when a valid change is saved."""
        inserts = []

        db = MagicMock()

        def table_side(name):
            tbl = MagicMock()

            sel = MagicMock()
            sel.select       = MagicMock(return_value=sel)
            sel.eq           = MagicMock(return_value=sel)
            sel.maybe_single = MagicMock(return_value=sel)
            sel.execute      = MagicMock(return_value=MagicMock(data={
                "daily_customer_message_limit": 5,
                "quiet_hours_start": None,
                "quiet_hours_end":   None,
                "timezone":          "Africa/Lagos",
            }))
            tbl.select.return_value = sel

            upd = MagicMock()
            upd.eq.return_value      = upd
            upd.execute.return_value = MagicMock(data={})
            tbl.update.return_value  = upd

            def capture_insert(data):
                inserts.append({"table": name, "data": data})
                ins = MagicMock()
                ins.execute.return_value = None
                return ins
            tbl.insert.side_effect = capture_insert

            return tbl

        db.table.side_effect = table_side

        app.dependency_overrides[get_current_org] = lambda: _mock_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: db

        r = TestClient(app).patch(
            "/api/v1/admin/messaging-limits",
            json={"daily_customer_message_limit": 7},
        )

        assert r.status_code == 200
        audit = [
            i for i in inserts
            if isinstance(i["data"], dict)
            and i["data"].get("action") == "messaging_limits.updated"
        ]
        assert audit, f"Expected audit log insert, got: {inserts}"
