"""
tests/integration/test_ops_routes.py
Integration tests for Operations Intelligence routes — Phase 6A.

Pattern 32: fixture teardowns use .pop(), never .clear().
Pattern 24: all test UUIDs are valid UUID format.
Pattern 28: routes depend on get_current_org, not get_current_user.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ── Test constants (Pattern 24) ───────────────────────────────────────────────

ORG_ID = "00000000-0000-0000-0000-000000000010"
USER_ID_OWNER = "00000000-0000-0000-0000-000000000001"
USER_ID_AGENT = "00000000-0000-0000-0000-000000000002"

ORG_OWNER = {
    "id": USER_ID_OWNER,
    "org_id": ORG_ID,
    "role": "owner",
    "roles": {"permissions": {}},
}
ORG_AGENT = {
    "id": USER_ID_AGENT,
    "org_id": ORG_ID,
    "role": "agent",
    "roles": {"permissions": {}},
}

# ── Test client ───────────────────────────────────────────────────────────────

client = TestClient(app, raise_server_exceptions=False)


# ── DB mock factory ───────────────────────────────────────────────────────────


def _make_db() -> MagicMock:
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.lte.return_value = chain
    chain.insert.return_value = chain
    db.table.return_value = chain
    return db


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/dashboard/metrics
# ─────────────────────────────────────────────────────────────────────────────


class TestDashboardMetrics:
    """Tests for GET /api/v1/dashboard/metrics."""

    @pytest.fixture(autouse=True)
    def _overrides(self):
        """Pattern 32: set overrides, yield, pop (never clear)."""
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_OWNER
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)  # Pattern 32
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_correct_shape(self, _overrides):
        resp = client.get("/api/v1/dashboard/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        body = data["data"]
        # All expected fields must be present
        for field in (
            "leads_total",
            "leads_this_week",
            "active_customers",
            "open_tickets",
            "sla_breached_tickets",
            "churn_risk_high",
            "churn_risk_critical",
            "renewals_due_30_days",
            "overdue_tasks",
        ):
            assert field in body, f"Missing field: {field}"

    def test_owner_receives_revenue_fields(self, _overrides):
        resp = client.get("/api/v1/dashboard/metrics")
        assert resp.status_code == 200
        body = resp.json()["data"]
        # Owner's MRR comes back (None is valid if no subs — field must exist)
        assert "mrr_ngn" in body
        assert "revenue_at_risk_ngn" in body

    def test_agent_revenue_fields_are_null(self, _overrides):
        """Agent role must not receive revenue data (§12.5)."""
        app.dependency_overrides[get_current_org] = lambda: ORG_AGENT
        resp = client.get("/api/v1/dashboard/metrics")
        app.dependency_overrides[get_current_org] = lambda: ORG_OWNER  # restore
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["mrr_ngn"] is None
        assert body["revenue_at_risk_ngn"] is None

    def test_requires_authentication(self, _overrides):
        """Without auth override the route must return 401 or 403 (unauthenticated).
        FastAPI's HTTPBearer returns 403 when no Bearer token is supplied."""
        saved = app.dependency_overrides.pop(get_current_org)  # remove auth
        try:
            resp = client.get("/api/v1/dashboard/metrics")
            assert resp.status_code in (401, 403)
        finally:
            app.dependency_overrides[get_current_org] = saved  # Pattern 32 restore


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/ask
# ─────────────────────────────────────────────────────────────────────────────


class TestAskYourData:
    """Tests for POST /api/v1/ask."""

    @pytest.fixture(autouse=True)
    def _overrides(self):
        """Pattern 32: set overrides, yield, pop."""
        mock_db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: mock_db
        app.dependency_overrides[get_current_org] = lambda: ORG_OWNER
        yield mock_db
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def _mock_claude_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        resp.usage = MagicMock(input_tokens=100, output_tokens=50)
        return resp

    def test_valid_question_returns_200_with_answer(self, _overrides):
        with patch("app.services.ops_service._get_anthropic") as mock_ai:
            mock_ai.return_value.messages.create.return_value = (
                self._mock_claude_response("You have 3 open tickets.")
            )
            resp = client.post("/api/v1/ask", json={"question": "How many open tickets?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "answer" in data["data"]
        assert len(data["data"]["answer"]) > 0

    def test_empty_question_returns_422(self, _overrides):
        """§11.2: min_length=1 enforced by Pydantic."""
        resp = client.post("/api/v1/ask", json={"question": ""})
        assert resp.status_code == 422

    def test_question_over_1000_chars_returns_422(self, _overrides):
        """§11.2: max_length=1000 enforced by Pydantic."""
        resp = client.post("/api/v1/ask", json={"question": "x" * 1001})
        assert resp.status_code == 422

    def test_missing_question_field_returns_422(self, _overrides):
        resp = client.post("/api/v1/ask", json={})
        assert resp.status_code == 422

    def test_ai_degradation_still_returns_200(self, _overrides):
        """S14: AI failure must return 200 with graceful fallback, never 500."""
        with patch("app.services.ops_service._get_anthropic") as mock_ai:
            mock_ai.side_effect = Exception("Anthropic API unreachable")
            resp = client.post("/api/v1/ask", json={"question": "What is our MRR?"})
        assert resp.status_code == 200
        answer = resp.json()["data"]["answer"]
        assert "temporarily unavailable" in answer.lower()

    def test_requires_authentication(self, _overrides):
        """Without auth override the route must return 401 or 403 (unauthenticated).
        FastAPI's HTTPBearer returns 403 when no Bearer token is supplied."""
        saved = app.dependency_overrides.pop(get_current_org)
        try:
            resp = client.post("/api/v1/ask", json={"question": "How many leads?"})
            assert resp.status_code in (401, 403)
        finally:
            app.dependency_overrides[get_current_org] = saved