# tests/integration/test_whatsapp_connection_routes.py
# MULTI-ORG-WA-1 — Integration tests for WhatsApp connection admin routes
#
# Pattern 32: class-based autouse fixture, pop() teardown — never clear().
# Pattern 44: get_current_org overridden directly.
# Pattern 61: _ORG_PAYLOAD uses "id" not "user_id" for user UUID.
# Pattern 62: get_supabase dependency overridden — never direct call.
# Pattern 53: static routes tested — GET/POST/DELETE /whatsapp/* are static.

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

ORG_ID  = "cccccccc-cccc-cccc-cccc-cccccccccccc"
USER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

PHONE_ID = "111222333444555"
TOKEN    = "EAAtest_valid_token_xyz"
WABA_ID  = "999888777666555"


def _owner_org():
    return {
        "org_id": ORG_ID,
        "id": USER_ID,
        "roles": {
            "template": "owner",
            "permissions": {"manage_integrations": True},
        },
    }


def _ops_manager_org():
    return {
        "org_id": ORG_ID,
        "id": USER_ID,
        "roles": {
            "template": "ops_manager",
            "permissions": {"manage_integrations": True},
        },
    }


def _sales_agent_org():
    return {
        "org_id": ORG_ID,
        "id": USER_ID,
        "roles": {
            "template": "sales_agent",
            "permissions": {},
        },
    }


# ── GET /whatsapp/status ──────────────────────────────────────────────────────

class TestGetWhatsAppStatus:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase]     = lambda: self.mock_db
        app.dependency_overrides[get_current_org]  = _owner_org
        yield
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_connected_true_when_credentials_set(self):
        self.mock_db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id":     PHONE_ID,
                "whatsapp_access_token": TOKEN,
                "whatsapp_waba_id":      WABA_ID,
            }
        with TestClient(app) as client:
            r = client.get("/api/v1/admin/whatsapp/status")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["connected"] is True
        assert data["whatsapp_phone_id"] == PHONE_ID
        assert data["whatsapp_waba_id"] == WABA_ID
        # Token must NEVER appear in any response — S3
        assert "whatsapp_access_token" not in data
        assert TOKEN not in str(r.json())

    def test_returns_connected_false_when_no_phone_id(self):
        self.mock_db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id":     None,
                "whatsapp_access_token": None,
                "whatsapp_waba_id":      None,
            }
        with TestClient(app) as client:
            r = client.get("/api/v1/admin/whatsapp/status")
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is False

    def test_returns_connected_false_when_token_missing(self):
        """Phone ID set but no token → not considered connected."""
        self.mock_db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id":     PHONE_ID,
                "whatsapp_access_token": None,
                "whatsapp_waba_id":      None,
            }
        with TestClient(app) as client:
            r = client.get("/api/v1/admin/whatsapp/status")
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is False


# ── POST /whatsapp/connect ────────────────────────────────────────────────────

class TestConnectWhatsApp:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _owner_org
        yield
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_connect_saves_credentials_when_meta_verifies(self):
        """Valid payload + Meta returns 200 → credentials saved, connected=True returned."""
        mock_meta_resp = MagicMock()
        mock_meta_resp.status_code = 200

        with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__  = AsyncMock(return_value=False)
            mock_async_client.get        = AsyncMock(return_value=mock_meta_resp)
            mock_client_cls.return_value = mock_async_client

            with TestClient(app) as client:
                r = client.post("/api/v1/admin/whatsapp/connect", json={
                    "whatsapp_phone_id":     PHONE_ID,
                    "whatsapp_access_token": TOKEN,
                    "whatsapp_waba_id":      WABA_ID,
                })

        assert r.status_code == 200
        assert r.json()["data"]["connected"] is True
        # DB update was called
        self.mock_db.table.return_value.update.assert_called_once()
        update_kwargs = self.mock_db.table.return_value.update.call_args[0][0]
        assert update_kwargs["whatsapp_phone_id"] == PHONE_ID
        assert update_kwargs["whatsapp_access_token"] == TOKEN
        assert update_kwargs["whatsapp_waba_id"] == WABA_ID

    def test_connect_returns_422_when_meta_rejects(self):
        """Meta returns non-200 → 422 returned, nothing saved."""
        mock_meta_resp = MagicMock()
        mock_meta_resp.status_code = 401

        with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__  = AsyncMock(return_value=False)
            mock_async_client.get        = AsyncMock(return_value=mock_meta_resp)
            mock_client_cls.return_value = mock_async_client

            with TestClient(app) as client:
                r = client.post("/api/v1/admin/whatsapp/connect", json={
                    "whatsapp_phone_id":     "bad-id",
                    "whatsapp_access_token": "bad-token",
                })

        assert r.status_code == 422
        self.mock_db.table.return_value.update.assert_not_called()

    def test_connect_403_for_sales_agent(self):
        """Sales agent cannot connect WhatsApp — 403."""
        app.dependency_overrides[get_current_org] = _sales_agent_org
        with TestClient(app) as client:
            r = client.post("/api/v1/admin/whatsapp/connect", json={
                "whatsapp_phone_id":     PHONE_ID,
                "whatsapp_access_token": TOKEN,
            })
        assert r.status_code == 403

    def test_connect_200_for_ops_manager(self):
        """ops_manager is permitted to connect."""
        app.dependency_overrides[get_current_org] = _ops_manager_org
        mock_meta_resp = MagicMock()
        mock_meta_resp.status_code = 200

        with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__  = AsyncMock(return_value=False)
            mock_async_client.get        = AsyncMock(return_value=mock_meta_resp)
            mock_client_cls.return_value = mock_async_client

            with TestClient(app) as client:
                r = client.post("/api/v1/admin/whatsapp/connect", json={
                    "whatsapp_phone_id":     PHONE_ID,
                    "whatsapp_access_token": TOKEN,
                })

        assert r.status_code == 200

    def test_connect_422_on_empty_phone_id(self):
        """Empty phone_id fails Pydantic min_length=1 → 422."""
        with TestClient(app) as client:
            r = client.post("/api/v1/admin/whatsapp/connect", json={
                "whatsapp_phone_id":     "",
                "whatsapp_access_token": TOKEN,
            })
        assert r.status_code == 422

    def test_connect_422_on_empty_token(self):
        """Empty token fails Pydantic min_length=1 → 422."""
        with TestClient(app) as client:
            r = client.post("/api/v1/admin/whatsapp/connect", json={
                "whatsapp_phone_id":     PHONE_ID,
                "whatsapp_access_token": "",
            })
        assert r.status_code == 422

    def test_token_never_in_response(self):
        """Access token must not appear in any response body — S3."""
        mock_meta_resp = MagicMock()
        mock_meta_resp.status_code = 200

        with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
            mock_async_client = AsyncMock()
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__  = AsyncMock(return_value=False)
            mock_async_client.get        = AsyncMock(return_value=mock_meta_resp)
            mock_client_cls.return_value = mock_async_client

            with TestClient(app) as client:
                r = client.post("/api/v1/admin/whatsapp/connect", json={
                    "whatsapp_phone_id":     PHONE_ID,
                    "whatsapp_access_token": TOKEN,
                })

        assert TOKEN not in str(r.json())
        assert "whatsapp_access_token" not in str(r.json())


# ── DELETE /whatsapp/disconnect ───────────────────────────────────────────────

class TestDisconnectWhatsApp:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _owner_org
        yield
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_disconnect_sets_all_three_columns_to_none(self):
        """Disconnect nulls phone_id, access_token, and waba_id."""
        with TestClient(app) as client:
            r = client.delete("/api/v1/admin/whatsapp/disconnect")
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is False
        update_kwargs = self.mock_db.table.return_value.update.call_args[0][0]
        assert update_kwargs["whatsapp_phone_id"]     is None
        assert update_kwargs["whatsapp_access_token"] is None
        assert update_kwargs["whatsapp_waba_id"]      is None

    def test_disconnect_403_for_sales_agent(self):
        """Sales agent cannot disconnect — 403."""
        app.dependency_overrides[get_current_org] = _sales_agent_org
        with TestClient(app) as client:
            r = client.delete("/api/v1/admin/whatsapp/disconnect")
        assert r.status_code == 403

    def test_disconnect_writes_audit_log(self):
        """Audit log is written on successful disconnect."""
        with TestClient(app) as client:
            r = client.delete("/api/v1/admin/whatsapp/disconnect")
        assert r.status_code == 200
        # audit_logs table insert was called
        insert_calls = [
            call for call in self.mock_db.table.call_args_list
            if call[0][0] == "audit_logs"
        ]
        assert len(insert_calls) >= 1
