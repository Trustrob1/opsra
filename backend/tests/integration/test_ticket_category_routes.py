"""
tests/integration/test_ticket_category_routes.py
CONFIG-1 — Dynamic Ticket/KB Category Configuration

Integration tests:
  - GET /admin/ticket-categories: returns stored config
  - GET /admin/ticket-categories: returns defaults when null
  - PATCH /admin/ticket-categories: saves valid config
  - PATCH /admin/ticket-categories: rejects duplicate keys
  - PATCH /admin/ticket-categories: rejects all-disabled
  - PATCH /admin/ticket-categories: rejects invalid key format
  - PATCH /admin/ticket-categories: rejects label > 80 chars
"""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Constants — valid UUIDs (Pattern 24)
# ---------------------------------------------------------------------------

ORG_ID  = "cccccccc-cccc-cccc-cccc-cccccccccccc"
USER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

# Pattern 58: permissions nested inside roles
# Pattern 61: user UUID at "id" not "user_id"
_ORG_PAYLOAD = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {
        "template": "owner",
        "permissions": {"manage_users": True},
    },
}

VALID_CATEGORIES = [
    {"key": "technical_bug",    "label": "Technical Bug",    "enabled": True},
    {"key": "billing",          "label": "Billing",          "enabled": True},
    {"key": "feature_question", "label": "Feature Question", "enabled": True},
    {"key": "onboarding_help",  "label": "Onboarding Help",  "enabled": True},
    {"key": "account_access",   "label": "Account Access",   "enabled": True},
    {"key": "hardware",         "label": "Hardware",         "enabled": True},
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def override_deps():
    mock_db = _mock_db()
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: mock_db
    yield mock_db
    # Pattern 32: pop overrides, never clear()
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


def _mock_db():
    db = MagicMock()
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
# GET /admin/ticket-categories
# ---------------------------------------------------------------------------

class TestGetTicketCategories:

    def test_returns_stored_config(self, override_deps):
        mock_db = override_deps
        result_mock = MagicMock()
        result_mock.data = {"ticket_categories": VALID_CATEGORIES}
        (mock_db.table.return_value
                .select.return_value
                .eq.return_value
                .maybe_single.return_value
                .execute.return_value) = result_mock

        r = client.get("/api/v1/admin/ticket-categories")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert len(body["data"]["categories"]) == 6
        assert body["data"]["categories"][0]["key"] == "technical_bug"

    def test_returns_defaults_when_null(self, override_deps):
        mock_db = override_deps
        result_mock = MagicMock()
        result_mock.data = {"ticket_categories": None}
        (mock_db.table.return_value
                .select.return_value
                .eq.return_value
                .maybe_single.return_value
                .execute.return_value) = result_mock

        r = client.get("/api/v1/admin/ticket-categories")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        keys = [c["key"] for c in body["data"]["categories"]]
        assert "technical_bug" in keys
        assert "billing" in keys


# ---------------------------------------------------------------------------
# PATCH /admin/ticket-categories
# ---------------------------------------------------------------------------

class TestUpdateTicketCategories:

    def test_saves_valid_config(self, override_deps):
        mock_db = override_deps
        update_result = MagicMock()
        update_result.data = [{"ticket_categories": VALID_CATEGORIES}]
        (mock_db.table.return_value
                .update.return_value
                .eq.return_value
                .execute.return_value) = update_result
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        r = client.patch(
            "/api/v1/admin/ticket-categories",
            json={"categories": VALID_CATEGORIES},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert len(r.json()["data"]["categories"]) == 6

    def test_rejects_duplicate_keys(self, override_deps):
        dupes = VALID_CATEGORIES[:2] + [
            {"key": "billing", "label": "Billing Duplicate", "enabled": True}
        ]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": dupes})
        assert r.status_code == 422

    def test_rejects_all_disabled(self, override_deps):
        all_off = [{"key": c["key"], "label": c["label"], "enabled": False} for c in VALID_CATEGORIES]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": all_off})
        assert r.status_code == 422

    def test_rejects_invalid_key_format(self, override_deps):
        bad = [{"key": "Bad Key!", "label": "Bad", "enabled": True}] + VALID_CATEGORIES[1:]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": bad})
        assert r.status_code == 422

    def test_rejects_label_over_80_chars(self, override_deps):
        long_label = [{"key": "technical_bug", "label": "A" * 81, "enabled": True}] + VALID_CATEGORIES[1:]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": long_label})
        assert r.status_code == 422

    def test_custom_category_accepted(self, override_deps):
        """Orgs can add their own categories beyond the defaults."""
        mock_db = override_deps
        update_result = MagicMock()
        update_result.data = [{}]
        (mock_db.table.return_value
                .update.return_value
                .eq.return_value
                .execute.return_value) = update_result
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        custom = VALID_CATEGORIES + [{"key": "integration_support", "label": "Integration Support", "enabled": True}]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": custom})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_disabled_default_accepted(self, override_deps):
        """Disabling a default category (hardware) is valid as long as one is still enabled."""
        mock_db = override_deps
        update_result = MagicMock()
        update_result.data = [{}]
        (mock_db.table.return_value
                .update.return_value
                .eq.return_value
                .execute.return_value) = update_result
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        partial = [
            {"key": "technical_bug",    "label": "Technical Bug",    "enabled": True},
            {"key": "billing",          "label": "Billing",          "enabled": True},
            {"key": "feature_question", "label": "Feature Question", "enabled": True},
            {"key": "onboarding_help",  "label": "Onboarding Help",  "enabled": True},
            {"key": "account_access",   "label": "Account Access",   "enabled": True},
            {"key": "hardware",         "label": "Hardware",         "enabled": False},
        ]
        r = client.patch("/api/v1/admin/ticket-categories", json={"categories": partial})
        assert r.status_code == 200
