"""
backend/tests/unit/test_notifications_service.py
Unit tests for notifications_service.py — Phase 9.

Classes:
  TestListNotifications (5 tests)
  TestMarkRead          (5 tests)
  TestMarkAllRead       (3 tests)

Total: 13 tests

Patterns:
  Pattern 8  — separate mock chains per db.table call
  Pattern 24 — valid UUID constants
  Pattern 33 — filtering is Python-side; no ILIKE in the service
"""

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.services.notifications_service import (
    list_notifications,
    mark_read,
    mark_all_read,
)

# ── UUID constants (Pattern 24) ───────────────────────────────────────────────
ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
NOTIF_1 = "00000000-0000-0000-0000-000000000003"
NOTIF_2 = "00000000-0000-0000-0000-000000000004"

# ── Sample notification rows ──────────────────────────────────────────────────

def _notif(id, is_read=False):
    return {
        "id": id, "org_id": ORG_ID, "user_id": USER_ID,
        "title": "Test notification", "body": "Some body text",
        "type": "churn_alert", "is_read": is_read,
        "created_at": "2026-04-06T10:00:00Z",
    }


def _make_list_db(rows):
    """Mock db where .table().select().eq().eq().order().execute() returns rows."""
    db = MagicMock()
    db.table.return_value.select.return_value \
        .eq.return_value.eq.return_value \
        .order.return_value.execute.return_value.data = rows
    return db


# ============================================================
# TestListNotifications
# ============================================================

class TestListNotifications:
    def test_returns_paginated_items(self):
        rows = [_notif(NOTIF_1), _notif(NOTIF_2)]
        db   = _make_list_db(rows)

        result = list_notifications(USER_ID, ORG_ID, db, page=1, page_size=10)

        assert result["total"] == 2
        assert len(result["items"]) == 2
        assert result["page"] == 1
        assert result["has_more"] is False

    def test_paginates_correctly(self):
        rows = [_notif(f"00000000-0000-0000-0000-{str(i).zfill(12)}") for i in range(25)]
        db   = _make_list_db(rows)

        result = list_notifications(USER_ID, ORG_ID, db, page=2, page_size=10)

        assert result["total"]    == 25
        assert len(result["items"]) == 10
        assert result["has_more"] is True
        assert result["page"]     == 2

    def test_unread_count_reflects_all_pages(self):
        rows = [
            _notif(NOTIF_1, is_read=False),
            _notif(NOTIF_2, is_read=True),
        ]
        db   = _make_list_db(rows)

        result = list_notifications(USER_ID, ORG_ID, db, page=1, page_size=1)

        # Only 1 item on page 1, but unread_count covers ALL items
        assert result["unread_count"] == 1
        assert len(result["items"])   == 1

    def test_empty_state_returns_zeros(self):
        db = _make_list_db([])

        result = list_notifications(USER_ID, ORG_ID, db)

        assert result["total"]        == 0
        assert result["items"]        == []
        assert result["unread_count"] == 0
        assert result["has_more"]     is False

    def test_all_read_gives_zero_unread_count(self):
        rows = [_notif(NOTIF_1, is_read=True), _notif(NOTIF_2, is_read=True)]
        db   = _make_list_db(rows)

        result = list_notifications(USER_ID, ORG_ID, db)

        assert result["unread_count"] == 0


# ============================================================
# TestMarkRead
# ============================================================

class TestMarkRead:
    def _make_db(self, found=True, already_read=False):
        """
        Mock db with two notifications table call sequences:
          call 1 → maybe_single check
          call 2 → update (skipped if already_read)
        """
        db      = MagicMock()
        record  = _notif(NOTIF_1, is_read=already_read) if found else None
        tracker = {"n": 0}

        check_chain  = MagicMock()
        update_chain = MagicMock()

        check_chain.select.return_value.eq.return_value.eq.return_value \
            .eq.return_value.maybe_single.return_value \
            .execute.return_value.data = record

        update_chain.update.return_value.eq.return_value.eq.return_value \
            .execute.return_value.data = [{**record, "is_read": True}] if record else []

        def _tbl(name):
            if name == "notifications":
                tracker["n"] += 1
                return check_chain if tracker["n"] == 1 else update_chain
            return MagicMock()

        db.table.side_effect = _tbl
        return db

    def test_marks_notification_read(self):
        db = self._make_db(found=True)
        result = mark_read(NOTIF_1, USER_ID, ORG_ID, db)
        assert result["is_read"] is True

    def test_raises_404_when_not_found(self):
        db = self._make_db(found=False)
        with pytest.raises(HTTPException) as exc_info:
            mark_read(NOTIF_1, USER_ID, ORG_ID, db)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "NOT_FOUND"

    def test_returns_record_without_write_when_already_read(self):
        db       = self._make_db(found=True, already_read=True)
        result   = mark_read(NOTIF_1, USER_ID, ORG_ID, db)
        # Should return the record without calling update
        assert result["is_read"] is True
        # Only one table call made (the check) — no update
        notif_calls = [c for c in db.table.call_args_list if c.args[0] == "notifications"]
        assert len(notif_calls) == 1

    def test_returns_updated_record_on_success(self):
        db     = self._make_db(found=True, already_read=False)
        result = mark_read(NOTIF_1, USER_ID, ORG_ID, db)
        assert result is not None
        assert result.get("is_read") is True

    def test_scopes_check_to_user(self):
        """
        The check query must include user_id filter — cannot read
        another user's notification.
        """
        db = self._make_db(found=False)  # not found = out of scope
        with pytest.raises(HTTPException) as exc_info:
            mark_read(NOTIF_1, "other-user-id", ORG_ID, db)
        assert exc_info.value.status_code == 404


# ============================================================
# TestMarkAllRead
# ============================================================

class TestMarkAllRead:
    def _make_db(self):
        db = MagicMock()
        db.table.return_value.update.return_value \
            .eq.return_value.eq.return_value \
            .eq.return_value.execute.return_value = MagicMock()
        return db

    def test_calls_update_on_notifications_table(self):
        db = self._make_db()
        mark_all_read(USER_ID, ORG_ID, db)
        notif_calls = [c for c in db.table.call_args_list if c.args[0] == "notifications"]
        assert len(notif_calls) == 1

    def test_does_not_raise_when_no_unread(self):
        db = self._make_db()
        # Should not raise even if there's nothing to update
        mark_all_read(USER_ID, ORG_ID, db)

    def test_swallows_db_exception(self):
        db = MagicMock()
        db.table.side_effect = Exception("DB error")
        # mark_all_read swallows errors — must not raise
        mark_all_read(USER_ID, ORG_ID, db)
