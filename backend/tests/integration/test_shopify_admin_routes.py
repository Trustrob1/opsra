"""
tests/integration/test_shopify_admin_routes.py
SHOP-1A — admin route integration tests (6 tests)
Pattern 32: class-based autouse fixture, dependency_overrides pop teardown.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org


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


def _mock_db(org_data=None, product_count=0):
    db = MagicMock()

    def _chain(data=None, count=0):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.update.return_value = m
        m.maybe_single.return_value = m
        m.execute.return_value = MagicMock(data=data or {}, count=count)
        return m

    def table_side_effect(t):
        if t == "organisations":
            return _chain(org_data)
        if t == "products":
            return _chain([], count=product_count)
        return _chain()

    db.table.side_effect = table_side_effect
    return db


_CONNECTED_ORG = {
    "shopify_connected":      True,
    "shopify_shop_domain":    "my-store.myshopify.com",
    "shopify_last_sync_at":   "2026-04-24T10:00:00Z",
    "shopify_access_token":   "shpat_test",
    "shopify_webhook_secret": "secret",
}

_DISCONNECTED_ORG = {
    "shopify_connected":   False,
    "shopify_shop_domain": None,
    "shopify_last_sync_at": None,
}


class TestShopifyAdminRoutes:
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

    def test_get_status_not_connected(self):
        self._override(db=_mock_db(_DISCONNECTED_ORG), org=_owner_org())
        r = self.client.get("/api/v1/admin/shopify/status")
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is False

    def test_get_status_connected_with_product_count(self):
        self._override(db=_mock_db(_CONNECTED_ORG, product_count=42), org=_owner_org())
        r = self.client.get("/api/v1/admin/shopify/status")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["connected"] is True
        assert data["shop_domain"] == "my-store.myshopify.com"

    def test_connect_saves_and_triggers_sync(self):
        self._override(db=_mock_db(_DISCONNECTED_ORG), org=_owner_org())
        with patch("app.routers.shopify._run_bulk_sync") as mock_sync:
            r = self.client.post(
                "/api/v1/admin/shopify/connect",
                json={
                    "shop_domain": "my-store.myshopify.com",
                    "access_token": "shpat_test123456789",
                },
            )
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is True

    def test_disconnect_clears_config(self):
        self._override(db=_mock_db(_CONNECTED_ORG), org=_owner_org())
        r = self.client.delete("/api/v1/admin/shopify/disconnect")
        assert r.status_code == 200
        assert r.json()["data"]["connected"] is False

    def test_sync_triggers_background_task(self):
        self._override(db=_mock_db(_CONNECTED_ORG), org=_owner_org())
        with patch("app.routers.shopify._run_bulk_sync"):
            r = self.client.post("/api/v1/admin/shopify/sync")
        assert r.status_code == 200
        assert r.json()["data"]["sync_started"] is True

    def test_non_owner_connect_returns_403(self):
        self._override(db=_mock_db(_DISCONNECTED_ORG), org=_staff_org())
        r = self.client.post(
            "/api/v1/admin/shopify/connect",
            json={
                "shop_domain": "my-store.myshopify.com",
                "access_token": "shpat_test123456789",
            },
        )
        assert r.status_code == 403
