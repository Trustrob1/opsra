"""
tests/unit/test_message_dedup.py
----------------------------------
Unit tests for the message-ID deduplication gate in _handle_inbound_message.

Verifies:
  1. First delivery of a message_id → processed normally
  2. Second delivery of same message_id → skipped, no downstream calls
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call


def _make_db(dedup_data=None):
    """
    Build a mock DB where whatsapp_messages dedup query returns dedup_data.
    All other queries return safe defaults.
    """
    db = MagicMock()
    call_count = {"n": 0}

    def table_side(table_name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.is_.return_value = chain
        chain.neq.return_value = chain
        chain.gt.return_value = chain
        chain.insert.return_value = chain
        chain.update.return_value = chain
        chain.execute.return_value = MagicMock(data=[])

        if table_name == "whatsapp_messages":
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call is the dedup check
                chain.execute.return_value = MagicMock(data=dedup_data or [])
        return chain

    db.table.side_effect = table_side
    return db


class TestMessageDedup:

    def _make_message(self, msg_id="msg-abc-123"):
        return {
            "id": msg_id,
            "from": "2348031234567",
            "type": "text",
            "text": {"body": "Hello"},
        }

    def test_first_delivery_is_processed(self):
        """First delivery (dedup check returns empty) → processing continues."""
        from app.routers.webhooks import _handle_inbound_message

        db = _make_db(dedup_data=[])  # no existing record
        message = self._make_message("msg-001")

        with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(None, None, None, None)), \
             patch("app.routers.webhooks._lookup_org_by_phone_number_id", return_value=None), \
             patch("app.routers.webhooks.triage_service") as mock_triage:
            mock_triage.get_active_session.return_value = None

            _handle_inbound_message(db, message, "Test User", "phone-id-123")

        # Should have called table() — processing did not short-circuit
        assert db.table.called

    def test_duplicate_message_is_skipped(self):
        """Second delivery (dedup check returns existing row) → skipped immediately."""
        from app.routers.webhooks import _handle_inbound_message

        # Dedup check returns an existing row → duplicate
        db = _make_db(dedup_data=[{"id": "existing-row-uuid"}])
        message = self._make_message("msg-001")

        with patch("app.routers.webhooks._lookup_record_by_phone") as mock_lookup, \
             patch("app.routers.webhooks._lookup_org_by_phone_number_id") as mock_org_lookup:

            _handle_inbound_message(db, message, "Test User", "phone-id-123")

        # Downstream lookups must NOT have been called — function returned early
        mock_lookup.assert_not_called()
        mock_org_lookup.assert_not_called()

    def test_dedup_check_failure_is_fail_open(self):
        """If the dedup DB check itself raises, processing continues (fail-open)."""
        from app.routers.webhooks import _handle_inbound_message

        db = MagicMock()
        db.table.side_effect = Exception("db connection error")

        message = self._make_message("msg-002")

        # Should NOT raise even though dedup check fails
        with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(None, None, None, None)), \
             patch("app.routers.webhooks._lookup_org_by_phone_number_id", return_value=None), \
             patch("app.routers.webhooks.triage_service") as mock_triage:
            mock_triage.get_active_session.return_value = None

            # Must not raise
            try:
                _handle_inbound_message(db, message, "Test User", "phone-id-123")
            except Exception:
                assert False, "_handle_inbound_message raised when dedup check failed"
