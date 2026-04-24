"""
tests/integration/test_growth_config_routes.py
GPM-1D — 12 integration tests for growth config routes.

Written against the actual growth_config.py (shared post-session):
  - TeamCreate.name max_length=100 (not 50)
  - DELETE /growth/teams/{id} is a SOFT delete (update is_active=False), returns 200
  - GET /growth/direct-sales returns data: { items, total, page, page_size, has_more }
  - POST /growth/direct-sales: owner OR ops_manager can write (not owner-only)
  - DELETE /growth/spend/{id}: owner-only write

Pattern 32: class-based autouse fixture, dependency_overrides pop teardown.
Pattern 61: _ORG_PAYLOAD uses "id" not "user_id".
Pattern 62: routes use Depends(get_supabase).
"""
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.routers.auth import get_current_org

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

USER_ID = "user-owner-001"
ORG_ID  = "org-test-001"


def _owner_org():
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "roles":  {"template": "owner", "permissions": {"manage_settings": True}},
    }


def _non_owner_org():
    return {
        "id":     "user-agent-002",
        "org_id": ORG_ID,
        "roles":  {"template": "sales_agent", "permissions": {}},
    }


def _make_db():
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.is_.return_value = chain
    chain.maybe_single.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.delete.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    db.table.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Growth Teams — 7 tests
# ---------------------------------------------------------------------------

class TestGrowthTeamsRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_teams_returns_empty_list(self):
        self.mock_db.table.return_value.execute.return_value = MagicMock(data=[], count=0)
        with TestClient(app) as client:
            r = client.get("/api/v1/growth/teams")
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_create_team_success(self):
        new_team = {
            "id": "team-001", "org_id": ORG_ID,
            "name": "Team Alpha", "color": "#00BFA5", "is_active": True,
        }
        self.mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[new_team])
        with TestClient(app) as client:
            r = client.post("/api/v1/growth/teams", json={"name": "Team Alpha", "color": "#00BFA5"})
        assert r.status_code == 201
        assert r.json()["data"]["name"] == "Team Alpha"

    def test_create_team_name_too_long_returns_422(self):
        # TeamCreate.name max_length=100 — send 101 chars
        with TestClient(app) as client:
            r = client.post("/api/v1/growth/teams", json={"name": "A" * 101, "color": "#00BFA5"})
        assert r.status_code == 422

    def test_patch_team_updates_name_and_active(self):
        existing = {"id": "team-001"}
        updated  = {"id": "team-001", "org_id": ORG_ID, "name": "Team Beta", "is_active": False}
        lookup_result = MagicMock()
        lookup_result.execute.return_value = MagicMock(data=existing)
        self.mock_db.table.return_value.maybe_single.return_value = lookup_result
        self.mock_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[updated])
        with TestClient(app) as client:
            r = client.patch("/api/v1/growth/teams/team-001", json={"name": "Team Beta", "is_active": False})
        assert r.status_code == 200

    def test_delete_team_soft_deletes(self):
        # DELETE is a soft delete — sets is_active=False, returns 200.
        # maybe_single() must return a dedicated mock so its execute()
        # doesn't collide with the shared chain.execute default (data=[]).
        existing = {"id": "team-001"}
        lookup_result = MagicMock()
        lookup_result.execute.return_value = MagicMock(data=existing)
        self.mock_db.table.return_value.maybe_single.return_value = lookup_result
        with TestClient(app) as client:
            r = client.delete("/api/v1/growth/teams/team-001")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_team_wrong_org_returns_404(self):
        lookup_result = MagicMock()
        lookup_result.execute.return_value = MagicMock(data=None)
        self.mock_db.table.return_value.maybe_single.return_value = lookup_result
        with TestClient(app) as client:
            r = client.delete("/api/v1/growth/teams/team-nonexistent")
        assert r.status_code == 404

    def test_non_owner_post_returns_403(self):
        app.dependency_overrides[get_current_org] = lambda: _non_owner_org()
        with TestClient(app) as client:
            r = client.post("/api/v1/growth/teams", json={"name": "Hack Team", "color": "#ff0000"})
        assert r.status_code == 403
        # Restore for teardown
        app.dependency_overrides[get_current_org] = lambda: _owner_org()


# ---------------------------------------------------------------------------
# Campaign Spend — 3 tests
# ---------------------------------------------------------------------------

class TestCampaignSpendRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_spend_returns_list(self):
        entries = [
            {"id": "sp-1", "org_id": ORG_ID, "spend_type": "team",
             "team_name": "Team A", "amount": 500.0,
             "period_start": "2026-01-01", "period_end": "2026-01-31"},
        ]
        self.mock_db.table.return_value.execute.return_value = MagicMock(data=entries, count=1)
        with TestClient(app) as client:
            r = client.get("/api/v1/growth/spend")
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_create_spend_entry_team_type(self):
        new_entry = {
            "id": "sp-2", "org_id": ORG_ID, "spend_type": "team",
            "team_name": "Team A", "amount": 300.0,
            "period_start": "2026-02-01", "period_end": "2026-02-28",
        }
        self.mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[new_entry])
        with TestClient(app) as client:
            r = client.post("/api/v1/growth/spend", json={
                "spend_type": "team", "team_name": "Team A",
                "amount": 300.0,
                "period_start": "2026-02-01", "period_end": "2026-02-28",
            })
        assert r.status_code == 201

    def test_create_spend_entry_channel_type(self):
        new_entry = {
            "id": "sp-3", "org_id": ORG_ID, "spend_type": "channel",
            "channel_name": "facebook", "amount": 150.0,
            "period_start": "2026-02-01", "period_end": "2026-02-28",
        }
        self.mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[new_entry])
        with TestClient(app) as client:
            r = client.post("/api/v1/growth/spend", json={
                "spend_type": "channel", "channel_name": "facebook",
                "amount": 150.0,
                "period_start": "2026-02-01", "period_end": "2026-02-28",
            })
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Direct Sales — 2 tests
# ---------------------------------------------------------------------------

class TestDirectSalesRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_direct_sales_returns_paginated_dict(self):
        # list_direct_sales wraps items in { items, total, page, page_size, has_more }
        sales = [{"id": "ds-1", "org_id": ORG_ID, "customer_name": "Acme Ltd",
                  "amount": 12000.0, "sale_date": "2026-01-15"}]
        self.mock_db.table.return_value.execute.return_value = MagicMock(data=sales, count=1)
        with TestClient(app) as client:
            r = client.get("/api/v1/growth/direct-sales")
        assert r.status_code == 200
        body = r.json()["data"]
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)

    def test_delete_spend_entry_owner_only(self):
        existing = {"id": "sp-del-1", "org_id": ORG_ID}
        lookup_result = MagicMock()
        lookup_result.execute.return_value = MagicMock(data=existing)
        self.mock_db.table.return_value.maybe_single.return_value = lookup_result
        with TestClient(app) as client:
            r = client.delete("/api/v1/growth/spend/sp-del-1")
        assert r.status_code == 200
        assert r.json()["success"] is True
