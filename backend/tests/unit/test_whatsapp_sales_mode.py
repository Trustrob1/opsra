"""
tests/unit/test_whatsapp_sales_mode.py
COMM-2 — Unit tests for GET/PATCH /admin/whatsapp-sales-mode

Run:
    pytest tests/unit/test_whatsapp_sales_mode.py -v

Patterns observed from existing admin.py tests:
  Pattern 28  — get_current_org used, not get_current_user
  Pattern 44  — override get_current_org directly in app.dependency_overrides
  Pattern 61  — _ORG_PAYLOAD uses "id" not "user_id" for the user UUID
  Pattern 59  — never set two competing execute.return_value on same db mock
  Pattern 62  — db via Depends(get_supabase)
  Pattern 32  — always pop overrides after test (use try/finally or fixture)
"""
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID  = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

# Pattern 61: "id" key for the authenticated user UUID (not "user_id")
# Pattern 58: permissions nested inside roles dict
_ORG_PAYLOAD = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles": {
        "template":    "owner",
        "permissions": {
            "manage_users": True,
        },
    },
}

_ORG_PAYLOAD_OPS = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles": {
        "template":    "ops_manager",
        "permissions": {"manage_users": True},
    },
}

_ORG_PAYLOAD_AGENT = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles": {
        "template":    "sales_agent",
        "permissions": {},
    },
}


def _mock_db():
    """Return a MagicMock that chains Supabase query methods correctly."""
    db = MagicMock()
    chain = MagicMock()
    # All chained methods return the same chain (Pattern 59)
    db.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data={})
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Pattern 32 — always clean up dependency overrides."""
    yield
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


client = TestClient(app)


# ── GET /admin/whatsapp-sales-mode ────────────────────────────────────────────

class TestGetWASalesMode:

    def test_returns_saved_mode(self):
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"whatsapp_sales_mode": "bot"}
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "bot"

    def test_defaults_to_human_when_null(self):
        """Column NULL or missing → default 'human'."""
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"whatsapp_sales_mode": None}
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_defaults_to_human_when_row_empty(self):
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data={})
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_returns_list_data_format(self):
        """Some Supabase versions return data as a list — handle both."""
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data=[{"whatsapp_sales_mode": "human"}]
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_requires_authentication(self):
        """No override → FastAPI dependency raises 401/403."""
        r = client.get("/api/v1/admin/whatsapp-sales-mode")
        assert r.status_code in (401, 403)


# ── PATCH /admin/whatsapp-sales-mode ─────────────────────────────────────────

class TestPatchWASalesMode:

    # ── Human mode (no guards needed) ────────────────────────────────────────

    def test_owner_can_set_human(self):
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_ops_manager_can_set_human(self):
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD_OPS
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    # ── RBAC guard ────────────────────────────────────────────────────────────

    def test_sales_agent_cannot_update(self):
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD_AGENT
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 403

    # ── Commerce guard for bot mode ───────────────────────────────────────────

    def test_bot_mode_rejected_when_shopify_not_connected(self):
        db = _mock_db()
        # First DB call (guard): fetch commerce_config + shopify_connected
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "shopify_connected": False,
                    "commerce_config":   {"enabled": True},
                }
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 422
        body = r.json()
        assert "Commerce must be enabled" in str(body)

    def test_bot_mode_rejected_when_commerce_disabled(self):
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "shopify_connected": True,
                    "commerce_config":   {"enabled": False},
                }
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 422

    def test_bot_mode_accepted_when_commerce_enabled(self):
        db = _mock_db()
        # Guard call returns commerce enabled + shopify connected
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "shopify_connected": True,
                    "commerce_config":   {"enabled": True},
                }
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "bot"

    # ── Commerce guard for ai_agent mode ─────────────────────────────────────

    def test_ai_agent_mode_rejected_when_commerce_disabled(self):
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "shopify_connected": True,
                    "commerce_config":   {"enabled": False},
                }
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "ai_agent"},
        )

        assert r.status_code == 422

    def test_ai_agent_mode_accepted_when_commerce_enabled(self):
        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "shopify_connected": True,
                    "commerce_config":   {"enabled": True},
                }
            )
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "ai_agent"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "ai_agent"

    # ── Pydantic validation ───────────────────────────────────────────────────

    def test_invalid_mode_rejected(self):
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "magic"},
        )

        assert r.status_code == 422

    def test_missing_mode_field_rejected(self):
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={},
        )

        assert r.status_code == 422

    # ── DB write verified ─────────────────────────────────────────────────────

    def test_update_writes_correct_column(self):
        """Verify the DB update call targets whatsapp_sales_mode column."""
        db = _mock_db()
        written = {}

        def _capture_update(data):
            written.update(data)
            return db.table.return_value.select.return_value.eq.return_value

        db.table.return_value.update.side_effect = _capture_update

        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert "whatsapp_sales_mode" in written
        assert written["whatsapp_sales_mode"] == "human"

    # ── Audit log verified ────────────────────────────────────────────────────

    def test_audit_log_written_on_save(self):
        """write_audit_log must be called once on successful PATCH."""
        db = _mock_db()
        app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
        app.dependency_overrides[get_supabase]    = lambda: db

        # Pattern 63: write_audit_log is defined in admin.py (same module)
        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = client.patch(
                "/api/v1/admin/whatsapp-sales-mode",
                json={"mode": "human"},
            )
            assert r.status_code == 200
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["action"] == "whatsapp_sales_mode.updated"
            assert call_kwargs["new_value"] == {"whatsapp_sales_mode": "human"}
