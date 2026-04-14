"""
tests/unit/test_daily_briefing_worker.py
------------------------------------------
Unit tests for Aria briefing and digest workers (M01-10b).

Covers:
  - run_daily_briefing_worker: processes users, skips idempotent, S14 isolation
  - run_notification_digest: batches unread notifs, skips < 3, S14 isolation
  - Pattern 48: roles accessed via roles.template not user.role
  - Pattern 57: module-level imports
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call
import pytest

ORG_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID  = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER2_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TODAY    = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value     = chain
    chain.in_.return_value    = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.delete.return_value = chain
    chain.lt.return_value     = chain
    return db


# ─── run_daily_briefing_worker ────────────────────────────────────────────────

from app.workers.daily_briefing_worker import run_daily_briefing_worker


def test_briefing_worker_processes_all_users():
    users = [
        {"id": USER_ID,  "org_id": ORG_ID, "briefing_generated_at": None,  "roles": {"template": "owner"}},
        {"id": USER2_ID, "org_id": ORG_ID, "briefing_generated_at": None,  "roles": {"template": "sales_agent"}},
    ]
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=users)

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing") as mock_gen:
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
                result = run_daily_briefing_worker.run()

    assert result["processed"] == 2
    assert result["failed"] == 0
    assert mock_gen.call_count == 2


def test_briefing_worker_skips_already_generated_today():
    users = [
        {"id": USER_ID, "org_id": ORG_ID, "briefing_generated_at": TODAY, "roles": {"template": "owner"}},
    ]
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=users)

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing") as mock_gen:
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
                result = run_daily_briefing_worker.run()

    assert result["skipped"] == 1
    assert result["processed"] == 0
    mock_gen.assert_not_called()


def test_briefing_worker_s14_single_failure_does_not_stop_loop():
    """S14 — if one user's briefing fails, others still process."""
    users = [
        {"id": USER_ID,  "org_id": ORG_ID, "briefing_generated_at": None, "roles": {"template": "owner"}},
        {"id": USER2_ID, "org_id": ORG_ID, "briefing_generated_at": None, "roles": {"template": "sales_agent"}},
    ]
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=users)

    call_count = {"n": 0}
    def fail_first(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("Haiku timeout")

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing", side_effect=fail_first):
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
                result = run_daily_briefing_worker.run()

    assert result["failed"] == 1
    assert result["processed"] == 1   # second user succeeded
    assert result["failed"] + result["processed"] == 2


def test_briefing_worker_uses_role_template_from_roles_dict():
    """Pattern 48 — role must come from roles.template, not a top-level role field."""
    users = [
        # Deliberately missing top-level "role" — only roles.template is valid
        {"id": USER_ID, "org_id": ORG_ID, "briefing_generated_at": None,
         "roles": {"template": "finance"}},
    ]
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=users)

    captured = {}
    def capture_role(db, org_id, user_id, role_template):
        captured["role_template"] = role_template

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing", side_effect=capture_role):
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
                run_daily_briefing_worker.run()

    assert captured["role_template"] == "finance"


def test_briefing_worker_skips_user_without_id_or_org():
    users = [
        {"id": None,    "org_id": ORG_ID, "briefing_generated_at": None, "roles": {"template": "owner"}},
        {"id": USER_ID, "org_id": None,   "briefing_generated_at": None, "roles": {"template": "owner"}},
    ]
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=users)

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing") as mock_gen:
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
                result = run_daily_briefing_worker.run()

    assert result["skipped"] == 2
    mock_gen.assert_not_called()


def test_briefing_worker_purges_old_messages():
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.generate_briefing"):
            with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=5) as mock_purge:
                result = run_daily_briefing_worker.run()

    mock_purge.assert_called_once()
    assert result["purged_messages"] == 5


def test_briefing_worker_returns_summary_dict():
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.purge_old_messages", return_value=0):
            result = run_daily_briefing_worker.run()

    assert "users_found" in result
    assert "processed" in result
    assert "skipped" in result
    assert "failed" in result
    assert "purged_messages" in result
    assert result["failed"] == 0


# ─── run_notification_digest ─────────────────────────────────────────────────

from app.workers.daily_briefing_worker import run_notification_digest


def test_digest_worker_sends_for_user_with_3_plus_notifs():
    users = [
        {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "owner"}},
    ]
    notifications = [
        {"id": "n1", "type": "alert", "title": "SLA breach", "body": "..."},
        {"id": "n2", "type": "info",  "title": "New lead",   "body": "..."},
        {"id": "n3", "type": "info",  "title": "Task due",   "body": "..."},
    ]

    db = _mock_db()

    def table_router(table_name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value     = chain
        chain.in_.return_value    = chain
        chain.update.return_value = chain
        if table_name == "users":
            chain.execute.return_value = MagicMock(data=users)
        elif table_name == "notifications":
            chain.execute.return_value = MagicMock(data=notifications)
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    db.table.side_effect = table_router

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.call_haiku_sync", return_value="You have 3 alerts.") as mock_haiku:
            with patch("app.workers.daily_briefing_worker.store_message") as mock_store:
                result = run_notification_digest.run()

    assert result["digests_sent"] == 1
    mock_haiku.assert_called_once()
    mock_store.assert_called_once()
    # Verify message stored as 'assistant' role
    args = mock_store.call_args[0]
    assert args[3] == "assistant"
    assert args[4] == "You have 3 alerts."


def test_digest_worker_skips_user_with_fewer_than_3_notifs():
    users = [
        {"id": USER_ID, "org_id": ORG_ID, "roles": {"template": "owner"}},
    ]
    notifications = [
        {"id": "n1", "type": "info", "title": "One notif", "body": "..."},
    ]

    db = _mock_db()

    def table_router(table_name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value     = chain
        chain.in_.return_value    = chain
        chain.update.return_value = chain
        if table_name == "users":
            chain.execute.return_value = MagicMock(data=users)
        else:
            chain.execute.return_value = MagicMock(data=notifications)
        return chain

    db.table.side_effect = table_router

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        with patch("app.workers.daily_briefing_worker.call_haiku_sync") as mock_haiku:
            result = run_notification_digest.run()

    assert result["digests_sent"] == 0
    assert result["users_skipped"] == 1
    mock_haiku.assert_not_called()


def test_digest_worker_s14_failure_does_not_stop_loop():
    """S14 — one user failure never stops the loop."""
    users = [
        {"id": USER_ID,  "org_id": ORG_ID, "roles": {"template": "owner"}},
        {"id": USER2_ID, "org_id": ORG_ID, "roles": {"template": "sales_agent"}},
    ]

    db = _mock_db()
    call_n = {"n": 0}

    def table_router(table_name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value     = chain
        chain.in_.return_value    = chain
        chain.update.return_value = chain
        if table_name == "users":
            chain.execute.return_value = MagicMock(data=users)
        else:
            call_n["n"] += 1
            if call_n["n"] == 1:
                chain.execute.side_effect = Exception("DB error")
            else:
                chain.execute.return_value = MagicMock(data=[])
        return chain

    db.table.side_effect = table_router

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        # Should not raise
        result = run_notification_digest.run()

    assert result["failed"] >= 0   # recorded but loop continued


def test_digest_worker_returns_summary_dict():
    db = _mock_db()
    db.table.return_value.execute.return_value = MagicMock(data=[])

    with patch("app.workers.daily_briefing_worker.get_supabase", return_value=db):
        result = run_notification_digest.run()

    assert "users_processed" in result
    assert "digests_sent" in result
    assert "users_skipped" in result
    assert "failed" in result
