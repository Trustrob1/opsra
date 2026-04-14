"""
tests/integration/test_demo_recap_routes.py
--------------------------------------------
M01-9 — Integration tests: PATCH /{lead_id}/demos/{demo_id} with outcome=attended
         → recap field returned in response.

Pattern 32: dependency overrides popped in teardown — never restore.
Pattern 42: patch at app.services.demo_service (where name is USED in router).
Pattern 44: override get_current_org directly.
Pattern 24: all UUIDs are valid UUID format.

Tests (5):
  1. attended outcome → response contains recap field (non-null)
  2. no_show outcome  → response recap field is None
  3. rescheduled outcome → response recap field is None
  4. invalid outcome value → 422 validation error, service never called
  5. missing outcome field → 422 validation error, service never called
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Constants (Pattern 24 — valid UUID format) ────────────────────────────────

ORG_ID  = "00000000-0000-0000-0000-000000000010"
USER_ID = "00000000-0000-0000-0000-000000000011"
LEAD_ID = "00000000-0000-0000-0000-000000000012"
DEMO_ID = "00000000-0000-0000-0000-000000000013"

# Org dict returned by get_current_org — sales_agent role
MOCK_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "is_active": True,
    "roles": {"template": "sales_agent"},
}

# Full demo object returned by demo_service.log_outcome for attended
ATTENDED_DEMO = {
    "id": DEMO_ID,
    "org_id": ORG_ID,
    "lead_id": LEAD_ID,
    "status": "attended",
    "outcome": "attended",
    "outcome_notes": "Great demo. Lead wants proposal.",
    "outcome_logged_at": "2026-04-10T11:00:00+00:00",
    "scheduled_at": "2026-04-10T10:00:00+00:00",
    "medium": "virtual",
    "duration_minutes": 30,
    "notes": None,
    "assigned_to": USER_ID,
    "confirmed_by": USER_ID,
    "confirmed_at": "2026-04-09T08:00:00+00:00",
    "confirmation_sent": True,
    "reminder_24h_sent": True,
    "reminder_1h_sent": True,
    "noshow_task_created": False,
    "parent_demo_id": None,
    "lead_preferred_time": None,
    "created_by": USER_ID,
    "created_at": "2026-04-08T10:00:00+00:00",
    "updated_at": "2026-04-10T11:00:00+00:00",
    "rep_nudge_sent_at": None,
    "manager_nudge_sent_at": None,
    "recap": {
        "summary": "The demo went well. Lead was engaged with automation features.",
        "key_interests": ["Invoicing automation", "WhatsApp integration"],
        "concerns_raised": ["Onboarding timeline"],
        "lead_readiness": "Needs proposal",
        "recommended_next_action": "Send proposal by end of week.",
    },
}

NO_SHOW_DEMO = {
    **ATTENDED_DEMO,
    "status": "no_show",
    "outcome": "no_show",
    "recap": None,
    "noshow_task_created": True,
}

RESCHEDULED_DEMO = {
    **ATTENDED_DEMO,
    "status": "rescheduled",
    "outcome": "rescheduled",
    "recap": None,
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """
    TestClient with get_current_org and get_supabase overridden.
    Pattern 32: overrides popped in teardown.
    Pattern 44: override get_current_org directly.
    """
    from app.main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    db_mock = MagicMock()
    app.dependency_overrides[get_current_org] = lambda: MOCK_ORG
    app.dependency_overrides[get_supabase]    = lambda: db_mock

    with TestClient(app) as c:
        yield c

    # Pattern 32: pop, never restore
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def client_affiliate():
    """
    TestClient with affiliate_partner role — used to verify 403 is NOT returned
    after the M01-9 fix (require_not_affiliate removed from log_demo_outcome).
    """
    from app.main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    affiliate_org = {**MOCK_ORG, "roles": {"template": "affiliate_partner"}}
    db_mock = MagicMock()
    app.dependency_overrides[get_current_org] = lambda: affiliate_org
    app.dependency_overrides[get_supabase]    = lambda: db_mock

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLogOutcomeRecapIntegration:

    # Pattern 42: patch at app.services.demo_service — where the name is used in router
    @patch("app.services.demo_service.log_outcome", return_value=ATTENDED_DEMO)
    def test_attended_outcome_returns_recap(self, mock_log, client):
        """
        PATCH attended → 200, response data contains non-null recap with
        all required recap fields.
        """
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "attended", "outcome_notes": "Great demo. Lead wants proposal."},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

        data = body["data"]
        assert data["status"] == "attended"
        assert data["recap"] is not None
        assert data["recap"]["lead_readiness"] == "Needs proposal"
        assert isinstance(data["recap"]["key_interests"], list)
        assert isinstance(data["recap"]["concerns_raised"], list)
        assert "summary" in data["recap"]
        assert "recommended_next_action" in data["recap"]

        # Verify service was called with correct args
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["outcome"] == "attended"
        assert call_kwargs["org_id"] == ORG_ID
        assert call_kwargs["lead_id"] == LEAD_ID
        assert call_kwargs["demo_id"] == DEMO_ID

    @patch("app.services.demo_service.log_outcome", return_value=NO_SHOW_DEMO)
    def test_no_show_outcome_recap_is_null(self, mock_log, client):
        """PATCH no_show → 200, recap field is None."""
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "no_show"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "no_show"
        assert body["data"]["recap"] is None

    @patch("app.services.demo_service.log_outcome", return_value=RESCHEDULED_DEMO)
    def test_rescheduled_outcome_recap_is_null(self, mock_log, client):
        """PATCH rescheduled → 200, recap field is None."""
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "rescheduled", "outcome_notes": "Lead wants to reschedule."},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["recap"] is None

    @patch("app.services.demo_service.log_outcome")
    def test_invalid_outcome_returns_422(self, mock_log, client):
        """
        outcome must match pattern ^(attended|no_show|rescheduled)$.
        Invalid value → 422, service never called.
        """
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "cancelled"},
        )

        assert resp.status_code == 422
        mock_log.assert_not_called()

    @patch("app.services.demo_service.log_outcome")
    def test_missing_outcome_field_returns_422(self, mock_log, client):
        """outcome is required — omitting it → 422, service never called."""
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome_notes": "Some notes but no outcome"},
        )

        assert resp.status_code == 422
        mock_log.assert_not_called()

    @patch("app.services.demo_service.log_outcome", return_value=ATTENDED_DEMO)
    def test_affiliate_can_log_outcome_after_fix(self, mock_log, client_affiliate):
        """
        M01-9 fix: require_not_affiliate removed from log_demo_outcome.
        affiliate_partner role should now get 200, not 403.
        """
        resp = client_affiliate.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "attended", "outcome_notes": "Demo went well."},
        )

        assert resp.status_code == 200
        assert resp.json()["success"] is True
