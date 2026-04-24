"""
tests/integration/test_shopify_webhook_routes.py
SHOP-1A — webhook route integration tests (8 tests)
Pattern 32: class-based autouse fixture, dependency_overrides pop teardown.
"""
import base64
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.database import get_supabase


def _make_sig(body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()


def _mock_db(org_data=None):
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=org_data)
    db.table.return_value = chain
    return db


_ORG = {
    "id": "org-1",
    "shopify_webhook_secret": "test_secret",
    "shopify_connected": True,
}


class TestShopifyWebhookRoutes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        yield
        app.dependency_overrides.pop(get_supabase, None)

    def _override_db(self, org_data=None):
        db = _mock_db(org_data)
        app.dependency_overrides[get_supabase] = lambda: db
        return db

    def _headers(self, body: bytes, topic: str, shop: str, secret: str = "test_secret"):
        return {
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": shop,
            "X-Shopify-Hmac-Sha256": _make_sig(body, secret),
            "Content-Type": "application/json",
        }

    # ── Security ──────────────────────────────────────────────────────────────

    def test_invalid_hmac_returns_401(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 1}).encode()
        r = self.client.post(
            "/webhooks/shopify",
            content=body,
            headers={
                "X-Shopify-Topic": "products/update",
                "X-Shopify-Shop-Domain": "shop.myshopify.com",
                "X-Shopify-Hmac-Sha256": "bad_sig",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401

    def test_unknown_topic_returns_200(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 1}).encode()
        r = self.client.post(
            "/webhooks/shopify",
            content=body,
            headers=self._headers(body, "app/uninstalled", "shop.myshopify.com"),
        )
        assert r.status_code == 200

    def test_no_org_found_returns_200(self):
        self._override_db(None)
        body = json.dumps({"id": 1}).encode()
        r = self.client.post(
            "/webhooks/shopify",
            content=body,
            headers=self._headers(body, "products/update", "unknown.myshopify.com"),
        )
        assert r.status_code == 200

    # ── Topic routing ─────────────────────────────────────────────────────────

    def test_products_update_calls_sync(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 123, "title": "Test", "status": "active"}).encode()
        with patch("app.services.shopify_service.sync_product") as mock_sync:
            r = self.client.post(
                "/webhooks/shopify",
                content=body,
                headers=self._headers(body, "products/update", "shop.myshopify.com"),
            )
        assert r.status_code == 200
        mock_sync.assert_called_once()

    def test_products_delete_calls_handler(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 123}).encode()
        with patch("app.services.shopify_service.handle_product_deleted") as mock_del:
            r = self.client.post(
                "/webhooks/shopify",
                content=body,
                headers=self._headers(body, "products/delete", "shop.myshopify.com"),
            )
        assert r.status_code == 200
        mock_del.assert_called_once()

    def test_checkouts_update_calls_abandoned_cart(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 1001, "line_items": []}).encode()
        with patch("app.services.shopify_service.handle_abandoned_cart") as mock_cart:
            r = self.client.post(
                "/webhooks/shopify",
                content=body,
                headers=self._headers(body, "checkouts/update", "shop.myshopify.com"),
            )
        assert r.status_code == 200
        mock_cart.assert_called_once()

    def test_orders_create_calls_handler(self):
        self._override_db(_ORG)
        body = json.dumps({"id": 9001, "name": "#1001"}).encode()
        with patch("app.services.shopify_service.handle_order_created") as mock_order:
            r = self.client.post(
                "/webhooks/shopify",
                content=body,
                headers=self._headers(body, "orders/create", "shop.myshopify.com"),
            )
        assert r.status_code == 200
        mock_order.assert_called_once()

    def test_handler_exception_returns_200(self):
        """S14 — handler crash must never return 5xx to Shopify."""
        self._override_db(_ORG)
        body = json.dumps({"id": 1}).encode()
        with patch(
            "app.services.shopify_service.sync_product",
            side_effect=Exception("boom"),
        ):
            r = self.client.post(
                "/webhooks/shopify",
                content=body,
                headers=self._headers(body, "products/update", "shop.myshopify.com"),
            )
        assert r.status_code == 200
