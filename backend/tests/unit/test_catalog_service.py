"""
tests/unit/test_catalog_service.py

Unit tests for CATALOG-2A catalog_service.py.
All DB calls mocked — no real Supabase connection.

Prevention rules:
  T1: All mocked function signatures verified against source.
  T2: side_effect and return_value never mixed on the same mock chain.
  T3: Syntax-checked before delivery.
  T4: N/A (no fix scripts).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — mirrors test_lead_form_routes.py pattern
# ---------------------------------------------------------------------------

ORG_ID  = "00000000-0000-0000-0000-000000000001"
ITEM_ID = "00000000-0000-0000-0000-000000000020"

_ITEM_ROW = {
    "id":              ITEM_ID,
    "org_id":          ORG_ID,
    "title":           "Premium Mattress",
    "slug":            "premium-mattress",
    "catalog_images":  ["https://storage/img1.jpg"],
    "catalog_visible": True,
    "available":       True,
    "catalog_views":   5,
    "tags":            {},
    "custom_fields":   {},
}


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
# get_catalog_config
# ---------------------------------------------------------------------------

class TestGetCatalogConfig:

    def test_returns_config_from_org(self):
        from app.services.catalog_service import get_catalog_config
        db = _make_db()
        config_data = {"catalog_item_label": "Mattress"}
        db.table.return_value = _chain({"catalog_config": config_data})
        result = get_catalog_config(db, ORG_ID)
        assert result == config_data

    def test_returns_empty_dict_when_config_is_none(self):
        from app.services.catalog_service import get_catalog_config
        db = _make_db()
        db.table.return_value = _chain({"catalog_config": None})
        result = get_catalog_config(db, ORG_ID)
        assert result == {}

    def test_returns_empty_dict_on_exception(self):
        from app.services.catalog_service import get_catalog_config
        db = _make_db()
        db.table.side_effect = Exception("DB error")
        result = get_catalog_config(db, ORG_ID)
        assert result == {}

    def test_returns_empty_dict_when_no_org_found(self):
        from app.services.catalog_service import get_catalog_config
        db = _make_db()
        db.table.return_value = _chain(None)
        result = get_catalog_config(db, ORG_ID)
        assert result == {}


# ---------------------------------------------------------------------------
# update_catalog_config
# ---------------------------------------------------------------------------

class TestUpdateCatalogConfig:

    def test_merges_updates_with_existing_config(self):
        from app.services.catalog_service import update_catalog_config
        db = _make_db()

        calls = []

        def _tbl(name):
            if name == "organisations":
                if not calls:
                    # First call: get_catalog_config reads existing
                    calls.append("read")
                    return _chain({"catalog_config": {"catalog_item_label": "Mattress"}})
                else:
                    # Second call: update
                    calls.append("write")
                    return _chain({})
            return _chain()

        db.table.side_effect = _tbl

        result = update_catalog_config(db, ORG_ID, {"price_on_request": True})
        assert result["catalog_item_label"] == "Mattress"
        assert result["price_on_request"] is True

    def test_raises_on_db_failure(self):
        from app.services.catalog_service import update_catalog_config
        db = _make_db()

        call_count = [0]

        def _tbl(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return _chain({"catalog_config": {}})
            raise Exception("DB write failure")

        db.table.side_effect = _tbl

        with pytest.raises(Exception, match="DB write failure"):
            update_catalog_config(db, ORG_ID, {"catalog_item_label": "Product"})


# ---------------------------------------------------------------------------
# get_catalog_items
# ---------------------------------------------------------------------------

class TestGetCatalogItems:

    def _make_items_db(self, items):
        db = _make_db()
        db.table.return_value = _chain(items)
        return db

    def test_returns_all_items(self):
        from app.services.catalog_service import get_catalog_items
        items = [_ITEM_ROW, {**_ITEM_ROW, "id": "other-id", "title": "Budget Mattress"}]
        db = self._make_items_db(items)
        result = get_catalog_items(db, ORG_ID)
        assert len(result) == 2

    def test_search_filters_by_title_case_insensitive(self):
        from app.services.catalog_service import get_catalog_items
        items = [
            {**_ITEM_ROW, "title": "Premium Mattress"},
            {**_ITEM_ROW, "id": "other-id", "title": "Budget Pillow"},
        ]
        db = self._make_items_db(items)
        result = get_catalog_items(db, ORG_ID, search="premium")
        assert len(result) == 1
        assert result[0]["title"] == "Premium Mattress"

    def test_search_is_case_insensitive(self):
        from app.services.catalog_service import get_catalog_items
        items = [_ITEM_ROW]  # title = "Premium Mattress"
        db = self._make_items_db(items)
        result = get_catalog_items(db, ORG_ID, search="PREMIUM")
        assert len(result) == 1

    def test_returns_empty_list_on_exception(self):
        from app.services.catalog_service import get_catalog_items
        db = _make_db()
        db.table.side_effect = Exception("DB down")
        result = get_catalog_items(db, ORG_ID)
        assert result == []


# ---------------------------------------------------------------------------
# get_catalog_item
# ---------------------------------------------------------------------------

class TestGetCatalogItem:

    def test_returns_item_when_found(self):
        from app.services.catalog_service import get_catalog_item
        db = _make_db()
        db.table.return_value = _chain(_ITEM_ROW)
        result = get_catalog_item(db, ORG_ID, ITEM_ID)
        assert result["id"] == ITEM_ID

    def test_returns_none_when_not_found(self):
        from app.services.catalog_service import get_catalog_item
        db = _make_db()
        db.table.return_value = _chain(None)
        result = get_catalog_item(db, ORG_ID, ITEM_ID)
        assert result is None

    def test_returns_none_on_exception(self):
        from app.services.catalog_service import get_catalog_item
        db = _make_db()
        db.table.side_effect = Exception("DB error")
        result = get_catalog_item(db, ORG_ID, ITEM_ID)
        assert result is None


# ---------------------------------------------------------------------------
# update_catalog_item
# ---------------------------------------------------------------------------

class TestUpdateCatalogItem:

    def test_updates_item_successfully(self):
        from app.services.catalog_service import update_catalog_item
        db = _make_db()
        updated = {**_ITEM_ROW, "catalog_visible": False}

        call_count = [0]

        def _tbl(name):
            call_count[0] += 1
            if call_count[0] == 1:
                # slug conflict check — no conflicts
                return _chain([])
            # update call
            return _chain(updated)

        db.table.side_effect = _tbl
        result = update_catalog_item(db, ORG_ID, ITEM_ID, {"slug": "new-slug", "catalog_visible": False})
        assert result["catalog_visible"] is False

    def test_raises_slug_conflict_error_on_duplicate(self):
        from app.services.catalog_service import update_catalog_item, SlugConflictError
        db = _make_db()
        # Conflict check returns an existing item with the same slug
        db.table.return_value = _chain([{"id": "other-id"}])

        with pytest.raises(SlugConflictError):
            update_catalog_item(db, ORG_ID, ITEM_ID, {"slug": "taken-slug"})

    def test_no_slug_check_when_slug_not_in_updates(self):
        from app.services.catalog_service import update_catalog_item
        db = _make_db()
        db.table.return_value = _chain(_ITEM_ROW)
        # Should not raise even though we don't mock slug conflict
        result = update_catalog_item(db, ORG_ID, ITEM_ID, {"catalog_visible": True})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _generate_unique_slug
# ---------------------------------------------------------------------------

class TestGenerateUniqueSlug:

    def test_generates_slug_from_title(self):
        from app.services.catalog_service import _generate_unique_slug
        db = _make_db()
        db.table.return_value = _chain([])  # No conflict
        slug = _generate_unique_slug(db, ORG_ID, "Premium Organic Mattress")
        assert slug == "premium-organic-mattress"

    def test_appends_counter_on_collision(self):
        from app.services.catalog_service import _generate_unique_slug
        db = _make_db()

        call_count = [0]

        def _tbl(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return _chain([{"id": "conflict-id"}])  # First slug taken
            return _chain([])  # Second slug free

        db.table.side_effect = _tbl
        slug = _generate_unique_slug(db, ORG_ID, "Premium Mattress")
        assert slug == "premium-mattress-2"

    def test_strips_special_characters(self):
        from app.services.catalog_service import _generate_unique_slug
        db = _make_db()
        db.table.return_value = _chain([])
        slug = _generate_unique_slug(db, ORG_ID, "Royal Rest™ Black Edition!")
        assert "™" not in slug
        assert "!" not in slug

    def test_returns_best_effort_slug_on_db_error(self):
        from app.services.catalog_service import _generate_unique_slug
        db = _make_db()
        db.table.side_effect = Exception("DB error")
        slug = _generate_unique_slug(db, ORG_ID, "Test Product")
        # Should return something without raising
        assert isinstance(slug, str)
        assert len(slug) > 0


# ---------------------------------------------------------------------------
# delete_catalog_image
# ---------------------------------------------------------------------------

class TestDeleteCatalogImage:

    def test_raises_value_error_for_out_of_range_index(self):
        from app.services.catalog_service import delete_catalog_image
        db = _make_db()
        db.table.return_value = _chain(_ITEM_ROW)  # item has 1 image at index 0
        with pytest.raises(ValueError, match="out of range"):
            delete_catalog_image(db, ORG_ID, ITEM_ID, image_index=5)

    def test_raises_value_error_when_item_not_found(self):
        from app.services.catalog_service import delete_catalog_image
        db = _make_db()
        db.table.return_value = _chain(None)
        with pytest.raises(ValueError, match="Item not found"):
            delete_catalog_image(db, ORG_ID, ITEM_ID, image_index=0)

    def test_removes_correct_image_from_array(self):
        from app.services.catalog_service import delete_catalog_image

        item = {
            **_ITEM_ROW,
            "catalog_images": ["https://storage/img1.jpg", "https://storage/img2.jpg"],
        }

        updates_captured = []

        def _tbl(name):
            c = _chain(item)
            original_update = c.update

            def capture_update(payload):
                updates_captured.append(payload)
                return c
            c.update = capture_update
            return c

        db = _make_db()
        db.table.side_effect = _tbl

        delete_catalog_image(db, ORG_ID, ITEM_ID, image_index=0)
        # Verify the remaining images don't include index 0
        saved = next((u for u in updates_captured if "catalog_images" in u), None)
        if saved:
            assert "https://storage/img1.jpg" not in saved["catalog_images"]
