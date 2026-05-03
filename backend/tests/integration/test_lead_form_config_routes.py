"""
tests/integration/test_lead_form_config_routes.py
Integration tests for LEAD-FORM-CONFIG routes.

Pattern 32: dependency overrides cleared in autouse fixture teardown.
Pattern 61: org["id"] not org["user_id"].
Pattern 62: db via Depends(get_supabase).
Pattern 63: patch paths derived from source imports.
"""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

USER_ID = "user-owner-001"
ORG_ID  = "org-test-001"

VALID_FIELDS = [
    {"key": "email",            "label": "Email Address",    "visible": True,  "required": False},
    {"key": "business_name",    "label": "Business Name",    "visible": True,  "required": False},
    {"key": "product_interest", "label": "Product Interest", "visible": True,  "required": True},
    {"key": "problem_stated",   "label": "Problem Stated",   "visible": False, "required": False},
]

def _org(role="owner"):
    return {
        "id":     USER_ID,
        "org_id": ORG_ID,
        "is_active": True,
        "roles":  {"template": role, "permissions": {}},
    }

def _make_db(saved_config=None):
    db = MagicMock()
    def table_side(name):
        tbl = MagicMock()
        sel = MagicMock()
        sel.eq.return_value           = sel
        sel.maybe_single.return_value = sel
        sel.execute.return_value.data = {"lead_form_config": saved_config}
        tbl.select.return_value = sel
        upd = MagicMock()
        upd.eq.return_value = upd
        upd.execute.return_value.data = [{}]
        tbl.update.return_value = upd
        ins = MagicMock()
        ins.execute.return_value.data = [{}]
        tbl.insert.return_value = ins
        return tbl
    db.table.side_effect = table_side
    return db

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()

def _client(role="owner", saved_config=None):
    db = _make_db(saved_config)
    app.dependency_overrides[get_current_org] = lambda: _org(role)
    app.dependency_overrides[get_supabase]    = lambda: db
    return TestClient(app), db


class TestGetLeadFormConfig:

    def test_get_returns_default_when_null(self):
        client, _ = _client(role="owner", saved_config=None)
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200
        fields = res.json()["data"]["fields"]
        assert len(fields) == 9

    def test_get_returns_saved_config(self):
        client, _ = _client(role="owner", saved_config=VALID_FIELDS)
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200
        fields = res.json()["data"]["fields"]
        assert len(fields) == 4
        assert fields[0]["key"] == "email"

    def test_ops_manager_can_get(self):
        client, _ = _client(role="ops_manager", saved_config=None)
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 200

    def test_sales_agent_gets_403(self):
        client, _ = _client(role="sales_agent", saved_config=None)
        res = client.get("/api/v1/admin/lead-form-config")
        assert res.status_code == 403


class TestPatchLeadFormConfig:

    def test_owner_can_save_valid_config(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": VALID_FIELDS})
        assert res.status_code == 200
        keys = [f["key"] for f in res.json()["data"]["fields"]]
        assert "email" in keys

    def test_ops_manager_gets_403_on_patch(self):
        client, _ = _client(role="ops_manager")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": VALID_FIELDS})
        assert res.status_code == 403

    def test_invalid_key_returns_422(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": [
            {"key": "birthday", "label": "Birthday", "visible": True, "required": False}
        ]})
        assert res.status_code == 422

    def test_hidden_required_combo_returns_422(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": [
            {"key": "email", "label": "Email", "visible": False, "required": True}
        ]})
        assert res.status_code == 422

    def test_label_over_50_chars_returns_422(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": [
            {"key": "email", "label": "A" * 51, "visible": True, "required": False}
        ]})
        assert res.status_code == 422

    def test_phone_and_full_name_silently_ignored(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": [
            {"key": "email",     "label": "Email",     "visible": True, "required": False},
            {"key": "phone",     "label": "Phone",     "visible": True, "required": True},
            {"key": "full_name", "label": "Full Name", "visible": True, "required": True},
        ]})
        assert res.status_code == 200
        saved_keys = [f["key"] for f in res.json()["data"]["fields"]]
        assert "phone"     not in saved_keys
        assert "full_name" not in saved_keys
        assert "email"     in saved_keys

    def test_product_interest_visible_required_is_valid(self):
        client, _ = _client(role="owner")
        res = client.patch("/api/v1/admin/lead-form-config", json={"fields": [
            {"key": "product_interest", "label": "Product Interest", "visible": True, "required": True},
        ]})
        assert res.status_code == 200
