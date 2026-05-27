"""
tests/unit/test_report_delivery_worker.py
Unit tests for report_delivery_worker — RPT-1A.

Run: pytest tests/unit/test_report_delivery_worker.py -v
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Mock DB helper (same pattern as service tests)
# ---------------------------------------------------------------------------

class _MockQuery:
    def __init__(self, data):
        self._data = data if data is not None else []

    def select(self, *a, **kw):  return self
    def eq(self, *a, **kw):      return self
    def update(self, *a, **kw):  return self
    def execute(self):
        r = MagicMock()
        r.data = self._data
        return r


def _make_db(table_data: dict) -> MagicMock:
    db = MagicMock()
    db.table.side_effect = lambda name: _MockQuery(table_data.get(name, []))
    return db


# ---------------------------------------------------------------------------
# _should_fire (imported from worker for isolation testing)
# ---------------------------------------------------------------------------

from app.workers.report_delivery_worker import _should_fire


class TestShouldFire:

    # Wednesday 2026-05-27 08:15 UTC — weekday()=2
    _NOW = datetime(2026, 5, 27, 8, 15, 0, tzinfo=timezone.utc)

    def _weekly(self, dow, hour=8, last_sent=None):
        return {
            "frequency":    "weekly",
            "day_of_week":  dow,
            "send_hour":    hour,
            "last_sent_at": last_sent,
        }

    def _monthly(self, dom, hour=8, last_sent=None):
        return {
            "frequency":    "monthly",
            "day_of_month": dom,
            "send_hour":    hour,
            "last_sent_at": last_sent,
        }

    def test_weekly_fires_on_correct_day_and_hour(self):
        assert _should_fire(self._weekly(dow=2, hour=8), self._NOW) is True

    def test_weekly_skips_wrong_weekday(self):
        assert _should_fire(self._weekly(dow=0, hour=8), self._NOW) is False

    def test_weekly_skips_wrong_hour(self):
        assert _should_fire(self._weekly(dow=2, hour=9), self._NOW) is False

    def test_weekly_skips_if_already_sent_today(self):
        assert _should_fire(
            self._weekly(dow=2, hour=8, last_sent="2026-05-27T08:00:00Z"),
            self._NOW,
        ) is False

    def test_weekly_fires_if_sent_on_different_day(self):
        """Sent last week — should fire again this week."""
        assert _should_fire(
            self._weekly(dow=2, hour=8, last_sent="2026-05-20T08:00:00Z"),
            self._NOW,
        ) is True

    def test_monthly_fires_on_correct_day(self):
        assert _should_fire(self._monthly(dom=27, hour=8), self._NOW) is True

    def test_monthly_skips_wrong_day(self):
        assert _should_fire(self._monthly(dom=1, hour=8), self._NOW) is False

    def test_missing_day_of_week_returns_false(self):
        assert _should_fire({"frequency": "weekly", "day_of_week": None, "send_hour": 8}, self._NOW) is False

    def test_missing_day_of_month_returns_false(self):
        assert _should_fire({"frequency": "monthly", "day_of_month": None, "send_hour": 8}, self._NOW) is False


# ---------------------------------------------------------------------------
# run_report_delivery
# ---------------------------------------------------------------------------

from app.workers.report_delivery_worker import run_report_delivery


class TestRunReportDelivery:

    def _report_row(self, freq, day_val, hour=8, channel="email", last_sent=None):
        row = {
            "id":               "sched-1",
            "org_id":           "org-1",
            "label":            "Weekly Report",
            "frequency":        freq,
            "send_hour":        hour,
            "sections":         ["executive_summary"],
            "period_preset":    "last_7d",
            "team_filter":      None,
            "rep_filter":       None,
            "delivery_channel": channel,
            "recipients":       ["owner@example.com"],
            "is_active":        True,
            "last_sent_at":     last_sent,
        }
        if freq == "weekly":
            row["day_of_week"]  = day_val
            row["day_of_month"] = None
        else:
            row["day_of_week"]  = None
            row["day_of_month"] = day_val
        return row

    @patch("app.workers.report_delivery_worker.get_supabase")
    @patch("app.workers.report_delivery_worker.datetime")
    @patch("app.workers.report_delivery_worker._send_report_email")
    @patch("app.workers.report_delivery_worker.generate_report_pdf")
    @patch("app.workers.report_delivery_worker.get_full_report")
    def test_weekly_report_fires_on_correct_day(
        self, mock_report, mock_pdf, mock_email, mock_dt, mock_db
    ):
        """Weekly report scheduled for Wednesday fires on Wednesday."""
        now = datetime(2026, 5, 27, 8, 0, 0, tzinfo=timezone.utc)  # Wednesday
        mock_dt.now.return_value = now

        mock_db.return_value = _make_db({
            "scheduled_reports": [self._report_row("weekly", day_val=2)],
        })
        mock_report.return_value = {"report_meta": {
            "period_label": "21 May 2026 – 27 May 2026",
            "org_name": "Test",
        }}
        mock_pdf.return_value = b"%PDF"

        result = run_report_delivery()

        assert result["delivered"] == 1
        assert result["failed"] == 0
        mock_email.assert_called_once()

    @patch("app.workers.report_delivery_worker.get_supabase")
    @patch("app.workers.report_delivery_worker.datetime")
    @patch("app.workers.report_delivery_worker._send_report_email")
    @patch("app.workers.report_delivery_worker.get_full_report")
    def test_weekly_report_skips_if_already_sent_today(
        self, mock_report, mock_email, mock_dt, mock_db
    ):
        """Report not delivered if last_sent_at is today."""
        now = datetime(2026, 5, 27, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now

        row = self._report_row("weekly", day_val=2, last_sent="2026-05-27T08:00:00Z")
        mock_db.return_value = _make_db({"scheduled_reports": [row]})

        result = run_report_delivery()

        assert result["delivered"] == 0
        assert result["skipped"] == 1
        mock_email.assert_not_called()

    @patch("app.workers.report_delivery_worker.get_supabase")
    @patch("app.workers.report_delivery_worker.datetime")
    @patch("app.workers.report_delivery_worker._send_report_email")
    @patch("app.workers.report_delivery_worker.generate_report_pdf")
    @patch("app.workers.report_delivery_worker.get_full_report")
    def test_monthly_report_fires_on_correct_day(
        self, mock_report, mock_pdf, mock_email, mock_dt, mock_db
    ):
        """Monthly report scheduled for day 27 fires on May 27."""
        now = datetime(2026, 5, 27, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now

        mock_db.return_value = _make_db({
            "scheduled_reports": [self._report_row("monthly", day_val=27)],
        })
        mock_report.return_value = {"report_meta": {"period_label": "Apr–May", "org_name": "Org"}}
        mock_pdf.return_value = b"%PDF"

        result = run_report_delivery()

        assert result["delivered"] == 1
        mock_email.assert_called_once()

    @patch("app.workers.report_delivery_worker.get_supabase")
    @patch("app.workers.report_delivery_worker.datetime")
    @patch("app.workers.report_delivery_worker._send_report_email")
    @patch("app.workers.report_delivery_worker.generate_report_pdf")
    @patch("app.workers.report_delivery_worker.get_full_report")
    def test_delivery_failure_does_not_stop_loop(
        self, mock_report, mock_pdf, mock_email, mock_dt, mock_db
    ):
        """S14: one report failing email delivery must not block others."""
        now = datetime(2026, 5, 27, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now

        rows = [
            {**self._report_row("weekly", day_val=2), "id": "sched-1", "recipients": ["a@test.com"]},
            {**self._report_row("weekly", day_val=2), "id": "sched-2", "recipients": ["b@test.com"]},
        ]
        mock_db.return_value = _make_db({"scheduled_reports": rows})
        mock_report.return_value = {"report_meta": {"period_label": "X", "org_name": "Y"}}
        mock_pdf.return_value = b"%PDF"

        # First email fails, second succeeds
        mock_email.side_effect = [Exception("SMTP error"), None]

        result = run_report_delivery()

        assert result["failed"] == 1
        assert result["delivered"] == 1
        assert result["processed"] == 2

    @patch("app.workers.report_delivery_worker.get_supabase")
    @patch("app.workers.report_delivery_worker.datetime")
    def test_returns_summary_dict_with_zero_when_no_reports_due(self, mock_dt, mock_db):
        """Returns { processed:0, delivered:0, failed:0, skipped:0 } with no active reports."""
        now = datetime(2026, 5, 27, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_db.return_value = _make_db({"scheduled_reports": []})

        result = run_report_delivery()

        assert result == {"processed": 0, "delivered": 0, "failed": 0, "skipped": 0}
