"""
tests/integration/test_catalog_routes.py

Integration tests for CATALOG-2A authenticated catalog admin routes.
All routes under /api/v1/catalog — owner/ops_manager only.

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 28 : get_current_org overridden for auth
  - Pattern 32 : pop() teardown
  - Pattern 63 : patch() targets the router module (lazy import resolution)
  - T1–T4      : prevention rules applied
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
ITEM_ID = "00000000-0000-0000-0000-000000000020"

_CURRENT_ORG_OWNER = {"id": ORG_ID, "role": "owner",       "name": "Royal Rest"}
_CURRENT_ORG_OPS   = {"id": ORG_ID, "role": "ops_manager", "name": "Royal Rest"}
_CURRENT_ORG_REP   = {"id": ORG_ID, "role": "sales_rep",   "name": "Royal Rest"}

_CATALOG_CONFIG = {
    "catalog_item_label":        "Mattress",
    "catalog_item_label_plural": "Mattresses",
    "price_label_template":      "₦{price}",
    "price_on_request":          False,
    "external_sync":             "shopify",
    "cta_buttons": [
        {"id": "showroom_visit", "label": "🏪 Visit Showroom"},
        {"id": "get_invoice",    "label": "💳 Get Invoice"},
    ],
    "tag_dimensions": [],
}

_CONFIG_NON_SHOPIFY = {**_CATALOG_CONFIG, "external_sync": "none"}

_ITEM_ROW = {
    "id":              ITEM_ID,
    "org_id":          ORG_ID,
    "title":           "Premium Mattress",
    "slug":            "premium-mattress",
    "catalog_images":  ["https://storage/img1.jpg", "https://storage/img2.jpg"],
    "catalog_visible": True,
    "available":       True,
    "catalog_views":   12,
    "inventory_count": 30,
    "tags":            {},
    "custom_fields":   {},
    "created_at":      "2026-05-01T10:00:00Z",
    "updated_at":      "2026-05-20T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(data=None):
    chain = MagicMock()
    result = MagicMock()
    result.data = data if data is not None else []
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "maybe_single", "insert",
              "update", "order", "limit", "neq", "in_"):
        getattr(chain, m).return_value = chain
    return chain


def _make_db():
    db = MagicMock()
    db.table.return_value = _chain()
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_owner():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    db = _make_db()
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _CURRENT_ORG_OWNER
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.pop(get_supabase,    None)
    app.dependency_overrides.pop(get_current_org, None)


@pytest.fixture
def client_ops():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    db = _make_db()
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _CURRENT_ORG_OPS
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.pop(get_supabase,    None)
    app.dependency_overrides.pop(get_current_org, None)


@pytest.fixture
def client_rep():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    db = _make_db()
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _CURRENT_ORG_REP
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.pop(get_supabase,    None)
    app.dependency_overrides.pop(get_current_org, None)


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/config
# ---------------------------------------------------------------------------

class TestGetConfig:

    def test_owner_gets_config(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG):
            resp = tc.get("/api/v1/catalog/config")
        assert resp.status_code == 200
        assert resp.json()["catalog_config"]["catalog_item_label"] == "Mattress"

    def test_ops_manager_gets_config(self, client_ops):
        tc, _ = client_ops
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG):
            resp = tc.get("/api/v1/catalog/config")
        assert resp.status_code == 200

    def test_sales_rep_gets_403(self, client_rep):
        tc, _ = client_rep
        resp = tc.get("/api/v1/catalog/config")
        assert resp.status_code == 403

    def test_empty_config_returns_200(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value={}):
            resp = tc.get("/api/v1/catalog/config")
        assert resp.status_code == 200
        assert resp.json()["catalog_config"] == {}


# ---------------------------------------------------------------------------
# PATCH /api/v1/catalog/config
# ---------------------------------------------------------------------------

class TestPatchConfig:

    _VALID_BODY = {
        "catalog_item_label":        "Product",
        "catalog_item_label_plural": "Products",
        "price_on_request":          False,
        "cta_buttons": [
            {"id": "showroom_visit", "label": "Visit Showroom"},
            {"id": "get_invoice",    "label": "Get Invoice"},
        ],
    }

    def test_valid_update_returns_200(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.update_catalog_config", return_value=_CATALOG_CONFIG):
            resp = tc.patch("/api/v1/catalog/config", json=self._VALID_BODY)
        assert resp.status_code == 200

    def test_invalid_button_id_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "cta_buttons": [
            {"id": "bad id!", "label": "Bad"},
            {"id": "ok_id",   "label": "OK"},
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_too_many_buttons_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "cta_buttons": [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
            {"id": "c", "label": "C"},
            {"id": "d", "label": "D"},  # 4 buttons — exceeds max of 3
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_too_few_buttons_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "cta_buttons": [
            {"id": "only_one", "label": "Only One"},
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_button_label_exceeds_24_chars_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "cta_buttons": [
            {"id": "btn_a", "label": "A" * 25},  # 25 chars — over limit
            {"id": "btn_b", "label": "OK"},
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_invalid_tag_dimension_key_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "tag_dimensions": [
            {"key": "bad key!", "label": "Bad", "type": "single_select", "options": ["A"]},
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_invalid_tag_dimension_type_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "tag_dimensions": [
            {"key": "health", "label": "Health", "type": "invalid_type", "options": ["A"]},
        ]}
        resp = tc.patch("/api/v1/catalog/config", json=body)
        assert resp.status_code == 422

    def test_sales_rep_gets_403(self, client_rep):
        tc, _ = client_rep
        resp = tc.patch("/api/v1/catalog/config", json=self._VALID_BODY)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/items
# ---------------------------------------------------------------------------

class TestListItems:

    def test_returns_items_list(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_items", return_value=[_ITEM_ROW]):
            resp = tc.get("/api/v1/catalog/items")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["items"][0]["id"] == ITEM_ID

    def test_search_param_passed_to_service(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_items", return_value=[]) as mock_fn:
            tc.get("/api/v1/catalog/items?search=premium")
        _, kwargs = mock_fn.call_args
        assert kwargs.get("search") == "premium"

    def test_visible_only_param_passed(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_items", return_value=[]) as mock_fn:
            tc.get("/api/v1/catalog/items?visible_only=true")
        _, kwargs = mock_fn.call_args
        assert kwargs.get("visible_only") is True

    def test_sales_rep_gets_403(self, client_rep):
        tc, _ = client_rep
        resp = tc.get("/api/v1/catalog/items")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/catalog/items
# ---------------------------------------------------------------------------

class TestCreateItem:

    _VALID_BODY = {"title": "New Pillow", "price": 5000.0}

    def test_non_shopify_org_creates_item(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CONFIG_NON_SHOPIFY), \
             patch("app.routers.catalog.create_catalog_item", return_value={**_ITEM_ROW, "title": "New Pillow"}):
            resp = tc.post("/api/v1/catalog/items", json=self._VALID_BODY)
        assert resp.status_code == 201

    def test_shopify_org_gets_403(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG):
            resp = tc.post("/api/v1/catalog/items", json=self._VALID_BODY)
        assert resp.status_code == 403

    def test_missing_title_returns_422(self, client_owner):
        tc, _ = client_owner
        resp = tc.post("/api/v1/catalog/items", json={"price": 5000.0})
        assert resp.status_code == 422

    def test_description_over_5000_chars_returns_422(self, client_owner):
        tc, _ = client_owner
        body = {**self._VALID_BODY, "description": "x" * 5001}
        resp = tc.post("/api/v1/catalog/items", json=body)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/items/{item_id}/stats
# ---------------------------------------------------------------------------

class TestGetItemStats:

    def test_returns_stats_for_existing_item(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.get(f"/api/v1/catalog/items/{ITEM_ID}/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["catalog_views"] == 12
        assert "created_at" in body
        assert "updated_at" in body

    def test_returns_404_for_unknown_item(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=None):
            resp = tc.get(f"/api/v1/catalog/items/{ITEM_ID}/stats")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/catalog/items/{item_id}/images
# ---------------------------------------------------------------------------

class TestUploadImage:

    def test_valid_jpeg_upload_returns_201(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW), \
             patch("app.routers.catalog.upload_catalog_image", return_value="https://storage/new.jpg"):
            resp = tc.post(
                f"/api/v1/catalog/items/{ITEM_ID}/images",
                files={"file": ("photo.jpg", b"fake jpeg bytes", "image/jpeg")},
            )
        assert resp.status_code == 201
        assert resp.json()["url"] == "https://storage/new.jpg"

    def test_invalid_mime_type_returns_400(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.post(
                f"/api/v1/catalog/items/{ITEM_ID}/images",
                files={"file": ("doc.pdf", b"pdf bytes", "application/pdf")},
            )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_oversized_file_returns_400(self, client_owner):
        tc, _ = client_owner
        big_bytes = b"x" * (5 * 1024 * 1024 + 1)  # 5MB + 1 byte
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.post(
                f"/api/v1/catalog/items/{ITEM_ID}/images",
                files={"file": ("big.jpg", big_bytes, "image/jpeg")},
            )
        assert resp.status_code == 400
        assert "5 MB" in resp.json()["detail"]

    def test_item_not_found_returns_404(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=None):
            resp = tc.post(
                f"/api/v1/catalog/items/{ITEM_ID}/images",
                files={"file": ("photo.png", b"png bytes", "image/png")},
            )
        assert resp.status_code == 404

    def test_webp_allowed(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW), \
             patch("app.routers.catalog.upload_catalog_image", return_value="https://storage/img.webp"):
            resp = tc.post(
                f"/api/v1/catalog/items/{ITEM_ID}/images",
                files={"file": ("img.webp", b"webp bytes", "image/webp")},
            )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# DELETE /api/v1/catalog/items/{item_id}/images/{image_index}
# ---------------------------------------------------------------------------

class TestDeleteImage:

    def test_valid_delete_returns_204(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.delete_catalog_image", return_value=None):
            resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}/images/0")
        assert resp.status_code == 204

    def test_invalid_index_returns_400(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.delete_catalog_image",
                   side_effect=ValueError("Image index 99 is out of range")):
            resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}/images/99")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/catalog/items/{item_id}
# ---------------------------------------------------------------------------

class TestGetItem:

    def test_returns_item(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.get(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 200
        assert resp.json()["item"]["id"] == ITEM_ID

    def test_returns_404_when_not_found(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_item", return_value=None):
            resp = tc.get(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 404

    def test_sales_rep_gets_403(self, client_rep):
        tc, _ = client_rep
        resp = tc.get(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/catalog/items/{item_id}
# ---------------------------------------------------------------------------

class TestPatchItem:

    def test_valid_update_returns_200(self, client_owner):
        tc, _ = client_owner
        updated = {**_ITEM_ROW, "catalog_visible": False}
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW), \
             patch("app.routers.catalog.update_catalog_item", return_value=updated):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"catalog_visible": False})
        assert resp.status_code == 200
        assert resp.json()["item"]["catalog_visible"] is False

    def test_slug_conflict_returns_409(self, client_owner):
        tc, _ = client_owner
        from app.services.catalog_service import SlugConflictError
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW), \
             patch("app.routers.catalog.update_catalog_item",
                   side_effect=SlugConflictError("Slug 'taken' is already in use.")):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"slug": "taken"})
        assert resp.status_code == 409

    def test_shopify_org_cannot_set_available(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"available": False})
        assert resp.status_code == 403

    def test_shopify_org_cannot_set_inventory_count(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"inventory_count": 10})
        assert resp.status_code == 403

    def test_non_shopify_can_set_available(self, client_owner):
        tc, _ = client_owner
        updated = {**_ITEM_ROW, "available": False}
        with patch("app.routers.catalog.get_catalog_config", return_value=_CONFIG_NON_SHOPIFY), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW), \
             patch("app.routers.catalog.update_catalog_item", return_value=updated):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"available": False})
        assert resp.status_code == 200

    def test_invalid_slug_format_returns_422(self, client_owner):
        tc, _ = client_owner
        resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}",
                        json={"slug": "Invalid Slug With Spaces!"})
        assert resp.status_code == 422

    def test_empty_body_returns_400(self, client_owner):
        tc, _ = client_owner
        resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={})
        assert resp.status_code == 400

    def test_item_not_found_returns_404(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG), \
             patch("app.routers.catalog.get_catalog_item", return_value=None):
            resp = tc.patch(f"/api/v1/catalog/items/{ITEM_ID}", json={"catalog_visible": True})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/catalog/items/{item_id}
# ---------------------------------------------------------------------------

class TestDeleteItem:

    def test_non_shopify_soft_deletes_item(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CONFIG_NON_SHOPIFY), \
             patch("app.routers.catalog.get_catalog_item", return_value=_ITEM_ROW):
            resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 204

    def test_shopify_org_gets_403(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CATALOG_CONFIG):
            resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 403

    def test_item_not_found_returns_404(self, client_owner):
        tc, _ = client_owner
        with patch("app.routers.catalog.get_catalog_config", return_value=_CONFIG_NON_SHOPIFY), \
             patch("app.routers.catalog.get_catalog_item", return_value=None):
            resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 404

    def test_sales_rep_gets_403(self, client_rep):
        tc, _ = client_rep
        resp = tc.delete(f"/api/v1/catalog/items/{ITEM_ID}")
        assert resp.status_code == 403
