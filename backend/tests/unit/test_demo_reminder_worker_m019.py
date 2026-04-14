"""
tests/unit/test_demo_reminder_worker_m019.py
---------------------------------------------
M01-9 — Unit tests for post-demo nudge logic in demo_reminder_worker.py

Fixes applied vs original version:
  - test_rep_nudge_fires_at_t_plus_2h:
      noshow_task_created=True so auto no-show branch is skipped,
      allowing nudge checks to be reached.
  - test_manager_escalation_fires_when_due:
      same fix — noshow_task_created=True.
  - test_auto_noshow_takes_priority_over_nudges:
      patch target corrected to app.services.demo_service.log_outcome
      (Pattern 42 — patch where name is USED, not where defined).
      log_outcome is imported lazily inside _process_demo via
      'from app.services.demo_service import log_outcome', so the
      worker module has no attribute 'log_outcome' to patch directly.

Coverage:
  1.  _is_business_hours — weekday within hours → True
  2.  _is_business_hours — weekday outside hours → False
  3.  _is_business_hours — weekend → False
  4.  _next_business_day_morning — Friday evening → Monday 09:00
  5.  _next_business_day_morning — Saturday → Monday 09:00
  6.  _escalation_due — T+4h not yet reached → False
  7.  _escalation_due — T+4h reached, inside business hours → True
  8.  _escalation_due — T+4h reached, outside hours, hold point not passed → False
  9.  _escalation_due — T+4h reached, outside hours, hold point passed → True
  10. _process_demo — rep nudge fires at T+2h when rep_nudge_sent_at is null
  11. _process_demo — rep nudge NOT fired if rep_nudge_sent_at already set
  12. _process_demo — manager escalation fires when due and manager_nudge_sent_at null
  13. _process_demo — manager escalation NOT fired if manager_nudge_sent_at already set
  14. _process_demo — no nudges fired if demo is in the future
  15. _process_demo — auto no-show takes priority over nudges
  16. run_demo_reminder_check summary includes rep_nudges + manager_nudges keys
  17. _get_all_manager_ids — returns only owner/admin/ops_manager
  18. _get_all_manager_ids — DB failure returns empty list, does not raise
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID  = "00000000-0000-0000-0000-000000000020"
LEAD_ID = "00000000-0000-0000-0000-000000000021"
DEMO_ID = "00000000-0000-0000-0000-000000000022"
REP_ID  = "00000000-0000-0000-0000-000000000023"
MGR_ID  = "00000000-0000-0000-0000-000000000024"

# Monday 2026-04-13 14:00 UTC — business hours
NOW_BIZ     = datetime(2026, 4, 13, 14, 0, 0, tzinfo=timezone.utc)
# Monday 2026-04-13 21:00 UTC — outside business hours
NOW_EVENING = datetime(2026, 4, 13, 21, 0, 0, tzinfo=timezone.utc)
# Saturday 2026-04-11 14:00 UTC — weekend
NOW_WEEKEND = datetime(2026, 4, 11, 14, 0, 0, tzinfo=timezone.utc)


def _demo(
    scheduled_at: datetime,
    rep_nudge_sent_at=None,
    manager_nudge_sent_at=None,
    noshow_task_created=False,
    assigned_to=REP_ID,
):
    return {
        "id": DEMO_ID,
        "org_id": ORG_ID,
        "lead_id": LEAD_ID,
        "assigned_to": assigned_to,
        "scheduled_at": scheduled_at.isoformat(),
        "status": "confirmed",
        "reminder_24h_sent": False,
        "reminder_1h_sent": False,
        "noshow_task_created": noshow_task_created,
        "rep_nudge_sent_at": rep_nudge_sent_at,
        "manager_nudge_sent_at": manager_nudge_sent_at,
    }


def _make_db(manager_ids=None):
    """Minimal Supabase mock — routes by table name."""
    lead_data = {
        "id": LEAD_ID, "full_name": "Amara Osei",
        "whatsapp": "2348000000000", "phone": None,
    }
    user_rows = [
        {"id": mid, "is_active": True, "roles": {"template": "ops_manager"}}
        for mid in (manager_ids or [MGR_ID])
    ]

    def table_side(name):
        t = MagicMock()
        t.select.return_value = t
        t.eq.return_value     = t
        t.neq.return_value    = t
        t.update.return_value = t
        t.maybe_single.return_value = t
        t.is_.return_value    = t
        t.gte.return_value    = t
        t.lte.return_value    = t
        t.insert.return_value = t
        if name == "leads":
            t.execute.return_value = MagicMock(data=lead_data)
        elif name == "users":
            t.execute.return_value = MagicMock(data=user_rows)
        else:
            t.execute.return_value = MagicMock(data=None)
        return t

    db = MagicMock()
    db.table.side_effect = table_side
    return db


# ── Business hours tests ──────────────────────────────────────────────────────

class TestBusinessHours:

    def test_weekday_inside_hours(self):
        from app.workers.demo_reminder_worker import _is_business_hours
        dt = datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
        assert _is_business_hours(dt) is True

    def test_weekday_outside_hours_evening(self):
        from app.workers.demo_reminder_worker import _is_business_hours
        dt = datetime(2026, 4, 13, 20, 0, 0, tzinfo=timezone.utc)
        assert _is_business_hours(dt) is False

    def test_weekend_returns_false(self):
        from app.workers.demo_reminder_worker import _is_business_hours
        dt = datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc)
        assert _is_business_hours(dt) is False

    def test_next_biz_morning_friday_evening(self):
        from app.workers.demo_reminder_worker import _next_business_day_morning
        friday_evening = datetime(2026, 4, 10, 21, 0, 0, tzinfo=timezone.utc)
        result = _next_business_day_morning(friday_evening)
        assert result.weekday() == 0   # Monday
        assert result.hour == 9
        assert result.minute == 0

    def test_next_biz_morning_saturday(self):
        from app.workers.demo_reminder_worker import _next_business_day_morning
        saturday = datetime(2026, 4, 11, 14, 0, 0, tzinfo=timezone.utc)
        result = _next_business_day_morning(saturday)
        assert result.weekday() == 0   # Monday
        assert result.hour == 9


# ── Escalation due logic ──────────────────────────────────────────────────────

class TestEscalationDue:

    def test_threshold_not_reached_returns_false(self):
        from app.workers.demo_reminder_worker import _escalation_due
        scheduled = NOW_BIZ - timedelta(hours=2)
        assert _escalation_due(scheduled, NOW_BIZ) is False

    def test_threshold_reached_in_biz_hours_returns_true(self):
        from app.workers.demo_reminder_worker import _escalation_due
        scheduled = NOW_BIZ - timedelta(hours=5)
        assert _escalation_due(scheduled, NOW_BIZ) is True

    def test_threshold_reached_outside_hours_hold_not_passed(self):
        from app.workers.demo_reminder_worker import _escalation_due
        # T+4h lands outside hours and hold point (next morning) not yet reached
        scheduled_late = NOW_EVENING - timedelta(hours=4, minutes=1)
        assert _escalation_due(scheduled_late, NOW_EVENING) is False

    def test_threshold_reached_hold_point_passed(self):
        from app.workers.demo_reminder_worker import _escalation_due
        # Friday 16:00 demo, now Monday 10:00 — hold was Monday 09:00
        friday_16 = datetime(2026, 4, 10, 16, 0, 0, tzinfo=timezone.utc)
        monday_10 = datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
        assert _escalation_due(friday_16, monday_10) is True


# ── _process_demo nudge tests ─────────────────────────────────────────────────

class TestProcessDemoNudges:

    @patch("app.workers.demo_reminder_worker._now")
    def test_rep_nudge_fires_at_t_plus_2h(self, mock_now):
        """
        T+2h past, rep_nudge_sent_at null → rep in-app notification sent.
        noshow_task_created=True ensures auto no-show branch is skipped
        so execution reaches the nudge checks.
        """
        scheduled = NOW_BIZ - timedelta(hours=3)
        mock_now.return_value = NOW_BIZ
        db = _make_db()
        demo = _demo(scheduled, noshow_task_created=True, rep_nudge_sent_at=None)

        from app.workers.demo_reminder_worker import _process_demo
        result = _process_demo(db, demo, phone_id="")

        assert result["rep_nudge"] is True
        assert result["auto_noshow"] is False

        notif_calls = [
            c for c in db.table.call_args_list
            if c.args and c.args[0] == "notifications"
        ]
        assert len(notif_calls) >= 1

    @patch("app.workers.demo_reminder_worker._now")
    def test_rep_nudge_not_fired_if_already_sent(self, mock_now):
        """rep_nudge_sent_at already set → no second nudge."""
        scheduled = NOW_BIZ - timedelta(hours=3)
        mock_now.return_value = NOW_BIZ
        db = _make_db()
        demo = _demo(
            scheduled,
            noshow_task_created=True,
            rep_nudge_sent_at="2026-04-13T12:00:00+00:00",
        )

        from app.workers.demo_reminder_worker import _process_demo
        result = _process_demo(db, demo, phone_id="")

        assert result["rep_nudge"] is False

    @patch("app.workers.demo_reminder_worker._now")
    def test_manager_escalation_fires_when_due(self, mock_now):
        """
        T+4h crossed, business hours, manager_nudge_sent_at null → managers notified.
        noshow_task_created=True ensures auto no-show branch is skipped.
        """
        scheduled = NOW_BIZ - timedelta(hours=5)
        mock_now.return_value = NOW_BIZ
        db = _make_db(manager_ids=[MGR_ID])
        demo = _demo(
            scheduled,
            noshow_task_created=True,
            rep_nudge_sent_at="2026-04-13T11:00:00+00:00",
            manager_nudge_sent_at=None,
        )

        from app.workers.demo_reminder_worker import _process_demo
        result = _process_demo(db, demo, phone_id="")

        assert result["manager_nudge"] is True

        notif_calls = [
            c for c in db.table.call_args_list
            if c.args and c.args[0] == "notifications"
        ]
        assert len(notif_calls) >= 1

    @patch("app.workers.demo_reminder_worker._now")
    def test_manager_escalation_not_fired_if_already_sent(self, mock_now):
        """manager_nudge_sent_at already set → no second escalation."""
        scheduled = NOW_BIZ - timedelta(hours=5)
        mock_now.return_value = NOW_BIZ
        db = _make_db()
        demo = _demo(
            scheduled,
            noshow_task_created=True,
            rep_nudge_sent_at="2026-04-13T11:00:00+00:00",
            manager_nudge_sent_at="2026-04-13T13:00:00+00:00",
        )

        from app.workers.demo_reminder_worker import _process_demo
        result = _process_demo(db, demo, phone_id="")

        assert result["manager_nudge"] is False

    @patch("app.workers.demo_reminder_worker._now")
    def test_future_demo_no_nudges(self, mock_now):
        """Demo is in the future — no nudges fired."""
        scheduled = NOW_BIZ + timedelta(hours=30)
        mock_now.return_value = NOW_BIZ
        db = _make_db()
        demo = _demo(scheduled)

        from app.workers.demo_reminder_worker import _process_demo
        result = _process_demo(db, demo, phone_id="")

        assert result["rep_nudge"] is False
        assert result["manager_nudge"] is False
        assert result["auto_noshow"] is False

    @patch("app.workers.demo_reminder_worker._now")
    def test_auto_noshow_takes_priority_over_nudges(self, mock_now):
        """
        Auto no-show fires at T+30min and returns early —
        nudge checks never reached.
        Pattern 42: patch at app.services.demo_service.log_outcome —
        log_outcome is imported lazily inside _process_demo, so it is NOT
        an attribute on the worker module. Patching the worker module directly
        raises AttributeError.
        """
        scheduled = NOW_BIZ - timedelta(minutes=60)
        mock_now.return_value = NOW_BIZ
        db = _make_db()
        demo = _demo(scheduled, noshow_task_created=False)

        # Pattern 42: patch where the name is USED
        with patch("app.services.demo_service.log_outcome") as mock_lo:
            mock_lo.return_value = {"id": DEMO_ID, "status": "no_show"}
            from app.workers.demo_reminder_worker import _process_demo
            result = _process_demo(db, demo, phone_id="")

        assert result["auto_noshow"] is True
        assert result["rep_nudge"] is False
        assert result["manager_nudge"] is False


# ── Manager ID helper tests ───────────────────────────────────────────────────

class TestGetAllManagerIds:

    def test_returns_only_managers(self):
        """Only owner/admin/ops_manager rows returned, not sales_agent."""
        db = MagicMock()
        tbl = MagicMock()
        tbl.select.return_value = tbl
        tbl.eq.return_value     = tbl
        tbl.execute.return_value = MagicMock(data=[
            {"id": "aaa", "is_active": True, "roles": {"template": "ops_manager"}},
            {"id": "bbb", "is_active": True, "roles": {"template": "sales_agent"}},
            {"id": "ccc", "is_active": True, "roles": {"template": "owner"}},
        ])
        db.table.return_value = tbl

        from app.workers.demo_reminder_worker import _get_all_manager_ids
        result = _get_all_manager_ids(db, ORG_ID)

        assert "aaa" in result
        assert "ccc" in result
        assert "bbb" not in result

    def test_db_failure_returns_empty_list(self):
        """DB error → returns [] without raising (S14)."""
        db = MagicMock()
        db.table.side_effect = Exception("connection refused")

        from app.workers.demo_reminder_worker import _get_all_manager_ids
        result = _get_all_manager_ids(db, ORG_ID)

        assert result == []


# ── Summary keys test ─────────────────────────────────────────────────────────

class TestWorkerSummaryKeys:

    @patch("app.workers.demo_reminder_worker.get_supabase")
    def test_summary_includes_nudge_keys(self, mock_get_db):
        """run_demo_reminder_check returns summary with rep_nudges + manager_nudges."""
        db = MagicMock()
        db.table.return_value.select.return_value \
            .execute.return_value = MagicMock(data=[])
        mock_get_db.return_value = db

        from app.workers.demo_reminder_worker import run_demo_reminder_check
        result = run_demo_reminder_check.run()

        assert "rep_nudges" in result
        assert "manager_nudges" in result
        assert result["failed"] == 0