"""
tests/integration/test_sales_mode_routes.py
SM-1: Sales Mode Engine — integration tests (8 tests)
Pattern 32: class-based autouse fixture, dependency_overrides pop teardown.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org


def _mock_db(sales_mode="consultative", triage_config=None):
    db = MagicMock()

    def _chain(data=None):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.maybe_single.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.execute.return_value = MagicMock(data=data or {})
        return m

    org_data = {
        "sales_mode": sales_mode,
        "whatsapp_triage_config": triage_config or {},
    }

    db.table.side_effect = lambda t: _chain(org_data if t == "organisations" else {})
    return db


def _owner_org():
    return {
        "id": "user-1",
        "org_id": "org-1",
        "roles": {"template": "owner"},
    }


def _staff_org():
    return {
        "id": "user-2",
        "org_id": "org-1",
        "roles": {"template": "sales_agent"},
    }


class TestSalesModeRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def _override(self, db=None, org=None):
        if db:
            app.dependency_overrides[get_supabase] = lambda: db
        if org:
            app.dependency_overrides[get_current_org] = lambda: org

    # ── GET /admin/sales-mode ─────────────────────────────────────────────

    def test_get_sales_mode_returns_current(self):
        self._override(db=_mock_db("hybrid"), org=_owner_org())
        r = self.client.get("/api/v1/admin/sales-mode")
        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "hybrid"

    # ── PATCH /admin/sales-mode ───────────────────────────────────────────

    def test_patch_sales_mode_valid(self):
        self._override(db=_mock_db(), org=_owner_org())
        r = self.client.patch("/api/v1/admin/sales-mode", json={"mode": "transactional"})
        assert r.status_code == 200
        assert r.json()["data"]["mode"] == "transactional"

    def test_patch_sales_mode_invalid_422(self):
        self._override(db=_mock_db(), org=_owner_org())
        r = self.client.patch("/api/v1/admin/sales-mode", json={"mode": "invalid_mode"})
        assert r.status_code == 422

    def test_patch_sales_mode_non_owner_403(self):
        self._override(db=_mock_db(), org=_staff_org())
        r = self.client.patch("/api/v1/admin/sales-mode", json={"mode": "hybrid"})
        assert r.status_code == 403

    def test_patch_sales_mode_ops_manager_allowed(self):
        ops_org = {**_owner_org(), "roles": {"template": "ops_manager"}}
        self._override(db=_mock_db(), org=ops_org)
        r = self.client.patch("/api/v1/admin/sales-mode", json={"mode": "consultative"})
        assert r.status_code == 200

    # ── GET /admin/contact-menus ──────────────────────────────────────────

    def test_get_contact_menus_returns_both(self):
        triage = {
            "returning_contact_menu": {"items": [{"id": "rc_1", "label": "Buy", "description": "", "action": "qualify"}]},
            "known_customer_menu":    {"items": [{"id": "kc_1", "label": "Help", "description": "", "action": "support_ticket"}]},
        }
        self._override(db=_mock_db(triage_config=triage), org=_owner_org())
        r = self.client.get("/api/v1/admin/contact-menus")
        assert r.status_code == 200
        data = r.json()["data"]
        assert "returning_contact_menu" in data
        assert "known_customer_menu" in data

    # ── PATCH /admin/contact-menus ────────────────────────────────────────

    def test_patch_contact_menus_valid(self):
        self._override(db=_mock_db(), org=_owner_org())
        payload = {
            "returning_contact_menu": {
                "greeting": "Hi!",
                "section_title": "Options",
                "items": [{"id": "rc_1", "label": "Ready to buy", "description": "", "action": "qualify"}],
            }
        }
        r = self.client.patch("/api/v1/admin/contact-menus", json=payload)
        assert r.status_code == 200

    def test_patch_contact_menus_label_too_long_422(self):
        self._override(db=_mock_db(), org=_owner_org())
        payload = {
            "returning_contact_menu": {
                "items": [{"id": "rc_1", "label": "X" * 25, "description": "", "action": "qualify"}],
            }
        }
        r = self.client.patch("/api/v1/admin/contact-menus", json=payload)
        assert r.status_code == 422
