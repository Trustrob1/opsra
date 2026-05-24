"""
app/services/catalog_service.py
---------------------------------
CATALOG-2A: Catalog business logic.
S14: public functions that are called from routes raise typed exceptions
on known error conditions (SlugConflictError, ValueError) so the router
can map them to the correct HTTP status code. Generic failures re-raise
so the router catches and returns 500.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class SlugConflictError(Exception):
    """Raised when a requested slug is already taken within the same org."""


# ---------------------------------------------------------------------------
# Column list — used by every item fetch
# ---------------------------------------------------------------------------

_CATALOG_ITEM_COLS = (
    "id, org_id, shopify_id, title, description, catalog_description, price, compare_at_price, "
    "image_url, handle, status, is_active, variants, tags, slug, "
    "catalog_images, extra_catalog_images, custom_fields, catalog_visible, available, "
    "inventory_count, catalog_views, created_at, updated_at"
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def get_catalog_config(db, org_id: str) -> dict:
    """Fetch org catalog_config JSONB. Returns {} if not yet set."""
    try:
        result = (
            db.table("organisations")
            .select("catalog_config")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else {}
        return (data or {}).get("catalog_config") or {}
    except Exception as exc:
        logger.warning("get_catalog_config failed org=%s: %s", org_id, exc)
        return {}


def update_catalog_config(db, org_id: str, updates: dict) -> dict:
    """
    Merge updates into org catalog_config JSONB and persist.
    Returns the merged config dict.
    Raises on DB failure so the router can return 500.
    """
    current = get_catalog_config(db, org_id)
    merged = {**current, **updates}
    db.table("organisations").update({
        "catalog_config": merged,
    }).eq("id", org_id).execute()
    return merged


# ---------------------------------------------------------------------------
# Items — read
# ---------------------------------------------------------------------------

def get_catalog_items(
    db,
    org_id: str,
    visible_only: bool = False,
    available_only: bool = False,
    search: Optional[str] = None,
) -> list:
    """
    Fetch all products for org with catalog columns.
    visible_only / available_only applied in DB.
    search: Python-side case-insensitive filter on title (Pattern 33 — no ILIKE).
    S14.
    """
    try:
        query = (
            db.table("products")
            .select(_CATALOG_ITEM_COLS)
            .eq("org_id", org_id)
        )
        if visible_only:
            query = query.eq("catalog_visible", True)
        if available_only:
            query = query.eq("available", True)

        result = query.order("title").execute()
        items = result.data if isinstance(result.data, list) else []

        # Pattern 33: Python-side search filter
        if search:
            term = search.lower()
            items = [i for i in items if term in (i.get("title") or "").lower()]

        return items
    except Exception as exc:
        logger.warning("get_catalog_items failed org=%s: %s", org_id, exc)
        return []


def get_catalog_item(db, org_id: str, item_id: str) -> Optional[dict]:
    """Fetch single product. Returns None if not found or on error."""
    try:
        result = (
            db.table("products")
            .select(_CATALOG_ITEM_COLS)
            .eq("org_id", org_id)
            .eq("id", item_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        return data
    except Exception as exc:
        logger.warning("get_catalog_item failed org=%s item=%s: %s", org_id, item_id, exc)
        return None


# ---------------------------------------------------------------------------
# Items — write
# ---------------------------------------------------------------------------

def update_catalog_item(db, org_id: str, item_id: str, updates: dict) -> dict:
    """
    Update allowed catalog fields on a product.
    Validates slug uniqueness before saving (raises SlugConflictError on conflict).
    Returns updated row.
    """
    # Slug uniqueness check
    if "slug" in updates:
        new_slug = updates["slug"]
        conflict = (
            db.table("products")
            .select("id")
            .eq("org_id", org_id)
            .eq("slug", new_slug)
            .neq("id", item_id)
            .execute()
        )
        existing = conflict.data if isinstance(conflict.data, list) else []
        if existing:
            raise SlugConflictError(f"Slug '{new_slug}' is already in use by another item.")

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("products")
        .update(updates)
        .eq("org_id", org_id)
        .eq("id", item_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return data or {}


def create_catalog_item(db, org_id: str, payload: dict) -> dict:
    """
    Create a new catalog item (non-Shopify orgs only).
    Auto-generates a unique slug from title.
    Raises on DB failure.
    """
    now = datetime.now(timezone.utc).isoformat()
    slug = _generate_unique_slug(db, org_id, payload.get("title") or "")

    row = {
        "org_id":          org_id,
        "title":           (payload.get("title") or "")[:500],
        "description":     payload.get("description"),
        "price":           payload.get("price"),
        "slug":            slug,
        "catalog_visible": True,
        "available":       payload.get("available", True),
        "inventory_count": payload.get("inventory_count"),
        "tags":            payload.get("tags") or {},
        "custom_fields":   payload.get("custom_fields") or {},
        "catalog_images":        [],
        "extra_catalog_images":  [],
        "catalog_description":   payload.get("catalog_description"),
        "catalog_views":         0,
        "is_active":       True,
        "status":          "active",
        "created_at":      now,
        "updated_at":      now,
    }

    result = db.table("products").insert(row).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return data or {}


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def upload_catalog_image(
    db,
    org_id: str,
    item_id: str,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """
    Upload image to Supabase Storage catalog bucket.
    Appends public URL to products.catalog_images.
    Returns the new public URL.
    Raises on failure so the router can return 500.
    """
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    storage_path = f"{org_id}/{item_id}/{safe_name}"

    db.storage.from_("catalog").upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    public_url = db.storage.from_("catalog").get_public_url(storage_path)

    # Append URL to catalog_images array
    item = get_catalog_item(db, org_id, item_id)
    current_images = list((item or {}).get("catalog_images") or [])
    updated_images = current_images + [public_url]

    db.table("products").update({
        "catalog_images": updated_images,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("org_id", org_id).eq("id", item_id).execute()

    return public_url


def delete_catalog_image(db, org_id: str, item_id: str, image_index: int) -> None:
    """
    Remove image at index from catalog_images array.
    Also deletes from Supabase Storage (best-effort — DB update never blocked by Storage failure).
    Raises ValueError on invalid index or item not found.
    """
    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise ValueError("Item not found.")

    images = list((item or {}).get("catalog_images") or [])
    if image_index < 0 or image_index >= len(images):
        raise ValueError(f"Image index {image_index} is out of range (item has {len(images)} images).")

    url_to_delete = images[image_index]
    updated_images = [u for i, u in enumerate(images) if i != image_index]

    # Update DB first — this is the authoritative operation
    db.table("products").update({
        "catalog_images": updated_images,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("org_id", org_id).eq("id", item_id).execute()

    # Delete from Storage — best-effort, never blocks the response
    try:
        if "/catalog/" in url_to_delete:
            storage_path = url_to_delete.split("/catalog/", 1)[1].split("?")[0]
            db.storage.from_("catalog").remove([storage_path])
    except Exception as exc:
        logger.warning(
            "delete_catalog_image: Storage delete failed (DB already updated) path=%s: %s",
            url_to_delete, exc,
        )

def upload_extra_catalog_image(
    db,
    org_id: str,
    item_id: str,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """
    Upload an extra catalog-only image to Supabase Storage.
    Appends public URL to products.extra_catalog_images.
    Never touched by Shopify sync.
    Returns the new public URL.
    Raises on failure.
    """
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    storage_path = f"{org_id}/{item_id}/extra_{safe_name}"

    db.storage.from_("catalog").upload(
        path=storage_path,
        file=file_bytes,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    public_url = db.storage.from_("catalog").get_public_url(storage_path)

    item = get_catalog_item(db, org_id, item_id)
    current = list((item or {}).get("extra_catalog_images") or [])
    updated = current + [public_url]

    db.table("products").update({
        "extra_catalog_images": updated,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("org_id", org_id).eq("id", item_id).execute()

    return public_url


def delete_extra_catalog_image(db, org_id: str, item_id: str, image_index: int) -> None:
    """
    Remove image at index from extra_catalog_images array.
    Also deletes from Supabase Storage (best-effort).
    Raises ValueError on invalid index or item not found.
    """
    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise ValueError("Item not found.")

    images = list((item or {}).get("extra_catalog_images") or [])
    if image_index < 0 or image_index >= len(images):
        raise ValueError(f"Image index {image_index} is out of range (item has {len(images)} extra images).")

    url_to_delete = images[image_index]
    updated = [u for i, u in enumerate(images) if i != image_index]

    db.table("products").update({
        "extra_catalog_images": updated,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("org_id", org_id).eq("id", item_id).execute()

    try:
        if "/catalog/" in url_to_delete:
            storage_path = url_to_delete.split("/catalog/", 1)[1].split("?")[0]
            db.storage.from_("catalog").remove([storage_path])
    except Exception as exc:
        logger.warning(
            "delete_extra_catalog_image: Storage delete failed (DB already updated) path=%s: %s",
            url_to_delete, exc,
        )


# ---------------------------------------------------------------------------
# Slug utility
# ---------------------------------------------------------------------------

def _generate_unique_slug(db, org_id: str, title: str) -> str:
    """
    Generate a unique URL-safe slug from title.
    Appends -2, -3, etc. on collision within the same org.
    Returns best-effort slug on DB error (never raises).
    """
    base = re.sub(r'[^a-zA-Z0-9]+', '-', title.strip().lower()).strip('-') or "item"
    slug = base
    counter = 2
    while True:
        try:
            result = (
                db.table("products")
                .select("id")
                .eq("org_id", org_id)
                .eq("slug", slug)
                .execute()
            )
            existing = result.data if isinstance(result.data, list) else []
            if not existing:
                return slug
            slug = f"{base}-{counter}"
            counter += 1
        except Exception:
            return slug  # Best-effort on DB error
