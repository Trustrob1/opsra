"""
tests/integration/test_performance_hub_routes.py
---------------------------------------------------
Integration tests for PERF-1A authenticated routes.
Class-based + autouse fixture pattern (Pattern 32).
All UUIDs valid format (Pattern 24).
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# UUID constants (Pattern 24)
# ---------------------------------------------------------------------------
ORG_ID   = "aaaa0001-0000-0000-0000-000000000000"
USER_ID  = "bbbb0002-0000-0000-0000-000000000000"
STAFF_ID = "cccc0003-0000-0000-0000-000000000000"
TMPL_ID  = "dddd0004-0000-0000-0000-000000000000"
LOG_ID   = "eeee0005-0000-0000-0000-000000000000"


def _owner_org():
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "owner"}}

def _manager_org():
    return {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "ops_manager"}}

def _staff_org():
    return {"id": STAFF_ID, "org_id": ORG_ID, "roles": {"template": "sales_agent"}}


def _make_db():
    db = MagicMock()
    db.table.return_value = db
    db.select.return_value = db
    db.insert.return_value = db
    db.update.return_value = db
    db.delete.return_value = db
    db.eq.return_value = db
    db.limit.return_value = db
    db.order.return_value = db
    db.single.return_value = db
    db.execute.return_value = MagicMock(data=[])
    return db


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

class TestScorecard:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _owner_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_scorecard_owner_ok(self):
        with patch("app.services.performance_service.get_scorecard",
                   new_callable=AsyncMock, return_value=[]):
            with TestClient(app) as client:
                r = client.get("/api/v1/performance/scorecard")
        assert r.status_code == 200

    def test_scorecard_staff_forbidden(self):
        app.dependency_overrides[get_current_org] = _staff_org
        with TestClient(app) as client:
            r = client.get("/api/v1/performance/scorecard")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# KPI Templates
# ---------------------------------------------------------------------------

class TestKpiTemplates:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _manager_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_kpi_templates_manager_ok(self):
        with patch("app.services.performance_service.get_kpi_templates", return_value=[]):
            with TestClient(app) as client:
                r = client.get("/api/v1/performance/kpi-templates")
        assert r.status_code == 200

    def test_get_kpi_templates_staff_forbidden(self):
        app.dependency_overrides[get_current_org] = _staff_org
        with TestClient(app) as client:
            r = client.get("/api/v1/performance/kpi-templates")
        assert r.status_code == 403

    def test_create_kpi_template_ok(self):
        with patch("app.services.performance_service.create_kpi_template",
                   return_value={"id": TMPL_ID}):
            with TestClient(app) as client:
                r = client.post("/api/v1/performance/kpi-templates", json={
                    "role_template": "sales_agent",
                    "kpi_name": "Test KPI",
                    "kpi_unit": "count",
                    "sort_order": 0,
                })
        assert r.status_code == 201

    def test_update_kpi_template_ok(self):
        with patch("app.services.performance_service.update_kpi_template",
                   return_value={"id": TMPL_ID}):
            with TestClient(app) as client:
                r = client.patch(f"/api/v1/performance/kpi-templates/{TMPL_ID}",
                                 json={"is_active": False})
        assert r.status_code == 200

    def test_update_kpi_template_no_fields(self):
        with TestClient(app) as client:
            r = client.patch(f"/api/v1/performance/kpi-templates/{TMPL_ID}", json={})
        assert r.status_code == 400

    def test_delete_kpi_template_ok(self):
        with patch("app.services.performance_service.soft_delete_kpi_template",
                   return_value={"id": TMPL_ID}):
            with TestClient(app) as client:
                r = client.delete(f"/api/v1/performance/kpi-templates/{TMPL_ID}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

class TestHealthScore:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _manager_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_health_score_manager_ok(self):
        payload = {"health_score": 80.0, "colour": "green", "components": {}, "weights": {}}
        with patch("app.services.performance_service.get_health_score",
                   new_callable=AsyncMock, return_value=payload):
            with TestClient(app) as client:
                r = client.get("/api/v1/performance/health-score")
        assert r.status_code == 200
        assert r.json()["data"]["health_score"] == 80.0

    def test_health_score_staff_forbidden(self):
        app.dependency_overrides[get_current_org] = _staff_org
        with TestClient(app) as client:
            r = client.get("/api/v1/performance/health-score")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Owner Dashboard Setup
# ---------------------------------------------------------------------------

class TestOwnerDashboardSetup:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _owner_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_setup_owner_ok(self):
        with patch("app.services.performance_service.get_or_create_owner_dashboard_token",
                   return_value={"token": "tok_abc", "pin_set": False}):
            with TestClient(app) as client:
                r = client.get("/api/v1/performance/owner-dashboard/setup")
        assert r.status_code == 200

    def test_get_setup_manager_forbidden(self):
        app.dependency_overrides[get_current_org] = _manager_org
        with TestClient(app) as client:
            r = client.get("/api/v1/performance/owner-dashboard/setup")
        assert r.status_code == 403

    def test_post_setup_sets_pin(self):
        with patch("app.services.performance_service.set_owner_dashboard_pin",
                   return_value=True):
            with TestClient(app) as client:
                r = client.post("/api/v1/performance/owner-dashboard/setup",
                                json={"pin": "1234"})
        assert r.status_code == 200

    def test_post_setup_invalid_pin_letters(self):
        with TestClient(app) as client:
            r = client.post("/api/v1/performance/owner-dashboard/setup",
                            json={"pin": "abcd"})
        assert r.status_code == 422

    def test_post_setup_pin_too_short(self):
        with TestClient(app) as client:
            r = client.post("/api/v1/performance/owner-dashboard/setup",
                            json={"pin": "12"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Staff Log
# ---------------------------------------------------------------------------

class TestStaffLog:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _staff_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_create_staff_log_ok(self):
        with patch("app.services.performance_service.create_staff_log",
                   return_value={"id": LOG_ID}):
            with TestClient(app) as client:
                r = client.post("/api/v1/performance/staff-log", json={
                    "kpi_key": "leads_contacted",
                    "kpi_label": "Leads Contacted",
                    "value": 5,
                    "attendance_status": "present",
                })
        assert r.status_code == 201

    def test_update_staff_log_manager_ok(self):
        app.dependency_overrides[get_current_org] = _manager_org
        with patch("app.services.performance_service.update_staff_log",
                   return_value={"id": LOG_ID}):
            with TestClient(app) as client:
                r = client.patch(f"/api/v1/performance/staff-log/{LOG_ID}",
                                 json={"value": 10.0})
        assert r.status_code == 200

    def test_update_staff_log_staff_forbidden(self):
        with TestClient(app) as client:
            r = client.patch(f"/api/v1/performance/staff-log/{LOG_ID}",
                             json={"value": 10.0})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Staff Profile
# ---------------------------------------------------------------------------

class TestStaffProfile:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _manager_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_staff_profile_manager_ok(self):
        with patch("app.services.performance_service.get_staff_profile",
                   new_callable=AsyncMock,
                   return_value={"user_id": STAFF_ID, "score_pct": 80.0}):
            with TestClient(app) as client:
                r = client.get(f"/api/v1/performance/staff/{STAFF_ID}")
        assert r.status_code == 200

    def test_get_staff_profile_self_ok(self):
        """Staff can view their own profile — STAFF_ID matches org["id"]."""
        app.dependency_overrides[get_current_org] = _staff_org
        with patch("app.services.performance_service.get_staff_profile",
                   new_callable=AsyncMock,
                   return_value={"user_id": STAFF_ID, "score_pct": 60.0}):
            with TestClient(app) as client:
                r = client.get(f"/api/v1/performance/staff/{STAFF_ID}")
        assert r.status_code == 200

    def test_get_staff_profile_other_staff_forbidden(self):
        """Staff cannot view another user's profile."""
        OTHER_ID = "ffff0006-0000-0000-0000-000000000000"
        app.dependency_overrides[get_current_org] = _staff_org
        with TestClient(app) as client:
            r = client.get(f"/api/v1/performance/staff/{OTHER_ID}")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

class TestTargets:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_db = _make_db()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _manager_org
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_get_targets_manager_ok(self):
        with patch("app.services.performance_service.get_targets_for_user_month",
                   return_value=[]):
            with TestClient(app) as client:
                r = client.get(f"/api/v1/performance/targets/{STAFF_ID}/2026-06")
        assert r.status_code == 200

    def test_set_targets_manager_ok(self):
        with patch("app.services.performance_service.set_targets", return_value=[]):
            with TestClient(app) as client:
                r = client.post("/api/v1/performance/targets", json={
                    "user_id": STAFF_ID,
                    "month": "2026-06",
                    "targets": [{"kpi_name": "Leads Contacted",
                                 "target_value": 50,
                                 "kpi_unit": "count"}],
                })
        assert r.status_code == 201

    def test_set_targets_staff_forbidden(self):
        app.dependency_overrides[get_current_org] = _staff_org
        with TestClient(app) as client:
            r = client.post("/api/v1/performance/targets", json={
                "user_id": STAFF_ID,
                "month": "2026-06",
                "targets": [{"kpi_name": "Leads Contacted", "target_value": 50}],
            })
        assert r.status_code == 403

    def test_acknowledge_targets_ok(self):
        app.dependency_overrides[get_current_org] = _staff_org
        with patch("app.services.performance_service.acknowledge_targets",
                   return_value=True):
            with TestClient(app) as client:
                r = client.post(
                    f"/api/v1/performance/targets/{TMPL_ID}/acknowledge",
                    params={"month": "2026-06"},
                )
        assert r.status_code == 200
