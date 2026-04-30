"""
tests/unit/test_aria_limits.py
-------------------------------
9E-G tests for G3 (Aria session limits) and G4 (template rejection broadcast cancellation).

G3 Coverage:
  1.  History over 20 messages → only last 20 sent to API
  2.  History exactly 20 → all 20 sent
  3.  History under 20 → all sent unchanged
  4.  Daily call limit not reached → build_chat_payload succeeds
  5.  Daily call limit reached → build_chat_payload raises ValueError
  6.  check_aria_call_limit: under limit → True, counter incremented
  7.  check_aria_call_limit: at limit → False
  8.  check_aria_call_limit: Redis unavailable → True (S14)
  9.  Aria key format: aria_calls:{user_id}:{date}
  10. purge_old_messages: deletes rows older than cutoff

G4 Coverage:
  11. Template rejected → active broadcasts cancelled
  12. Template rejected → owner notified
  13. Template approved → no broadcasts cancelled
  14. No active broadcasts for rejected template → no cancellation, no error
  15. _cancel_broadcasts: DB error → S14, no exception raised
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch, call
import pytest


ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000099"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    db = MagicMock()
    chain = MagicMock()
    for method in ("select", "eq", "in_", "update", "insert", "delete",
                   "order", "limit", "lt", "is_", "maybe_single"):
        getattr(chain, method).return_value = chain
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    return db, chain


def _make_redis_mock(current_value: int = 0):
    r = MagicMock()
    r.get.return_value = str(current_value)
    pipe = MagicMock()
    pipe.incr.return_value = pipe
    pipe.expire.return_value = pipe
    pipe.execute.return_value = [current_value + 1, True]
    r.pipeline.return_value = pipe
    return r


# ---------------------------------------------------------------------------
# G3 — History slicing
# ---------------------------------------------------------------------------

class TestAriaHistorySlicing:

    def _make_messages(self, n: int) -> list[dict]:
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(n)
        ]

    def test_history_over_20_sliced_to_last_20(self):
        """get_history is called with limit=20 — only 20 messages returned."""
        from app.services.assistant_service import get_history

        db, chain = _make_db()
        # Simulate DB returning 20 rows (already limited by the query)
        rows = [
            {"role": "user", "content": f"msg {i}", "created_at": f"2026-01-{i+1:02d}"}
            for i in range(20)
        ]
        chain.execute.return_value = MagicMock(data=list(reversed(rows)))

        result = get_history(db, ORG_ID, USER_ID, limit=20)

        # Verify limit was passed to the query
        chain.limit.assert_called_with(20)
        assert len(result) == 20

    def test_history_exactly_20_returned_unchanged(self):
        """Exactly 20 messages → all returned."""
        from app.services.assistant_service import get_history

        db, chain = _make_db()
        rows = [
            {"role": "user", "content": f"msg {i}", "created_at": f"2026-01-{i+1:02d}"}
            for i in range(20)
        ]
        chain.execute.return_value = MagicMock(data=rows)

        result = get_history(db, ORG_ID, USER_ID)

        assert len(result) == 20

    def test_history_under_20_returned_unchanged(self):
        """5 messages → all 5 returned."""
        from app.services.assistant_service import get_history

        db, chain = _make_db()
        rows = [
            {"role": "user", "content": f"msg {i}", "created_at": f"2026-01-{i+1:02d}"}
            for i in range(5)
        ]
        chain.execute.return_value = MagicMock(data=rows)

        result = get_history(db, ORG_ID, USER_ID)

        assert len(result) == 5

    def test_history_reversed_to_chronological_order(self):
        """get_history orders DESC from DB then reverses → oldest first."""
        from app.services.assistant_service import get_history

        db, chain = _make_db()
        # DB returns newest first (DESC)
        rows = [
            {"role": "user", "content": "newest", "created_at": "2026-01-03"},
            {"role": "assistant", "content": "middle", "created_at": "2026-01-02"},
            {"role": "user", "content": "oldest", "created_at": "2026-01-01"},
        ]
        chain.execute.return_value = MagicMock(data=rows)

        result = get_history(db, ORG_ID, USER_ID)

        # After reversal: oldest first
        assert result[0]["content"] == "oldest"
        assert result[-1]["content"] == "newest"


# ---------------------------------------------------------------------------
# G3 — Daily call limit
# ---------------------------------------------------------------------------

class TestAriaDailyCallLimit:

    def test_under_limit_build_chat_payload_succeeds(self):
        """Under 50 calls → build_chat_payload returns (system, messages)."""
        from app.services.assistant_service import build_chat_payload

        db, chain = _make_db()
        chain.execute.return_value = MagicMock(data=[])

        with patch("app.services.assistant_service.check_aria_call_limit",
                   return_value=True), \
             patch("app.services.assistant_service.get_role_context",
                   return_value={}), \
             patch("app.services.assistant_service.get_history",
                   return_value=[]):
            system, messages = build_chat_payload(db, ORG_ID, USER_ID, "owner", "hello")

        assert isinstance(system, str)
        assert isinstance(messages, list)
        assert messages[-1]["role"] == "user"

    def test_at_limit_build_chat_payload_raises(self):
        """At 50 calls → build_chat_payload raises ValueError with 'aria_daily_limit_reached'."""
        from app.services.assistant_service import build_chat_payload

        db, _ = _make_db()

        with patch("app.services.assistant_service.check_aria_call_limit",
                   return_value=False):
            with pytest.raises(ValueError, match="aria_daily_limit_reached"):
                build_chat_payload(db, ORG_ID, USER_ID, "owner", "hello")

    def test_check_aria_call_limit_under_limit_returns_true(self):
        """Under limit → True, counter incremented."""
        from app.services.assistant_service import check_aria_call_limit

        r = _make_redis_mock(current_value=10)

        with patch("app.services.assistant_service._get_redis", return_value=r):
            result = check_aria_call_limit(USER_ID)

        assert result is True
        r.pipeline.return_value.incr.assert_called_once()

    def test_check_aria_call_limit_at_limit_returns_false(self):
        """At 50 calls → False."""
        from app.services.assistant_service import check_aria_call_limit

        r = _make_redis_mock(current_value=50)

        with patch("app.services.assistant_service._get_redis", return_value=r):
            result = check_aria_call_limit(USER_ID)

        assert result is False

    def test_check_aria_call_limit_redis_unavailable_returns_true(self):
        """Redis unavailable → S14 → True (never block)."""
        from app.services.assistant_service import check_aria_call_limit

        with patch("app.services.assistant_service._get_redis", return_value=None):
            result = check_aria_call_limit(USER_ID)

        assert result is True

    def test_aria_key_format_is_correct(self):
        """Redis key must be aria_calls:{user_id}:{YYYY-MM-DD}."""
        from app.services.assistant_service import check_aria_call_limit

        r = _make_redis_mock(current_value=0)
        today = date.today().isoformat()
        expected_key = f"aria_calls:{USER_ID}:{today}"

        with patch("app.services.assistant_service._get_redis", return_value=r):
            check_aria_call_limit(USER_ID)

        r.get.assert_called_with(expected_key)


# ---------------------------------------------------------------------------
# G3 — purge_old_messages
# ---------------------------------------------------------------------------

class TestPurgeOldMessages:

    def test_purge_deletes_rows_before_cutoff(self):
        """purge_old_messages calls delete().lt('session_date', cutoff)."""
        from app.services.assistant_service import purge_old_messages

        db, chain = _make_db()
        chain.execute.return_value = MagicMock(data=[{"id": "1"}, {"id": "2"}])

        deleted = purge_old_messages(db, cutoff_date="2026-03-01")

        db.table.assert_called_with("assistant_messages")
        chain.lt.assert_called_with("session_date", "2026-03-01")
        assert deleted == 2

    def test_purge_uses_30_day_default_cutoff(self):
        """Without explicit cutoff, uses today minus 30 days."""
        from app.services.assistant_service import purge_old_messages
        from datetime import timedelta

        db, chain = _make_db()
        chain.execute.return_value = MagicMock(data=[])

        purge_old_messages(db)

        expected_cutoff = (date.today() - timedelta(days=30)).isoformat()
        chain.lt.assert_called_with("session_date", expected_cutoff)


# ---------------------------------------------------------------------------
# G4 — Template rejection broadcast cancellation
# ---------------------------------------------------------------------------

def _make_webhooks_db(
    template_rows=None,
    broadcast_rows=None,
    owner_users=None,
):
    """Build a db mock for webhook tests with per-table control."""
    table_mocks = {}

    def _make_chain(data=None):
        c = MagicMock()
        for m in ("select", "eq", "in_", "update", "insert",
                  "delete", "order", "limit", "is_", "execute"):
            getattr(c, m).return_value = c
        c.execute.return_value = MagicMock(data=data or [])
        return c

    def _table(name):
        if name not in table_mocks:
            table_mocks[name] = _make_chain()
        return table_mocks[name]

    db = MagicMock()
    db.table.side_effect = _table

    # Pre-create mocks
    _table("whatsapp_templates")
    _table("broadcasts")
    _table("notifications")
    _table("users")

    if template_rows is not None:
        table_mocks["whatsapp_templates"].execute.return_value = MagicMock(
            data=template_rows
        )
    if broadcast_rows is not None:
        table_mocks["broadcasts"].execute.return_value = MagicMock(
            data=broadcast_rows
        )
    if owner_users is not None:
        table_mocks["users"].execute.return_value = MagicMock(
            data=owner_users
        )

    return db, table_mocks


class TestTemplateBroadcastCancellation:

    def test_rejected_template_cancels_active_broadcasts(self):
        """
        When a template is rejected, broadcasts with status 'scheduled' or
        'sending' using that template are set to 'cancelled'.
        """
        from app.routers.webhooks import _cancel_broadcasts_for_rejected_template

        template_rows = [{"id": "tmpl-001", "org_id": ORG_ID, "name": "first_touch"}]
        broadcast_rows = [
            {"id": "bc-001", "name": "March Campaign"},
            {"id": "bc-002", "name": "April Launch"},
        ]
        db, mocks = _make_webhooks_db(
            template_rows=template_rows,
            broadcast_rows=broadcast_rows,
            owner_users=[{"id": USER_ID, "roles": {"template": "owner"}}],
        )

        _cancel_broadcasts_for_rejected_template(db, "meta-123", "first_touch")

        # Verify update was called on broadcasts table
        update_calls = mocks["broadcasts"].update.call_args_list
        assert any(
            call[0][0].get("status") == "cancelled"
            for call in update_calls
            if call[0]
        )

    def test_rejected_template_notifies_owner(self):
        """Owner receives an in-app notification when broadcasts are cancelled."""
        from app.routers.webhooks import _cancel_broadcasts_for_rejected_template

        template_rows = [{"id": "tmpl-001", "org_id": ORG_ID, "name": "first_touch"}]
        broadcast_rows = [{"id": "bc-001", "name": "March Campaign"}]
        owner_users = [{"id": USER_ID, "roles": {"template": "owner"}}]

        db, mocks = _make_webhooks_db(
            template_rows=template_rows,
            broadcast_rows=broadcast_rows,
            owner_users=owner_users,
        )

        _cancel_broadcasts_for_rejected_template(db, "meta-123", "first_touch")

        mocks["notifications"].insert.assert_called()
        insert_data = mocks["notifications"].insert.call_args[0][0]
        assert insert_data["type"] == "broadcast_cancelled"
        assert insert_data["user_id"] == USER_ID
        assert insert_data["org_id"] == ORG_ID

    def test_approved_template_does_not_cancel_broadcasts(self):
        """
        The _handle_template_status_update function only calls the cancel
        helper when new_status == 'rejected'. Verify approved status skips it.
        """
        from app.routers.webhooks import _handle_template_status_update

        db, mocks = _make_webhooks_db(
            template_rows=[{"id": "tmpl-001", "org_id": ORG_ID, "name": "first_touch"}],
        )
        mocks["whatsapp_templates"].execute.return_value = MagicMock(
            data=[{"id": "tmpl-001", "org_id": ORG_ID, "name": "first_touch"}]
        )

        value = {
            "message_template_id": "meta-123",
            "message_template_name": "first_touch",
            "event": "APPROVED",
        }

        with patch("app.routers.webhooks._cancel_broadcasts_for_rejected_template") as mock_cancel:
            _handle_template_status_update(db, value)

        mock_cancel.assert_not_called()

    def test_no_active_broadcasts_no_error(self):
        """Rejected template with no active broadcasts → no crash, no notification."""
        from app.routers.webhooks import _cancel_broadcasts_for_rejected_template

        template_rows = [{"id": "tmpl-001", "org_id": ORG_ID, "name": "first_touch"}]
        db, mocks = _make_webhooks_db(
            template_rows=template_rows,
            broadcast_rows=[],  # no active broadcasts
        )

        # Must not raise
        _cancel_broadcasts_for_rejected_template(db, "meta-123", "first_touch")

        mocks["notifications"].insert.assert_not_called()

    def test_db_error_in_cancel_does_not_raise(self):
        """S14: any DB exception in _cancel_broadcasts_for_rejected_template is swallowed."""
        from app.routers.webhooks import _cancel_broadcasts_for_rejected_template

        db = MagicMock()
        db.table.side_effect = Exception("DB unavailable")

        # Must not raise
        _cancel_broadcasts_for_rejected_template(db, "meta-123", "first_touch")
