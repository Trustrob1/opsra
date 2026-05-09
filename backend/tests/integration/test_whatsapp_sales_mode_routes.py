"""
tests/integration/test_whatsapp_sales_mode_routes.py
COMM-2 — Integration tests: HTTP routes via TestClient + mocked dependencies.

Run:
    pytest tests/integration/test_whatsapp_sales_mode_routes.py -v

These tests hit the actual FastAPI routes (not service functions directly)
with overridden auth + DB dependencies, verifying the full request/response
cycle including Pydantic validation, RBAC enforcement, and commerce guard.
"""
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

# ── Fixtures ──────────────────────────────────────────────────────────────────

ORG_ID  = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())

# Pattern 61: user UUID at "id" not "user_id"
# Pattern 58: permissions nested inside roles dict
_OWNER = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {"template": "owner", "permissions": {"manage_users": True}},
}
_OPS = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {"template": "ops_manager", "permissions": {"manage_users": True}},
}
_AGENT = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {"template": "sales_agent", "permissions": {}},
}


def _db(mode="human", shopify_connected=True, commerce_enabled=True):
    """
    Returns a mock DB that returns consistent data for every select().
    The single data shape covers both the GET (whatsapp_sales_mode) and
    the PATCH guard query (commerce_config + shopify_connected), which
    use different .select() columns but the same chain.
    Pattern 59: single execute return_value — no competing mocks.
    """
    db = MagicMock()
    chain = MagicMock()
    db.table.return_value = chain
    chain.select.return_value  = chain
    chain.eq.return_value      = chain
    chain.update.return_value  = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data={
        "whatsapp_sales_mode": mode,
        "shopify_connected":   shopify_connected,
        "commerce_config":     {"enabled": commerce_enabled},
    })
    return db


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    yield
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


client = TestClient(app, raise_server_exceptions=False)


# ── GET ───────────────────────────────────────────────────────────────────────

class TestGetIntegration:

    def test_200_returns_mode_field(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db("bot")

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["mode"] == "bot"

    def test_200_all_three_valid_modes_readable(self):
        for mode in ("human", "bot", "ai_agent"):
            app.dependency_overrides[get_current_org] = lambda: _OWNER
            app.dependency_overrides[get_supabase]    = lambda m=mode: _db(m)
            r = client.get("/api/v1/admin/whatsapp-sales-mode")
            assert r.status_code == 200
            assert r.json()["data"]["mode"] == mode

    def test_200_null_column_returns_human(self):
        db = _db()
        db.table.return_value.maybe_single.return_value.execute.return_value = \
            MagicMock(data={"whatsapp_sales_mode": None})
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: db

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_response_envelope_shape(self):
        """Verify standard { success, data, message, error } envelope."""
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.get("/api/v1/admin/whatsapp-sales-mode")

        body = r.json()
        assert "success" in body
        assert "data"    in body
        assert "mode"    in body["data"]


# ── PATCH ─────────────────────────────────────────────────────────────────────

class TestPatchIntegration:

    # ── Success paths ─────────────────────────────────────────────────────────

    def test_owner_sets_human(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "human"

    def test_ops_manager_sets_bot_when_commerce_enabled(self):
        app.dependency_overrides[get_current_org] = lambda: _OPS
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=True, commerce_enabled=True
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "bot"

    def test_owner_sets_ai_agent_when_commerce_enabled(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=True, commerce_enabled=True
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "ai_agent"},
        )

        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "ai_agent"

    def test_response_message_present(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.json().get("message") == "WhatsApp sales mode saved"

    # ── RBAC failures ─────────────────────────────────────────────────────────

    def test_403_sales_agent(self):
        app.dependency_overrides[get_current_org] = lambda: _AGENT
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 403

    def test_403_message_is_descriptive(self):
        app.dependency_overrides[get_current_org] = lambda: _AGENT
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        body = r.json()
        detail = body.get("detail", "")
        assert "owner" in str(detail).lower() or "ops" in str(detail).lower()

    # ── Commerce guard failures ───────────────────────────────────────────────

    def test_422_bot_shopify_not_connected(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=False, commerce_enabled=True
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 422

    def test_422_bot_commerce_not_enabled(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=True, commerce_enabled=False
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        assert r.status_code == 422

    def test_422_ai_agent_commerce_not_enabled(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=True, commerce_enabled=False
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "ai_agent"},
        )

        assert r.status_code == 422

    def test_422_error_message_mentions_commerce(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=False, commerce_enabled=False
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "bot"},
        )

        body = r.json()
        detail = body.get("detail", {})
        msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        assert "commerce" in msg.lower() or "shopify" in msg.lower()

    # ── Human mode bypasses commerce guard ───────────────────────────────────

    def test_human_mode_succeeds_even_without_shopify(self):
        """Setting human mode never requires commerce — no guard call needed."""
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=False, commerce_enabled=False
        )

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human"},
        )

        assert r.status_code == 200

    # ── Pydantic validation ───────────────────────────────────────────────────

    def test_422_invalid_mode_value(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        for bad in ("auto", "manual", "HUMAN", "", "null"):
            r = client.patch(
                "/api/v1/admin/whatsapp-sales-mode",
                json={"mode": bad},
            )
            assert r.status_code == 422, f"Expected 422 for mode={bad!r}"

    def test_422_empty_body(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={},
        )

        assert r.status_code == 422

    def test_422_extra_field_does_not_cause_500(self):
        """Extra fields should be silently ignored by Pydantic, not 500."""
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human", "unexpected_field": "value"},
        )

        assert r.status_code == 200

    # ── Audit log ─────────────────────────────────────────────────────────────

    def test_audit_log_called_with_correct_action(self):
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db()

        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = client.patch(
                "/api/v1/admin/whatsapp-sales-mode",
                json={"mode": "human"},
            )
            assert r.status_code == 200
            mock_audit.assert_called_once()
            kwargs = mock_audit.call_args[1]
            assert kwargs["action"]    == "whatsapp_sales_mode.updated"
            assert kwargs["org_id"]    == ORG_ID
            assert kwargs["user_id"]   == USER_ID
            assert kwargs["new_value"] == {"whatsapp_sales_mode": "human"}

    def test_audit_log_not_called_on_403(self):
        """No audit log should be written when RBAC rejects the request."""
        app.dependency_overrides[get_current_org] = lambda: _AGENT
        app.dependency_overrides[get_supabase]    = lambda: _db()

        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = client.patch(
                "/api/v1/admin/whatsapp-sales-mode",
                json={"mode": "human"},
            )
            assert r.status_code == 403
            mock_audit.assert_not_called()

    def test_audit_log_not_called_on_422(self):
        """No audit log written when commerce guard rejects."""
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        app.dependency_overrides[get_supabase]    = lambda: _db(
            shopify_connected=False, commerce_enabled=False
        )

        with patch("app.routers.admin.write_audit_log") as mock_audit:
            r = client.patch(
                "/api/v1/admin/whatsapp-sales-mode",
                json={"mode": "bot"},
            )
            assert r.status_code == 422
            mock_audit.assert_not_called()

    # ── S1: org_id from JWT, never from body ──────────────────────────────────

    def test_org_id_from_jwt_not_body(self):
        """
        S1: Sending org_id in the body must not affect which org is updated.
        The route ignores body org_id — only org["org_id"] from JWT is used.
        """
        app.dependency_overrides[get_current_org] = lambda: _OWNER
        db = _db()
        app.dependency_overrides[get_supabase] = lambda: db

        r = client.patch(
            "/api/v1/admin/whatsapp-sales-mode",
            json={"mode": "human", "org_id": str(uuid.uuid4())},
        )

        assert r.status_code == 200
        # Verify the DB update used ORG_ID from JWT, not the body org_id
        update_calls = db.table.return_value.update.call_args_list
        eq_calls     = db.table.return_value.eq.call_args_list
        # At least one .eq("id", ORG_ID) call must exist (the WHERE clause)
        eq_args = [str(c) for c in eq_calls]
        assert any(ORG_ID in arg for arg in eq_args)
