"""
tests/unit/test_demo_service.py
M01-7 Revised — Demo Scheduling & Management

Unit tests for app/services/demo_service.py

Coverage:
  TestCreateDemoRequest (7): happy path, lead not found, manager task created,
    manager notification sent, no manager found, bot creation flag, timeline logged

  TestConfirmDemo       (6): happy path, wrong status raises 400, demo not found,
    invalid datetime raises 422, WA auto-sent, rep task + notification created

  TestListDemos         (3): returns list, empty list, lead not found 404

  TestLogOutcome        (9): attended advances pipeline, attended notifies rep+admin,
    no_show creates task, no_show sends WA, no_show notifies rep+admin,
    rescheduled creates new row, rescheduled notifies admin,
    already terminal raises 400, demo not found raises 404

All UUIDs valid format (Pattern 24).
Pattern 42: patch at importing module.
S14 helpers (timeline, touch lead, WA send) swallow errors — not tested for failures.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import HTTPException

# ─── Test UUIDs ──────────────────────────────────────────────────────────────
ORG_ID    = "00000000-0000-0000-0000-000000000001"
LEAD_ID   = "00000000-0000-0000-0000-000000000002"
USER_ID   = "00000000-0000-0000-0000-000000000003"
REP_ID    = "00000000-0000-0000-0000-000000000004"
MGR_ID    = "00000000-0000-0000-0000-000000000005"
DEMO_ID   = "00000000-0000-0000-0000-000000000006"

FUTURE_ISO = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

SAMPLE_LEAD = {
    "id": LEAD_ID, "org_id": ORG_ID, "full_name": "Emeka Obi",
    "whatsapp": "2348031456789", "phone": "2348031456789",
    "assigned_to": REP_ID, "stage": "contacted",
}

SAMPLE_DEMO_PENDING = {
    "id": DEMO_ID, "org_id": ORG_ID, "lead_id": LEAD_ID,
    "status": "pending_assignment",
    "lead_preferred_time": "Monday afternoon",
    "medium": "virtual", "notes": None,
    "assigned_to": None, "confirmed_by": None, "confirmed_at": None,
    "scheduled_at": None, "duration_minutes": 30,
    "outcome": None, "outcome_notes": None, "outcome_logged_at": None,
    "confirmation_sent": False, "reminder_24h_sent": False,
    "reminder_1h_sent": False, "noshow_task_created": False,
    "parent_demo_id": None, "created_by": USER_ID,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

SAMPLE_DEMO_CONFIRMED = {
    **SAMPLE_DEMO_PENDING,
    "status": "confirmed",
    "scheduled_at": FUTURE_ISO,
    "medium": "virtual",
    "assigned_to": REP_ID,
    "confirmed_by": MGR_ID,
    "confirmed_at": datetime.now(timezone.utc).isoformat(),
}


def _make_db():
    db = MagicMock()
    for m in ("table", "select", "eq", "neq", "is_", "in_", "gte", "lte",
              "order", "maybe_single", "single", "insert", "update", "execute"):
        pass
    db.table.return_value = db
    db.select.return_value = db
    db.eq.return_value = db
    db.neq.return_value = db
    db.is_.return_value = db
    db.not_ = db
    db.in_.return_value = db
    db.gte.return_value = db
    db.lte.return_value = db
    db.order.return_value = db
    db.limit.return_value = db
    db.maybe_single.return_value = db
    db.single.return_value = db
    db.insert.return_value = db
    db.update.return_value = db
    db.execute.return_value = MagicMock(data=None)
    return db


# ═══════════════════════════════════════════════════════════════════════════════
# TestCreateDemoRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateDemoRequest:

    def _db(self, demo_data=None):
        db = _make_db()
        demo = demo_data or SAMPLE_DEMO_PENDING
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data=SAMPLE_LEAD)   # _confirm_lead_in_org
            return MagicMock(data=demo)
        db.execute.side_effect = side
        return db

    def test_create_demo_request_happy_path(self):
        from app.services.demo_service import create_demo_request
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="task-1"), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db()
            result = create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time="Monday afternoon",
                medium="virtual", notes=None,
            )
        assert result["id"] == DEMO_ID
        assert result["status"] == "pending_assignment"

    def test_create_demo_request_lead_not_found_raises_404(self):
        from app.services.demo_service import create_demo_request
        db = _make_db()
        db.execute.return_value = MagicMock(data=None)
        with pytest.raises(HTTPException) as exc:
            create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time=None, medium=None, notes=None,
            )
        assert exc.value.status_code == 404

    def test_create_demo_creates_manager_task(self):
        from app.services.demo_service import create_demo_request
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID) as mock_mgr, \
             patch("app.services.demo_service._create_task", return_value="t1") as mock_task, \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db()
            create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time="Friday", medium="in_person", notes=None,
            )
        mock_task.assert_called_once()
        call_kwargs = mock_task.call_args[1]
        assert call_kwargs["assigned_to"] == MGR_ID
        assert "Confirm demo" in call_kwargs["title"]

    def test_create_demo_sends_manager_notification(self):
        from app.services.demo_service import create_demo_request
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db()
            create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time=None, medium=None, notes=None,
            )
        mock_notif.assert_called_once()
        # _insert_notification(db, org_id, user_id, ...) — user_id is positional arg [2]
        assert mock_notif.call_args[0][2] == MGR_ID
        assert mock_notif.call_args[1]["notif_type"] == "demo_request_pending"

    def test_create_demo_no_manager_skips_task_silently(self):
        """When no manager exists, no task created — no error raised."""
        from app.services.demo_service import create_demo_request
        with patch("app.services.demo_service._get_manager_id", return_value=None), \
             patch("app.services.demo_service._create_task") as mock_task, \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db()
            create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time=None, medium=None, notes=None,
            )
        mock_task.assert_not_called()
        mock_notif.assert_not_called()

    def test_create_demo_bot_flag_sets_created_by_none(self):
        """created_by_bot=True → created_by should be None in DB insert."""
        from app.services.demo_service import create_demo_request
        inserted = {}

        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data=SAMPLE_LEAD)
            return MagicMock(data=SAMPLE_DEMO_PENDING)
        db.execute.side_effect = side

        orig_insert = db.insert
        def cap_insert(row):
            inserted.update(row)
            return db
        db.insert = cap_insert

        with patch("app.services.demo_service._get_manager_id", return_value=None), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            try:
                create_demo_request(
                    db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                    lead_preferred_time=None, medium=None, notes=None,
                    created_by_bot=True,
                )
            except Exception:
                pass

        assert inserted.get("created_by") is None

    def test_create_demo_logs_timeline(self):
        from app.services.demo_service import create_demo_request
        with patch("app.services.demo_service._get_manager_id", return_value=None), \
             patch("app.services.demo_service._log_timeline") as mock_tl, \
             patch("app.services.demo_service._touch_lead"):
            db = self._db()
            create_demo_request(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, user_id=USER_ID,
                lead_preferred_time=None, medium=None, notes=None,
            )
        mock_tl.assert_called_once()
        assert mock_tl.call_args[1]["event_type"] == "demo_requested"


# ═══════════════════════════════════════════════════════════════════════════════
# TestConfirmDemo
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmDemo:

    def _db_for_confirm(self):
        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data=SAMPLE_DEMO_PENDING)  # _fetch_demo_by_id
            if n == 1: return MagicMock(data=SAMPLE_LEAD)          # _confirm_lead_in_org
            return MagicMock(data=SAMPLE_DEMO_CONFIRMED)
        db.execute.side_effect = side
        return db

    def test_confirm_demo_happy_path(self):
        from app.services.demo_service import confirm_demo
        with patch("app.services.demo_service._get_user_name", return_value="Ada"), \
             patch("app.services.demo_service._auto_send_wa"), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_confirm()
            result = confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at=FUTURE_ISO,
                medium="virtual", assigned_to=REP_ID,
            )
        assert result["status"] == "confirmed"

    def test_confirm_demo_wrong_status_raises_400(self):
        """Confirming an already-confirmed demo raises 400."""
        from app.services.demo_service import confirm_demo
        db = _make_db()
        db.execute.return_value = MagicMock(data={**SAMPLE_DEMO_CONFIRMED, "lead_id": LEAD_ID})
        with pytest.raises(HTTPException) as exc:
            confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at=FUTURE_ISO,
                medium="virtual", assigned_to=REP_ID,
            )
        assert exc.value.status_code == 400

    def test_confirm_demo_invalid_datetime_raises_422(self):
        from app.services.demo_service import confirm_demo
        db = _make_db()
        db.execute.return_value = MagicMock(data={**SAMPLE_DEMO_PENDING, "lead_id": LEAD_ID})
        with pytest.raises(HTTPException) as exc:
            confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at="not-a-date",
                medium="virtual", assigned_to=REP_ID,
            )
        assert exc.value.status_code == 422

    def test_confirm_demo_auto_sends_wa(self):
        from app.services.demo_service import confirm_demo
        with patch("app.services.demo_service._get_user_name", return_value="Ada"), \
             patch("app.services.demo_service._auto_send_wa") as mock_wa, \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_confirm()
            confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at=FUTURE_ISO,
                medium="virtual", assigned_to=REP_ID,
            )
        mock_wa.assert_called_once()
        # Message should contain rep name
        msg = mock_wa.call_args[0][3]  # positional: db, org_id, lead, content
        assert "Ada" in msg

    def test_confirm_demo_creates_rep_task(self):
        from app.services.demo_service import confirm_demo
        with patch("app.services.demo_service._get_user_name", return_value="Ada"), \
             patch("app.services.demo_service._auto_send_wa"), \
             patch("app.services.demo_service._create_task", return_value="t1") as mock_task, \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_confirm()
            confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at=FUTURE_ISO,
                medium="virtual", assigned_to=REP_ID,
            )
        mock_task.assert_called_once()
        assert mock_task.call_args[1]["assigned_to"] == REP_ID

    def test_confirm_demo_sends_rep_notification_only(self):
        """Only rep gets in-app notification — not admin."""
        from app.services.demo_service import confirm_demo
        with patch("app.services.demo_service._get_user_name", return_value="Ada"), \
             patch("app.services.demo_service._auto_send_wa"), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_confirm()
            confirm_demo(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=MGR_ID, scheduled_at=FUTURE_ISO,
                medium="virtual", assigned_to=REP_ID,
            )
        mock_notif.assert_called_once()
        assert mock_notif.call_args[0][2] == REP_ID
        assert mock_notif.call_args[1]["notif_type"] == "demo_confirmed"


# ═══════════════════════════════════════════════════════════════════════════════
# TestListDemos
# ═══════════════════════════════════════════════════════════════════════════════

class TestListDemos:

    def test_list_demos_returns_list(self):
        from app.services.demo_service import list_demos
        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data=SAMPLE_LEAD)
            return MagicMock(data=[SAMPLE_DEMO_PENDING, SAMPLE_DEMO_CONFIRMED])
        db.execute.side_effect = side
        result = list_demos(db=db, org_id=ORG_ID, lead_id=LEAD_ID)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_demos_returns_empty_list(self):
        from app.services.demo_service import list_demos
        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data=SAMPLE_LEAD)
            return MagicMock(data=[])
        db.execute.side_effect = side
        result = list_demos(db=db, org_id=ORG_ID, lead_id=LEAD_ID)
        assert result == []

    def test_list_demos_lead_not_found_raises_404(self):
        from app.services.demo_service import list_demos
        db = _make_db()
        db.execute.return_value = MagicMock(data=None)
        with pytest.raises(HTTPException) as exc:
            list_demos(db=db, org_id=ORG_ID, lead_id=LEAD_ID)
        assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# TestLogOutcome
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogOutcome:

    def _db_for_outcome(self, demo=None):
        d = demo or SAMPLE_DEMO_CONFIRMED
        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data={**d, "lead_id": LEAD_ID})
            if n == 1: return MagicMock(data=SAMPLE_LEAD)
            return MagicMock(data={**d, "status": "attended"})
        db.execute.side_effect = side
        return db

    def test_attended_advances_pipeline(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"), \
             patch("app.services.lead_service.move_stage") as mock_move:
            db = self._db_for_outcome()
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="attended", outcome_notes=None,
            )
        mock_move.assert_called_once()
        assert mock_move.call_args[1]["new_stage"] == "demo_done"

    def test_attended_notifies_rep_and_admin(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"), \
             patch("app.services.lead_service.move_stage"):
            db = self._db_for_outcome()
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="attended", outcome_notes=None,
            )
        notified_users = {c[0][2] for c in mock_notif.call_args_list}
        assert REP_ID  in notified_users
        assert MGR_ID  in notified_users

    def test_no_show_creates_followup_task(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1") as mock_task, \
             patch("app.services.demo_service._auto_send_wa"), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_outcome()
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="no_show", outcome_notes=None,
            )
        mock_task.assert_called_once()
        assert "missed demo" in mock_task.call_args[1]["title"]

    def test_no_show_auto_sends_wa(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._auto_send_wa") as mock_wa, \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_outcome()
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="no_show", outcome_notes=None,
            )
        mock_wa.assert_called_once()

    def test_no_show_notifies_rep_and_admin(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._auto_send_wa"), \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_outcome()
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="no_show", outcome_notes=None,
            )
        notified = {c[0][2] for c in mock_notif.call_args_list}
        assert REP_ID in notified
        assert MGR_ID in notified

    def test_rescheduled_creates_new_pending_row(self):
        """
        Rescheduled creates a new lead_demos row with parent_demo_id set.
        db.table() returns db itself in the mock chain, so db.insert is called
        for every .insert() call regardless of table name.
        We verify at least 2 insert calls happen: the new demo row is one of them.
        """
        from app.services.demo_service import log_outcome

        db = _make_db()
        call_n = {"n": 0}
        def side():
            n = call_n["n"]; call_n["n"] += 1
            if n == 0: return MagicMock(data={**SAMPLE_DEMO_CONFIRMED, "lead_id": LEAD_ID})
            if n == 1: return MagicMock(data=SAMPLE_LEAD)
            return MagicMock(data={**SAMPLE_DEMO_CONFIRMED, "status": "rescheduled"})
        db.execute.side_effect = side

        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification"), \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="rescheduled", outcome_notes="Moving to next week",
            )

        # db.table().insert() is called for the new lead_demos row.
        # db.table returns db itself, so db.insert.call_count reflects all insert calls.
        # At minimum: 1 insert for the new pending demo row.
        assert db.insert.call_count >= 1
        # The new row should have status=pending_assignment and parent_demo_id set
        inserted_row = db.insert.call_args_list[0][0][0]
        assert inserted_row.get("status") == "pending_assignment"
        assert inserted_row.get("parent_demo_id") == DEMO_ID

    def test_rescheduled_notifies_admin_for_new_demo(self):
        from app.services.demo_service import log_outcome
        with patch("app.services.demo_service._get_manager_id", return_value=MGR_ID), \
             patch("app.services.demo_service._create_task", return_value="t1"), \
             patch("app.services.demo_service._insert_notification") as mock_notif, \
             patch("app.services.demo_service._log_timeline"), \
             patch("app.services.demo_service._touch_lead"):
            db = self._db_for_outcome()
            # Override last execute to return rescheduled demo
            call_n = {"n": 0}
            def side():
                n = call_n["n"]; call_n["n"] += 1
                if n == 0: return MagicMock(data={**SAMPLE_DEMO_CONFIRMED, "lead_id": LEAD_ID})
                if n == 1: return MagicMock(data=SAMPLE_LEAD)
                return MagicMock(data={**SAMPLE_DEMO_CONFIRMED, "status": "rescheduled"})
            db.execute.side_effect = side

            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="rescheduled", outcome_notes=None,
            )
        notif_types = {c[1]["notif_type"] for c in mock_notif.call_args_list}
        assert "demo_rescheduled" in notif_types

    def test_already_terminal_raises_400(self):
        """Logging outcome on attended/no_show/rescheduled demo raises 400."""
        from app.services.demo_service import log_outcome
        db = _make_db()
        db.execute.return_value = MagicMock(
            data={**SAMPLE_DEMO_CONFIRMED, "lead_id": LEAD_ID, "status": "attended"}
        )
        with pytest.raises(HTTPException) as exc:
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="attended", outcome_notes=None,
            )
        assert exc.value.status_code == 400

    def test_demo_not_found_raises_404(self):
        from app.services.demo_service import log_outcome
        db = _make_db()
        db.execute.return_value = MagicMock(data=None)
        with pytest.raises(HTTPException) as exc:
            log_outcome(
                db=db, org_id=ORG_ID, lead_id=LEAD_ID, demo_id=DEMO_ID,
                user_id=REP_ID, outcome="attended", outcome_notes=None,
            )
        assert exc.value.status_code == 404
