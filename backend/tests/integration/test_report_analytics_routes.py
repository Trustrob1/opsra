"""
tests/integration/test_report_analytics_routes.py
Integration tests for /api/v1/reports/* routes — RPT-1A.

Run: pytest tests/integration/test_report_analytics_routes.py -v
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.routers.auth import get_current_org


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org(role: str = "owner") -> dict:
    return {
        "id":     "user-uuid-test",
        "org_id": "org-uuid-test",
        "roles":  {"template": role},
    }


class _MockQuery:
    def __init__(self, data):
        self._data = data if data is not None else []

    def select(self, *a, **kw):  return self
    def eq(self, *a, **kw):      return self
    def neq(self, *a, **kw):     return self
    def is_(self, *a, **kw):     return self
    def in_(self, *a, **kw):     return self
    def maybe_single(self):       return self
    def order(self, *a, **kw):   return self
    def limit(self, *a, **kw):   return self
    def range(self, *a, **kw):   return self
    def update(self, *a, **kw):  return self
    def insert(self, *a, **kw):  return self
    def delete(self):             return self

    @property
    def not_(self):
        return self

    def execute(self):
        r = MagicMock()
        r.data  = self._data
        r.count = len(self._data) if isinstance(self._data, list) else 0
        return r


def _make_db(table_data: dict) -> MagicMock:
    db = MagicMock()
    db.table.side_effect = lambda name: _MockQuery(table_data.get(name, []))
    return db


# Minimal report returned by mocked get_full_report
_MOCK_REPORT = {
    "report_meta": {
        "org_id": "org-uuid-test",
        "org_name": "Test Org",
        "date_from": "2026-05-01",
        "date_to": "2026-05-31",
        "period_label": "1 May 2026 – 31 May 2026",
        "comparison_period_label": "1 Apr 2026 – 30 Apr 2026",
        "compare_mode": "previous_period",
        "filters": {"team": None, "rep_id": None},
        "sections_included": ["executive_summary"],
        "generated_at": "2026-05-27T08:00:00Z",
    },
    "executive_summary": {"metrics": {}},
}

# Minimal valid scheduled report row
_SCHED_ROW = {
    "id":               "sched-uuid-1",
    "org_id":           "org-uuid-test",
    "created_by":       "user-uuid-test",
    "label":            "Weekly Report",
    "frequency":        "weekly",
    "day_of_week":      1,
    "day_of_month":     None,
    "send_hour":        8,
    "sections":         ["executive_summary"],
    "period_preset":    "last_7d",
    "team_filter":      None,
    "rep_filter":       None,
    "delivery_channel": "email",
    "recipients":       ["owner@example.com"],
    "is_active":        True,
    "last_sent_at":     None,
    "created_at":       "2026-05-01T00:00:00Z",
    "updated_at":       "2026-05-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_owner():
    """TestClient with owner role dependency overrides."""
    app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
    app.dependency_overrides[get_supabase]    = lambda: _make_db({
        "scheduled_reports": [_SCHED_ROW],
        "organisations":     [{"id": "org-uuid-test", "name": "Test Org"}],
    })
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_ops_manager():
    app.dependency_overrides[get_current_org] = lambda: _make_org("ops_manager")
    app.dependency_overrides[get_supabase]    = lambda: _make_db({"scheduled_reports": []})
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_sales_agent():
    app.dependency_overrides[get_current_org] = lambda: _make_org("sales_agent")
    app.dependency_overrides[get_supabase]    = lambda: _make_db({})
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/reports/full
# ---------------------------------------------------------------------------

class TestGetReportFull:

    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_returns_full_report_json_for_owner(self, _, client_owner):
        resp = client_owner.get("/api/v1/reports/full", params={"period_preset": "last_30d"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "report_meta" in body["data"]

    def test_returns_403_for_sales_agent(self, client_sales_agent):
        resp = client_sales_agent.get("/api/v1/reports/full", params={"period_preset": "last_30d"})
        assert resp.status_code == 403

    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_accepts_period_preset_last_30d(self, mock_fn, client_owner):
        resp = client_owner.get("/api/v1/reports/full", params={"period_preset": "last_30d"})
        assert resp.status_code == 200
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["date_to"] is not None

    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_accepts_custom_date_from_and_date_to(self, mock_fn, client_owner):
        resp = client_owner.get(
            "/api/v1/reports/full",
            params={"date_from": "2026-05-01", "date_to": "2026-05-31"},
        )
        assert resp.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs["date_from"] == "2026-05-01"
        assert kwargs["date_to"]   == "2026-05-31"

    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_accepts_sections_filter(self, mock_fn, client_owner):
        resp = client_owner.get(
            "/api/v1/reports/full",
            params={"period_preset": "last_7d", "sections": "executive_summary,revenue"},
        )
        assert resp.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs["sections"] == ["executive_summary", "revenue"]

    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_accepts_rep_id_filter(self, mock_fn, client_owner):
        rep_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        resp = client_owner.get(
            "/api/v1/reports/full",
            params={"period_preset": "last_7d", "rep_id": rep_uuid},
        )
        assert resp.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs["rep_id"] == rep_uuid

    def test_returns_422_for_invalid_section_key(self, client_owner):
        resp = client_owner.get(
            "/api/v1/reports/full",
            params={"period_preset": "last_7d", "sections": "nonexistent_section"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/reports/download
# ---------------------------------------------------------------------------

class TestDownloadReport:

    @patch("app.routers.report_analytics.generate_report_pdf", return_value=b"%PDF-test")
    @patch("app.routers.report_analytics.get_full_report", return_value=_MOCK_REPORT)
    def test_returns_pdf_bytes_with_correct_content_type(self, _, __, client_owner):
        resp = client_owner.get(
            "/api/v1/reports/download",
            params={"period_preset": "last_30d"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-test"

    @patch("app.routers.report_analytics._check_download_rate_limit", return_value=False)
    def test_returns_429_when_rate_limit_exceeded(self, _, client_owner):
        resp = client_owner.get(
            "/api/v1/reports/download",
            params={"period_preset": "last_30d"},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert "10 reports per hour" in body["detail"]["message"]


# ---------------------------------------------------------------------------
# GET /api/v1/reports/sections
# ---------------------------------------------------------------------------

class TestGetSections:

    def test_returns_all_12_sections(self, client_owner):
        resp = client_owner.get("/api/v1/reports/sections")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 12

    def test_each_section_has_key_label_description(self, client_owner):
        resp = client_owner.get("/api/v1/reports/sections")
        for sec in resp.json()["data"]:
            assert "key" in sec
            assert "label" in sec
            assert "description" in sec

    def test_returns_403_for_sales_agent(self, client_sales_agent):
        resp = client_sales_agent.get("/api/v1/reports/sections")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/reports/scheduled
# ---------------------------------------------------------------------------

class TestListScheduledReports:

    def test_returns_empty_list_for_org_with_no_schedules(self):
        app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: _make_db({"scheduled_reports": []})
        client = TestClient(app)
        try:
            resp = client.get("/api/v1/reports/scheduled")
            assert resp.status_code == 200
            assert resp.json()["data"] == []
        finally:
            app.dependency_overrides.clear()

    def test_includes_next_send_at_in_response(self, client_owner):
        resp = client_owner.get("/api/v1/reports/scheduled")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # Each row should have next_send_at (may be None for bad config but key must exist)
        for row in data:
            assert "next_send_at" in row


# ---------------------------------------------------------------------------
# POST /api/v1/reports/scheduled
# ---------------------------------------------------------------------------

class TestCreateScheduledReport:

    _valid_payload = {
        "label":            "Weekly Ops Report",
        "frequency":        "weekly",
        "day_of_week":      1,
        "send_hour":        8,
        "sections":         ["executive_summary"],
        "period_preset":    "last_7d",
        "delivery_channel": "email",
        "recipients":       ["owner@example.com"],
    }

    def test_owner_can_create_scheduled_report(self, client_owner):
        with patch.object(
            _make_db({"scheduled_reports": []}).table("scheduled_reports").__class__,
            "execute",
        ):
            resp = client_owner.post("/api/v1/reports/scheduled", json=self._valid_payload)
        # 201 or 200 depending on DB mock returning data
        assert resp.status_code in (200, 201)

    def test_ops_manager_cannot_create_scheduled_report(self, client_ops_manager):
        resp = client_ops_manager.post("/api/v1/reports/scheduled", json=self._valid_payload)
        assert resp.status_code == 403

    def test_422_for_missing_day_of_week_on_weekly_schedule(self, client_owner):
        payload = {**self._valid_payload}
        del payload["day_of_week"]   # day_of_week required for weekly
        resp = client_owner.post("/api/v1/reports/scheduled", json=payload)
        assert resp.status_code == 422

    def test_422_for_invalid_section_key(self, client_owner):
        payload = {**self._valid_payload, "sections": ["not_a_real_section"]}
        resp = client_owner.post("/api/v1/reports/scheduled", json=payload)
        assert resp.status_code == 422

    def test_422_for_invalid_recipient_format(self, client_owner):
        payload = {**self._valid_payload, "recipients": ["notanemail"]}
        resp = client_owner.post("/api/v1/reports/scheduled", json=payload)
        assert resp.status_code == 422

    def test_422_for_missing_day_of_month_on_monthly_schedule(self, client_owner):
        payload = {
            **self._valid_payload,
            "frequency": "monthly",
            "day_of_week": None,
            # day_of_month deliberately omitted
        }
        resp = client_owner.post("/api/v1/reports/scheduled", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/v1/reports/scheduled/{id}
# ---------------------------------------------------------------------------

class TestUpdateScheduledReport:

    def test_owner_can_update_is_active_to_false(self):
        sched_id = _SCHED_ROW["id"]
        updated_row = {**_SCHED_ROW, "is_active": False}

        app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: _make_db({
            "scheduled_reports": [_SCHED_ROW],
        })
        client = TestClient(app)
        try:
            resp = client.patch(
                f"/api/v1/reports/scheduled/{sched_id}",
                json={"is_active": False},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_ops_manager_cannot_update_scheduled_report(self, client_ops_manager):
        resp = client_ops_manager.patch(
            f"/api/v1/reports/scheduled/{_SCHED_ROW['id']}",
            json={"is_active": False},
        )
        assert resp.status_code == 403

    def test_returns_404_for_wrong_org(self):
        """Report belonging to a different org returns 404."""
        app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
        # DB returns no rows for this org
        app.dependency_overrides[get_supabase] = lambda: _make_db({"scheduled_reports": []})
        client = TestClient(app)
        try:
            resp = client.patch(
                "/api/v1/reports/scheduled/nonexistent-id",
                json={"is_active": False},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/v1/reports/scheduled/{id}
# ---------------------------------------------------------------------------

class TestDeleteScheduledReport:

    def test_soft_deletes_sets_is_active_false(self):
        sched_id = _SCHED_ROW["id"]
        app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: _make_db({
            "scheduled_reports": [_SCHED_ROW],
        })
        client = TestClient(app)
        try:
            resp = client.delete(f"/api/v1/reports/scheduled/{sched_id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["data"]["deleted"] is True
            assert body["data"]["report_id"] == sched_id
        finally:
            app.dependency_overrides.clear()

    def test_returns_404_for_wrong_org(self):
        app.dependency_overrides[get_current_org] = lambda: _make_org("owner")
        app.dependency_overrides[get_supabase]    = lambda: _make_db({"scheduled_reports": []})
        client = TestClient(app)
        try:
            resp = client.delete("/api/v1/reports/scheduled/nonexistent-id")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_ops_manager_cannot_delete(self, client_ops_manager):
        resp = client_ops_manager.delete(f"/api/v1/reports/scheduled/{_SCHED_ROW['id']}")
        assert resp.status_code == 403
