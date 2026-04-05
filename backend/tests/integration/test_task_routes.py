"""
tests/integration/test_task_routes.py
Integration tests for Task Management routes — Phase 7A.

Pattern 32: dependency teardowns use .pop(), never .clear().
Pattern 24: all test UUIDs are valid UUID format.
Pattern 37: org fixtures use roles.template shape.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ── Test constants ─────────────────────────────────────────────────────────────

ORG_ID   = "00000000-0000-0000-0000-000000000010"
USER_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID2 = "00000000-0000-0000-0000-000000000002"
TASK_ID  = "00000000-0000-0000-0000-000000000020"

# Pattern 37
ORG_OWNER = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "owner", "permissions": {}},
}
ORG_AGENT = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "sales_agent", "permissions": {}},
}

client = TestClient(app, raise_server_exceptions=False)


def _make_task(**overrides) -> dict:
    base = {
        "id": TASK_ID, "org_id": ORG_ID,
        "title": "Test task", "description": None,
        "task_type": "manual", "source_module": None,
        "source_record_id": None, "assigned_to": USER_ID,
        "created_by": USER_ID, "status": "open",
        "priority": "medium",
        "due_at": "2030-01-01T10:00:00+00:00",
        "completed_at": None, "snoozed_until": None,
        "completion_notes": None, "ai_confirmed_by": None,
        "deleted_at": None,
        "created_at": "2026-04-04T08:00:00+00:00",
        "updated_at": "2026-04-04T08:00:00+00:00",
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


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/tasks
# ─────────────────────────────────────────────────────────────────────────────

class TestListTasksRoute:
    @pytest.fixture(autouse=True)
    def _overrides(self):
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)    # Pattern 32
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_paginated_shape(self, _overrides):
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]
        assert "page" in data["data"]
        assert "has_more" in data["data"]

    def test_requires_auth(self, _overrides):
        saved = app.dependency_overrides.pop(get_current_org)
        try:
            resp = client.get("/api/v1/tasks")
            assert resp.status_code in (401, 403)
        finally:
            app.dependency_overrides[get_current_org] = saved   # Pattern 32


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/tasks
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateTaskRoute:
    @pytest.fixture(autouse=True)
    def _overrides(self):
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_valid_task_returns_201(self, _overrides):
        resp = client.post("/api/v1/tasks", json={"title": "Follow up with Amaka"})
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_missing_title_returns_422(self, _overrides):
        resp = client.post("/api/v1/tasks", json={})
        assert resp.status_code == 422

    def test_empty_title_returns_422(self, _overrides):
        resp = client.post("/api/v1/tasks", json={"title": ""})
        assert resp.status_code == 422

    def test_title_over_255_returns_422(self, _overrides):
        resp = client.post("/api/v1/tasks", json={"title": "x" * 256})
        assert resp.status_code == 422

    def test_agent_assigning_to_other_returns_403(self, _overrides):
        resp = client.post(
            "/api/v1/tasks",
            json={"title": "Task", "assigned_to": USER_ID2},
        )
        assert resp.status_code == 403

    def test_owner_can_assign_to_other(self, _overrides):
        app.dependency_overrides[get_current_org] = lambda: ORG_OWNER
        resp = client.post(
            "/api/v1/tasks",
            json={"title": "Task", "assigned_to": USER_ID2},
        )
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        assert resp.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/tasks/{id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetTaskRoute:
    @pytest.fixture(autouse=True)
    def _overrides(self):
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_for_existing_task(self, _overrides):
        resp = client.get(f"/api/v1/tasks/{TASK_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == TASK_ID

    def test_returns_404_for_missing_task(self, _overrides):
        db = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        chain.select.return_value = chain
        chain.eq.return_value = chain
        db.table.return_value = chain
        app.dependency_overrides[get_supabase] = lambda: db
        resp = client.get(f"/api/v1/tasks/{TASK_ID}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/tasks/{id}/complete
# ─────────────────────────────────────────────────────────────────────────────

class TestCompleteTaskRoute:
    @pytest.fixture(autouse=True)
    def _overrides(self):
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_completes_task_returns_200(self, _overrides):
        resp = client.post(f"/api/v1/tasks/{TASK_ID}/complete", json={})
        assert resp.status_code == 200
        assert "completed" in resp.json()["message"].lower()

    def test_completes_with_notes(self, _overrides):
        resp = client.post(
            f"/api/v1/tasks/{TASK_ID}/complete",
            json={"completion_notes": "Called and resolved."},
        )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/tasks/{id}/snooze
# ─────────────────────────────────────────────────────────────────────────────

class TestSnoozeTaskRoute:
    @pytest.fixture(autouse=True)
    def _overrides(self):
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_snooze_returns_200(self, _overrides):
        resp = client.post(
            f"/api/v1/tasks/{TASK_ID}/snooze",
            json={"snoozed_until": "2030-12-01T09:00:00+00:00"},
        )
        assert resp.status_code == 200
        assert "snoozed" in resp.json()["message"].lower()

    def test_missing_snoozed_until_returns_422(self, _overrides):
        resp = client.post(f"/api/v1/tasks/{TASK_ID}/snooze", json={})
        assert resp.status_code == 422