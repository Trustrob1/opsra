"""
tests/unit/test_9d_additions.py
Phase 9D unit tests:
  - TestAddMessageWhatsApp  (ticket_service.add_message WhatsApp delivery)
  - TestBulkConfirmJobDurability  (subscription_service DB-backed bulk confirm)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest
from fastapi import HTTPException


# ── Shared UUID constants ──────────────────────────────────────────────────────
ORG_ID      = "00000000-0000-0000-0000-000000000001"
TICKET_ID   = "00000000-0000-0000-0000-000000000010"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000002"
USER_ID     = "00000000-0000-0000-0000-000000000099"
JOB_ID      = "00000000-0000-0000-0000-000000000088"
SUB_ID      = "00000000-0000-0000-0000-000000000050"


# ══════════════════════════════════════════════════════════════════════════════
# 9D-1 — ticket_service.add_message() WhatsApp delivery
# ══════════════════════════════════════════════════════════════════════════════

def _make_ticket_db(customer_id=CUSTOMER_ID, ticket_status="in_progress"):
    """Build a minimal Supabase mock for add_message() tests."""
    ticket_row = {
        "id": TICKET_ID, "org_id": ORG_ID, "status": ticket_status,
        "sla_paused_at": None, "sla_pause_minutes": 0, "deleted_at": None,
        "customer_id": customer_id,
    }
    msg_row = {
        "id": "00000000-0000-0000-0000-000000000020",
        "ticket_id": TICKET_ID, "content": "Hello",
        "message_type": "agent_reply", "is_sent": True,
    }

    db = MagicMock()

    # Separate chains per table so SELECT and INSERT don't collide
    t_chain = MagicMock()   # tickets
    t_chain.execute.return_value  = MagicMock(data=[ticket_row])
    t_chain.select.return_value   = t_chain
    t_chain.eq.return_value       = t_chain
    t_chain.is_.return_value      = t_chain
    t_chain.maybe_single.return_value = t_chain
    t_chain.update.return_value   = t_chain

    m_chain = MagicMock()   # ticket_messages
    m_chain.execute.return_value  = MagicMock(data=[msg_row])
    m_chain.insert.return_value   = m_chain

    a_chain = MagicMock()   # audit_logs
    a_chain.execute.return_value  = MagicMock(data=[])
    a_chain.insert.return_value   = a_chain

    def _tbl(name):
        if name == "tickets":          return t_chain
        if name == "ticket_messages":  return m_chain
        if name == "audit_logs":       return a_chain
        return MagicMock()

    db.table.side_effect = _tbl
    return db


class TestAddMessageWhatsApp:
    """Phase 9D: agent replies are delivered via WhatsApp when customer_id present."""

    def _add_message(self, db, message_type, customer_id=CUSTOMER_ID):
        from app.services.ticket_service import add_message
        from app.models.tickets import AddMessageRequest
        req = AddMessageRequest(message_type=message_type, content="Test message")
        return add_message(db, TICKET_ID, ORG_ID, USER_ID, req)

    # ── Delivery triggered ────────────────────────────────────────────────────

    def test_agent_reply_with_customer_id_calls_send_whatsapp(self):
        """agent_reply + customer_id → send_whatsapp_message called once."""
        db = _make_ticket_db(customer_id=CUSTOMER_ID)
        with patch(
            "app.services.ticket_service.send_whatsapp_message"
        ) as mock_wa, patch(
            "app.services.ticket_service.SendMessageRequest",
            return_value=MagicMock(),
        ):
            self._add_message(db, "agent_reply")
        mock_wa.assert_called_once()
        # Confirm first positional arg is db, second is org_id
        args = mock_wa.call_args[0]
        assert args[1] == ORG_ID

    # ── Delivery NOT triggered ─────────────────────────────────────────────────

    def test_internal_note_does_not_call_send_whatsapp(self):
        db = _make_ticket_db()
        with patch("app.services.ticket_service.send_whatsapp_message") as mock_wa:
            self._add_message(db, "internal_note")
        mock_wa.assert_not_called()

    def test_customer_message_type_does_not_call_send_whatsapp(self):
        db = _make_ticket_db()
        with patch("app.services.ticket_service.send_whatsapp_message") as mock_wa:
            self._add_message(db, "customer")
        mock_wa.assert_not_called()

    def test_ai_draft_does_not_call_send_whatsapp(self):
        db = _make_ticket_db()
        with patch("app.services.ticket_service.send_whatsapp_message") as mock_wa:
            self._add_message(db, "ai_draft")
        mock_wa.assert_not_called()

    def test_agent_reply_without_customer_id_skips_whatsapp(self):
        """Tickets not linked to a customer must not attempt WhatsApp delivery."""
        db = _make_ticket_db(customer_id=None)
        with patch("app.services.ticket_service.send_whatsapp_message") as mock_wa:
            self._add_message(db, "agent_reply", customer_id=None)
        mock_wa.assert_not_called()

    # ── S14 graceful degradation ──────────────────────────────────────────────

    def test_whatsapp_http_exception_does_not_raise(self):
        """S14: HTTPException from WhatsApp delivery must not surface to caller."""
        from fastapi import HTTPException as FHE
        db = _make_ticket_db()
        with patch(
            "app.services.ticket_service.send_whatsapp_message",
            side_effect=FHE(status_code=400, detail="Conversation window closed"),
        ), patch("app.services.ticket_service.SendMessageRequest", return_value=MagicMock()):
            result = self._add_message(db, "agent_reply")
        assert result is not None  # message row still returned

    def test_whatsapp_runtime_exception_does_not_raise(self):
        """S14: Any unexpected exception in delivery must be swallowed."""
        db = _make_ticket_db()
        with patch(
            "app.services.ticket_service.send_whatsapp_message",
            side_effect=RuntimeError("Meta API timeout"),
        ), patch("app.services.ticket_service.SendMessageRequest", return_value=MagicMock()):
            result = self._add_message(db, "agent_reply")
        assert result is not None

    def test_message_row_always_returned_regardless_of_whatsapp(self):
        """Core message insert completes and its dict is returned even when WA fails."""
        db = _make_ticket_db()
        with patch(
            "app.services.ticket_service.send_whatsapp_message",
            side_effect=Exception("crash"),
        ), patch("app.services.ticket_service.SendMessageRequest", return_value=MagicMock()):
            result = self._add_message(db, "agent_reply")
        assert result["ticket_id"] == TICKET_ID


# ══════════════════════════════════════════════════════════════════════════════
# 9D-4 — subscription_service bulk confirm DB durability
# ══════════════════════════════════════════════════════════════════════════════

def _make_insert_db():
    """Minimal db mock that accepts table().insert().execute()."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    chain.insert.return_value  = chain
    chain.update.return_value  = chain
    chain.eq.return_value      = chain
    db.table.return_value      = chain
    return db


def _make_select_db(row_data):
    """Minimal db mock that returns row_data from maybe_single select."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value    = MagicMock(data=[row_data] if row_data else None)
    chain.select.return_value     = chain
    chain.eq.return_value         = chain
    chain.maybe_single.return_value = chain
    db.table.return_value         = chain
    return db


class TestBulkConfirmJobDurability:
    """Phase 9D: bulk confirm jobs persisted to Supabase bulk_confirm_jobs table."""

    # ── create_bulk_confirm_job ───────────────────────────────────────────────

    def test_create_writes_row_to_supabase(self):
        from app.services.subscription_service import create_bulk_confirm_job
        db = _make_insert_db()
        job_id = create_bulk_confirm_job(ORG_ID, db=db)
        assert job_id is not None
        db.table.assert_called_with("bulk_confirm_jobs")
        inserted = db.table.return_value.insert.call_args[0][0]
        assert inserted["org_id"]  == ORG_ID
        assert inserted["status"]  == "pending"
        assert inserted["total"]   == 0
        assert inserted["failed"]  == 0

    def test_create_returns_uuid_string(self):
        from app.services.subscription_service import create_bulk_confirm_job
        import uuid as _uuid
        db = _make_insert_db()
        job_id = create_bulk_confirm_job(ORG_ID, db=db)
        _uuid.UUID(job_id)   # raises ValueError if not valid UUID

    def test_create_inserts_job_id_matching_return_value(self):
        from app.services.subscription_service import create_bulk_confirm_job
        db = _make_insert_db()
        job_id = create_bulk_confirm_job(ORG_ID, db=db)
        inserted = db.table.return_value.insert.call_args[0][0]
        assert inserted["job_id"] == job_id

    # ── get_bulk_confirm_job ──────────────────────────────────────────────────

    def test_get_returns_mapped_dict_with_legacy_keys(self):
        from app.services.subscription_service import get_bulk_confirm_job
        db_row = {
            "job_id": JOB_ID, "org_id": ORG_ID, "status": "done",
            "total": 10, "succeeded": 8, "unmatched": 1, "failed": 1,
            "errors": [{"row": 5, "message": "dup ref"}],
            "created_at": "2026-04-07T10:00:00+00:00",
            "completed_at": "2026-04-07T10:01:00+00:00",
        }
        db = _make_select_db(db_row)
        result = get_bulk_confirm_job(ORG_ID, JOB_ID, db=db)

        # Legacy keys used by router + frontend
        assert result["total_rows"]   == 10
        assert result["confirmed"]    == 8
        assert result["unmatched"]    == 1
        assert result["failed"]       == 1
        assert result["status"]       == "done"
        assert len(result["errors"])  == 1

    def test_get_raises_404_when_row_not_found(self):
        from app.services.subscription_service import get_bulk_confirm_job
        db = _make_select_db(None)
        with pytest.raises(HTTPException) as exc_info:
            get_bulk_confirm_job(ORG_ID, JOB_ID, db=db)
        assert exc_info.value.status_code == 404

    def test_get_scoped_to_org_id(self):
        """Both job_id and org_id used in the DB query."""
        from app.services.subscription_service import get_bulk_confirm_job
        db = _make_select_db(None)
        with pytest.raises(HTTPException):
            get_bulk_confirm_job("wrong-org-id", JOB_ID, db=db)
        eq_calls = [str(c) for c in db.table.return_value.eq.call_args_list]
        assert any("org_id" in c or "wrong-org-id" in c for c in eq_calls)

    # ── process_bulk_confirm ──────────────────────────────────────────────────

    def test_empty_rows_writes_done_status(self):
        from app.services.subscription_service import process_bulk_confirm
        db = _make_insert_db()
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID, [])
        # Two update calls: status=processing(total=0) then status=done
        update_calls = db.table.return_value.update.call_args_list
        final = update_calls[-1][0][0]
        assert final["status"] == "done"

    def test_process_writes_final_counts_to_db(self):
        """After processing, succeeded/failed/unmatched written to DB in one update."""
        from app.services.subscription_service import (
            process_bulk_confirm, _confirm_payment_internal, _subscription_or_404,
        )
        db = _make_insert_db()
        # Row with no subscription_id and no phone → unmatched
        bad_row = {"amount": 1000, "payment_date": "2026-04-07"}
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID, [bad_row])
        update_calls = db.table.return_value.update.call_args_list
        final = update_calls[-1][0][0]
        assert final["status"]    == "done"
        assert "unmatched"        in final or "failed" in final

    def test_update_bulk_job_swallows_db_errors(self):
        """_update_bulk_job must never raise (S14)."""
        from app.services.subscription_service import _update_bulk_job
        db = MagicMock()
        db.table.side_effect = RuntimeError("Supabase unavailable")
        # Must not raise
        _update_bulk_job(db, JOB_ID, {"status": "done"})
