"""
tests/unit/test_report_analytics_service.py
Unit tests for report_analytics_service — RPT-1A.

Run: pytest tests/unit/test_report_analytics_service.py -v
"""
import sys
import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.services.report_analytics_service import (
    _compute_comparison_period,
    _resolve_period_preset,
    get_executive_summary,
    get_response_time_report,
    get_rep_performance_report,
    get_full_report,
    generate_report_pdf,
)


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

class _MockQuery:
    """
    Fluent mock query builder. All chain methods return self.
    execute() returns the configured data for the table.
    """
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
    """Return a mock db that returns configured rows for each table."""
    db = MagicMock()
    db.table.side_effect = lambda name: _MockQuery(table_data.get(name, []))
    return db


# ---------------------------------------------------------------------------
# _compute_comparison_period
# ---------------------------------------------------------------------------

class TestComputeComparisonPeriod:

    def test_returns_prior_period_of_same_duration(self):
        """Prior period must be exactly the same number of days."""
        pf, pt = _compute_comparison_period("2026-05-01", "2026-05-31")
        orig_dur = (date(2026, 5, 31) - date(2026, 5, 1)).days + 1
        comp_dur = (date.fromisoformat(pt) - date.fromisoformat(pf)).days + 1
        assert orig_dur == comp_dur

    def test_prior_period_ends_day_before_current_start(self):
        """Prior period ends the day before the current period starts."""
        pf, pt = _compute_comparison_period("2026-05-01", "2026-05-31")
        assert pt == "2026-04-30"

    def test_single_day_period(self):
        """Single-day period maps to the immediately prior day."""
        pf, pt = _compute_comparison_period("2026-05-27", "2026-05-27")
        assert pf == "2026-05-26"
        assert pt == "2026-05-26"

    def test_7_day_period(self):
        pf, pt = _compute_comparison_period("2026-05-21", "2026-05-27")
        assert pf == "2026-05-14"
        assert pt == "2026-05-20"


# ---------------------------------------------------------------------------
# _resolve_period_preset
# ---------------------------------------------------------------------------

class TestResolvePeriodPreset:

    def test_last_7d(self):
        today = datetime.now(timezone.utc).date()
        df, dt = _resolve_period_preset("last_7d")
        assert dt == today.isoformat()
        assert df == (today - timedelta(days=7)).isoformat()

    def test_this_month(self):
        today = datetime.now(timezone.utc).date()
        df, dt = _resolve_period_preset("this_month")
        assert df == today.replace(day=1).isoformat()
        assert dt == today.isoformat()

    def test_last_month(self):
        today  = datetime.now(timezone.utc).date()
        first  = today.replace(day=1)
        last_p = first - timedelta(days=1)
        df, dt = _resolve_period_preset("last_month")
        assert dt == last_p.isoformat()
        assert df == last_p.replace(day=1).isoformat()

    def test_unknown_preset_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown period preset"):
            _resolve_period_preset("nonsense")

    def test_custom_raises_value_error(self):
        with pytest.raises(ValueError):
            _resolve_period_preset("custom")


# ---------------------------------------------------------------------------
# get_executive_summary
# ---------------------------------------------------------------------------

class TestGetExecutiveSummary:

    def _make_overview_return(self, revenue, leads, conversions, rate, close, cac):
        return {
            "total_revenue":         revenue,
            "revenue_growth_pct":    None,
            "total_leads":           leads,
            "total_conversions":     conversions,
            "overall_conversion_rate": rate,
            "avg_close_time_days":   close,
            "cac":                   cac,
            "total_spend":           0,
        }

    @patch("app.services.report_analytics_service.get_overview_metrics")
    def test_returns_all_six_metric_blocks(self, mock_overview):
        mock_overview.return_value = self._make_overview_return(500000, 20, 5, 25.0, 14.0, 10000)
        db = _make_db({})

        result = get_executive_summary(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

        assert "metrics" in result
        metrics = result["metrics"]
        for key in ("total_revenue", "total_leads", "total_conversions",
                    "conversion_rate", "avg_close_time_days", "cac"):
            assert key in metrics
            assert "current" in metrics[key]
            assert "previous" in metrics[key]
            assert "delta" in metrics[key]
            assert "direction" in metrics[key]

    @patch("app.services.report_analytics_service.get_overview_metrics")
    def test_direction_up_when_current_revenue_exceeds_previous(self, mock_overview):
        """Revenue direction = 'up' when current > previous."""
        def side_effect(db, org_id, date_from, date_to):
            # Return higher revenue for the later period
            if date_from and date_from.month == 5:
                return self._make_overview_return(850000, 30, 8, 26.7, 12.0, 8000)
            return self._make_overview_return(720000, 25, 6, 24.0, 15.0, 10000)

        mock_overview.side_effect = side_effect
        db = _make_db({})

        result = get_executive_summary(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

        assert result["metrics"]["total_revenue"]["direction"] == "up"
        assert result["metrics"]["total_revenue"]["current"] == 850000
        assert result["metrics"]["total_revenue"]["previous"] == 720000

    @patch("app.services.report_analytics_service.get_overview_metrics")
    def test_s14_returns_error_dict_on_failure(self, mock_overview):
        mock_overview.side_effect = Exception("DB unavailable")
        db = _make_db({})

        result = get_executive_summary(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

        assert result.get("error") == "section unavailable"


# ---------------------------------------------------------------------------
# get_response_time_report
# ---------------------------------------------------------------------------

# Base timestamps for response time tests
_T0  = "2026-05-01T10:00:00+00:00"   # inbound
_T05 = "2026-05-01T10:05:00+00:00"   # AI outbound (+5 min)
_T30 = "2026-05-01T10:30:00+00:00"   # human outbound (+30 min)
_T60 = "2026-05-01T11:00:00+00:00"   # second lead inbound (+60 min from T0)


def _messages_one_thread_with_ai():
    """Lead-1 thread: inbound → AI (5min) → human (30min). Lead-2: inbound only."""
    return [
        # Lead-1
        {"id": "m1", "lead_id": "lead-1", "direction": "inbound",  "sent_by": None,    "created_at": _T0},
        {"id": "m2", "lead_id": "lead-1", "direction": "outbound", "sent_by": None,    "created_at": _T05},  # AI
        {"id": "m3", "lead_id": "lead-1", "direction": "outbound", "sent_by": "rep-1", "created_at": _T30},  # human
        # Lead-2: no human reply
        {"id": "m4", "lead_id": "lead-2", "direction": "inbound",  "sent_by": None,    "created_at": _T60},
    ]


class TestGetResponseTimeReport:

    def _run(self, messages, compare_messages=None):
        all_msgs = messages + (compare_messages or [])
        db = _make_db({
            "whatsapp_messages": all_msgs,
            "organisations":     [{"id": "org-1", "sla_hot_hours": 1}],
            "users":             [{"id": "rep-1", "full_name": "Alice"}],
        })
        return get_response_time_report(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

    def test_first_response_time_computed_from_messages(self):
        """org_avg_first_response_mins equals the delta from inbound to first human reply."""
        result = self._run(_messages_one_thread_with_ai())
        curr = result.get("current", {})
        # Lead-1: inbound at T0, human at T30 → 30 mins
        assert curr.get("org_avg_first_response_mins") == 30.0

    def test_ai_sent_messages_excluded_from_first_response(self):
        """AI outbound (sent_by=None) must NOT count as the first human response."""
        result = self._run(_messages_one_thread_with_ai())
        curr = result.get("current", {})
        # If AI was counted, result would be 5.0 — must be 30.0
        assert curr.get("org_avg_first_response_mins") != 5.0
        assert curr.get("org_avg_first_response_mins") == 30.0

    def test_threads_with_no_human_reply_counted_as_no_response(self):
        """Lead with inbound but no human outbound increments no_response_threads."""
        result = self._run(_messages_one_thread_with_ai())
        curr = result.get("current", {})
        assert curr.get("no_response_threads") == 1

    def test_direction_up_when_response_time_improves(self):
        """Lower response time = improvement = direction 'up' (invert=True)."""
        current_msgs = [
            # Current: 20-min response
            {"id": "c1", "lead_id": "lead-A", "direction": "inbound",  "sent_by": None,    "created_at": "2026-05-01T10:00:00+00:00"},
            {"id": "c2", "lead_id": "lead-A", "direction": "outbound", "sent_by": "rep-1", "created_at": "2026-05-01T10:20:00+00:00"},
        ]
        compare_msgs = [
            # Comparison: 60-min response (worse)
            {"id": "p1", "lead_id": "lead-B", "direction": "inbound",  "sent_by": None,    "created_at": "2026-04-01T10:00:00+00:00"},
            {"id": "p2", "lead_id": "lead-B", "direction": "outbound", "sent_by": "rep-1", "created_at": "2026-04-01T11:00:00+00:00"},
        ]
        result = self._run(current_msgs, compare_msgs)
        # Current avg < previous avg → direction = "up"
        assert result.get("direction") == "up"

    def test_s14_db_failure_returns_error_flag(self):
        """DB failure returns error dict, never raises."""
        db = MagicMock()
        db.table.side_effect = Exception("DB connection failed")

        result = get_response_time_report(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

        assert result.get("error") == "section unavailable"


# ---------------------------------------------------------------------------
# get_rep_performance_report
# ---------------------------------------------------------------------------

class TestGetRepPerformanceReport:

    @patch("app.services.report_analytics_service.get_response_time_report")
    @patch("app.services.report_analytics_service.get_sales_rep_metrics")
    def test_ai_mode_pct_computed_from_message_ratios(self, mock_reps, mock_rt):
        """
        ai_mode_pct = AI outbound messages in rep's threads /
                      total outbound messages in rep's threads * 100
        """
        mock_reps.return_value = [
            {
                "rep_id": "rep-1", "rep_name": "Alice",
                "leads_assigned": 1, "close_rate": 20.0,
                "revenue_closed": 100000, "customers_assigned": 0,
                "messages_sent": 2, "avg_response_time_mins": 20.0,
                "demos_booked": 0, "demo_show_rate": 0.0, "avg_lead_score": 60.0,
            }
        ]
        mock_rt.return_value = {"current": {"per_rep": []}, "previous": {}}

        # Thread for lead-1 (assigned to rep-1):
        #   2 AI outbound + 2 human outbound by rep-1 = 50% AI
        messages = [
            {"sent_by": None,    "lead_id": "lead-1", "created_at": "2026-05-01T10:00:00Z"},
            {"sent_by": None,    "lead_id": "lead-1", "created_at": "2026-05-02T10:00:00Z"},
            {"sent_by": "rep-1", "lead_id": "lead-1", "created_at": "2026-05-03T10:00:00Z"},
            {"sent_by": "rep-1", "lead_id": "lead-1", "created_at": "2026-05-04T10:00:00Z"},
        ]
        db = _make_db({
            "whatsapp_messages": messages,
            "tasks": [],
            "users": [],
        })

        result = get_rep_performance_report(
            db=db, org_id="org-1",
            date_from="2026-05-01", date_to="2026-05-31",
            compare_date_from="2026-04-01", compare_date_to="2026-04-30",
        )

        current = result.get("current", [])
        rep = next((r for r in current if r.get("rep_id") == "rep-1"), None)
        assert rep is not None, "rep-1 not found in current"
        assert rep.get("ai_mode_pct") == 50.0    # 2 AI / 4 total = 50%
        assert rep.get("human_mode_pct") == 50.0


# ---------------------------------------------------------------------------
# get_full_report — S14 section isolation
# ---------------------------------------------------------------------------

class TestGetFullReport:

    @patch("app.services.report_analytics_service.get_executive_summary")
    def test_failing_section_returns_error_dict_other_sections_unaffected(self, mock_exec):
        """
        If one section raises an unhandled exception, it returns an error dict.
        Other sections in the same report are not blocked.
        """
        mock_exec.side_effect = RuntimeError("Unexpected DB failure")

        db = _make_db({
            "organisations": [{"id": "org-1", "name": "Test Org"}],
            "leads":         [],
            "direct_sales":  [],
            "tasks":         [],
            "tickets":       [],
            "customers":     [],
            "whatsapp_messages": [],
            "users":         [],
            "campaign_spend": [],
        })

        result = get_full_report(
            db=db,
            org_id="org-1",
            date_from="2026-05-01",
            date_to="2026-05-31",
            sections=["executive_summary", "lost_leads"],
        )

        # executive_summary failed → error dict
        assert result["executive_summary"].get("error") == "section unavailable"
        # lost_leads should still be present and not an error
        assert "lost_leads" in result
        assert result["lost_leads"].get("error") is None or "current" in result["lost_leads"]

    def test_report_meta_always_present(self):
        db = _make_db({
            "organisations": [{"id": "org-1", "name": "Test Org"}],
            "leads": [], "direct_sales": [], "tasks": [], "tickets": [],
            "customers": [], "whatsapp_messages": [], "users": [],
            "campaign_spend": [],
        })

        result = get_full_report(
            db=db,
            org_id="org-1",
            date_from="2026-05-01",
            date_to="2026-05-31",
            sections=["lost_leads"],
        )

        assert "report_meta" in result
        meta = result["report_meta"]
        assert meta["org_id"] == "org-1"
        assert meta["date_from"] == "2026-05-01"
        assert meta["date_to"] == "2026-05-31"
        assert "generated_at" in meta


# ---------------------------------------------------------------------------
# generate_report_pdf
# ---------------------------------------------------------------------------

class TestGenerateReportPdf:

    def _minimal_report(self):
        return {
            "report_meta": {
                "org_id":   "org-1",
                "org_name": "Test Org",
                "date_from": "2026-05-01",
                "date_to":   "2026-05-31",
                "period_label": "1 May 2026 – 31 May 2026",
                "comparison_period_label": "1 Apr 2026 – 30 Apr 2026",
                "compare_mode": "previous_period",
                "filters": {"team": None, "rep_id": None},
                "sections_included": [],
                "generated_at": "2026-05-27T08:00:00Z",
            }
        }

    def test_returns_bytes(self):
        """generate_report_pdf returns raw bytes (PDF)."""
        mock_weasyprint = MagicMock()
        mock_weasyprint.HTML.return_value.write_pdf.return_value = b"%PDF-1.4 test"

        with patch.dict(sys.modules, {"weasyprint": mock_weasyprint}):
            result = generate_report_pdf(self._minimal_report())

        assert isinstance(result, bytes)

    def test_raises_value_error_if_report_meta_missing(self):
        """ValueError raised when report_meta key is absent."""
        with pytest.raises(ValueError, match="report_meta"):
            generate_report_pdf({})

    def test_raises_value_error_if_report_data_empty(self):
        """ValueError raised for completely empty dict."""
        with pytest.raises(ValueError):
            generate_report_pdf({})
