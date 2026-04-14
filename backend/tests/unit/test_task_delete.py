"""
tests/test_task_delete.py
Unit + integration tests for task archive/restore/archived-list — M01-9b.

Covers:
  Unit:
    soft_delete_task — happy path (own task), manager deletes other's task,
      permission denied for unrelated user
    restore_task — happy path, not-archived error, permission denied
    list_tasks archived=True — returns only deleted rows, respects personal scoping

  Integration:
    DELETE /api/v1/tasks/{id} — 200 own task, 403 unrelated user, 404 missing
    POST /api/v1/tasks/{id}/restore — 200 manager, 403 agent, 404 not archived
    GET  /api/v1/tasks?archived=true — returns archived tasks only

Pattern 24: all UUIDs valid format.
Pattern 32: dependency overrides use pop() teardown — never clear().
Pattern 44: override get_current_org directly.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org, get_supabase

# ── UUID constants (Pattern 24) ───────────────────────────────────────────────

ORG_ID    = "a1b2c3d4-0000-0000-0000-000000000001"
OWNER_ID  = "a1b2c3d4-0000-0000-0000-000000000002"
AGENT_ID  = "a1b2c3d4-0000-0000-0000-000000000003"
OTHER_ID  = "a1b2c3d4-0000-0000-0000-000000000004"
TASK_ID   = "a1b2c3d4-0000-0000-0000-000000000010"

def _owner_org():
    return {
        "org_id": ORG_ID,
        "id":     OWNER_ID,
        "roles":  {"template": "owner", "permissions": {}},
    }

def _agent_org(user_id=AGENT_ID):
    return {
        "org_id": ORG_ID,
        "id":     user_id,
        "roles":  {"template": "sales_agent", "permissions": {}},
    }

def _task_row(task_id=TASK_ID, assigned_to=AGENT_ID, created_by=AGENT_ID, deleted_at=None):
    return {
        "id":          task_id,
        "org_id":      ORG_ID,
        "title":       "Test task",
        "status":      "open",
        "priority":    "medium",
        "assigned_to": assigned_to,
        "created_by":  created_by,
        "deleted_at":  deleted_at,
        "due_at":      None,
        "created_at":  "2026-04-12T10:00:00+00:00",
        "updated_at":  "2026-04-12T10:00:00+00:00",
    }

# ── Unit tests — soft_delete_task ─────────────────────────────────────────────

class TestSoftDeleteTask:
    def _make_db(self, task_row, update_result=None):
        db = MagicMock()
        # get_task query (no deleted_at in row = not deleted)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [task_row]
        # update query
        updated = {**task_row, "deleted_at": "2026-04-12T12:00:00+00:00"}
        db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            update_result or updated
        ]
        db.table.return_value.insert.return_value.execute.return_value.data = []
        return db

    def test_agent_deletes_own_task(self):
        from app.services.task_service import soft_delete_task
        org = _agent_org(AGENT_ID)
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID)
        db = self._make_db(task)
        result = soft_delete_task(TASK_ID, org, db)
        assert result["id"] == TASK_ID

    def test_manager_deletes_any_task(self):
        from app.services.task_service import soft_delete_task
        org = _owner_org()
        task = _task_row(assigned_to=OTHER_ID, created_by=OTHER_ID)
        db = self._make_db(task)
        result = soft_delete_task(TASK_ID, org, db)
        assert result["id"] == TASK_ID

    def test_unrelated_agent_cannot_delete(self):
        from app.services.task_service import soft_delete_task
        org = _agent_org(OTHER_ID)   # OTHER_ID is neither creator nor assignee
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID)
        db = self._make_db(task)
        with pytest.raises(PermissionError, match="only archive tasks"):
            soft_delete_task(TASK_ID, org, db)

    def test_missing_task_raises_value_error(self):
        from app.services.task_service import soft_delete_task
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with pytest.raises(ValueError):
            soft_delete_task(TASK_ID, _agent_org(), db)


# ── Unit tests — restore_task ─────────────────────────────────────────────────

class TestRestoreTask:
    def _make_db(self, task_row):
        db = MagicMock()
        # _get_any_task fetches regardless of deleted_at
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [task_row]
        # update
        restored = {**task_row, "deleted_at": None}
        db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [restored]
        db.table.return_value.insert.return_value.execute.return_value.data = []
        return db

    def test_agent_restores_own_archived_task(self):
        from app.services.task_service import restore_task
        org  = _agent_org(AGENT_ID)
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID, deleted_at="2026-04-12T12:00:00+00:00")
        db   = self._make_db(task)
        result = restore_task(TASK_ID, org, db)
        assert result["deleted_at"] is None

    def test_manager_restores_any_task(self):
        from app.services.task_service import restore_task
        org  = _owner_org()
        task = _task_row(assigned_to=OTHER_ID, created_by=OTHER_ID, deleted_at="2026-04-12T12:00:00+00:00")
        db   = self._make_db(task)
        result = restore_task(TASK_ID, org, db)
        assert result["deleted_at"] is None

    def test_not_archived_raises_value_error(self):
        from app.services.task_service import restore_task
        org  = _agent_org()
        task = _task_row(deleted_at=None)   # not archived
        db   = self._make_db(task)
        with pytest.raises(ValueError, match="not archived"):
            restore_task(TASK_ID, org, db)

    def test_unrelated_agent_cannot_restore(self):
        from app.services.task_service import restore_task
        org  = _agent_org(OTHER_ID)
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID, deleted_at="2026-04-12T12:00:00+00:00")
        db   = self._make_db(task)
        with pytest.raises(PermissionError, match="only restore"):
            restore_task(TASK_ID, org, db)


# ── Unit tests — list_tasks archived=True ─────────────────────────────────────

class TestListTasksArchived:
    def _db_with_rows(self, rows):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = rows
        return db

    def test_archived_true_returns_only_deleted(self):
        from app.services.task_service import list_tasks
        rows = [
            _task_row("a1b2c3d4-0000-0000-0000-000000000011", deleted_at=None),
            _task_row("a1b2c3d4-0000-0000-0000-000000000012", deleted_at="2026-04-12T12:00:00+00:00"),
        ]
        db = self._db_with_rows(rows)
        result = list_tasks(_agent_org(AGENT_ID), db, archived=True)
        ids = [t["id"] for t in result["items"]]
        assert "a1b2c3d4-0000-0000-0000-000000000012" in ids
        assert "a1b2c3d4-0000-0000-0000-000000000011" not in ids

    def test_archived_false_excludes_deleted(self):
        from app.services.task_service import list_tasks
        rows = [
            _task_row("a1b2c3d4-0000-0000-0000-000000000011", deleted_at=None, assigned_to=AGENT_ID),
            _task_row("a1b2c3d4-0000-0000-0000-000000000012", deleted_at="2026-04-12T12:00:00+00:00", assigned_to=AGENT_ID),
        ]
        db = self._db_with_rows(rows)
        result = list_tasks(_agent_org(AGENT_ID), db, archived=False)
        ids = [t["id"] for t in result["items"]]
        assert "a1b2c3d4-0000-0000-0000-000000000011" in ids
        assert "a1b2c3d4-0000-0000-0000-000000000012" not in ids

    def test_archived_personal_scoping(self):
        """Agent sees only their own archived tasks, not others'."""
        from app.services.task_service import list_tasks
        rows = [
            _task_row("a1b2c3d4-0000-0000-0000-000000000011",
                      assigned_to=AGENT_ID, deleted_at="2026-04-12T12:00:00+00:00"),
            _task_row("a1b2c3d4-0000-0000-0000-000000000012",
                      assigned_to=OTHER_ID, deleted_at="2026-04-12T12:00:00+00:00"),
        ]
        db = self._db_with_rows(rows)
        result = list_tasks(_agent_org(AGENT_ID), db, archived=True, team_view=False)
        ids = [t["id"] for t in result["items"]]
        assert "a1b2c3d4-0000-0000-0000-000000000011" in ids
        assert "a1b2c3d4-0000-0000-0000-000000000012" not in ids


# ── Integration tests ─────────────────────────────────────────────────────────

client = TestClient(app)

def _mock_db_for_routes(task_row, updated_row=None):
    db = MagicMock()
    # select (get_task / _get_any_task)
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [task_row]
    # update
    db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        updated_row or task_row
    ]
    # audit insert
    db.table.return_value.insert.return_value.execute.return_value.data = []
    return db


class TestDeleteRoute:
    def test_delete_own_task_returns_200(self):
        task    = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID)
        updated = {**task, "deleted_at": "2026-04-12T12:00:00+00:00"}
        db = _mock_db_for_routes(task, updated)

        app.dependency_overrides[get_current_org] = lambda: _agent_org(AGENT_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.delete(f"/api/v1/tasks/{TASK_ID}")
            assert r.status_code == 200
            assert r.json()["success"] is True
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_delete_unrelated_task_returns_403(self):
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID)
        db   = _mock_db_for_routes(task)

        app.dependency_overrides[get_current_org] = lambda: _agent_org(OTHER_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.delete(f"/api/v1/tasks/{TASK_ID}")
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_delete_missing_task_returns_404(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        app.dependency_overrides[get_current_org] = lambda: _agent_org()
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.delete(f"/api/v1/tasks/{TASK_ID}")
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_manager_deletes_any_task_returns_200(self):
        task    = _task_row(assigned_to=OTHER_ID, created_by=OTHER_ID)
        updated = {**task, "deleted_at": "2026-04-12T12:00:00+00:00"}
        db      = _mock_db_for_routes(task, updated)

        app.dependency_overrides[get_current_org] = lambda: _owner_org()
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.delete(f"/api/v1/tasks/{TASK_ID}")
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)


class TestRestoreRoute:
    def test_restore_archived_task_returns_200(self):
        task    = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID,
                            deleted_at="2026-04-12T12:00:00+00:00")
        restored = {**task, "deleted_at": None}
        db = _mock_db_for_routes(task, restored)

        app.dependency_overrides[get_current_org] = lambda: _agent_org(AGENT_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.post(f"/api/v1/tasks/{TASK_ID}/restore")
            assert r.status_code == 200
            assert r.json()["success"] is True
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_restore_non_archived_returns_404(self):
        task = _task_row(deleted_at=None)  # not archived
        db   = _mock_db_for_routes(task)

        app.dependency_overrides[get_current_org] = lambda: _agent_org()
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.post(f"/api/v1/tasks/{TASK_ID}/restore")
            assert r.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_restore_unrelated_task_returns_403(self):
        task = _task_row(assigned_to=AGENT_ID, created_by=AGENT_ID,
                         deleted_at="2026-04-12T12:00:00+00:00")
        db   = _mock_db_for_routes(task)

        app.dependency_overrides[get_current_org] = lambda: _agent_org(OTHER_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.post(f"/api/v1/tasks/{TASK_ID}/restore")
            assert r.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)


class TestArchivedListRoute:
    def test_archived_list_returns_200(self):
        archived_task = _task_row(
            assigned_to=AGENT_ID, created_by=AGENT_ID,
            deleted_at="2026-04-12T12:00:00+00:00",
        )
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [archived_task]

        app.dependency_overrides[get_current_org] = lambda: _agent_org(AGENT_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.get("/api/v1/tasks", params={"archived": "true"})
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["total"] == 1
            assert data["items"][0]["id"] == TASK_ID
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)

    def test_default_list_excludes_archived(self):
        """GET /tasks without archived=true must not return deleted tasks."""
        task = _task_row(
            assigned_to=AGENT_ID, created_by=AGENT_ID,
            deleted_at="2026-04-12T12:00:00+00:00",  # archived
        )
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [task]

        app.dependency_overrides[get_current_org] = lambda: _agent_org(AGENT_ID)
        app.dependency_overrides[get_supabase]    = lambda: db
        try:
            r = client.get("/api/v1/tasks")
            assert r.status_code == 200
            assert r.json()["data"]["total"] == 0
        finally:
            app.dependency_overrides.pop(get_current_org, None)
            app.dependency_overrides.pop(get_supabase, None)
