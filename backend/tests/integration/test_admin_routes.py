"""
tests/integration/test_admin_routes.py
Integration tests for admin routes — Section 5.7.
Uses synchronous TestClient.
Mocks: get_supabase overridden via dependency_overrides.
       get_current_org overridden to return a mock admin user.
"""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


def make_mock_org():
    """Admin user with all management permissions."""
    return {
        "id": "admin-user-uuid",
        "org_id": "org-uuid-001",
        "email": "admin@acme.example",
        "full_name": "Test Admin",
        "is_active": True,
        "roles": {
            "template": "owner",
            "permissions": {
                "manage_users": True,
                "manage_roles": True,
                "manage_routing_rules": True,
                "manage_integrations": True,
                "force_logout_users": True,
                "is_admin": True,
            },
        },
    }


def make_client(mock_db=None):
    """
    Return a TestClient with get_supabase and get_current_org overridden.
    Caller owns dependency_overrides.clear() after use.
    """
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_org = make_mock_org()
    if mock_db is None:
        mock_db = MagicMock()

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: mock_org
    return app, TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/users
# ---------------------------------------------------------------------------

def test_list_users_returns_user_list():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .order.return_value.execute.return_value.data = [
            {"id": "user-001", "email": "rep@test.com", "full_name": "Sales Rep", "is_active": True}
        ]

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.get("/api/v1/admin/users",
                    headers={"Authorization": "Bearer mock-token"})

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 1


# ---------------------------------------------------------------------------
# POST /api/v1/admin/users
# ---------------------------------------------------------------------------

def test_create_user_success():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    from unittest.mock import patch

    mock_db = MagicMock()
    # role check returns a role
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .maybe_single.return_value.execute.return_value.data = {"id": "role-uuid-001"}
    # insert returns new user
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "new-user-uuid", "email": "newrep@test.com"}
    ]

    # Phase 8B: auth creation now uses httpx.post directly — mock at that level
    mock_httpx_resp = MagicMock()
    mock_httpx_resp.json.return_value = {"id": "new-user-uuid"}
    mock_httpx_resp.raise_for_status.return_value = None

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with patch("app.routers.admin.httpx.post", return_value=mock_httpx_resp):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/admin/users",
                json={"email": "newrep@test.com", "full_name": "New Rep",
                      "role_id": "role-uuid-001", "password": "SecurePass123"},
                headers={"Authorization": "Bearer mock-token"},
            )

    app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/users/{id} — soft deactivation
# ---------------------------------------------------------------------------

def test_deactivate_user_sets_is_active_false():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .maybe_single.return_value.execute.return_value.data = {
            "id": "user-to-deactivate", "is_active": True
        }
    mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value \
        .execute.return_value = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock()

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.delete("/api/v1/admin/users/user-to-deactivate",
                       headers={"Authorization": "Bearer mock-token"})

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_cannot_deactivate_own_account():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_org = make_mock_org()
    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    app.dependency_overrides[get_current_org] = lambda: mock_org

    with TestClient(app) as c:
        # Use the admin's own id as the user to deactivate
        resp = c.delete(f"/api/v1/admin/users/{mock_org['id']}",
                       headers={"Authorization": "Bearer mock-token"})

    app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/roles
# ---------------------------------------------------------------------------

def test_create_role_success():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "new-role-uuid", "name": "Custom Sales", "template": "sales_agent"}
    ]
    mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "new-role-uuid", "name": "Custom Sales", "template": "sales_agent"}]
    )

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.post(
            "/api/v1/admin/roles",
            json={"name": "Custom Sales", "template": "sales_agent",
                  "permissions": {"view_leads": True, "create_leads": True}},
            headers={"Authorization": "Bearer mock-token"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert resp.json()["success"] is True


def test_create_role_invalid_template_returns_422():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.post(
            "/api/v1/admin/roles",
            json={"name": "Bad Role", "template": "super_admin", "permissions": {}},
            headers={"Authorization": "Bearer mock-token"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/roles/{id} — blocked if users assigned
# ---------------------------------------------------------------------------

def test_delete_role_blocked_if_users_assigned():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    # Role exists
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .maybe_single.return_value.execute.return_value.data = {
            "id": "role-uuid-001", "name": "Sales"
        }
    # 3 users assigned — count attribute
    assigned = MagicMock()
    assigned.count = 3
    mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .execute.return_value = assigned

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.delete("/api/v1/admin/roles/role-uuid-001",
                       headers={"Authorization": "Bearer mock-token"})

    app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DUPLICATE_DETECTED"


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/routing-rules
# ---------------------------------------------------------------------------

def test_update_routing_rules_replaces_full_set():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .execute.return_value.data = []
    mock_db.table.return_value.delete.return_value.eq.return_value \
        .execute.return_value = MagicMock()
    mock_db.table.return_value.insert.return_value.execute.return_value.data = [
        {"event_type": "new_hot_lead", "channel": "whatsapp_inapp"}
    ]

    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.put(
            "/api/v1/admin/routing-rules",
            json={"rules": [{"event_type": "new_hot_lead", "channel": "whatsapp_inapp"}]},
            headers={"Authorization": "Bearer mock-token"},
        )

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/admin/integrations
# ---------------------------------------------------------------------------

def test_get_integration_status_returns_all_services():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    app.dependency_overrides[get_current_org] = lambda: make_mock_org()

    with TestClient(app) as c:
        resp = c.get("/api/v1/admin/integrations",
                    headers={"Authorization": "Bearer mock-token"})

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    for key in ("whatsapp", "meta_lead_ads", "anthropic", "email", "redis"):
        assert key in data




# ---------------------------------------------------------------------------
# UUID constants (Pattern 24) — shared across Phase 8A integration tests
# ---------------------------------------------------------------------------
_ROLE_ID     = "00000000-0000-0000-0000-000000000002"
_USER_ID     = "00000000-0000-0000-0000-000000000003"
_OVERRIDE_ID = "00000000-0000-0000-0000-000000000004"
_RULE_ID     = "00000000-0000-0000-0000-000000000005"


# ---------------------------------------------------------------------------
# GET /api/v1/admin/roles/{id}/overrides
# ---------------------------------------------------------------------------

class TestListUserOverridesRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self.mock_db.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = []

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_list(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_auth_required(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        app.dependency_overrides.pop(get_current_org, None)
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/admin/roles/{_ROLE_ID}/overrides")
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/v1/admin/roles/{id}/overrides
# ---------------------------------------------------------------------------

class TestCreateUserOverrideRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from unittest.mock import patch

        self.mock_db = MagicMock()

        # Patch admin_service.create_user_override so we don't need deep DB mocks
        self._patcher = patch(
            "app.routers.admin.admin_service.create_user_override",
            return_value={
                "id": _OVERRIDE_ID,
                "user_id": _USER_ID,
                "permission_key": "view_revenue",
                "granted": True,
            },
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_201_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides",
                json={"user_id": _USER_ID, "permission_key": "view_revenue", "granted": True},
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_422_missing_required_field(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides",
                json={"user_id": _USER_ID},   # missing permission_key and granted
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 422

    def test_404_propagated_when_user_not_in_role(self):
        from app.main import app
        from unittest.mock import patch
        from fastapi import HTTPException

        self._patcher.stop()
        patcher_404 = patch(
            "app.routers.admin.admin_service.create_user_override",
            side_effect=HTTPException(status_code=404,
                                      detail={"code": "NOT_FOUND", "message": "User not in role"}),
        )
        patcher_404.start()

        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides",
                json={"user_id": _USER_ID, "permission_key": "view_revenue", "granted": True},
                headers={"Authorization": "Bearer mock-token"},
            )
        patcher_404.stop()
        self._patcher = patch(
            "app.routers.admin.admin_service.create_user_override",
            return_value={},
        )
        self._patcher.start()

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/roles/{id}/overrides/{override_id}
# ---------------------------------------------------------------------------

class TestDeleteUserOverrideRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from unittest.mock import patch

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.admin.admin_service.delete_user_override",
            return_value=None,
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.delete(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides/{_OVERRIDE_ID}",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_404_propagated_when_override_not_found(self):
        from app.main import app
        from unittest.mock import patch
        from fastapi import HTTPException

        self._patcher.stop()
        patcher_404 = patch(
            "app.routers.admin.admin_service.delete_user_override",
            side_effect=HTTPException(status_code=404,
                                      detail={"code": "NOT_FOUND", "message": "Override not found"}),
        )
        patcher_404.start()

        with TestClient(app) as c:
            resp = c.delete(
                f"/api/v1/admin/roles/{_ROLE_ID}/overrides/{_OVERRIDE_ID}",
                headers={"Authorization": "Bearer mock-token"},
            )
        patcher_404.stop()
        self._patcher = patch("app.routers.admin.admin_service.delete_user_override",
                              return_value=None)
        self._patcher.start()

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/admin/routing-rules
# ---------------------------------------------------------------------------

class TestCreateRoutingRuleRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from unittest.mock import patch

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.admin.admin_service.create_routing_rule",
            return_value={
                "id": _RULE_ID, "org_id": "org-uuid-001",
                "event_type": "new_hot_lead", "channel": "whatsapp_inapp",
            },
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_201_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/admin/routing-rules",
                json={"event_type": "new_hot_lead", "channel": "whatsapp_inapp",
                      "within_hours_only": True},
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 201
        assert resp.json()["success"] is True
        assert resp.json()["data"]["event_type"] == "new_hot_lead"

    def test_422_missing_event_type(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/admin/routing-rules",
                json={"channel": "whatsapp_inapp"},   # missing event_type
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 422

   


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/routing-rules/{id}
# ---------------------------------------------------------------------------

class TestUpdateRoutingRuleRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from unittest.mock import patch

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.admin.admin_service.update_routing_rule",
            return_value={
                "id": _RULE_ID, "event_type": "new_hot_lead", "channel": "email",
            },
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/admin/routing-rules/{_RULE_ID}",
                json={"channel": "email"},
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_404_propagated_when_rule_not_found(self):
        from app.main import app
        from unittest.mock import patch
        from fastapi import HTTPException

        self._patcher.stop()
        patcher_404 = patch(
            "app.routers.admin.admin_service.update_routing_rule",
            side_effect=HTTPException(status_code=404,
                                      detail={"code": "NOT_FOUND", "message": "Rule not found"}),
        )
        patcher_404.start()

        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/admin/routing-rules/{_RULE_ID}",
                json={"channel": "email"},
                headers={"Authorization": "Bearer mock-token"},
            )
        patcher_404.stop()
        self._patcher = patch("app.routers.admin.admin_service.update_routing_rule",
                              return_value={})
        self._patcher.start()

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/routing-rules/{id}
# ---------------------------------------------------------------------------

class TestDeleteRoutingRuleRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from unittest.mock import patch

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.admin.admin_service.delete_routing_rule",
            return_value=None,
        )
        self._patcher.start()

        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: make_mock_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.delete(
                f"/api/v1/admin/routing-rules/{_RULE_ID}",
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "deleted" in resp.json()["data"]["message"].lower()

    def test_404_propagated_when_rule_not_found(self):
        from app.main import app
        from unittest.mock import patch
        from fastapi import HTTPException

        self._patcher.stop()
        patcher_404 = patch(
            "app.routers.admin.admin_service.delete_routing_rule",
            side_effect=HTTPException(status_code=404,
                                      detail={"code": "NOT_FOUND", "message": "Rule not found"}),
        )
        patcher_404.start()

        with TestClient(app) as c:
            resp = c.delete(
                f"/api/v1/admin/routing-rules/{_RULE_ID}",
                headers={"Authorization": "Bearer mock-token"},
            )
        patcher_404.stop()
        self._patcher = patch("app.routers.admin.admin_service.delete_routing_rule",
                              return_value=None)
        self._patcher.start()

        assert resp.status_code == 404