"""
tests/integration/test_concurrent_edits.py
9E-C — C7: Concurrent edit detection on PATCH routes.

Tests:
  - PATCH /leads/{id} with stale updated_at → 409 Conflict
  - PATCH /leads/{id} with current updated_at → 200 OK

Requirements: The C7 router patch must be applied to app/routers/leads.py
(and customers.py / tickets.py) before these tests will pass. See
c7_router_patches.py for the exact code to add.

Pattern 32: Integration test teardowns pop overrides, never clear().
Pattern 44: Override get_current_org directly.
T1: All mocked function signatures verified against service source.
T2: No mixing of side_effect and return_value on same mock chain.
T3: Syntax validated before delivery.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
LEAD_ID = "00000000-0000-0000-0000-000000000020"

# Timestamps used in tests
CURRENT_TS = "2026-04-29T10:00:00+00:00"
STALE_TS   = "2026-04-29T09:00:00+00:00"  # older than what's in DB


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with get_current_org overridden (Pattern 44)."""
    from app.main import app
    from app.routers.leads import router as leads_router

    mock_org = {
        "id": USER_ID,
        "org_id": ORG_ID,
        "name": "Test Org",
        "roles": {"template": "owner"},
    }

    mock_db = MagicMock()

    # Override all dependencies that would hit real infrastructure
    from app.dependencies import get_current_org, get_current_user
    from app.database import get_supabase, reset_supabase_client

    app.dependency_overrides[get_current_org] = lambda: mock_org
    app.dependency_overrides[get_current_user] = lambda: mock_org
    app.dependency_overrides[get_supabase] = lambda: mock_db

    with TestClient(app) as c:
        yield c

    # Pattern 32: pop each override, never clear()
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_supabase, None)
    reset_supabase_client()


# ---------------------------------------------------------------------------
# C7 tests
# ---------------------------------------------------------------------------

class TestConcurrentEditC7:
    """
    C7: PATCH /leads/{id} with updated_at precondition.

    Backend logic (to be added in leads router):
      payload.updated_at is the client's last-known version timestamp.
      If db_record.updated_at > payload.updated_at → 409 Conflict.
      Response body: { code: "CONCURRENT_MODIFICATION",
                       message: "Record modified by another user. Reload to see changes." }
    """

    @patch("app.services.lead_service.update_lead")
    @patch("app.services.lead_service._lead_or_404")
    def test_patch_with_stale_updated_at_returns_409(
        self, mock_404, mock_update, client
    ):
        """
        Sending a PATCH with an updated_at that is older than the DB record's
        updated_at should return HTTP 409 Conflict.

        The router compares payload.updated_at against the fetched record's
        updated_at BEFORE calling update_lead().
        """
        # DB record has been modified AFTER the client's version
        db_lead = {
            "id": LEAD_ID,
            "org_id": ORG_ID,
            "full_name": "Test Lead",
            "updated_at": CURRENT_TS,  # newer than client's stale_ts
        }
        mock_404.return_value = db_lead
        # update_lead should NOT be called — we expect 409 before it's reached
        mock_update.return_value = db_lead

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}",
            json={
                "full_name": "Updated Name",
                "updated_at": STALE_TS,  # client has an older version
            },
        )

        assert resp.status_code == 409, (
            f"Expected 409 for stale updated_at, got {resp.status_code}. "
            "Ensure C7 router patch has been applied to leads.py."
        )
        body = resp.json()
        detail = body.get("detail") or {}
        assert detail.get("code") == "CONCURRENT_MODIFICATION", (
            f"Expected CONCURRENT_MODIFICATION error code, got: {detail}"
        )

    @patch("app.services.lead_service.update_lead")
    @patch("app.services.lead_service._lead_or_404")
    def test_patch_with_current_updated_at_returns_200(
        self, mock_404, mock_update, client
    ):
        """
        Sending a PATCH with the current updated_at (matching or newer than DB)
        should succeed with HTTP 200.
        """
        db_lead = {
            "id": LEAD_ID,
            "org_id": ORG_ID,
            "full_name": "Test Lead",
            "updated_at": STALE_TS,  # DB record is older than client's version
        }
        mock_404.return_value = db_lead

        updated_lead = {**db_lead, "full_name": "Updated Name", "updated_at": CURRENT_TS}
        mock_update.return_value = updated_lead

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}",
            json={
                "full_name": "Updated Name",
                "updated_at": CURRENT_TS,  # client has the latest version
            },
        )

        assert resp.status_code == 200, (
            f"Expected 200 for current updated_at, got {resp.status_code}. "
            f"Body: {resp.text}"
        )
        body = resp.json()
        assert body.get("data", {}).get("full_name") == "Updated Name" or \
               body.get("full_name") == "Updated Name"

    @patch("app.services.lead_service.update_lead")
    @patch("app.services.lead_service._lead_or_404")
    def test_patch_without_updated_at_returns_200(
        self, mock_404, mock_update, client
    ):
        """
        PATCH requests that omit updated_at entirely are treated as
        unconditional updates — for backwards compatibility.
        Must return 200.
        """
        db_lead = {
            "id": LEAD_ID,
            "org_id": ORG_ID,
            "full_name": "Test Lead",
            "updated_at": CURRENT_TS,
        }
        mock_404.return_value = db_lead
        mock_update.return_value = {**db_lead, "full_name": "Updated Name"}

        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}",
            json={"full_name": "Updated Name"},  # no updated_at field
        )

        # No precondition check when updated_at is absent
        assert resp.status_code == 200, (
            f"Expected 200 when updated_at is omitted, got {resp.status_code}."
        )
