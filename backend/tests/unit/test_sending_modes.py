"""
backend/tests/unit/test_sending_modes.py
-----------------------------------------
Unit tests for M01-4 (Three Sending Modes) and M01-5
(Re-engagement Fallback Worker).

Patch targets:
  TestDispatchOutboxRow    → app.services.whatsapp_service._call_meta_send
  TestReviewWindowSender   → app.workers.qualification_worker._dispatch_outbox_row
  TestQualificationFallback → app.workers.qualification_worker._call_meta_send

Pattern 24: all UUIDs are valid format.
Pattern 42: patch at the module where the name is used, not where it's defined.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Constants — Pattern 24: valid UUID format
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
LEAD_ID = "00000000-0000-0000-0000-000000000002"
USER_ID = "00000000-0000-0000-0000-000000000003"
SESS_ID = "00000000-0000-0000-0000-000000000004"


# ===========================================================================
# TestQueueOutboxMessage
# ===========================================================================

class TestQueueOutboxMessage:

    def test_full_approval_creates_pending_row(self):
        from app.services.whatsapp_service import queue_outbox_message

        inserted_row = {}

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                r.data = {"qualification_sending_mode": "full_approval", "review_window_minutes": 5}
                return r
            t.execute.side_effect = _exec

            def _insert(row):
                inserted_row.update(row)
                ins = MagicMock()
                def _ins_exec():
                    res = MagicMock()
                    res.data = {**row, "id": "00000000-0000-0000-0000-000000000010"}
                    return res
                ins.execute.side_effect = _ins_exec
                return ins
            t.insert.side_effect = _insert
            return t

        db = MagicMock()
        db.table.side_effect = _tbl

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            queue_outbox_message(
                db=db, org_id=ORG_ID,
                lead_id=LEAD_ID, customer_id=None,
                content="Hello!", template_name=None,
                source_type="qualification_reply", queued_by=USER_ID,
            )

        assert inserted_row.get("status") == "pending"
        assert inserted_row.get("lead_id") == LEAD_ID
        assert inserted_row.get("content") == "Hello!"

    def test_review_window_sets_send_after(self):
        from app.services.whatsapp_service import queue_outbox_message

        inserted_row = {}

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                r.data = {"qualification_sending_mode": "review_window", "review_window_minutes": 10}
                return r
            t.execute.side_effect = _exec

            def _insert(row):
                inserted_row.update(row)
                ins = MagicMock()
                def _ins_exec():
                    res = MagicMock()
                    res.data = {**row, "id": "00000000-0000-0000-0000-000000000011"}
                    return res
                ins.execute.side_effect = _ins_exec
                return ins
            t.insert.side_effect = _insert
            return t

        db = MagicMock()
        db.table.side_effect = _tbl

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            queue_outbox_message(
                db=db, org_id=ORG_ID,
                lead_id=LEAD_ID, customer_id=None,
                content="Hi there", template_name=None,
                source_type="first_touch", queued_by=USER_ID,
            )

        assert inserted_row.get("status") == "scheduled"
        assert "send_after" in inserted_row
        send_after_dt = datetime.fromisoformat(
            inserted_row["send_after"].replace("Z", "+00:00")
        )
        diff = (send_after_dt - datetime.now(timezone.utc)).total_seconds()
        assert 540 < diff < 660  # ~10 minutes

    def test_auto_send_dispatches_immediately(self):
        from app.services.whatsapp_service import queue_outbox_message

        pending_row = {
            "id": "00000000-0000-0000-0000-000000000012",
            "org_id": ORG_ID, "lead_id": LEAD_ID,
            "content": "Auto msg", "template_name": None, "status": "pending",
        }

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                r.data = {"qualification_sending_mode": "auto_send", "review_window_minutes": 5}
                return r
            t.execute.side_effect = _exec

            def _insert(row):
                ins = MagicMock()
                def _ins_exec():
                    res = MagicMock()
                    res.data = pending_row
                    return res
                ins.execute.side_effect = _ins_exec
                return ins
            t.insert.side_effect = _insert
            return t

        db = MagicMock()
        db.table.side_effect = _tbl

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x), \
             patch("app.services.whatsapp_service._dispatch_outbox_row",
                   return_value={**pending_row, "status": "sent"}) as mock_dispatch:
            result = queue_outbox_message(
                db=db, org_id=ORG_ID,
                lead_id=LEAD_ID, customer_id=None,
                content="Auto msg", template_name=None,
                source_type="qualification_reply", queued_by=USER_ID,
            )

        mock_dispatch.assert_called_once()
        assert result["status"] == "sent"

    def test_unknown_mode_falls_back_to_full_approval(self):
        from app.services.whatsapp_service import queue_outbox_message

        inserted_row = {}

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                r.data = {"qualification_sending_mode": "INVALID", "review_window_minutes": 5}
                return r
            t.execute.side_effect = _exec

            def _insert(row):
                inserted_row.update(row)
                ins = MagicMock()
                def _ins_exec():
                    res = MagicMock()
                    res.data = {**row, "id": "00000000-0000-0000-0000-000000000013"}
                    return res
                ins.execute.side_effect = _ins_exec
                return ins
            t.insert.side_effect = _insert
            return t

        db = MagicMock()
        db.table.side_effect = _tbl

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            queue_outbox_message(
                db=db, org_id=ORG_ID,
                lead_id=LEAD_ID, customer_id=None,
                content="Test", template_name=None,
                source_type="test", queued_by=USER_ID,
            )

        assert inserted_row.get("status") == "pending"
        assert "send_after" not in inserted_row


# ===========================================================================
# TestDispatchOutboxRow
# _call_meta_send lives in whatsapp_service → patch there
# ===========================================================================

class TestDispatchOutboxRow:

    def _base_row(self, **kwargs):
        row = {
            "id": "00000000-0000-0000-0000-000000000020",
            "org_id": ORG_ID, "lead_id": LEAD_ID, "customer_id": None,
            "content": "Hello lead!", "template_name": None, "status": "pending",
        }
        row.update(kwargs)
        return row

    def _make_db(self, phone_id="ph-111", wa_number="2348000000001"):
        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.insert.return_value = t
            t.update.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                if name == "organisations":
                    r.data = {"whatsapp_phone_id": phone_id}
                elif name == "leads":
                    r.data = {"whatsapp": wa_number, "phone": None}
                elif name == "whatsapp_outbox":
                    r.data = {**self._base_row(), "status": "sent"}
                else:
                    r.data = []
                return r
            t.execute.side_effect = _exec
            return t

        db.table.side_effect = _tbl
        return db

    def test_dispatch_happy_path_marks_sent(self):
        from app.services.whatsapp_service import _dispatch_outbox_row

        db = self._make_db()
        with patch("app.services.whatsapp_service._call_meta_send",
                   return_value={"messages": [{"id": "meta-001"}]}), \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = _dispatch_outbox_row(
                db=db, org_id=ORG_ID,
                outbox_row=self._base_row(), actioned_by=USER_ID,
            )
        assert result.get("status") == "sent"

    def test_dispatch_meta_failure_marks_failed(self):
        from app.services.whatsapp_service import _dispatch_outbox_row
        from fastapi import HTTPException

        db = self._make_db()
        with patch("app.services.whatsapp_service._call_meta_send",
                   side_effect=HTTPException(status_code=503, detail="INTEGRATION_ERROR")), \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = _dispatch_outbox_row(
                db=db, org_id=ORG_ID,
                outbox_row=self._base_row(), actioned_by=USER_ID,
            )
        assert result.get("status") == "failed"

    def test_dispatch_missing_phone_id_marks_failed(self):
        from app.services.whatsapp_service import _dispatch_outbox_row

        db = self._make_db(phone_id="")
        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = _dispatch_outbox_row(
                db=db, org_id=ORG_ID,
                outbox_row=self._base_row(), actioned_by=USER_ID,
            )
        assert result.get("status") == "failed"

    def test_dispatch_uses_template_payload_when_template_name_set(self):
        from app.services.whatsapp_service import _dispatch_outbox_row

        db = self._make_db()
        row = self._base_row(content=None, template_name="welcome_lead")
        with patch("app.services.whatsapp_service._call_meta_send",
                   return_value={"messages": [{"id": "meta-tmpl"}]}) as mock_send, \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            _dispatch_outbox_row(
                db=db, org_id=ORG_ID, outbox_row=row, actioned_by=USER_ID,
            )

        payload = mock_send.call_args[0][1]
        assert payload["type"] == "template"
        assert payload["template"]["name"] == "welcome_lead"


# ===========================================================================
# TestApproveOutboxMessage
# ===========================================================================

class TestApproveOutboxMessage:

    def _make_db(self, outbox_row):
        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.update.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                r.data = outbox_row
                return r
            t.execute.side_effect = _exec
            return t

        db.table.side_effect = _tbl
        return db

    def test_approve_pending_dispatches_and_returns_sent(self):
        from app.services.whatsapp_service import approve_outbox_message

        pending_row = {
            "id": "00000000-0000-0000-0000-000000000030",
            "org_id": ORG_ID, "lead_id": LEAD_ID,
            "content": "Hi", "template_name": None, "status": "pending",
        }
        db = self._make_db(pending_row)

        with patch("app.services.whatsapp_service._dispatch_outbox_row",
                   return_value={**pending_row, "status": "sent"}), \
             patch("app.services.whatsapp_service.write_audit_log"), \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = approve_outbox_message(
                db=db, org_id=ORG_ID,
                outbox_id="00000000-0000-0000-0000-000000000030",
                user_id=USER_ID,
            )
        assert result["status"] == "sent"

    def test_approve_already_sent_raises_400(self):
        from app.services.whatsapp_service import approve_outbox_message
        from fastapi import HTTPException

        sent_row = {
            "id": "00000000-0000-0000-0000-000000000031",
            "org_id": ORG_ID, "status": "sent",
        }
        db = self._make_db(sent_row)

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            with pytest.raises(HTTPException) as exc_info:
                approve_outbox_message(
                    db=db, org_id=ORG_ID,
                    outbox_id="00000000-0000-0000-0000-000000000031",
                    user_id=USER_ID,
                )
        assert exc_info.value.status_code == 400

    def test_approve_nonexistent_raises_404(self):
        from app.services.whatsapp_service import approve_outbox_message
        from fastapi import HTTPException

        db = self._make_db(None)

        with patch("app.services.whatsapp_service._normalise_data", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                approve_outbox_message(
                    db=db, org_id=ORG_ID,
                    outbox_id="00000000-0000-0000-0000-000000000099",
                    user_id=USER_ID,
                )
        assert exc_info.value.status_code == 404


# ===========================================================================
# TestCancelOutboxMessage
# Separate select and update chains so update returns the cancelled row.
# ===========================================================================

class TestCancelOutboxMessage:

    def _make_db_for_cancel(self, initial_status):
        row_id      = "00000000-0000-0000-0000-000000000040"
        initial_row = {"id": row_id, "org_id": ORG_ID, "status": initial_status}

        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.eq.return_value = t
            t.maybe_single.return_value = t

            # SELECT → returns initial row
            select_chain = MagicMock()
            select_chain.eq.return_value = select_chain
            select_chain.maybe_single.return_value = select_chain
            def _select_exec():
                r = MagicMock()
                r.data = initial_row
                return r
            select_chain.execute.side_effect = _select_exec
            t.select.return_value = select_chain

            # UPDATE → returns cancelled row
            update_chain = MagicMock()
            update_chain.eq.return_value = update_chain
            def _update_exec():
                r = MagicMock()
                r.data = {**initial_row, "status": "cancelled"}
                return r
            update_chain.execute.side_effect = _update_exec
            t.update.return_value = update_chain

            return t

        db.table.side_effect = _tbl
        return db

    def test_cancel_pending_marks_cancelled(self):
        from app.services.whatsapp_service import cancel_outbox_message

        db = self._make_db_for_cancel("pending")
        with patch("app.services.whatsapp_service.write_audit_log"), \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = cancel_outbox_message(
                db=db, org_id=ORG_ID,
                outbox_id="00000000-0000-0000-0000-000000000040",
                user_id=USER_ID,
            )
        assert result["status"] == "cancelled"

    def test_cancel_scheduled_marks_cancelled(self):
        from app.services.whatsapp_service import cancel_outbox_message

        db = self._make_db_for_cancel("scheduled")
        with patch("app.services.whatsapp_service.write_audit_log"), \
             patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            result = cancel_outbox_message(
                db=db, org_id=ORG_ID,
                outbox_id="00000000-0000-0000-0000-000000000040",
                user_id=USER_ID,
            )
        assert result["status"] == "cancelled"

    def test_cancel_already_sent_raises_400(self):
        from app.services.whatsapp_service import cancel_outbox_message
        from fastapi import HTTPException

        sent_row = {
            "id": "00000000-0000-0000-0000-000000000041",
            "org_id": ORG_ID, "status": "sent",
        }
        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.eq.return_value = t
            t.maybe_single.return_value = t
            def _exec():
                r = MagicMock()
                r.data = sent_row
                return r
            t.execute.side_effect = _exec
            return t
        db.table.side_effect = _tbl

        with patch("app.services.whatsapp_service._normalise_data", side_effect=lambda x: x):
            with pytest.raises(HTTPException) as exc_info:
                cancel_outbox_message(
                    db=db, org_id=ORG_ID,
                    outbox_id="00000000-0000-0000-0000-000000000041",
                    user_id=USER_ID,
                )
        assert exc_info.value.status_code == 400


# ===========================================================================
# TestListOutbox
# ===========================================================================

class TestListOutbox:

    def test_list_returns_paginated_result(self):
        from app.services.whatsapp_service import list_outbox

        db = MagicMock()
        chain = MagicMock()
        db.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        res = MagicMock()
        res.data = [{"id": "o1", "status": "pending"}]
        res.count = 1
        chain.execute.return_value = res

        result = list_outbox(db=db, org_id=ORG_ID)
        assert "items" in result
        assert "total" in result
        assert result["total"] == 1

    def test_list_filters_by_status(self):
        from app.services.whatsapp_service import list_outbox

        db = MagicMock()
        chain = MagicMock()
        db.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        res = MagicMock()
        res.data = []
        res.count = 0
        chain.execute.return_value = res

        list_outbox(db=db, org_id=ORG_ID, status="pending")
        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any("pending" in c for c in eq_calls)


# ===========================================================================
# TestReviewWindowSender
# run_review_window_sender uses _dispatch_outbox_row imported at worker
# module level → patch at app.workers.qualification_worker._dispatch_outbox_row
# ===========================================================================

class TestReviewWindowSender:

    def _make_db(self, rows):
        db = MagicMock()
        chain = MagicMock()
        db.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.lte.return_value = chain
        res = MagicMock()
        res.data = rows
        chain.execute.return_value = res
        return db

    def test_sends_scheduled_rows_past_send_after(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        rows = [{
            "id": "00000000-0000-0000-0000-000000000050",
            "org_id": ORG_ID, "lead_id": LEAD_ID,
            "status": "scheduled", "send_after": past,
        }]

        with patch("app.workers.qualification_worker._get_db",
                   return_value=self._make_db(rows)), \
             patch("app.workers.qualification_worker._dispatch_outbox_row",
                   return_value={"id": rows[0]["id"], "status": "sent"}) as mock_dispatch:
            from app.workers.qualification_worker import run_review_window_sender
            result = run_review_window_sender()

        assert result["sent"] == 1
        assert result["failed"] == 0
        mock_dispatch.assert_called_once()

    def test_no_rows_returns_zero_counts(self):
        with patch("app.workers.qualification_worker._get_db",
                   return_value=self._make_db([])):
            from app.workers.qualification_worker import run_review_window_sender
            result = run_review_window_sender()

        assert result["sent"] == 0
        assert result["failed"] == 0

    def test_dispatch_failure_increments_failed_not_sent(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        rows = [{
            "id": "00000000-0000-0000-0000-000000000051",
            "org_id": ORG_ID, "status": "scheduled", "send_after": past,
        }]

        with patch("app.workers.qualification_worker._get_db",
                   return_value=self._make_db(rows)), \
             patch("app.workers.qualification_worker._dispatch_outbox_row",
                   return_value={"id": rows[0]["id"], "status": "failed"}):
            from app.workers.qualification_worker import run_review_window_sender
            result = run_review_window_sender()

        assert result["sent"] == 0
        assert result["failed"] == 1


# ===========================================================================
# TestQualificationFallback
# run_qualification_fallback uses _call_meta_send imported at worker
# module level → patch at app.workers.qualification_worker._call_meta_send
# Notification is a direct DB insert — no service function to patch.
# ===========================================================================

class TestQualificationFallback:

    def _make_stuck_session(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        return {
            "id": SESS_ID,
            "lead_id": LEAD_ID,
            "org_id": ORG_ID,
            "stage": "awaiting_first_message",
            "ai_active": True,
            "fallback_sent_at": None,
            "created_at": cutoff,
        }

    def _make_db(self, orgs, sessions, lead):
        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.insert.return_value = t
            t.update.return_value = t
            t.eq.return_value = t
            t.is_.return_value = t
            t.lte.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                if name == "organisations":
                    r.data = orgs
                elif name == "lead_qualification_sessions":
                    r.data = sessions
                elif name == "leads":
                    r.data = lead
                else:
                    r.data = []
                return r
            t.execute.side_effect = _exec
            return t

        db.table.side_effect = _tbl
        return db

    def test_sends_whatsapp_template_when_phone_available(self):
        session = self._make_stuck_session()
        orgs = [{"id": ORG_ID, "whatsapp_phone_id": "ph-999",
                 "qualification_fallback_hours": 2}]
        lead = {"id": LEAD_ID, "full_name": "Test Lead",
                "whatsapp": "2348000000001", "phone": None, "assigned_to": USER_ID}

        db = self._make_db(orgs, [session], lead)

        with patch("app.workers.qualification_worker._get_db", return_value=db), \
             patch("app.workers.qualification_worker._call_meta_send",
                   return_value={"messages": [{"id": "meta-re"}]}) as mock_meta, \
             patch("app.workers.qualification_worker._normalise_data",
                   side_effect=lambda x: x):
            from app.workers.qualification_worker import run_qualification_fallback
            result = run_qualification_fallback()

        assert result["sent"] == 1
        assert result["notified"] == 0
        mock_meta.assert_called_once()

    def test_notifies_rep_when_no_whatsapp_number(self):
        session = self._make_stuck_session()
        orgs = [{"id": ORG_ID, "whatsapp_phone_id": "ph-999",
                 "qualification_fallback_hours": 2}]
        lead_no_wa = {"id": LEAD_ID, "full_name": "No WA Lead",
                      "whatsapp": None, "phone": None, "assigned_to": USER_ID}

        db = self._make_db(orgs, [session], lead_no_wa)

        with patch("app.workers.qualification_worker._get_db", return_value=db), \
             patch("app.workers.qualification_worker._normalise_data",
                   side_effect=lambda x: x):
            from app.workers.qualification_worker import run_qualification_fallback
            result = run_qualification_fallback()

        assert result["notified"] == 1
        assert result["sent"] == 0

    def test_stamps_fallback_sent_at_after_send(self):
        session = self._make_stuck_session()
        orgs = [{"id": ORG_ID, "whatsapp_phone_id": "ph-999",
                 "qualification_fallback_hours": 2}]
        lead = {"id": LEAD_ID, "full_name": "L",
                "whatsapp": "2348000000001", "phone": None, "assigned_to": USER_ID}

        stamp_calls = []
        db = MagicMock()

        def _tbl(name):
            t = MagicMock()
            t.select.return_value = t
            t.insert.return_value = t
            t.eq.return_value = t
            t.is_.return_value = t
            t.lte.return_value = t
            t.maybe_single.return_value = t

            def _exec():
                r = MagicMock()
                if name == "organisations":
                    r.data = orgs
                elif name == "lead_qualification_sessions":
                    r.data = [session]
                elif name == "leads":
                    r.data = lead
                else:
                    r.data = []
                return r
            t.execute.side_effect = _exec

            def _update(data):
                if isinstance(data, dict) and "fallback_sent_at" in data:
                    stamp_calls.append(data)
                upd = MagicMock()
                upd.eq.return_value = upd
                def _upd_exec():
                    r = MagicMock()
                    r.data = []
                    return r
                upd.execute.side_effect = _upd_exec
                return upd
            t.update.side_effect = _update
            return t

        db.table.side_effect = _tbl

        with patch("app.workers.qualification_worker._get_db", return_value=db), \
             patch("app.workers.qualification_worker._call_meta_send",
                   return_value={"messages": []}), \
             patch("app.workers.qualification_worker._normalise_data",
                   side_effect=lambda x: x):
            from app.workers.qualification_worker import run_qualification_fallback
            run_qualification_fallback()

        assert len(stamp_calls) >= 1
        assert "fallback_sent_at" in stamp_calls[0]

    def test_no_sessions_returns_zero_counts(self):
        orgs = [{"id": ORG_ID, "whatsapp_phone_id": "ph-999",
                 "qualification_fallback_hours": 2}]
        db = self._make_db(orgs, [], None)

        with patch("app.workers.qualification_worker._get_db", return_value=db):
            from app.workers.qualification_worker import run_qualification_fallback
            result = run_qualification_fallback()

        assert result["processed"] == 0
        assert result["sent"] == 0

    def test_one_failure_does_not_stop_other_sessions(self):
        session1 = self._make_stuck_session()
        session2 = {
            **self._make_stuck_session(),
            "id":      "00000000-0000-0000-0000-000000000005",
            "lead_id": "00000000-0000-0000-0000-000000000006",
        }
        orgs = [{"id": ORG_ID, "whatsapp_phone_id": "ph-999",
                 "qualification_fallback_hours": 2}]
        lead = {"id": LEAD_ID, "full_name": "L",
                "whatsapp": "234800000001", "phone": None, "assigned_to": USER_ID}

        db = self._make_db(orgs, [session1, session2], lead)

        with patch("app.workers.qualification_worker._get_db", return_value=db), \
             patch("app.workers.qualification_worker._call_meta_send",
                   side_effect=Exception("Meta down")), \
             patch("app.workers.qualification_worker._normalise_data",
                   side_effect=lambda x: x):
            from app.workers.qualification_worker import run_qualification_fallback
            result = run_qualification_fallback()

        assert result["processed"] == 2


# ===========================================================================
# TestOutboxAdminRoutes — Pydantic model validation
# ===========================================================================

class TestOutboxAdminRoutes:

    def test_patch_saves_sending_mode_and_window_minutes(self):
        from app.routers.admin import QualificationBotUpdate
        payload = QualificationBotUpdate(
            qualification_sending_mode="review_window",
            review_window_minutes=10,
        )
        assert payload.qualification_sending_mode == "review_window"
        assert payload.review_window_minutes == 10

    def test_rejects_invalid_sending_mode(self):
        from app.routers.admin import QualificationBotUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            QualificationBotUpdate(qualification_sending_mode="INVALID")

    def test_rejects_review_window_minutes_over_60(self):
        from app.routers.admin import QualificationBotUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            QualificationBotUpdate(review_window_minutes=999)

    def test_rejects_review_window_minutes_zero(self):
        from app.routers.admin import QualificationBotUpdate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            QualificationBotUpdate(review_window_minutes=0)

    def test_accepts_auto_send_mode(self):
        from app.routers.admin import QualificationBotUpdate
        payload = QualificationBotUpdate(qualification_sending_mode="auto_send")
        assert payload.qualification_sending_mode == "auto_send"

    def test_accepts_full_approval_mode(self):
        from app.routers.admin import QualificationBotUpdate
        payload = QualificationBotUpdate(qualification_sending_mode="full_approval")
        assert payload.qualification_sending_mode == "full_approval"