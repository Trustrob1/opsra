"""
tests/integration/test_public_catalog_routes.py
-------------------------------------------------
CATALOG-3A: Integration tests for public catalog routes.

Tests:
  - 404 on unknown org_slug
  - 404 on catalog_visible=False item
  - catalog_views incremented on single item fetch
  - tag filter returns only matching items
  - no auth header required (routes are truly public)
  - search returns matching items only
  - rate limit returns 429 after 60 requests
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_SLUG   = "royal-rest"
ITEM_SLUG  = "cloud-9-mattress"
ORG_ID     = "org-uuid-001"
ITEM_ID    = "item-uuid-001"

MOCK_ORG = {
    "id":           ORG_ID,
    "name":         "Royal Rest",
    "slug":                ORG_SLUG,
    "org_whatsapp_number": "2348012345678",
    "catalog_config": {
        "catalog_item_label":        "Mattress",
        "catalog_item_label_plural": "Mattresses",
        "price_label_template":      "₦{price}",
        "price_on_request":          False,
        "availability_labels":       {"available": "In Stock", "unavailable": "Out of Stock"},
        "cta_buttons":               [
            {"id": "get_invoice",    "label": "Get Invoice 🧾"},
            {"id": "visit_showroom", "label": "Visit Showroom 🏪"},
        ],
        "tag_dimensions": [
            {
                "key": "health_conditions", "label": "Health Benefits",
                "type": "multi_select", "filterable": True,
                "options": ["Back Pain", "Joint Pain", "None"],
            },
            {
                "key": "firmness", "label": "Firmness",
                "type": "single_select", "filterable": True,
                "options": ["Soft", "Medium", "Firm"],
            },
        ],
    },
}

MOCK_ITEM_VISIBLE = {
    "id":             ITEM_ID,
    "title":          "Cloud 9 Mattress",
    "slug":           ITEM_SLUG,
    "description":    "Premium orthopaedic mattress.",
    "price":          150000.0,
    "catalog_images": ["https://cdn.example.com/img1.jpg"],
    "tags":           {"health_conditions": ["Back Pain", "Joint Pain"], "firmness": "Medium"},
    "custom_fields":  {"thickness_cm": "30"},
    "available":      True,
    "catalog_views":  5,
}

MOCK_ITEM_HIDDEN = {
    **MOCK_ITEM_VISIBLE,
    "id":            "item-uuid-002",
    "slug":          "hidden-mattress",
    "catalog_visible": False,
}


def _make_db_mock(org_rows=None, item_rows=None, views_rows=None):
    """Build a Supabase mock that returns configured rows."""
    db = MagicMock()

    def _chain(rows):
        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.is_.return_value = q
        q.execute.return_value = MagicMock(data=rows)
        return q

    # organisations query
    org_chain = _chain(org_rows if org_rows is not None else [MOCK_ORG])
    # products query (list or single)
    item_chain = _chain(item_rows if item_rows is not None else [MOCK_ITEM_VISIBLE])
    # views query
    views_chain = _chain(views_rows if views_rows is not None else [{"catalog_views": 5}])

    call_count = [0]

    def _table_router(table_name):
        if table_name == "organisations":
            return org_chain
        if table_name == "products":
            call_count[0] += 1
            # First products call = fetch item(s); second = views read
            if call_count[0] == 2:
                return views_chain
            return item_chain
        return MagicMock()

    db.table.side_effect = _table_router
    return db


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from app.main import app
    # Clear in-process caches between tests
    from app.routers import public_catalog
    public_catalog._list_cache.clear()
    public_catalog._item_cache.clear()
    public_catalog._rate_store.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Test: 404 on unknown org_slug
# ---------------------------------------------------------------------------

def test_list_catalog_unknown_org_slug(client):
    db_mock = _make_db_mock(org_rows=[])  # org not found

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get("/api/v1/public/catalog/nonexistent-org")

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_get_item_unknown_org_slug(client):
    db_mock = _make_db_mock(org_rows=[])

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/nonexistent-org/{ITEM_SLUG}")

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test: 404 on catalog_visible=False item
# ---------------------------------------------------------------------------

def test_get_item_hidden_returns_404(client):
    # products query returns empty (catalog_visible=False filtered at DB level)
    db_mock = _make_db_mock(item_rows=[])

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/hidden-mattress")

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: catalog_views incremented on single item fetch
# ---------------------------------------------------------------------------

def test_get_item_increments_catalog_views(client):
    update_mock = MagicMock()
    db_main = _make_db_mock()

    # Separate db mock for the fire-and-forget increment
    db_increment = MagicMock()
    views_chain = MagicMock()
    views_chain.select.return_value = views_chain
    views_chain.eq.return_value = views_chain
    views_chain.execute.return_value = MagicMock(data=[{"catalog_views": 5}])

    update_chain = MagicMock()
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[])

    db_increment.table.return_value.select.return_value = views_chain
    db_increment.table.return_value.update.return_value = update_chain

    with patch("app.routers.public_catalog.get_supabase", side_effect=[db_main, db_increment]):
        with patch("app.routers.public_catalog._increment_catalog_views", new_callable=AsyncMock) as mock_incr:
            r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/{ITEM_SLUG}")

    assert r.status_code == 200
    mock_incr.assert_called_once_with(ORG_ID, ITEM_ID)


# ---------------------------------------------------------------------------
# Test: tag filter returns only matching items
# ---------------------------------------------------------------------------

def test_list_catalog_tag_filter_single_select(client):
    items = [
        {**MOCK_ITEM_VISIBLE, "id": "a", "slug": "firm-mattress",
         "tags": {"firmness": "Firm", "health_conditions": []}},
        {**MOCK_ITEM_VISIBLE, "id": "b", "slug": "soft-mattress",
         "tags": {"firmness": "Soft", "health_conditions": []}},
    ]
    db_mock = _make_db_mock(item_rows=items)

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}?firmness=Firm")

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["slug"] == "firm-mattress"


def test_list_catalog_tag_filter_multi_select(client):
    items = [
        {**MOCK_ITEM_VISIBLE, "id": "a", "slug": "back-pain",
         "tags": {"health_conditions": ["Back Pain"], "firmness": "Medium"}},
        {**MOCK_ITEM_VISIBLE, "id": "b", "slug": "no-conditions",
         "tags": {"health_conditions": [], "firmness": "Soft"}},
    ]
    db_mock = _make_db_mock(item_rows=items)

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}?health_conditions=Back+Pain")

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["slug"] == "back-pain"


# ---------------------------------------------------------------------------
# Test: no auth header required
# ---------------------------------------------------------------------------

def test_list_catalog_no_auth_header_required(client):
    db_mock = _make_db_mock()

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        # Deliberately no Authorization header
        r = client.get(
            f"/api/v1/public/catalog/{ORG_SLUG}",
            headers={},  # empty — no auth
        )

    assert r.status_code == 200


def test_get_item_no_auth_header_required(client):
    db_mock = _make_db_mock()

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        with patch("app.routers.public_catalog._increment_catalog_views", new_callable=AsyncMock):
            r = client.get(
                f"/api/v1/public/catalog/{ORG_SLUG}/{ITEM_SLUG}",
                headers={},
            )

    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Test: search returns matching items only
# ---------------------------------------------------------------------------

def test_search_catalog_title_match(client):
    items = [
        {**MOCK_ITEM_VISIBLE, "id": "a", "title": "Cloud 9 Mattress",    "description": "Premium."},
        {**MOCK_ITEM_VISIBLE, "id": "b", "title": "Budget Foam Mattress", "description": "Affordable."},
    ]
    db_mock = _make_db_mock(item_rows=items)

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/search?q=cloud")

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert "Cloud" in data["items"][0]["title"]


def test_search_catalog_description_match(client):
    items = [
        {**MOCK_ITEM_VISIBLE, "id": "a", "title": "Mattress A", "description": "great for orthopaedic support"},
        {**MOCK_ITEM_VISIBLE, "id": "b", "title": "Mattress B", "description": "standard foam"},
    ]
    db_mock = _make_db_mock(item_rows=items)

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/search?q=orthopaedic")

    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_search_catalog_no_match(client):
    db_mock = _make_db_mock(item_rows=[MOCK_ITEM_VISIBLE])

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/search?q=xyzzy")

    assert r.status_code == 200
    assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# Test: rate limit returns 429 after 60 requests
# ---------------------------------------------------------------------------

def test_rate_limit_triggers_after_60_requests(client):
    from app.routers import public_catalog

    # Pre-fill rate store with 60 entries for a fake IP
    now = __import__("time").monotonic()
    public_catalog._rate_store["testclient"] = [now] * 60

    db_mock = _make_db_mock()
    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}")

    assert r.status_code == 429
    assert "Retry-After" in r.headers


# ---------------------------------------------------------------------------
# Test: response never contains internal fields
# ---------------------------------------------------------------------------

def test_list_catalog_response_excludes_internal_fields(client):
    db_mock = _make_db_mock()

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}")

    assert r.status_code == 200
    data = r.json()
    # org_id must never appear in response body
    assert "org_id" not in data
    # external_sync must not leak
    config = data.get("catalog_config", {})
    assert "external_sync" not in config


def test_get_item_response_excludes_internal_fields(client):
    db_mock = _make_db_mock()

    with patch("app.routers.public_catalog.get_supabase", return_value=db_mock):
        with patch("app.routers.public_catalog._increment_catalog_views", new_callable=AsyncMock):
            r = client.get(f"/api/v1/public/catalog/{ORG_SLUG}/{ITEM_SLUG}")

    assert r.status_code == 200
    data = r.json()
    assert "org_id" not in data
    assert "external_sync" not in data.get("catalog_config", {})
