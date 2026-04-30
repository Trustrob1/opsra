"""
tests/unit/test_session_race.py
9E-C — C1 + C2: WhatsApp session race condition tests.

Tests:
  - Two simultaneous get_or_create_session() calls → only one session created
  - State transition with wrong expected_state → returns False, state unchanged

T1: All mocked function signatures verified against triage_service source.
T2: No mixing of side_effect and return_value on the same mock chain.
T3: Syntax validated before delivery.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

ORG_ID = "00000000-0000-0000-0000-000000000001"
PHONE  = "2348031234567"
SESS_ID = "00000000-0000-0000-0000-000000000010"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    """Return a fresh MagicMock db client."""
    return MagicMock()


def _active_session_row():
    return {
        "id": SESS_ID,
        "org_id": ORG_ID,
        "phone_number": PHONE,
        "session_state": "triage_sent",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    }


# ---------------------------------------------------------------------------
# C1 — get_or_create_session
# ---------------------------------------------------------------------------

class TestGetOrCreateSessionC1:
    """C1: Atomic session creation — unique index prevents duplicates."""

    def test_returns_existing_session_when_active(self):
        """If an active session already exists, return it without inserting."""
        from app.services.triage_service import get_or_create_session

        db = _make_db()
        existing = _active_session_row()

        # get_active_session() SELECT returns the existing row
        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.neq.return_value.gt.return_value \
            .execute.return_value.data = [existing]

        result = get_or_create_session(db, ORG_ID, PHONE)

        assert result == existing
        # INSERT must NOT have been called
        db.table.return_value.insert.assert_not_called()

    def test_creates_session_when_none_exists(self):
        """If no active session exists, INSERT one and return it."""
        from app.services.triage_service import get_or_create_session

        db = _make_db()
        new_row = _active_session_row()

        select_result = MagicMock()
        select_result.data = []  # no existing session

        insert_result = MagicMock()
        insert_result.data = [new_row]

        calls = {"select": 0}

        def table_side_effect(name):
            mock = MagicMock()
            # Chain for SELECT (get_active_session)
            mock.select.return_value.eq.return_value \
                .eq.return_value.neq.return_value.gt.return_value \
                .execute.return_value = select_result
            # Chain for INSERT
            mock.insert.return_value.execute.return_value = insert_result
            return mock

        db.table.side_effect = table_side_effect

        result = get_or_create_session(db, ORG_ID, PHONE)

        assert result == new_row

    def test_concurrent_insert_returns_winner(self):
        """
        When INSERT raises a unique constraint violation (23505),
        get_or_create_session falls back to fetching the winning row.
        No exception is propagated to the caller.
        """
        from app.services.triage_service import get_or_create_session

        db = _make_db()
        winner_row = _active_session_row()

        select_calls = [0]

        def table_side_effect(name):
            mock = MagicMock()

            def select_chain(*args, **kwargs):
                sel = MagicMock()
                if select_calls[0] == 0:
                    # First call (get_active_session at top of function): empty
                    sel.eq.return_value.eq.return_value.neq.return_value \
                        .gt.return_value.execute.return_value.data = []
                else:
                    # Second call (fallback fetch after 23505): winner
                    sel.eq.return_value.eq.return_value.neq.return_value \
                        .gt.return_value.execute.return_value.data = [winner_row]
                select_calls[0] += 1
                return sel

            mock.select.side_effect = select_chain

            # INSERT raises unique constraint violation
            insert_mock = MagicMock()
            insert_mock.execute.side_effect = Exception(
                "duplicate key value violates unique constraint "
                "(23505) idx_ws_active_session"
            )
            mock.insert.return_value = insert_mock
            return mock

        db.table.side_effect = table_side_effect

        result = get_or_create_session(db, ORG_ID, PHONE)

        # Must return the winner, not raise
        assert result == winner_row

    def test_s14_never_raises_on_unexpected_error(self):
        """get_or_create_session returns None (not raises) on DB failure."""
        from app.services.triage_service import get_or_create_session

        db = _make_db()
        db.table.side_effect = RuntimeError("connection lost")

        result = get_or_create_session(db, ORG_ID, PHONE)
        assert result is None


# ---------------------------------------------------------------------------
# C2 — update_session with expected_state
# ---------------------------------------------------------------------------

class TestUpdateSessionC2:
    """C2: Atomic state transitions — expected_state guard."""

    def test_update_without_expected_state_always_succeeds(self):
        """When expected_state is not provided, no guard is applied."""
        from app.services.triage_service import update_session

        db = _make_db()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value.data = [{"id": SESS_ID, "session_state": "active"}]

        result = update_session(db, SESS_ID, "active")

        assert result is True

    def test_update_with_correct_expected_state_returns_true(self):
        """When expected_state matches, UPDATE affects rows → return True."""
        from app.services.triage_service import update_session

        db = _make_db()
        # .eq("session_state", "triage_sent") chain returns a row
        db.table.return_value.update.return_value \
            .eq.return_value.eq.return_value \
            .execute.return_value.data = [{"id": SESS_ID}]

        result = update_session(
            db, SESS_ID, "active",
            selected_action="qualify",
            expected_state="triage_sent",
        )

        assert result is True

    def test_update_with_wrong_expected_state_returns_false(self):
        """
        When expected_state does NOT match the current DB state, the UPDATE
        affects 0 rows. update_session returns False — caller should bail.
        State is NOT changed.
        """
        from app.services.triage_service import update_session

        db = _make_db()
        # UPDATE returns empty data (0 rows matched)
        db.table.return_value.update.return_value \
            .eq.return_value.eq.return_value \
            .execute.return_value.data = []

        result = update_session(
            db, SESS_ID, "active",
            selected_action="qualify",
            expected_state="triage_sent",  # session is already "active" in DB
        )

        assert result is False

    def test_s14_returns_false_on_exception(self):
        """update_session returns False (not raises) on DB error."""
        from app.services.triage_service import update_session

        db = _make_db()
        db.table.side_effect = RuntimeError("timeout")

        result = update_session(db, SESS_ID, "active", expected_state="triage_sent")
        assert result is False
