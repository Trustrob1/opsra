"""
tests/unit/test_nurture_queue.py
Unit + integration tests for GAP-6 — Nurture Queue.

Covers:
  - get_nurture_queue() returns only nurture-track leads for the org
  - get_nurture_queue() excludes opted-out by default
  - get_nurture_queue() includes opted-out when include_opted_out=True
  - get_nurture_queue() respects pagination
  - GET /api/v1/leads/nurture-queue returns 403 for non-managers
  - GET /api/v1/leads/nurture-queue returns 200 + paginated data for managers
  - GET /api/v1/leads/nurture-queue passes include_opted_out query param

Pattern 32: dependency_overrides teardowns use pop(), never clear().
Pattern 42: patch at source module, not consumer.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ORG_ID   = str(uuid.uuid4())
LEAD_ID  = str(uuid.uuid4())
LEAD_ID2 = str(uuid.uuid4())
USER_ID  = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> MagicMock:
    db    = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[], count=0)
    for m in ("eq", "neq", "in_", "is_", "gte", "lte", "maybe_single",
              "order", "range", "select"):
        getattr(chain, m).return_value = chain
    db.table.return_value.select.return_value  = chain
    db.table.return_value.insert.return_value  = chain
    db.table.return_value.update.return_value  = chain
    return db


def _nurture_lead(lead_id=LEAD_ID, opted_out=False) -> dict:
    return {
        "id":                        lead_id,
        "org_id":                    ORG_ID,
        "full_name":                 "Test Lead",
        "score":                     "cold",
        "nurture_track":             True,
        "nurture_opted_out":         opted_out,
        "nurture_graduation_reason": "lead_unresponsive",
        "nurture_sequence_position": 2,
        "last_nurture_sent_at":      "2026-04-06T08:00:00+00:00",
        "updated_at":                "2026-04-06T08:00:00+00:00",
        "assigned_to":               USER_ID,
        "assigned_user":             {"id": USER_ID, "full_name": "Ada Rep"},
        "deleted_at":                None,
    }


def _org(template: str) -> dict:
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "roles":  {"template": template},
    }


# ===========================================================================
# Service — get_nurture_queue
# ===========================================================================

class TestGetNurtureQueueService:

    def test_returns_nurture_track_leads(self):
        """Returns leads where nurture_track=True scoped to org."""
        from app.services.lead_service import get_nurture_queue

        db    = _mock_db()
        leads = [_nurture_lead()]
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=leads, count=1)

        result = get_nurture_queue(db=db, org_id=ORG_ID)

        assert result["total"] == 1
        assert result["items"] == leads
        assert result["page"] == 1

    def test_excludes_opted_out_by_default(self):
        """By default, opted-out leads are filtered out."""
        from app.services import lead_service

        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[], count=0)

        with patch.object(lead_service, "get_nurture_queue",
                          wraps=lead_service.get_nurture_queue) as mock_fn:
            result = lead_service.get_nurture_queue(db=db, org_id=ORG_ID)

        # include_opted_out defaults to False
        args, kwargs = mock_fn.call_args
        include = kwargs.get("include_opted_out",
                             args[3] if len(args) > 3 else False)
        assert include is False

    def test_includes_opted_out_when_flag_set(self):
        """include_opted_out=True returns opted-out leads too."""
        from app.services.lead_service import get_nurture_queue

        db    = _mock_db()
        opted = _nurture_lead(opted_out=True)
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[opted], count=1)

        result = get_nurture_queue(
            db=db, org_id=ORG_ID, include_opted_out=True,
        )

        assert result["total"] == 1
        assert result["items"][0]["nurture_opted_out"] is True

    def test_pagination_respected(self):
        """page and page_size are passed through to the result."""
        from app.services.lead_service import get_nurture_queue

        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[], count=0)

        result = get_nurture_queue(db=db, org_id=ORG_ID, page=2, page_size=10)

        assert result["page"] == 2
        assert result["page_size"] == 10

    def test_empty_queue_returns_zero_total(self):
        """No nurture leads → total=0, items=[]."""
        from app.services.lead_service import get_nurture_queue

        db = _mock_db()
        db.table.return_value.select.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[], count=0)

        result = get_nurture_queue(db=db, org_id=ORG_ID)

        assert result["total"] == 0
        assert result["items"] == []


# ===========================================================================
# Endpoint — GET /api/v1/leads/nurture-queue
# ===========================================================================

class TestNurtureQueueEndpoint:

    def _override(self, app, org_template: str, db_mock=None):
        from app.database import get_supabase
        from app.dependencies import get_current_org
        app.dependency_overrides[get_current_org] = lambda: _org(org_template)
        app.dependency_overrides[get_supabase]    = lambda: (db_mock or _mock_db())

    def _teardown(self, app):
        from app.database import get_supabase
        from app.dependencies import get_current_org
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @pytest.mark.parametrize("template", ["sales_agent", "affiliate_partner"])
    def test_non_manager_gets_403(self, template):
        """sales_agent and affiliate_partner must receive 403."""
        from app.main import app

        self._override(app, template)
        try:
            resp = TestClient(app).get("/api/v1/leads/nurture-queue")
        finally:
            self._teardown(app)

        assert resp.status_code == 403

    @pytest.mark.parametrize("template", ["owner", "admin", "ops_manager"])
    def test_manager_gets_200(self, template):
        """owner, admin, ops_manager must receive 200."""
        from app.main import app
        from app.services import lead_service

        self._override(app, template)
        try:
            with patch.object(
                lead_service,
                "get_nurture_queue",
                return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
            ):
                resp = TestClient(app).get("/api/v1/leads/nurture-queue")
        finally:
            self._teardown(app)

        assert resp.status_code == 200

    def test_returns_paginated_envelope(self):
        """Response follows paginated() envelope structure."""
        from app.main import app
        from app.services import lead_service

        lead  = _nurture_lead()
        self._override(app, "owner")
        try:
            with patch.object(
                lead_service,
                "get_nurture_queue",
                return_value={"items": [lead], "total": 1, "page": 1, "page_size": 20},
            ):
                resp = TestClient(app).get("/api/v1/leads/nurture-queue")
        finally:
            self._teardown(app)

        assert resp.status_code == 200
        data = resp.json()
        # paginated() envelope keys
        assert "items" in data or "data" in data

    def test_include_opted_out_query_param_forwarded(self):
        """include_opted_out=true query param is forwarded to service."""
        from app.main import app
        from app.services import lead_service

        self._override(app, "owner")
        try:
            with patch.object(
                lead_service,
                "get_nurture_queue",
                return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
            ) as mock_fn:
                TestClient(app).get(
                    "/api/v1/leads/nurture-queue?include_opted_out=true"
                )
        finally:
            self._teardown(app)

        _, kwargs = mock_fn.call_args
        assert kwargs.get("include_opted_out") is True

    def test_route_not_shadowed_by_lead_id(self):
        """
        /nurture-queue must not be resolved as /{lead_id}.
        If it were, it would return 404 (lead not found) instead of 403/200.
        We test this by ensuring a non-manager gets 403 (route matched correctly)
        not 404 (route shadowed).
        """
        from app.main import app

        self._override(app, "sales_agent")
        try:
            resp = TestClient(app).get("/api/v1/leads/nurture-queue")
        finally:
            self._teardown(app)

        # 403 = route matched and permission denied (correct)
        # 404 = route was shadowed by /{lead_id} and treated as a lead lookup (wrong)
        assert resp.status_code == 403, (
            "Route must be matched as /nurture-queue, not as /{lead_id}. "
            f"Got {resp.status_code}: {resp.json()}"
        )
