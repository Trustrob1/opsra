"""
tests/integration/test_growth_dashboard_config_routes.py
Integration tests for GROWTH-DASH-CONFIG routes.

Tests:
  - GET returns default for new org (growth_dashboard_config is null)
  - GET — ops_manager can access
  - GET — sales_agent gets 403
  - PATCH saves valid config — owner succeeds
  - PATCH — ops_manager gets 403
  - PATCH with 3 sections — other 5 sections unchanged (partial merge)
  - PATCH: unknown key → 422
  - PATCH: overview visible:false → silently corrected to true

Pattern 32: dependency overrides cleared in autouse fixture teardown.
Pattern 61: org["id"] not org["user_id"].
Pattern 62: db via Depends(get_supabase).
"""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

USER_ID = "user-owner-001"
ORG_ID  = "org-test-001"


def _org(role="owner"):
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "is_active": True,
        "roles":  {"template": role, "permissions": {}},
    }


def _make_db(saved_config=None):
    db = MagicMock()

    def table_side(name):
        tbl = MagicMock()
        sel = MagicMock()
        sel.eq.return_value           = sel
        sel.maybe_single.return_value = sel
        sel.execute.return_value.data = {"growth_dashboard_config": saved_config}
        tbl.select.return_value = sel

        upd = MagicMock()
        upd.eq.return_value = upd
        upd.execute.return_value.data = [{}]
        tbl.update.return_value = upd

        ins = MagicMock()
        ins.execute.return_value.data = [{}]
        tbl.insert.return_value = ins

        return tbl

    db.table.side_effect = table_side
    return db


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(role="owner", saved_config=None):
    db = _make_db(saved_config)
    app.dependency_overrides[get_current_org] = lambda: _org(role)
    app.dependency_overrides[get_supabase]    = lambda: db
    return TestClient(app), db


# ── GET tests ─────────────────────────────────────────────────────────────────

class TestGetGrowthDashboardConfig:

    def test_get_returns_default_when_null(self):
        client, _ = _client(role="owner", saved_config=None)
        res = client.get("/api/v1/admin/growth-dashboard-config")
        assert res.status_code == 200
        data = res.json()["data"]
        assert "sections" in data
        assert len(data["sections"]) == 8

    def test_get_returns_saved_config(self):
        saved = {"sections": [
            {"key": "overview",   "visible": True},
            {"key": "funnel",     "visible": False},
        ]}
        client, _ = _client(role="owner", saved_config=saved)
        res = client.get("/api/v1/admin/growth-dashboard-config")
        assert res.status_code == 200
        sections = res.json()["data"]["sections"]
        assert len(sections) == 2

    def test_ops_manager_can_get(self):
        client, _ = _client(role="ops_manager")
        res = client.get("/api/v1/admin/growth-dashboard-config")
        assert res.status_code == 200

    def test_sales_agent_gets_403(self):
        client, _ = _client(role="sales_agent")
        res = client.get("/api/v1/admin/growth-dashboard-config")
        assert res.status_code == 403


# ── PATCH tests ───────────────────────────────────────────────────────────────

class TestPatchGrowthDashboardConfig:

    def test_owner_can_save_valid_config(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/growth-dashboard-config", json={
            "sections": [
                {"key": "funnel",           "visible": False},
                {"key": "team_performance", "visible": False},
            ]
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert "sections" in data

    def test_ops_manager_gets_403_on_patch(self):
        client, _ = _client(role="ops_manager")
        res = client.patch("/api/v1/admin/growth-dashboard-config", json={
            "sections": [{"key": "funnel", "visible": False}]
        })
        assert res.status_code == 403

    def test_unknown_key_returns_422(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/growth-dashboard-config", json={
            "sections": [{"key": "revenue_chart", "visible": True}]
        })
        assert res.status_code == 422

    def test_overview_visible_false_silently_corrected(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/growth-dashboard-config", json={
            "sections": [{"key": "overview", "visible": False}]
        })
        assert res.status_code == 200
        sections = res.json()["data"]["sections"]
        overview = next((s for s in sections if s["key"] == "overview"), None)
        assert overview is not None
        assert overview["visible"] is True

    def test_partial_payload_preserves_other_sections(self):
        """Submitting 3 sections should result in all 8 in response (merged with defaults)."""
        client, _ = _client(role="owner", saved_config=None)
        res = client.patch("/api/v1/admin/growth-dashboard-config", json={
            "sections": [
                {"key": "funnel",           "visible": False},
                {"key": "team_performance", "visible": False},
                {"key": "channels",         "visible": False},
            ]
        })
        assert res.status_code == 200
        sections = res.json()["data"]["sections"]
        # All 8 sections should be present (merged with defaults)
        assert len(sections) == 8
        # The 3 submitted should be False
        key_map = {s["key"]: s["visible"] for s in sections}
        assert key_map["funnel"]           is False
        assert key_map["team_performance"] is False
        assert key_map["channels"]         is False
        # Others default to True
        assert key_map["velocity"]         is True
        assert key_map["win_loss"]         is True
