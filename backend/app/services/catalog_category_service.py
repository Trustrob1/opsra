"""
app/services/catalog_category_service.py
----------------------------------------
STORE-1b - product categories for the public catalog (owner-managed; shown by Storefront, and by Classic as a filter).

A category is stored with the tools the catalog already has, so nothing new has to be migrated:
  * the list of categories is one reserved tag group (tag_dimensions entry with key "category"), in the owner's order
  * a product's categories are its tags["category"] list
  * the menu switch is catalog_config["show_categories"] (default on)

  list_categories(db, org_id)                       names, counts, menu switch
  save_categories(db, org_id, entries, show_menu)   add / rename / reorder / delete in one save
  add_category(db, org_id, name)                    add one (the product drawer's "Add new category")
  set_category_items(db, org_id, name, item_ids)    exactly these products are in the category
  keep_category(existing_dims, submitted_dims)      the generic tag editor can never drop or edit the category group

Rules
  * Names: 1-40 characters, no "/" or "\\", unique ignoring capitals, at most 20 categories.
  * Renaming rewrites the products that use the old name. Deleting removes the name from products. Products are never deleted.
  * Products in no category still show under "All" on the public page.
  * One tag group is used, so a business may have at most 10 tag groups in total.
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from app.services.catalog_service import (
    get_catalog_config,
    get_catalog_items,
    update_catalog_config,
)

logger = logging.getLogger(__name__)

CATEGORY_KEY = "category"
CATEGORY_LABEL = "Category"
MAX_CATEGORIES = 20
MAX_NAME = 40
MAX_DIMENSIONS = 10


class CategoryError(ValueError):
    """A problem the owner can fix (shown as-is)."""


def clean_name(raw) -> str:
    name = " ".join(str(raw or "").split())
    if not name:
        raise CategoryError("Type a name for the category.")
    if len(name) > MAX_NAME:
        raise CategoryError(f"A category name can be up to {MAX_NAME} characters.")
    if "/" in name or "\\" in name:
        raise CategoryError("A category name cannot contain / or \\.")
    return name


def _dims(config: Optional[dict]) -> list:
    d = (config or {}).get("tag_dimensions")
    return d if isinstance(d, list) else []


def get_dimension(config: Optional[dict]) -> Optional[dict]:
    for d in _dims(config):
        if isinstance(d, dict) and d.get("key") == CATEGORY_KEY:
            return d
    return None


def names_in(config: Optional[dict]) -> List[str]:
    dim = get_dimension(config)
    opts = (dim or {}).get("options")
    return [str(o) for o in opts] if isinstance(opts, list) else []


def item_categories(item: dict) -> List[str]:
    tags = item.get("tags") if isinstance(item, dict) else None
    if not isinstance(tags, dict):
        return []
    v = tags.get(CATEGORY_KEY)
    vals = v if isinstance(v, list) else [v] if v else []
    return [str(x) for x in vals if str(x).strip()]


def _index(names: Iterable[str]) -> dict:
    return {n.lower(): n for n in names}


def keep_category(existing_dims: Optional[list], submitted_dims: list) -> list:
    """The submitted tag groups, with the category group exactly as it is stored (never dropped, never edited)."""
    current = next((d for d in (existing_dims or []) if isinstance(d, dict) and d.get("key") == CATEGORY_KEY), None)
    out = [d for d in submitted_dims if (d.get("key") if isinstance(d, dict) else None) != CATEGORY_KEY]
    if current:
        out.append(current)
    return out


def _dimension(names: List[str]) -> dict:
    return {"key": CATEGORY_KEY, "label": CATEGORY_LABEL, "type": "multi_select", "filterable": True, "options": list(names)}


def _write_dimension(config: dict, names: List[str]) -> list:
    others = [d for d in _dims(config) if not (isinstance(d, dict) and d.get("key") == CATEGORY_KEY)]
    if names:
        if len(others) + 1 > MAX_DIMENSIONS:
            raise CategoryError("This catalog already uses 10 tag groups. Remove one before adding categories.")
        return others + [_dimension(names)]
    return others


def _set_item_tags(db, org_id: str, item: dict, cats: List[str]) -> None:
    tags = dict(item.get("tags") or {}) if isinstance(item.get("tags"), dict) else {}
    if cats:
        tags[CATEGORY_KEY] = cats
    else:
        tags.pop(CATEGORY_KEY, None)
    db.table("products").update({"tags": tags}).eq("org_id", org_id).eq("id", item["id"]).execute()


def _snapshot(config: dict, items: list) -> dict:
    names = names_in(config)
    visible = [i for i in items if i.get("catalog_visible")]
    counts = {n: 0 for n in names}
    uncategorised = 0
    for it in visible:
        mine = [c for c in item_categories(it) if c in counts]
        for c in mine:
            counts[c] += 1
        if not mine:
            uncategorised += 1
    return {
        "categories": [{"name": n, "count": counts[n]} for n in names],
        "show_in_menu": config.get("show_categories") is not False,
        "uncategorised": uncategorised,
    }


def list_categories(db, org_id: str) -> dict:
    return _snapshot(get_catalog_config(db, org_id), get_catalog_items(db, org_id))


def save_categories(db, org_id: str, entries: list, show_in_menu: Optional[bool] = None) -> dict:
    """entries: [{"name": "Pillows", "was": "Pillow"}] in the owner's order; "was" marks a rename."""
    if not isinstance(entries, list):
        raise CategoryError("Send the list of categories.")
    if len(entries) > MAX_CATEGORIES:
        raise CategoryError(f"You can have up to {MAX_CATEGORIES} categories.")
    config = get_catalog_config(db, org_id)
    old = names_in(config)
    old_idx = _index(old)

    new_names: List[str] = []
    rename: dict = {}          # old name -> new name
    seen = set()
    for e in entries:
        raw = e.get("name") if isinstance(e, dict) else e
        name = clean_name(raw)
        if name.lower() in seen:
            raise CategoryError(f"You already have a category called {name}.")
        seen.add(name.lower())
        was = e.get("was") if isinstance(e, dict) else None
        was_name = old_idx.get(str(was).strip().lower()) if was else None
        if was_name and was_name not in rename and was_name != name:
            rename[was_name] = name
        new_names.append(name)

    kept_old = {n for n in old if n in new_names or n in rename}      # old names that live on (same or renamed)
    removed = [n for n in old if n not in kept_old]

    new_dims = _write_dimension(config, new_names)

    items = get_catalog_items(db, org_id)
    for it in items:
        cats = item_categories(it)
        if not cats:
            continue
        updated: List[str] = []
        for c in cats:
            c2 = rename.get(c, c)
            if c in removed or (c2 not in new_names):
                continue
            if c2 not in updated:
                updated.append(c2)
        if updated != cats:
            _set_item_tags(db, org_id, it, updated)

    patch = {"tag_dimensions": new_dims}
    if show_in_menu is not None:
        patch["show_categories"] = bool(show_in_menu)
    merged = update_catalog_config(db, org_id, patch)
    return _snapshot(merged, get_catalog_items(db, org_id))


def add_category(db, org_id: str, name: str) -> dict:
    config = get_catalog_config(db, org_id)
    clean = clean_name(name)
    existing = names_in(config)
    if clean.lower() in _index(existing):
        raise CategoryError(f"You already have a category called {_index(existing)[clean.lower()]}.")
    if len(existing) >= MAX_CATEGORIES:
        raise CategoryError(f"You can have up to {MAX_CATEGORIES} categories.")
    merged = update_catalog_config(db, org_id, {"tag_dimensions": _write_dimension(config, existing + [clean])})
    snap = _snapshot(merged, get_catalog_items(db, org_id))
    snap["added"] = clean
    return snap


def set_category_items(db, org_id: str, name: str, item_ids: List[str]) -> dict:
    """Exactly these products are in the category afterwards."""
    config = get_catalog_config(db, org_id)
    real = _index(names_in(config)).get(str(name or "").strip().lower())
    if not real:
        raise CategoryError("That category does not exist.")
    items = get_catalog_items(db, org_id)
    by_id = {str(i["id"]): i for i in items}
    wanted = {str(x) for x in (item_ids or [])}
    unknown = wanted - set(by_id)
    if unknown:
        raise CategoryError("Some of those products are not in your catalog.")
    for iid, it in by_id.items():
        cats = item_categories(it)
        has = real in cats
        if iid in wanted and not has:
            _set_item_tags(db, org_id, it, cats + [real])
        elif iid not in wanted and has:
            _set_item_tags(db, org_id, it, [c for c in cats if c != real])
    snap = _snapshot(config, get_catalog_items(db, org_id))
    snap["selected"] = real
    snap["item_ids"] = sorted(wanted)
    return snap
