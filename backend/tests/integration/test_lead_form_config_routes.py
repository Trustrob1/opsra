"""
tests/integration/test_lead_form_config_routes.py
Integration tests for LEAD-FORM-CONFIG routes.

Tests:
  - GET returns default config for new org (lead_form_config is null)
  - GET returns saved config after PATCH
  - PATCH saves valid config — owner succeeds
  - PATCH — ops_manager GET succeeds, PATCH → 403
  - PATCH: invalid key → 422
  - PATCH: hidden+required combo → 422

Pattern T1: mock signatures verified before patching.
Pattern T2: no mixed side_effect + return_value.
Pattern 61: org["id"] not org["user_id"].
Pattern 62: db via Depends(get_supabase).
Pattern 63: patch paths derived from source imports.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

USER_ID  = "user-owner-001"
ORG_ID   = "org-test-001"

_OWNER_ORG = {
    "id":       USER_ID,
    "org_id":   ORG_ID,
    "is_active": True,
    "roles": {"template": "owner", "permissions": {}},
}

_OPS_ORG = {
    "id":       "user-ops-001",
    "org_id":   ORG_ID,
    "is_active": True,
    "roles": {"template": "ops_manager", "permissions": {}},
}

_SALES_ORG = {
    "id":       "user-sales-001",
    "org_id":   ORG_ID,
    "is_active": True,
    "roles": {"template": "sales_agent", "permissions": {}},
}

VALID_FIELDS = [
    {"key": "email",            "label": "Email Address",    "visible": True,  "required": False},
    {"key": "business_name",    "label": "Business Name",    "visible": True,  "required": False},
    {"key": "product_interest", "label": "Product Interest", "visible": True,  "required": True},
    {"key": "problem_stated",   "label": "Problem Stated",   "visible": False, "required": False},
]


def _make_app(org_payload):
    from main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    db = MagicMock()

    # GET: return null config (default scenario)
    null_result        = MagicMock()
    null_result.data   = {"lead_form_config": None}

    # GET: return saved config scenario — toggled per test via db._saved_config
    db._saved_config   = None

    def _select_org(*args, **kwargs):
        mock = MagicMock()
        mock.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "lead_form_config": db._saved_config
        }
        return mock

    db.table.return_value.select = _select_org
    db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    db.table.return_value.insert.return_value.execute.return_value.data = [{}]

    app.dependency_overrides[get_current_org] = lambda: org_payload
    app.dependency_overrides[get_supabase]    = lambda: db

    return TestClient(app), db


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    from main import app
    app.dependency_overrides.clear()


class TestGetLeadFormConfig:
    def test_get_returns_default_when_null(self):
        client, db = _make_app(_OWNER_ORG)
        db._saved_config = None
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200
        data = res.json()["data"]
        assert "fields" in data
        # Default has 9 fields
        assert len(data["fields"]) == 9

    def test_get_returns_saved_config(self):
        client, db = _make_app(_OWNER_ORG)
        db._saved_config = VALID_FIELDS
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200
        fields = res.json()["data"]["fields"]
        assert len(fields) == 4
        assert fields[0]["key"] == "email"

    def test_ops_manager_can_get(self):
        client, db = _make_app(_OPS_ORG)
        db._saved_config = None
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200

    def test_sales_agent_gets_403(self):
        client, db = _make_app(_SALES_ORG)
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 403


class TestPatchLeadFormConfig:
    def test_owner_can_save_valid_config(self):
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": VALID_FIELDS},
        )
        assert res.status_code == 200
        fields = res.json()["data"]["fields"]
        # phone/full_name filtered — only the 4 valid configurable fields
        assert len(fields) == 4

    def test_ops_manager_gets_403_on_patch(self):
        client, db = _make_app(_OPS_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": VALID_FIELDS},
        )
        assert res.status_code == 403

    def test_invalid_key_returns_422(self):
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": [{"key": "birthday", "label": "Birthday", "visible": True, "required": False}]},
        )
        assert res.status_code == 422

    def test_hidden_required_combo_returns_422(self):
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": [{"key": "email", "label": "Email", "visible": False, "required": True}]},
        )
        assert res.status_code == 422

    def test_label_over_50_chars_returns_422(self):
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": [{"key": "email", "label": "A" * 51, "visible": True, "required": False}]},
        )
        assert res.status_code == 422

    def test_phone_and_full_name_silently_ignored(self):
        """phone + full_name keys are filtered out — saved fields exclude them."""
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": [
                {"key": "email",     "label": "Email",     "visible": True, "required": False},
                {"key": "phone",     "label": "Phone",     "visible": True, "required": True},
                {"key": "full_name", "label": "Full Name", "visible": True, "required": True},
            ]},
        )
        assert res.status_code == 200
        saved_keys = [f["key"] for f in res.json()["data"]["fields"]]
        assert "phone"     not in saved_keys
        assert "full_name" not in saved_keys
        assert "email"     in saved_keys

    def test_product_interest_visible_required_is_valid(self):
        """product_interest can be required when visible=True."""
        client, db = _make_app(_OWNER_ORG)
        res = client.patch(
            "/api/v1/admin/lead-form-config",
            json={"fields": [
                {"key": "product_interest", "label": "Product Interest", "visible": True, "required": True},
            ]},
        )
        assert res.status_code == 200
