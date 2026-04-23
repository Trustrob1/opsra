"""
tests/integration/test_onboarding_routes.py
Integration tests for onboarding router — ORG-ONBOARDING-A.

Classes:
  TestGetChecklist        (2 tests)
  TestGetGoLiveStatus     (2 tests)
  TestActivateOrg         (3 tests)
  TestOpsManagerAccess    (1 test)

Total: 8 tests

Patterns:
  Pattern 28 — get_current_org overridden on every class
  Pattern 32 — class-level autouse fixture pops overrides in teardown
  Pattern 37 — mock org uses roles.template shape
  Pattern 24 — valid UUID constants
  Pattern 61 — org payload uses "id" not "user_id"
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"


def _owner_org():
    return {
        "id": USER_ID,
        "org_id": ORG_ID,
        "roles": {"template": "owner"},
    }


def _ops_org():
    return {
        "id": USER_ID,
        "org_id": ORG_ID,
        "roles": {"template": "ops_manager"},
    }


def _non_owner_org():
    return {
        "id": USER_ID,
        "org_id": ORG_ID,
        "roles": {"template": "sales_agent"},
    }


def _full_status():
    items = [
        {"id": f"item_{i}", "label": f"Item {i}", "group": "Group",
         "complete": True, "is_gate": False}
        for i in range(17)
    ]
    return {
        "percent_complete": 100,
        "go_live_ready": True,
        "is_live": False,
        "items": items,
    }


def _incomplete_status():
    items = [
        {"id": "whatsapp_connected", "label": "WhatsApp API connected",
         "group": "WhatsApp", "complete": False, "is_gate": True},
        {"id": "kb_minimum", "label": "Knowledge base populated",
         "group": "Support", "complete": False, "is_gate": True},
        *[
            {"id": f"item_{i}", "label": f"Item {i}", "group": "Group",
             "complete": True, "is_gate": False}
            for i in range(15)
        ],
    ]
    return {
        "percent_complete": 60,
        "go_live_ready": False,
        "is_live": False,
        "items": items,
    }


# ============================================================
# TestGetChecklist
# ============================================================

class TestGetChecklist:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.get_checklist_status",
            return_value=_full_status(),
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_17_items_and_percent_complete(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/onboarding/checklist",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) == 17
        assert "percent_complete" in data

    def test_non_owner_gets_403(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides[get_current_org] = lambda: _non_owner_org()
        with TestClient(app) as c:
            resp = c.get("/api/v1/onboarding/checklist",
                         headers={"Authorization": "Bearer mock-token"})
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        assert resp.status_code == 403


# ============================================================
# TestGetGoLiveStatus
# ============================================================

class TestGetGoLiveStatus:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.get_checklist_status",
            return_value=_full_status(),
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_is_live_go_live_ready_and_gate_items(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/onboarding/go-live-status",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "is_live"               in data
        assert "go_live_ready"         in data
        assert "gate_items_incomplete" in data

    def test_incomplete_gates_listed_correctly(self):
        from app.main import app
        self._patcher.stop()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.get_checklist_status",
            return_value=_incomplete_status(),
        )
        self._patcher.start()
        with TestClient(app) as c:
            resp = c.get("/api/v1/onboarding/go-live-status",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["go_live_ready"] is False
        assert "whatsapp_connected" in data["gate_items_incomplete"]
        assert "kb_minimum"         in data["gate_items_incomplete"]


# ============================================================
# TestActivateOrg
# ============================================================

class TestActivateOrg:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.activate_org",
            return_value="2026-04-22T10:00:00+00:00",
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_activated_true_and_went_live_at(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.post("/api/v1/onboarding/activate",
                          headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["activated"] is True
        assert "went_live_at" in data

    def test_returns_400_when_gates_incomplete(self):
        from app.main import app
        self._patcher.stop()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.activate_org",
            side_effect=HTTPException(
                status_code=400,
                detail={"message": "gates incomplete", "incomplete_gates": ["whatsapp_connected"]},
            ),
        )
        self._patcher.start()
        with TestClient(app) as c:
            resp = c.post("/api/v1/onboarding/activate",
                          headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 400

    def test_non_owner_gets_403(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides[get_current_org] = lambda: _non_owner_org()
        with TestClient(app) as c:
            resp = c.post("/api/v1/onboarding/activate",
                          headers={"Authorization": "Bearer mock-token"})
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        assert resp.status_code == 403


# ============================================================
# TestOpsManagerAccess
# ============================================================

class TestOpsManagerAccess:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.onboarding.onboarding_service.get_checklist_status",
            return_value=_full_status(),
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _ops_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_ops_manager_can_access_checklist(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/onboarding/checklist",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
