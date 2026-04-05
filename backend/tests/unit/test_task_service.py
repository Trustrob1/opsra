"""
tests/unit/test_task_service.py
Unit tests for task_service — Phase 7A.

Pattern 24: all test UUIDs are valid UUID format.
Pattern 37: org fixtures use roles.template shape (not flat "role" key).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.services.task_service import (
    _is_manager,
    _sort_key,
    list_tasks,
    get_task,
    create_task,
    update_task,
    complete_task,
    snooze_task,
)
from app.models.tasks import TaskCreate, TaskUpdate, CompleteRequest, SnoozeRequest

# ── Test constants (Pattern 24) ───────────────────────────────────────────────

ORG_ID   = "00000000-0000-0000-0000-000000000010"
USER_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID2 = "00000000-0000-0000-0000-000000000002"
TASK_ID  = "00000000-0000-0000-0000-000000000020"

# Pattern 37: roles.template shape — no flat "role" key
ORG_OWNER = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "owner", "permissions": {}},
}
ORG_OPS_MANAGER = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "ops_manager", "permissions": {}},
}
ORG_ADMIN = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "sales_agent", "permissions": {"is_admin": True}},
}
ORG_AGENT = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "sales_agent", "permissions": {}},
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_task(**overrides) -> dict:
    base = {
        "id":               TASK_ID,
        "org_id":           ORG_ID,
        "title":            "Follow up with customer",
        "description":      None,
        "task_type":        "manual",
        "source_module":    None,
        "source_record_id": None,
        "assigned_to":      USER_ID,
        "created_by":       USER_ID,
        "status":           "open",
        "priority":         "medium",
        "due_at":           "2030-01-01T10:00:00+00:00",
        "completed_at":     None,
        "snoozed_until":    None,
        "completion_notes": None,
        "ai_confirmed_by":  None,
        "deleted_at":       None,
        "created_at":       "2026-04-04T08:00:00+00:00",
        "updated_at":       "2026-04-04T08:00:00+00:00",
    }
    base.update(overrides)
    return base


def _make_db(task: dict = None) -> MagicMock:
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[task or _make_task()])
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    db.table.return_value = chain
    return db


def _make_empty_db() -> MagicMock:
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    db.table.return_value = chain
    return db


# ── TestIsManager ─────────────────────────────────────────────────────────────


class TestIsManager:
    def test_owner_is_manager(self):
        assert _is_manager(ORG_OWNER) is True

    def test_ops_manager_is_manager(self):
        assert _is_manager(ORG_OPS_MANAGER) is True

    def test_is_admin_permission_is_manager(self):
        assert _is_manager(ORG_ADMIN) is True

    def test_agent_is_not_manager(self):
        assert _is_manager(ORG_AGENT) is False

    def test_missing_roles_is_not_manager(self):
        assert _is_manager({"id": USER_ID, "org_id": ORG_ID, "roles": None}) is False

    def test_flat_role_key_ignored(self):
        """Pattern 37: flat role key must have no effect."""
        org = {"id": USER_ID, "org_id": ORG_ID, "role": "owner", "roles": {"template": "sales_agent", "permissions": {}}}
        assert _is_manager(org) is False


# ── TestSortKey ───────────────────────────────────────────────────────────────


class TestSortKey:
    def test_overdue_sorts_first(self):
        overdue = _make_task(due_at="2020-01-01T00:00:00+00:00", status="open")
        future  = _make_task(due_at="2030-01-01T00:00:00+00:00", status="open")
        assert _sort_key(overdue) < _sort_key(future)

    def test_completed_sorts_last(self):
        completed = _make_task(status="completed")
        overdue   = _make_task(due_at="2020-01-01T00:00:00+00:00", status="open")
        assert _sort_key(overdue) < _sort_key(completed)

    def test_critical_before_low(self):
        critical = _make_task(priority="critical", due_at="2030-01-02T00:00:00+00:00")
        low      = _make_task(priority="low",      due_at="2030-01-01T00:00:00+00:00")
        # Both future — critical should be group 1, priority 0 vs group 1, priority 3
        assert _sort_key(critical) < _sort_key(low)


# ── TestListTasks ─────────────────────────────────────────────────────────────


class TestListTasks:
    def test_personal_view_returns_only_own_tasks(self):
        task_mine  = _make_task(assigned_to=USER_ID)
        task_other = _make_task(id="00000000-0000-0000-0000-000000000099",
                                assigned_to=USER_ID2)
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_mine, task_other])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db)
        assert result["total"] == 1
        assert result["items"][0]["assigned_to"] == USER_ID

    def test_team_view_returns_all_for_manager(self):
        task_mine  = _make_task(assigned_to=USER_ID)
        task_other = _make_task(id="00000000-0000-0000-0000-000000000099",
                                assigned_to=USER_ID2)
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_mine, task_other])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_OWNER, db, team_view=True)
        assert result["total"] == 2

    def test_team_view_denied_for_agent(self):
        """Agent requesting team_view should still only see own tasks."""
        task_mine  = _make_task(assigned_to=USER_ID)
        task_other = _make_task(id="00000000-0000-0000-0000-000000000099",
                                assigned_to=USER_ID2)
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_mine, task_other])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db, team_view=True)
        assert result["total"] == 1

    def test_completed_excluded_by_default(self):
        task_open      = _make_task(status="open")
        task_completed = _make_task(id="00000000-0000-0000-0000-000000000099",
                                    status="completed")
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_open, task_completed])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db)
        assert result["total"] == 1
        assert result["items"][0]["status"] == "open"

    def test_deleted_tasks_excluded(self):
        task_live    = _make_task()
        task_deleted = _make_task(id="00000000-0000-0000-0000-000000000099",
                                  deleted_at="2026-01-01T00:00:00+00:00")
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_live, task_deleted])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db)
        assert result["total"] == 1

    def test_priority_filter(self):
        task_high   = _make_task(priority="high")
        task_medium = _make_task(id="00000000-0000-0000-0000-000000000099",
                                 priority="medium")
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[task_high, task_medium])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db, priority="high")
        assert result["total"] == 1
        assert result["items"][0]["priority"] == "high"

    def test_pagination(self):
        tasks = [_make_task(id=f"00000000-0000-0000-0000-{str(i).zfill(12)}") for i in range(1, 6)]
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=tasks)
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain

        result = list_tasks(ORG_AGENT, db, page=1, page_size=2)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["has_more"] is True


# ── TestGetTask ───────────────────────────────────────────────────────────────


class TestGetTask:
    def test_returns_task(self):
        db = _make_db()
        task = get_task(TASK_ID, ORG_ID, db)
        assert task["id"] == TASK_ID

    def test_raises_if_not_found(self):
        db = _make_empty_db()
        with pytest.raises(ValueError):
            get_task(TASK_ID, ORG_ID, db)

    def test_raises_if_deleted(self):
        db = _make_db(_make_task(deleted_at="2026-01-01T00:00:00+00:00"))
        with pytest.raises(ValueError):
            get_task(TASK_ID, ORG_ID, db)


# ── TestCreateTask ────────────────────────────────────────────────────────────


class TestCreateTask:
    def test_creates_task_assigned_to_self(self):
        db = _make_db()
        data = TaskCreate(title="Call customer")
        task = create_task(ORG_AGENT, db, data)
        assert task["id"] == TASK_ID

    def test_agent_cannot_assign_to_another(self):
        db = _make_db()
        data = TaskCreate(title="Call customer", assigned_to=USER_ID2)
        with pytest.raises(PermissionError):
            create_task(ORG_AGENT, db, data)

    def test_manager_can_assign_to_another(self):
        db = _make_db()
        data = TaskCreate(title="Call customer", assigned_to=USER_ID2)
        task = create_task(ORG_OWNER, db, data)
        assert task["id"] == TASK_ID

    def test_task_type_always_manual(self):
        db = MagicMock()
        inserted: dict = {}

        def _table(name):
            chain = MagicMock()
            if name == "tasks":
                def _insert(row):
                    inserted.update(row)
                    inner = MagicMock()
                    inner.execute.return_value = MagicMock(data=[{**row, "id": TASK_ID}])
                    return inner
                chain.insert.side_effect = _insert
            else:
                chain.insert.return_value = chain
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table
        data = TaskCreate(title="Test")
        create_task(ORG_AGENT, db, data)
        assert inserted.get("task_type") == "manual"

    def test_priority_defaults_to_medium(self):
        db = MagicMock()
        inserted: dict = {}

        def _table(name):
            chain = MagicMock()
            if name == "tasks":
                def _insert(row):
                    inserted.update(row)
                    inner = MagicMock()
                    inner.execute.return_value = MagicMock(data=[{**row, "id": TASK_ID}])
                    return inner
                chain.insert.side_effect = _insert
            else:
                chain.insert.return_value = chain
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = _table
        create_task(ORG_AGENT, db, TaskCreate(title="Test"))
        assert inserted.get("priority") == "medium"


# ── TestUpdateTask ────────────────────────────────────────────────────────────


class TestUpdateTask:
    def test_updates_title(self):
        db = _make_db()
        data = TaskUpdate(title="New title")
        task = update_task(TASK_ID, ORG_AGENT, db, data)
        assert task is not None

    def test_agent_cannot_reassign(self):
        db = _make_db()
        data = TaskUpdate(assigned_to=USER_ID2)
        with pytest.raises(PermissionError):
            update_task(TASK_ID, ORG_AGENT, db, data)

    def test_manager_can_reassign(self):
        db = _make_db()
        data = TaskUpdate(assigned_to=USER_ID2)
        task = update_task(TASK_ID, ORG_OWNER, db, data)
        assert task is not None

    def test_raises_if_not_found(self):
        db = _make_empty_db()
        with pytest.raises(ValueError):
            update_task(TASK_ID, ORG_AGENT, db, TaskUpdate(title="x"))


# ── TestCompleteTask ──────────────────────────────────────────────────────────


class TestCompleteTask:
    def test_completes_task(self):
        db = _make_db()
        task = complete_task(TASK_ID, ORG_AGENT, db)
        assert task is not None

    def test_completion_notes_accepted(self):
        db = _make_db()
        task = complete_task(TASK_ID, ORG_AGENT, db, notes="Resolved by phone call")
        assert task is not None

    def test_raises_if_not_found(self):
        db = _make_empty_db()
        with pytest.raises(ValueError):
            complete_task(TASK_ID, ORG_AGENT, db)


# ── TestSnoozeTask ────────────────────────────────────────────────────────────


class TestSnoozeTask:
    def test_snoozes_task(self):
        db = _make_db()
        task = snooze_task(TASK_ID, ORG_AGENT, db, "2030-12-01T09:00:00+00:00")
        assert task is not None

    def test_raises_if_not_found(self):
        db = _make_empty_db()
        with pytest.raises(ValueError):
            snooze_task(TASK_ID, ORG_AGENT, db, "2030-12-01T09:00:00+00:00")