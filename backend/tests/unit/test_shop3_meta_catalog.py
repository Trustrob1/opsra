"""
tests/unit/test_shop3_meta_catalog.py
SHOP-3 — Unit tests for:
  - sync_products_to_meta_catalog() in shopify_service.py
  - send_product_list() catalog path in whatsapp_service.py
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db(org_row=None, products=None):
    db = MagicMock()
    # organisations lookup
    org_result = MagicMock()
    org_result.data = org_row or {}
    (
        db.table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = org_result

    # products table lookup (chained differently)
    products_result = MagicMock()
    products_result.data = products or []
    return db, products_result


# ---------------------------------------------------------------------------
# sync_products_to_meta_catalog
# ---------------------------------------------------------------------------

class TestSyncProductsToMetaCatalog:

    def _db_with_products(self, org_row, products):
        """
        Build a mock db that returns org_row for .maybe_single() calls
        and products for .execute() on the products table chain.
        """
        db = MagicMock()

        call_count = {"n": 0}

        def execute_side_effect():
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                # First call = org lookup
                result.data = org_row
            else:
                # Second call = products fetch
                result.data = products
            return result

        (
            db.table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.side_effect
        ) = execute_side_effect

        (
            db.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute.side_effect
        ) = execute_side_effect

        return db

    def test_skips_when_no_catalog_id(self):
        from app.services.shopify_service import sync_products_to_meta_catalog
        db = MagicMock()
        org_result = MagicMock()
        org_result.data = {"meta_catalog_id": None, "whatsapp_access_token": "tok"}
        (
            db.table.return_value.select.return_value
            .eq.return_value.maybe_single.return_value
            .execute.return_value
        ) = org_result
        result = sync_products_to_meta_catalog(db, "org-1")
        assert result["skipped"] is True
        assert result["synced"] == 0

    def test_skips_when_catalog_id_empty_string(self):
        from app.services.shopify_service import sync_products_to_meta_catalog
        db = MagicMock()
        org_result = MagicMock()
        org_result.data = {"meta_catalog_id": "   ", "whatsapp_access_token": "tok"}
        (
            db.table.return_value.select.return_value
            .eq.return_value.maybe_single.return_value
            .execute.return_value
        ) = org_result
        result = sync_products_to_meta_catalog(db, "org-1")
        assert result["skipped"] is True

    def test_skips_when_no_access_token(self):
        from app.services.shopify_service import sync_products_to_meta_catalog
        db = MagicMock()
        org_result = MagicMock()
        org_result.data = {"meta_catalog_id": "123456789", "whatsapp_access_token": None}
        (
            db.table.return_value.select.return_value
            .eq.return_value.maybe_single.return_value
            .execute.return_value
        ) = org_result
        result = sync_products_to_meta_catalog(db, "org-1")
        assert result["skipped"] is True

    def test_returns_synced_count_on_success(self):
        from app.services.shopify_service import sync_products_to_meta_catalog

        org_row = {
            "meta_catalog_id": "9876543210",
            "whatsapp_access_token": "EAAtest",
            "shopify_shop_domain": "royal-rest.myshopify.com",
        }
        products = [
            {"id": "p1", "shopify_id": "111", "title": "Mattress A",
             "description": "<p>Comfy</p>", "price": 299.00,
             "image_url": "https://cdn.shopify.com/img.jpg",
             "handle": "mattress-a", "status": "active"},
            {"id": "p2", "shopify_id": "222", "title": "Mattress B",
             "description": None, "price": 149.00,
             "image_url": None, "handle": "mattress-b", "status": "active"},
        ]

        # Mock httpx response
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        db = MagicMock()
        call_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            r.data = org_row if call_n["n"] == 1 else products
            return r

        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = _exec
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = _exec

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = sync_products_to_meta_catalog(db, "org-1")

        assert result["synced"] == 2
        assert result["failed"] == 0
        assert result["skipped"] is False

    def test_per_product_failure_never_stops_loop(self):
        """S14: one product failing must not prevent others from syncing."""
        from app.services.shopify_service import sync_products_to_meta_catalog

        org_row = {
            "meta_catalog_id": "9876543210",
            "whatsapp_access_token": "EAAtest",
            "shopify_shop_domain": "royal-rest.myshopify.com",
        }
        products = [
            {"id": "p1", "shopify_id": "111", "title": "Good Product",
             "description": None, "price": 100.0,
             "image_url": None, "handle": "good", "status": "active"},
            {"id": "p2", "shopify_id": "222", "title": "Also Good",
             "description": None, "price": 200.0,
             "image_url": None, "handle": "also-good", "status": "active"},
        ]

        call_n = {"n": 0}
        post_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            r.data = org_row if call_n["n"] == 1 else products
            return r

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = _exec
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = _exec

        def _post(*args, **kwargs):
            post_n["n"] += 1
            if post_n["n"] == 1:
                raise RuntimeError("Network error on first product")
            r = MagicMock()
            r.status_code = 200
            return r

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = _post
            mock_client_cls.return_value = mock_client

            result = sync_products_to_meta_catalog(db, "org-1")

        assert result["synced"] == 1
        assert result["failed"] == 1
        assert result["skipped"] is False

    def test_meta_400_counts_as_failed_not_exception(self):
        from app.services.shopify_service import sync_products_to_meta_catalog

        org_row = {
            "meta_catalog_id": "9876543210",
            "whatsapp_access_token": "EAAtest",
            "shopify_shop_domain": "royal-rest.myshopify.com",
        }
        products = [
            {"id": "p1", "shopify_id": "111", "title": "Bad Product",
             "description": None, "price": 100.0,
             "image_url": None, "handle": "bad", "status": "active"},
        ]

        call_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            r.data = org_row if call_n["n"] == 1 else products
            return r

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = _exec
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = _exec

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = sync_products_to_meta_catalog(db, "org-1")

        assert result["synced"] == 0
        assert result["failed"] == 1

    def test_s14_outer_exception_never_raises(self):
        """Top-level S14: any unexpected crash returns a safe dict."""
        from app.services.shopify_service import sync_products_to_meta_catalog
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB is down")
        result = sync_products_to_meta_catalog(db, "org-1")
        assert isinstance(result, dict)
        assert "synced" in result

    def test_price_converted_to_cents(self):
        """Price 299.99 must be sent as '29999' (integer cents string)."""
        from app.services.shopify_service import sync_products_to_meta_catalog

        org_row = {
            "meta_catalog_id": "9876543210",
            "whatsapp_access_token": "EAAtest",
            "shopify_shop_domain": "royal-rest.myshopify.com",
        }
        products = [
            {"id": "p1", "shopify_id": "111", "title": "Expensive",
             "description": None, "price": 299.99,
             "image_url": None, "handle": "expensive", "status": "active"},
        ]

        call_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            r.data = org_row if call_n["n"] == 1 else products
            return r

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = _exec
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = _exec

        posted_payloads = []
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        def _post(url, json=None, headers=None):
            posted_payloads.append(json)
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = lambda s: mock_client
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = _post
            mock_client_cls.return_value = mock_client

            sync_products_to_meta_catalog(db, "org-1")

        assert len(posted_payloads) == 1
        assert posted_payloads[0]["price"] == "29999"
        assert posted_payloads[0]["currency"] == "NGN"
        assert posted_payloads[0]["retailer_id"] == "111"


# ---------------------------------------------------------------------------
# send_product_list — catalog path vs fallback path
# ---------------------------------------------------------------------------

class TestSendProductListShop3:

    def _make_db(self, catalog_id=None):
        db = MagicMock()
        # _get_org_wa_credentials call
        creds_result = MagicMock()
        creds_result.data = {
            "whatsapp_phone_id": "phone-123",
            "whatsapp_access_token": "EAAtest",
            "whatsapp_waba_id": None,
        }
        # catalog_id call
        cat_result = MagicMock()
        cat_result.data = {"meta_catalog_id": catalog_id}

        call_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            r.data = (
                creds_result.data if call_n["n"] == 1 else cat_result.data
            )
            return r

        (
            db.table.return_value.select.return_value
            .eq.return_value.maybe_single.return_value
            .execute.side_effect
        ) = _exec
        return db

    def _products(self, n=3):
        return [
            {
                "id": f"prod-{i}",
                "shopify_id": str(1000 + i),
                "title": f"Product {i}",
                "description": "<p>Description</p>",
                "price": float(100 * i),
                "tags": ["Beds"],
            }
            for i in range(1, n + 1)
        ]

    def test_uses_product_list_format_when_catalog_id_set(self):
        """When catalog_id is set, payload type must be product_list."""
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id="CATALOG123")
        sent_payloads = []

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.return_value = {"messages": [{"id": "wamid.test"}]}
            send_product_list(db, "org-1", "+2348012345678", self._products())

        mock_send.assert_called_once()
        payload = mock_send.call_args[0][1]
        assert payload["interactive"]["type"] == "product_list"
        assert "catalog_id" in payload["interactive"]["action"]
        assert payload["interactive"]["action"]["catalog_id"] == "CATALOG123"

    def test_product_list_sections_use_product_retailer_id(self):
        """product_items must use product_retailer_id matching shopify_id."""
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id="CATALOG123")

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.return_value = {}
            send_product_list(db, "org-1", "+2348012345678", self._products(2))

        payload = mock_send.call_args[0][1]
        sections = payload["interactive"]["action"]["sections"]
        assert len(sections) >= 1
        items = sections[0]["product_items"]
        assert all("product_retailer_id" in item for item in items)
        retailer_ids = [item["product_retailer_id"] for item in items]
        assert "1001" in retailer_ids
        assert "1002" in retailer_ids

    def test_falls_back_to_list_when_no_catalog_id(self):
        """Without catalog_id, payload type must be list (COMM-1 format)."""
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id=None)

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.return_value = {}
            send_product_list(db, "org-1", "+2348012345678", self._products())

        payload = mock_send.call_args[0][1]
        assert payload["interactive"]["type"] == "list"
        assert "sections" in payload["interactive"]["action"]
        # Rows must have id, title, description (text list format)
        rows = payload["interactive"]["action"]["sections"][0]["rows"]
        assert all("id" in r and "title" in r and "description" in r for r in rows)

    def test_s14_never_raises_on_catalog_path(self):
        """S14: _call_meta_send crashing must not propagate."""
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id="CATALOG123")

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.side_effect = RuntimeError("Meta API down")
            # Must not raise
            send_product_list(db, "org-1", "+2348012345678", self._products())

    def test_s14_never_raises_on_fallback_path(self):
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id=None)

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.side_effect = RuntimeError("Meta API down")
            send_product_list(db, "org-1", "+2348012345678", self._products())

    def test_empty_products_returns_early(self):
        from app.services.whatsapp_service import send_product_list

        db = self._make_db(catalog_id="CATALOG123")

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            send_product_list(db, "org-1", "+2348012345678", [])
            mock_send.assert_not_called()

    def test_catalog_id_lookup_failure_falls_back_gracefully(self):
        """If catalog_id DB lookup throws, must fall back to text list."""
        from app.services.whatsapp_service import send_product_list

        db = MagicMock()
        # creds succeed, catalog lookup throws
        call_n = {"n": 0}

        def _exec():
            call_n["n"] += 1
            r = MagicMock()
            if call_n["n"] == 1:
                r.data = {
                    "whatsapp_phone_id": "phone-123",
                    "whatsapp_access_token": "EAAtest",
                    "whatsapp_waba_id": None,
                }
                return r
            raise RuntimeError("Catalog lookup failed")

        (
            db.table.return_value.select.return_value
            .eq.return_value.maybe_single.return_value
            .execute.side_effect
        ) = _exec

        with patch("app.services.whatsapp_service._call_meta_send") as mock_send:
            mock_send.return_value = {}
            send_product_list(db, "org-1", "+2348012345678", self._products())

        # Should still send — using text list fallback
        mock_send.assert_called_once()
        payload = mock_send.call_args[0][1]
        assert payload["interactive"]["type"] == "list"
