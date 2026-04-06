"""
backend/tests/integration/test_notification_routes.py
Integration tests for notifications router — Phase 9.

Classes:
  TestListNotificationsRoute (3 tests)
  TestMarkReadRoute          (3 tests)
  TestMarkAllReadRoute       (2 tests)

Total: 8 tests

Patterns:
  Pattern 28 — get_current_org overridden on every class
  Pattern 32 — class-level autouse fixture pops overrides in teardown
  Pattern 34 — auth tests assert status_code in (401, 403)
  Pattern 24 — valid UUID constants
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

# ── UUID constants (Pattern 24) ───────────────────────────────────────────────
ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
NOTIF_1 = "00000000-0000-0000-0000-000000000003"


def _mock_org():
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "email":  "admin@test.com",
        "roles":  {"template": "owner", "permissions": {"is_admin": True}},
    }


def _sample_result():
    return {
        "items":        [{"id": NOTIF_1, "title": "Test", "is_read": False}],
        "total":        1,
        "page":         1,
        "page_size":    20,
        "has_more":     False,
        "unread_count": 1,
    }


# ============================================================
# TestListNotificationsRoute
# ============================================================

class TestListNotificationsRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.notifications.notifications_service.list_notifications",
            return_value=_sample_result(),
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_correct_shape(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get(
                "/api/v1/notifications",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "items"        in data
        assert "total"        in data
        assert "unread_count" in data

    def test_unread_count_present_in_response(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/notifications",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.json()["data"]["unread_count"] == 1

    def test_auth_required(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides.pop(get_current_org, None)
        with TestClient(app) as c:
            resp = c.get("/api/v1/notifications")
        app.dependency_overrides[get_current_org] = lambda: _mock_org()
        assert resp.status_code in (401, 403)  # Pattern 34


# ============================================================
# TestMarkReadRoute
# ============================================================

class TestMarkReadRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.notifications.notifications_service.mark_read",
            return_value={"id": NOTIF_1, "is_read": True},
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/notifications/{NOTIF_1}/read",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["is_read"] is True

    def test_404_propagated_when_not_found(self):
        from app.main import app
        from unittest.mock import patch as _patch
        from fastapi import HTTPException

        self._patcher.stop()
        p404 = _patch(
            "app.routers.notifications.notifications_service.mark_read",
            side_effect=HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Notification not found"},
            ),
        )
        p404.start()
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/notifications/{NOTIF_1}/read",
                headers={"Authorization": "Bearer mock-token"},
            )
        p404.stop()
        self._patcher = _patch(
            "app.routers.notifications.notifications_service.mark_read",
            return_value={"id": NOTIF_1, "is_read": True},
        )
        self._patcher.start()
        assert resp.status_code == 404

    def test_read_all_route_not_consumed_as_notification_id(self):
        """
        Regression: /read-all must be a separate static route, not routed to
        /{id}/read with id='read-all'.
        """
        from app.main import app
        from unittest.mock import patch as _patch

        mark_all_patcher = _patch(
            "app.routers.notifications.notifications_service.mark_all_read",
            return_value=None,
        )
        mark_all_patcher.start()
        with TestClient(app) as c:
            resp = c.patch(
                "/api/v1/notifications/read-all",
                headers={"Authorization": "Bearer mock-token"},
            )
        mark_all_patcher.stop()
        # Must hit the mark_all_read endpoint (200), not the /{id}/read endpoint
        assert resp.status_code == 200
        assert "marked as read" in resp.json()["data"].get("message", "")


# ============================================================
# TestMarkAllReadRoute
# ============================================================

class TestMarkAllReadRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.notifications.notifications_service.mark_all_read",
            return_value=None,
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_message(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.patch(
                "/api/v1/notifications/read-all",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "message" in resp.json()["data"]

    def test_auth_required(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides.pop(get_current_org, None)
        with TestClient(app) as c:
            resp = c.patch("/api/v1/notifications/read-all")
        app.dependency_overrides[get_current_org] = lambda: _mock_org()
        assert resp.status_code in (401, 403)  # Pattern 34
