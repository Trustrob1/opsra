"""
tests/integration/test_pipeline_stage_routes.py
CONFIG-6 — Dynamic Pipeline Stage Configuration

Integration tests:
  - GET /admin/pipeline-stages: returns config
  - GET /admin/pipeline-stages: returns defaults when null
  - PATCH /admin/pipeline-stages: saves valid config
  - PATCH /admin/pipeline-stages: rejects unknown stage key
  - PATCH /admin/pipeline-stages: rejects label > 50 chars
  - PATCH /admin/pipeline-stages: rejects when fewer than 2 enabled
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Constants — all valid UUIDs (Pattern 24)
# ---------------------------------------------------------------------------

ORG_ID  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# Pattern 58: permissions nested inside roles dict
# Pattern 61: user UUID is at "id" not "user_id"
_ORG_PAYLOAD = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {
        "template": "owner",
        "permissions": {
            "manage_users": True,
        },
    },
}

VALID_STAGES = [
    {"key": "new",           "label": "New Lead",      "enabled": True},
    {"key": "contacted",     "label": "Contacted",     "enabled": True},
    {"key": "meeting_done",  "label": "Demo Done",     "enabled": True},
    {"key": "proposal_sent", "label": "Proposal Sent", "enabled": True},
    {"key": "converted",     "label": "Converted",     "enabled": True},
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def override_deps():
    """Override FastAPI dependencies for all tests in this module."""
    mock_db = _mock_db()

    # Pattern 44: override get_current_org directly, not require_permission
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: mock_db

    yield mock_db

    # Pattern 32: pop overrides, never clear()
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


def _mock_db():
    db = MagicMock()
    # Default chain returns empty data
    chain = db.table.return_value
    chain.select.return_value    = chain
    chain.eq.return_value        = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value    = chain
    chain.insert.return_value    = chain
    chain.execute.return_value   = MagicMock(data=[])
    return db


client = TestClient(app)

# ---------------------------------------------------------------------------
# GET /admin/pipeline-stages
# ---------------------------------------------------------------------------

class TestGetPipelineStages:

    def test_returns_stored_config(self, override_deps):
        mock_db = override_deps
        result_mock = MagicMock()
        result_mock.data = {"pipeline_stages": VALID_STAGES}
        (mock_db.table.return_value
                .select.return_value
                .eq.return_value
                .maybe_single.return_value
                .execute.return_value) = result_mock

        r = client.get("/api/v1/admin/pipeline-stages")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert len(body["data"]["stages"]) == 5
        assert body["data"]["stages"][0]["key"] == "new"

    def test_returns_defaults_when_null(self, override_deps):
        mock_db = override_deps
        result_mock = MagicMock()
        result_mock.data = {"pipeline_stages": None}
        (mock_db.table.return_value
                .select.return_value
                .eq.return_value
                .maybe_single.return_value
                .execute.return_value) = result_mock

        r = client.get("/api/v1/admin/pipeline-stages")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        # Should return default 5 stages
        keys = [s["key"] for s in body["data"]["stages"]]
        assert "new" in keys
        assert "converted" in keys


# ---------------------------------------------------------------------------
# PATCH /admin/pipeline-stages
# ---------------------------------------------------------------------------

class TestUpdatePipelineStages:

    def test_saves_valid_config(self, override_deps):
        mock_db = override_deps
        update_result = MagicMock()
        update_result.data = [{"pipeline_stages": VALID_STAGES}]
        (mock_db.table.return_value
                .update.return_value
                .eq.return_value
                .execute.return_value) = update_result
        # audit log insert
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": VALID_STAGES},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert len(body["data"]["stages"]) == 5

    def test_rejects_unknown_stage_key(self, override_deps):
        bad_stages = [
            {"key": "new",        "label": "New",       "enabled": True},
            {"key": "fake_stage", "label": "Fake",      "enabled": True},  # invalid
            {"key": "converted",  "label": "Converted", "enabled": True},
        ]
        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": bad_stages},
        )
        assert r.status_code == 422

    def test_rejects_label_longer_than_50_chars(self, override_deps):
        long_label_stages = [
            {"key": "new",           "label": "A" * 51,       "enabled": True},
            {"key": "contacted",     "label": "Contacted",    "enabled": True},
            {"key": "meeting_done",  "label": "Demo Done",    "enabled": True},
            {"key": "proposal_sent", "label": "Proposal",     "enabled": True},
            {"key": "converted",     "label": "Converted",    "enabled": True},
        ]
        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": long_label_stages},
        )
        assert r.status_code == 422

    def test_rejects_fewer_than_2_enabled(self, override_deps):
        only_one_enabled = [
            {"key": "new",           "label": "New",          "enabled": True},
            {"key": "contacted",     "label": "Contacted",    "enabled": False},
            {"key": "meeting_done",  "label": "Demo Done",    "enabled": False},
            {"key": "proposal_sent", "label": "Proposal",     "enabled": False},
            {"key": "converted",     "label": "Converted",    "enabled": False},
        ]
        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": only_one_enabled},
        )
        assert r.status_code == 422

    def test_rejects_empty_label(self, override_deps):
        bad_stages = [
            {"key": "new",           "label": "",          "enabled": True},
            {"key": "contacted",     "label": "Contacted", "enabled": True},
            {"key": "meeting_done",  "label": "Demo Done", "enabled": True},
            {"key": "proposal_sent", "label": "Proposal",  "enabled": True},
            {"key": "converted",     "label": "Converted", "enabled": True},
        ]
        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": bad_stages},
        )
        assert r.status_code == 422

    def test_disabled_middle_stage_accepted(self, override_deps):
        """Disabling meeting_done is a valid config — new + converted still enabled."""
        mock_db = override_deps
        update_result = MagicMock()
        update_result.data = [{}]
        (mock_db.table.return_value
                .update.return_value
                .eq.return_value
                .execute.return_value) = update_result
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        stages_no_meeting = [
            {"key": "new",           "label": "New Lead",      "enabled": True},
            {"key": "contacted",     "label": "Contacted",     "enabled": True},
            {"key": "meeting_done",  "label": "Demo Done",     "enabled": False},
            {"key": "proposal_sent", "label": "Proposal Sent", "enabled": True},
            {"key": "converted",     "label": "Converted",     "enabled": True},
        ]
        r = client.patch(
            "/api/v1/admin/pipeline-stages",
            json={"stages": stages_no_meeting},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
