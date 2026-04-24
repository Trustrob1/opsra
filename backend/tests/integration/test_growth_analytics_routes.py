"""
tests/integration/test_growth_analytics_routes.py
Integration tests for GPM-1A growth analytics routes — 12 tests.

Pattern 32: class-based autouse fixture, dependency_overrides pop teardown.
Pattern 44: override get_current_org directly.
Pattern 58: _ORG_PAYLOAD has permissions nested inside roles dict.
Pattern 61: org["id"] is the user UUID.
Pattern 24: all UUIDs are valid UUID4 format.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import get_current_org
from app.database import get_supabase

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID  = "11111111-1111-4111-a111-111111111111"
USER_ID = "22222222-2222-4222-a222-222222222222"

_OWNER_ORG = {
    "org_id": ORG_ID,
    "id":     USER_ID,
    "roles":  {"template": "owner", "permissions": {}},
}

_OPS_ORG = {
    "org_id": ORG_ID,
    "id":     USER_ID,
    "roles":  {"template": "ops_manager", "permissions": {}},
}

_REP_ORG = {
    "org_id": ORG_ID,
    "id":     USER_ID,
    "roles":  {"template": "sales_agent", "permissions": {}},
}

_SUPPORT_ORG = {
    "org_id": ORG_ID,
    "id":     USER_ID,
    "roles":  {"template": "support_agent", "permissions": {}},
}

DATE_PARAMS = "?date_from=2025-03-01&date_to=2025-03-31"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_db():
    db = MagicMock()
    t = MagicMock()
    t.select.return_value = t
    t.eq.return_value = t
    t.is_.return_value = t
    t.order.return_value = t
    t.range.return_value = t
    t.execute.return_value.data = []
    t.execute.return_value.count = 0
    db.table.return_value = t
    return db


class TestGrowthAnalyticsRoutes:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.db = _mock_db()
        app.dependency_overrides[get_supabase] = lambda: self.db
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def _set_org(self, org_payload):
        app.dependency_overrides[get_current_org] = lambda: org_payload

    # -----------------------------------------------------------------------
    # 1. GET /overview: 200 with correct shape
    # -----------------------------------------------------------------------

    def test_overview_200_correct_shape(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/overview{DATE_PARAMS}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_revenue" in data
        assert "revenue_breakdown" in data
        assert "overall_conversion_rate" in data
        assert "cac" in data

    # -----------------------------------------------------------------------
    # 2. GET /teams: 200 with list
    # -----------------------------------------------------------------------

    def test_teams_200_returns_list(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/teams{DATE_PARAMS}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    # -----------------------------------------------------------------------
    # 3. GET /funnel: 200 with stage pcts
    # -----------------------------------------------------------------------

    def test_funnel_200_with_stages(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/funnel{DATE_PARAMS}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "stages" in data
        assert "overall_close_rate" in data

    # -----------------------------------------------------------------------
    # 4. GET /funnel: ?team= filter accepted
    # -----------------------------------------------------------------------

    def test_funnel_team_filter_accepted(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/funnel{DATE_PARAMS}&team=Team+A")
        assert resp.status_code == 200
        assert resp.json()["data"]["team"] == "Team A"

    # -----------------------------------------------------------------------
    # 5. GET /sales-reps: owner gets 200
    # -----------------------------------------------------------------------

    def test_sales_reps_owner_200(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/sales-reps{DATE_PARAMS}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    # -----------------------------------------------------------------------
    # 6. GET /sales-reps: sales_agent gets 200 (scoped)
    # -----------------------------------------------------------------------

    def test_sales_reps_sales_agent_200(self):
        self._set_org(_REP_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/sales-reps{DATE_PARAMS}")
        assert resp.status_code == 200

    # -----------------------------------------------------------------------
    # 7. GET /channels: 200
    # -----------------------------------------------------------------------

    def test_channels_200(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/channels{DATE_PARAMS}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    # -----------------------------------------------------------------------
    # 8. GET /velocity: 200 with weekly list
    # -----------------------------------------------------------------------

    def test_velocity_200(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/velocity{DATE_PARAMS}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    # -----------------------------------------------------------------------
    # 9. GET /pipeline-at-risk: 200
    # -----------------------------------------------------------------------

    def test_pipeline_at_risk_200(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get("/api/v1/analytics/growth/pipeline-at-risk")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    # -----------------------------------------------------------------------
    # 10. GET /win-loss: 200 with reason breakdown
    # -----------------------------------------------------------------------

    def test_win_loss_200(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/win-loss{DATE_PARAMS}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "won" in data
        assert "lost" in data
        assert "lost_reasons" in data

    # -----------------------------------------------------------------------
    # 11. Non-owner/non-ops on /overview → 403
    # -----------------------------------------------------------------------

    def test_overview_403_for_support_agent(self):
        self._set_org(_SUPPORT_ORG)
        resp = self.client.get(f"/api/v1/analytics/growth/overview{DATE_PARAMS}")
        assert resp.status_code == 403

    # -----------------------------------------------------------------------
    # 12. Invalid date range → 422
    # -----------------------------------------------------------------------

    def test_invalid_date_422(self):
        self._set_org(_OWNER_ORG)
        resp = self.client.get("/api/v1/analytics/growth/overview?date_from=not-a-date&date_to=also-not")
        assert resp.status_code == 422
