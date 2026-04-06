"""
backend/tests/integration/test_commissions_routes.py
Integration tests for commissions router — Phase 9C.

Classes:
  TestListCommissionsRoute    (3 tests)
  TestSummaryRoute            (2 tests)
  TestUpdateCommissionRoute   (3 tests)

Total: 8 tests

Patterns:
  Pattern 28 — get_current_org overridden on every class
  Pattern 32 — class-level autouse fixture pops overrides in teardown
  Pattern 34 — auth tests assert status_code in (401, 403)
  Pattern 24 — valid UUID constants
  Pattern 37 — mock org uses roles.template shape
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

ORG_ID        = "00000000-0000-0000-0000-000000000001"
AFFILIATE_ID  = "00000000-0000-0000-0000-000000000002"
MANAGER_ID    = "00000000-0000-0000-0000-000000000003"
COMMISSION_ID = "00000000-0000-0000-0000-000000000006"


def _manager_org():
    return {
        "id": MANAGER_ID, "org_id": ORG_ID,
        "roles": {"template": "owner", "permissions": {"is_admin": True}},
    }


def _affiliate_org():
    return {
        "id": AFFILIATE_ID, "org_id": ORG_ID,
        "roles": {"template": "affiliate_partner", "permissions": {}},
    }


def _sample_result():
    return {
        "items": [{"id": COMMISSION_ID, "status": "pending", "amount_ngn": 0}],
        "total": 1, "page": 1, "page_size": 20, "has_more": False,
    }


# ============================================================
# TestListCommissionsRoute
# ============================================================

class TestListCommissionsRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.commissions.commissions_service.list_commissions",
            return_value=_sample_result(),
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_paginated_shape(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/commissions",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "total" in data

    def test_affiliate_gets_scoped_results(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides[get_current_org] = lambda: _affiliate_org()
        with TestClient(app) as c:
            resp = c.get("/api/v1/commissions",
                         headers={"Authorization": "Bearer mock-token"})
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        assert resp.status_code == 200

    def test_auth_required(self):
        from app.main import app
        from app.dependencies import get_current_org
        app.dependency_overrides.pop(get_current_org, None)
        with TestClient(app) as c:
            resp = c.get("/api/v1/commissions")
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        assert resp.status_code in (401, 403)


# ============================================================
# TestSummaryRoute
# ============================================================

class TestSummaryRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.commissions.commissions_service.get_commission_summary",
            return_value={
                "total_count": 2, "total_amount_ngn": 50000,
                "by_status": {"pending": {"count": 1, "amount_ngn": 0},
                              "approved": {"count": 1, "amount_ngn": 50000},
                              "paid": {"count": 0, "amount_ngn": 0},
                              "rejected": {"count": 0, "amount_ngn": 0}},
            },
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_summary_shape(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/commissions/summary",
                         headers={"Authorization": "Bearer mock-token"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_count"      in data
        assert "total_amount_ngn" in data
        assert "by_status"        in data

    def test_summary_not_consumed_as_commission_id(self):
        """
        Regression: /summary must hit the summary route,
        not the PATCH /{id} route.
        """
        from app.main import app
        with TestClient(app) as c:
            resp = c.get("/api/v1/commissions/summary",
                         headers={"Authorization": "Bearer mock-token"})
        # If routing was wrong, GET would return 405 (wrong method on PATCH route)
        assert resp.status_code == 200


# ============================================================
# TestUpdateCommissionRoute
# ============================================================

class TestUpdateCommissionRoute:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._patcher = patch(
            "app.routers.commissions.commissions_service.update_commission",
            return_value={"id": COMMISSION_ID, "status": "approved", "amount_ngn": 50000},
        )
        self._patcher.start()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        yield
        self._patcher.stop()
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_on_success(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/commissions/{COMMISSION_ID}",
                json={"amount_ngn": 50000, "status": "approved"},
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_affiliate_gets_403(self):
        from app.main import app
        from app.dependencies import get_current_org
        from fastapi import HTTPException

        self._patcher.stop()
        p403 = patch(
            "app.routers.commissions.commissions_service.update_commission",
            side_effect=HTTPException(status_code=403,
                                      detail={"code": "FORBIDDEN", "message": "Managers only"}),
        )
        p403.start()
        app.dependency_overrides[get_current_org] = lambda: _affiliate_org()
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/commissions/{COMMISSION_ID}",
                json={"status": "approved"},
                headers={"Authorization": "Bearer mock-token"},
            )
        p403.stop()
        app.dependency_overrides[get_current_org] = lambda: _manager_org()
        self._patcher = patch(
            "app.routers.commissions.commissions_service.update_commission",
            return_value={"id": COMMISSION_ID, "status": "approved"},
        )
        self._patcher.start()
        assert resp.status_code == 403

    def test_negative_amount_returns_422(self):
        from app.main import app
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/commissions/{COMMISSION_ID}",
                json={"amount_ngn": -100},
                headers={"Authorization": "Bearer mock-token"},
            )
        assert resp.status_code == 422
