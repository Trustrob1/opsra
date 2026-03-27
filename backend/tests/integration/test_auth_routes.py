"""
tests/integration/test_auth_routes.py
Integration tests for all auth routes — Section 5.1.
Uses synchronous TestClient. Supabase mocked via dependency_overrides.
"""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


def _mock_login_success():
    mock = MagicMock()
    session = MagicMock(access_token="mock.access.token", refresh_token="mock.refresh.token")
    mock_user = MagicMock(id="user-uuid-001", email="agent@acme.example")
    mock.auth.sign_in_with_password.return_value = MagicMock(session=session, user=mock_user)
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return mock


def _mock_login_failure():
    mock = MagicMock()
    mock.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")
    return mock


def _mock_active_user(user_id="user-001", org_id="org-001"):
    mock = MagicMock()
    mock.auth.get_user.return_value = MagicMock(user=MagicMock(id=user_id))
    mock.table.return_value.select.return_value.eq.return_value.single.return_value \
        .execute.return_value.data = {
            "id": user_id, "org_id": org_id, "email": "agent@acme.example",
            "full_name": "Test Agent", "is_active": True,
            "whatsapp_number": None, "notification_prefs": {},
            "roles": {"template": "sales_agent", "permissions": {"view_leads": True}},
        }
    mock.auth.sign_out = MagicMock(return_value=None)
    mock.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return mock


def _mock_deactivated_user():
    mock = MagicMock()
    mock.auth.get_user.return_value = MagicMock(user=MagicMock(id="user-002"))
    mock.table.return_value.select.return_value.eq.return_value.single.return_value \
        .execute.return_value.data = {
            "id": "user-002", "org_id": "org-001", "email": "former@acme.example",
            "full_name": "Former Agent", "is_active": False,
            "roles": {"permissions": {}},
        }
    return mock


class TestHealthCheck:
    def test_health_returns_200(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestLogin:
    def test_valid_credentials_return_tokens(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_login_success()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/login",
                         json={"email": "agent@acme.example", "password": "Password1"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]

    def test_invalid_credentials_returns_error_envelope(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_login_failure()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/login",
                         json={"email": "agent@acme.example", "password": "WrongPass1"})
        app.dependency_overrides.clear()
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_missing_email_returns_422(self):
        from app.main import app
        from app.database import get_supabase
        from unittest.mock import MagicMock
        app.dependency_overrides[get_supabase] = lambda: MagicMock()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/login", json={"password": "Password1"})
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_missing_password_returns_422(self):
        from app.main import app
        from app.database import get_supabase
        from unittest.mock import MagicMock
        app.dependency_overrides[get_supabase] = lambda: MagicMock()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/login", json={"email": "a@b.com"})
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_response_envelope_shape(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_login_success()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/login",
                         json={"email": "agent@acme.example", "password": "Password1"})
        app.dependency_overrides.clear()
        body = resp.json()
        assert set(body.keys()) == {"success", "data", "message", "error"}


class TestLogout:
    def test_logout_with_valid_token_returns_200(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_active_user()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/logout",
                         headers={"Authorization": "Bearer valid.token"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_logout_without_token_returns_403_or_422(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/logout")
        assert resp.status_code in (403, 422)


class TestRefresh:
    def test_valid_refresh_token_returns_new_tokens(self):
        from app.main import app
        from app.database import get_supabase
        mock = MagicMock()
        new_session = MagicMock(access_token="new.access.token", refresh_token="new.refresh.token")
        mock.auth.refresh_session.return_value = MagicMock(session=new_session)
        app.dependency_overrides[get_supabase] = lambda: mock
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/refresh",
                         json={"refresh_token": "old.refresh.token"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]

    def test_missing_refresh_token_returns_422(self):
        from app.main import app
        from app.database import get_supabase
        from unittest.mock import MagicMock
        app.dependency_overrides[get_supabase] = lambda: MagicMock()
        with TestClient(app) as c:
            resp = c.post("/api/v1/auth/refresh", json={})
        app.dependency_overrides.clear()
        assert resp.status_code == 422


class TestMe:
    def test_returns_user_profile_for_valid_token(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_active_user()
        with TestClient(app) as c:
            resp = c.get("/api/v1/auth/me",
                        headers={"Authorization": "Bearer valid.token"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == "agent@acme.example"

    def test_no_token_returns_403_or_422(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/auth/me")
        assert resp.status_code in (403, 422)

    def test_deactivated_user_returns_401(self):
        from app.main import app
        from app.database import get_supabase
        app.dependency_overrides[get_supabase] = lambda: _mock_deactivated_user()
        with TestClient(app) as c:
            resp = c.get("/api/v1/auth/me",
                        headers={"Authorization": "Bearer valid.token"})
        app.dependency_overrides.clear()
        assert resp.status_code == 401


class TestRateLimitHelper:
    def test_allows_under_limit(self):
        from app.routers.auth import _check_reset_rate_limit
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value.execute.return_value = [3, True]
        _check_reset_rate_limit("192.168.1.1", mock_redis)

    def test_blocks_at_6th_attempt(self):
        from fastapi import HTTPException
        from app.routers.auth import _check_reset_rate_limit
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value.execute.return_value = [6, True]
        with pytest.raises(HTTPException) as exc_info:
            _check_reset_rate_limit("192.168.1.1", mock_redis)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_skips_check_when_redis_is_none(self):
        from app.routers.auth import _check_reset_rate_limit
        _check_reset_rate_limit("10.0.0.1", None)

    def test_sets_60_minute_ttl(self):
        from app.routers.auth import _check_reset_rate_limit
        mock_redis = MagicMock()
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, True]
        _check_reset_rate_limit("10.0.0.2", mock_redis)
        pipe.expire.assert_called_once()
        assert pipe.expire.call_args[0][1] == 3600

    def test_key_contains_client_ip(self):
        from app.routers.auth import _check_reset_rate_limit
        mock_redis = MagicMock()
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, True]
        _check_reset_rate_limit("203.0.113.42", mock_redis)
        key_used = pipe.incr.call_args[0][0]
        assert "203.0.113.42" in key_used