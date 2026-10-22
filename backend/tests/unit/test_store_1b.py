"""
tests/unit/test_store_1b.py
---------------------------
STORE-1b: product categories for the public catalog.
  * service: add / rename / reorder / delete, assign products, counts, limits, names
  * the generic tag editor can never drop or change the category group
  * owner routes: GET/PUT/POST /catalog/categories and PUT /catalog/categories/{name}/items (owner role, 422 for owner-fixable problems)
  * public style carries the menu switch
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import catalog_category_service as cat
from app.services import catalog_storefront_service as sf
from tests.unit.test_account_plans_1 import BIZ, PLATFORM, FakeDB, _Q


class _MS(_Q):
    def maybe_single(self): return self


class DB(FakeDB):
    def table(self, name): return _MS(self, name)


def _item(i, title, cats=None, visible=True, **tags):
    t = dict(tags)
    if cats is not None:
        t["category"] = cats
    return {"id": f"i{i}", "org_id": BIZ, "title": title, "tags": t, "catalog_visible": visible, "price": 100}


def _db(cfg=None, items=None):
    return DB(organisations=[{"id": BIZ, "catalog_config": cfg if cfg is not None else {}}],
              products=items if items is not None else [])


def _cfg(db):
    return db.rows("organisations")[0]["catalog_config"]


def _tags(db, iid):
    return next(r for r in db.rows("products") if r["id"] == iid)["tags"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


# ---------------------------------------------------------------- names

@pytest.mark.parametrize("raw,ok", [("Mattresses", "Mattresses"), ("  Back   pain  care ", "Back pain care"), ("x" * 40, "x" * 40)])
def test_clean_name_ok(raw, ok):
    assert cat.clean_name(raw) == ok


@pytest.mark.parametrize("raw", ["", "   ", None, "x" * 41, "a/b", "a\\b"])
def test_clean_name_rejects(raw):
    with pytest.raises(cat.CategoryError):
        cat.clean_name(raw)


# ---------------------------------------------------------------- add

def test_add_creates_reserved_group_and_keeps_other_groups():
    other = {"key": "feel", "label": "Feel", "type": "multi_select", "filterable": True, "options": ["Soft"]}
    db = _db({"tag_dimensions": [other]})
    out = cat.add_category(db, BIZ, "  Pillows ")
    dims = _cfg(db)["tag_dimensions"]
    assert dims[0] == other
    assert dims[1] == {"key": "category", "label": "Category", "type": "multi_select", "filterable": True, "options": ["Pillows"]}
    assert out["added"] == "Pillows" and [c["name"] for c in out["categories"]] == ["Pillows"]


def test_add_second_keeps_order_and_single_group():
    db = _db()
    cat.add_category(db, BIZ, "Mattresses")
    cat.add_category(db, BIZ, "Pillows")
    dims = [d for d in _cfg(db)["tag_dimensions"] if d["key"] == "category"]
    assert len(dims) == 1 and dims[0]["options"] == ["Mattresses", "Pillows"]


def test_add_duplicate_ignoring_capitals():
    db = _db()
    cat.add_category(db, BIZ, "Pillows")
    with pytest.raises(cat.CategoryError, match="already have a category called Pillows"):
        cat.add_category(db, BIZ, "pillows")


def test_add_over_twenty():
    db = _db({"tag_dimensions": [{"key": "category", "label": "Category", "type": "multi_select", "filterable": True,
                                  "options": [f"c{i}" for i in range(20)]}]})
    with pytest.raises(cat.CategoryError, match="up to 20"):
        cat.add_category(db, BIZ, "one more")


def test_add_when_ten_other_groups_already_exist():
    dims = [{"key": f"g{i}", "label": "G", "type": "multi_select", "filterable": True, "options": ["a"]} for i in range(10)]
    db = _db({"tag_dimensions": dims})
    with pytest.raises(cat.CategoryError, match="10 tag groups"):
        cat.add_category(db, BIZ, "Pillows")
    assert len(_cfg(db)["tag_dimensions"]) == 10


# ---------------------------------------------------------------- list / counts

def test_counts_only_visible_products_and_uncategorised():
    db = _db({"tag_dimensions": [cat._dimension(["Beds", "Pillows"])], "show_categories": False},
             [_item(1, "A", ["Beds"]), _item(2, "B", ["Beds", "Pillows"]), _item(3, "C", ["Pillows"], visible=False), _item(4, "D")])
    out = cat.list_categories(db, BIZ)
    assert out["categories"] == [{"name": "Beds", "count": 2}, {"name": "Pillows", "count": 1}]
    assert out["uncategorised"] == 1 and out["show_in_menu"] is False


def test_menu_defaults_on_and_empty_catalog_is_fine():
    out = cat.list_categories(_db(), BIZ)
    assert out == {"categories": [], "show_in_menu": True, "uncategorised": 0}


# ---------------------------------------------------------------- save: rename / reorder / delete

def _three():
    return _db({"tag_dimensions": [cat._dimension(["Beds", "Pillows", "Sheets"])]},
               [_item(1, "A", ["Beds", "Sheets"]), _item(2, "B", ["Pillows"]), _item(3, "C", [])])


def test_rename_rewrites_products():
    db = _three()
    out = cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Pillow range", "was": "Pillows"}, {"name": "Sheets"}])
    assert [c["name"] for c in out["categories"]] == ["Beds", "Pillow range", "Sheets"]
    assert _tags(db, "i2")["category"] == ["Pillow range"]
    assert _tags(db, "i1")["category"] == ["Beds", "Sheets"]


def test_reorder_only_changes_order():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Sheets"}, {"name": "Beds"}, {"name": "Pillows"}])
    assert cat.names_in(_cfg(db)) == ["Sheets", "Beds", "Pillows"]
    assert _tags(db, "i1")["category"] == ["Beds", "Sheets"]


def test_delete_removes_name_from_products_but_keeps_products():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Pillows"}])
    assert _tags(db, "i1")["category"] == ["Beds"]
    assert len(db.rows("products")) == 3


def test_delete_last_product_category_drops_the_tag_key():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Sheets"}])
    assert "category" not in _tags(db, "i2")


def test_delete_all_removes_the_group_and_leaves_other_groups():
    other = {"key": "feel", "label": "Feel", "type": "multi_select", "filterable": True, "options": ["Soft"]}
    db = _db({"tag_dimensions": [other, cat._dimension(["Beds"])]}, [_item(1, "A", ["Beds"], feel="Soft")])
    cat.save_categories(db, BIZ, [])
    assert _cfg(db)["tag_dimensions"] == [other]
    assert _tags(db, "i1") == {"feel": "Soft"}


def test_removed_name_recreated_without_was_starts_empty():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Sheets"}, {"name": "Pillows"}])  # same names, nothing removed
    assert _tags(db, "i2")["category"] == ["Pillows"]
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Sheets"}])
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Sheets"}, {"name": "Pillows"}])
    assert "category" not in _tags(db, "i2")


def test_swap_two_names():
    db = _db({"tag_dimensions": [cat._dimension(["A", "B"])]}, [_item(1, "x", ["A"]), _item(2, "y", ["B"])])
    cat.save_categories(db, BIZ, [{"name": "B", "was": "A"}, {"name": "A", "was": "B"}])
    assert _tags(db, "i1")["category"] == ["B"] and _tags(db, "i2")["category"] == ["A"]


def test_rename_into_existing_name_merges_without_duplicates():
    db = _db({"tag_dimensions": [cat._dimension(["A", "B"])]}, [_item(1, "x", ["A", "B"])])
    cat.save_categories(db, BIZ, [{"name": "B", "was": "A"}])
    assert _tags(db, "i1")["category"] == ["B"]


def test_rename_matches_old_name_ignoring_capitals():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Beds"}, {"name": "Cushions", "was": "pillows"}, {"name": "Sheets"}])
    assert _tags(db, "i2")["category"] == ["Cushions"]


def test_save_rejects_duplicates_blank_and_too_many_and_changes_nothing():
    db = _three()
    before = [dict(r) for r in db.rows("products")]
    for bad in ([{"name": "Beds"}, {"name": " beds "}], [{"name": "Beds"}, {"name": "BEDS"}], [{"name": "  "}], [{"name": f"c{i}"} for i in range(21)]):
        with pytest.raises(cat.CategoryError):
            cat.save_categories(db, BIZ, bad)
    assert db.rows("products") == before and cat.names_in(_cfg(db)) == ["Beds", "Pillows", "Sheets"]


def test_save_menu_switch_only_when_given():
    db = _three()
    cat.save_categories(db, BIZ, [{"name": "Beds"}], show_in_menu=False)
    assert _cfg(db)["show_categories"] is False
    cat.save_categories(db, BIZ, [{"name": "Beds"}])
    assert _cfg(db)["show_categories"] is False
    out = cat.save_categories(db, BIZ, [{"name": "Beds"}], show_in_menu=True)
    assert out["show_in_menu"] is True


def test_save_keeps_every_other_config_key():
    db = _db({"price_label_template": "N{price}", "template": "storefront", "tag_dimensions": []})
    cat.save_categories(db, BIZ, [{"name": "Beds"}])
    cfg = _cfg(db)
    assert cfg["price_label_template"] == "N{price}" and cfg["template"] == "storefront"


def test_save_when_ten_other_groups_exist_fails_cleanly():
    dims = [{"key": f"g{i}", "label": "G", "type": "multi_select", "filterable": True, "options": ["a"]} for i in range(10)]
    db = _db({"tag_dimensions": dims}, [_item(1, "x")])
    with pytest.raises(cat.CategoryError):
        cat.save_categories(db, BIZ, [{"name": "Beds"}])


# ---------------------------------------------------------------- assign products

def test_set_items_adds_and_removes_exactly():
    db = _three()
    out = cat.set_category_items(db, BIZ, "pillows", ["i1", "i3"])
    assert out["selected"] == "Pillows" and out["item_ids"] == ["i1", "i3"]
    assert _tags(db, "i1")["category"] == ["Beds", "Sheets", "Pillows"]
    assert _tags(db, "i3")["category"] == ["Pillows"]
    assert "category" not in _tags(db, "i2")


def test_set_items_empty_list_clears_the_category():
    db = _three()
    cat.set_category_items(db, BIZ, "Beds", [])
    assert _tags(db, "i1")["category"] == ["Sheets"]


def test_set_items_unknown_category_or_foreign_product():
    db = _three()
    with pytest.raises(cat.CategoryError, match="does not exist"):
        cat.set_category_items(db, BIZ, "Nope", [])
    with pytest.raises(cat.CategoryError, match="not in your catalog"):
        cat.set_category_items(db, BIZ, "Beds", ["i1", "other-org-item"])
    assert _tags(db, "i1")["category"] == ["Beds", "Sheets"]


def test_set_items_never_touches_other_orgs():
    db = _three()
    db.tables["products"].append({"id": "x1", "org_id": "other", "title": "Z", "tags": {"category": ["Beds"]}, "catalog_visible": True})
    cat.set_category_items(db, BIZ, "Beds", [])
    assert next(r for r in db.rows("products") if r["id"] == "x1")["tags"]["category"] == ["Beds"]


# ---------------------------------------------------------------- generic tag editor can't break categories

def test_keep_category_restores_dropped_group():
    stored = cat._dimension(["Beds"])
    out = cat.keep_category([stored], [{"key": "feel"}])
    assert out == [{"key": "feel"}, stored]


def test_keep_category_ignores_edits_to_the_group():
    stored = cat._dimension(["Beds"])
    out = cat.keep_category([stored], [{"key": "category", "label": "Hacked", "options": ["x"]}, {"key": "feel"}])
    assert out == [{"key": "feel"}, stored]


def test_keep_category_does_not_invent_a_group():
    assert cat.keep_category([], [{"key": "feel"}]) == [{"key": "feel"}]
    assert cat.keep_category(None, [{"key": "category", "options": ["x"]}]) == []


# ---------------------------------------------------------------- public style

def test_public_style_menu_switch():
    assert sf.public_style({})["show_categories"] is True
    assert sf.public_style({"show_categories": True})["show_categories"] is True
    assert sf.public_style({"show_categories": False})["show_categories"] is False
    assert sf.public_style(None)["show_categories"] is True


# ---------------------------------------------------------------- routes

@pytest.fixture()
def owner(request):
    from fastapi.testclient import TestClient
    from app.dependencies import get_current_org, get_supabase
    from app.main import app
    role = getattr(request, "param", "owner")
    db = _three()
    app.dependency_overrides[get_current_org] = lambda: {"org_id": BIZ, "roles": {"template": role}}
    app.dependency_overrides[get_supabase] = lambda: db
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        yield TestClient(app), db
    app.dependency_overrides.clear()


def test_route_get(owner):
    c, _ = owner
    r = c.get("/api/v1/catalog/categories")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()["categories"]] == ["Beds", "Pillows", "Sheets"]


def test_route_put_rename_and_menu(owner):
    c, db = owner
    r = c.put("/api/v1/catalog/categories", json={"categories": [{"name": "Beds"}, {"name": "Cushions", "was": "Pillows"}], "show_in_menu": False})
    assert r.status_code == 200, r.text
    assert r.json()["show_in_menu"] is False and _tags(db, "i2")["category"] == ["Cushions"]


def test_route_put_duplicate_is_422_with_plain_message(owner):
    c, _ = owner
    r = c.put("/api/v1/catalog/categories", json={"categories": [{"name": "Beds"}, {"name": "beds"}]})
    assert r.status_code == 422 and "already have a category" in r.json()["detail"]


def test_route_post_add(owner):
    c, db = owner
    r = c.post("/api/v1/catalog/categories", json={"name": "Toppers"})
    assert r.status_code == 201 and r.json()["added"] == "Toppers"
    assert cat.names_in(_cfg(db))[-1] == "Toppers"
    assert c.post("/api/v1/catalog/categories", json={"name": "toppers"}).status_code == 422


def test_route_put_items_with_encoded_name(owner):
    c, db = owner
    cat.add_category(db, BIZ, "Back pain care")
    r = c.put("/api/v1/catalog/categories/Back%20pain%20care/items", json={"item_ids": ["i2", "i3"]})
    assert r.status_code == 200, r.text
    assert r.json()["item_ids"] == ["i2", "i3"] and _tags(db, "i3")["category"] == ["Back pain care"]


def test_route_put_items_bad_ids_and_unknown_category(owner):
    c, _ = owner
    assert c.put("/api/v1/catalog/categories/Beds/items", json={"item_ids": ["zzz"]}).status_code == 422
    assert c.put("/api/v1/catalog/categories/Nope/items", json={"item_ids": []}).status_code == 422


@pytest.mark.parametrize("owner", ["sales_agent", "support"], indirect=True)
def test_routes_need_owner_or_ops_manager(owner):
    c, db = owner
    before = cat.names_in(_cfg(db))
    assert c.get("/api/v1/catalog/categories").status_code == 403
    assert c.put("/api/v1/catalog/categories", json={"categories": []}).status_code == 403
    assert c.post("/api/v1/catalog/categories", json={"name": "x"}).status_code == 403
    assert c.put("/api/v1/catalog/categories/Beds/items", json={"item_ids": []}).status_code == 403
    assert cat.names_in(_cfg(db)) == before


def test_config_patch_cannot_drop_the_category_group(owner):
    c, db = owner
    r = c.patch("/api/v1/catalog/config", json={"tag_dimensions": [{"key": "feel", "label": "Feel", "type": "multi_select", "options": ["Soft"]}]})
    assert r.status_code == 200, r.text
    keys = [d["key"] for d in _cfg(db)["tag_dimensions"]]
    assert keys == ["feel", "category"]
    assert cat.names_in(_cfg(db)) == ["Beds", "Pillows", "Sheets"]


def test_config_patch_without_dimensions_leaves_categories_alone(owner):
    c, db = owner
    assert c.patch("/api/v1/catalog/config", json={"announcement": "Hi"}).status_code == 200
    assert cat.names_in(_cfg(db)) == ["Beds", "Pillows", "Sheets"]
