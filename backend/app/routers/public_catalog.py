"""
app/routers/public_catalog.py
------------------------------
CATALOG-3A: Unauthenticated public catalog routes.

All routes under /api/v1/public/catalog — NO auth dependency.
Accessible by anyone: WhatsApp leads, web visitors, social referrals.

Security rules:
  - NEVER return org credentials, lead data, user data, financial data.
  - NEVER return org_id in response body.
  - Only public fields: org display name, wa_number, catalog_config display
    fields, and product public fields.

Pattern 53: static routes registered before parameterised routes.
Pattern 33: Python-side text filtering (no ILIKE).
Rate limiting: 60 req/min/IP via in-process dict (no slowapi dependency).
Caching: in-process 5-min list cache, 2-min item cache (Redis added in OPT-1).
catalog_views increment: fire-and-forget via asyncio.create_task().
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.database import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Rate limiting — 60 req/min per IP (in-process dict, same pattern as
# growth_insights.py panel rate limiter)
# ---------------------------------------------------------------------------
_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT  = 60    # requests
_RATE_WINDOW = 60.0  # seconds


def _check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW
    calls = [t for t in _rate_store.get(ip, []) if t > cutoff]
    if len(calls) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": "60"},
            detail="Too many requests. Please wait before trying again.",
        )
    calls.append(now)
    _rate_store[ip] = calls


# ---------------------------------------------------------------------------
# In-process cache (replaced by Redis in OPT-1)
# ---------------------------------------------------------------------------
_list_cache:  dict[str, tuple[float, Any]] = {}  # org_slug → (ts, data)
_item_cache:  dict[str, tuple[float, Any]] = {}  # "org_slug/item_slug" → (ts, data)
_LIST_TTL = 300.0  # 5 minutes
_ITEM_TTL = 120.0  # 2 minutes


def _cache_get(store: dict, key: str, ttl: float) -> Optional[Any]:
    entry = store.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None


def _cache_set(store: dict, key: str, value: Any) -> None:
    store[key] = (time.monotonic(), value)


def _cache_invalidate_org(org_slug: str) -> None:
    """Called on product update — clears list cache and all item caches for org."""
    _list_cache.pop(org_slug, None)
    stale = [k for k in _item_cache if k.startswith(f"{org_slug}/")]
    for k in stale:
        _item_cache.pop(k, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_price(price: Optional[float], template: str, price_on_request: bool) -> str:
    if price_on_request:
        return "Price on Request"
    if price is None:
        return ""
    try:
        formatted = f"{price:,.0f}"
        return template.replace("{price}", formatted)
    except Exception:
        return str(price)


def _public_item_fields(
    item: dict,
    price_template: str,
    price_on_request: bool,
) -> dict:
    """Return only the public-safe fields for a catalog item."""
    shopify_images = item.get("catalog_images") or []
    extra_images   = item.get("extra_catalog_images") or []
    return {
        "id":                 item.get("id"),
        "title":              item.get("title"),
        "slug":               item.get("slug"),
        "description":         item.get("description"),
        "catalog_description": item.get("catalog_description") or None,
        "price":              item.get("price"),
        "price_label":        _format_price(item.get("price"), price_template, price_on_request),
        "catalog_images":     shopify_images + extra_images,
        "tags":               item.get("tags") or {},
        "custom_fields":      item.get("custom_fields") or {},
        "available":          item.get("available", True),
        "catalog_views":      item.get("catalog_views", 0),
        "variants":           item.get("variants") or [],
    }


def _public_config_fields(catalog_config: dict) -> dict:
    """Strip internal sync fields — return only display-safe config fields."""
    return {
        "catalog_item_label":        catalog_config.get("catalog_item_label", "Product"),
        "catalog_item_label_plural": catalog_config.get("catalog_item_label_plural", "Products"),
        "price_label_template":      catalog_config.get("price_label_template", "₦{price}"),
        "price_on_request":          catalog_config.get("price_on_request", False),
        "availability_labels":       catalog_config.get("availability_labels", {
        "available": "In Stock", "unavailable": "Out of Stock",
        }),
        "cta_buttons":                catalog_config.get("cta_buttons", []),
        "tag_dimensions":             catalog_config.get("tag_dimensions", []),
        "gallery_section_label":      catalog_config.get("gallery_section_label", "Gallery"),
        "specifications_section_label": catalog_config.get("specifications_section_label", "Specifications"),
    }


def _extract_wizard_questions(qualification_flow: Optional[dict]) -> List[dict]:
    """
    Extract only the questions that have map_to_catalog_tag set.
    These are the questions the public catalog wizard uses to filter products.
    Safe to expose publicly — contains only question text and option labels,
    no lead data, no credentials, no internal IDs.
    Returns [] if no qualification_flow or no filterable questions configured.
    """
    if not qualification_flow:
        return []
    wizard = []
    for q in (qualification_flow.get("questions") or []):
        tag_key = q.get("map_to_catalog_tag")
        if not tag_key:
            continue
        options = []
        for opt in (q.get("options") or []):
            tag_value = opt.get("tag_value")
            if not tag_value:
                continue
            options.append({
                "id":        opt.get("id"),
                "label":     opt.get("label"),
                "tag_value": tag_value,
            })
        if not options:
            continue
        wizard.append({
            "text":               q.get("text") or "",
            "map_to_catalog_tag": tag_key,
            "options":            options,
        })
    return wizard


def _fetch_org_by_slug(db, org_slug: str) -> dict:
    """Fetch org row by slug. Raises 404 if not found."""
    result = (
        db.table("organisations")
        .select("id, name, slug, org_whatsapp_number, catalog_config, qualification_flow")
        .eq("slug", org_slug)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Catalog not found.")
    return rows[0]


def _fetch_visible_items(db, org_id: str) -> List[dict]:
    """Fetch all catalog_visible=True items for org."""
    result = (
        db.table("products")
        .select(
            "id, title, slug, description, catalog_description, price, catalog_images, "
            "extra_catalog_images, tags, custom_fields, available, catalog_views"
        )
        .eq("org_id", org_id)
        .eq("catalog_visible", True)
        .execute()
    )
    return result.data or []


async def _increment_catalog_views(org_id: str, item_id: str) -> None:
    """Fire-and-forget: increment catalog_views. Never blocks response."""
    try:
        db = get_supabase()
        # Read current count then increment — Supabase JS SDK supports .increment()
        # but Python client requires a read-modify-write.
        result = (
            db.table("products")
            .select("catalog_views")
            .eq("org_id", org_id)
            .eq("id", item_id)
            .execute()
        )
        rows = result.data or []
        if rows:
            current = rows[0].get("catalog_views") or 0
            db.table("products").update({
                "catalog_views": current + 1,
                "updated_at":    datetime.now(timezone.utc).isoformat(),
            }).eq("org_id", org_id).eq("id", item_id).execute()
    except Exception as exc:
        logger.warning("catalog_views increment failed item=%s: %s", item_id, exc)


# ---------------------------------------------------------------------------
# Routes — Pattern 53: static before parameterised
# /api/v1/public/catalog/{org_slug}/search  ← static sub-path
# /api/v1/public/catalog/{org_slug}         ← parameterised (list)
# /api/v1/public/catalog/{org_slug}/{item_slug} ← fully parameterised
# ---------------------------------------------------------------------------

@router.get("/public/catalog/{org_slug}/search")
async def search_catalog(
    org_slug: str,
    request:  Request,
    q:        str = Query(..., min_length=1, max_length=200),
):
    """
    Text search across title + description.
    Python-side filter (Pattern 33). No auth required.
    """
    _check_rate_limit(request)
    db = get_supabase()
    org = _fetch_org_by_slug(db, org_slug)
    org_id = org["id"]
    catalog_config = org.get("catalog_config") or {}
    pub_config = _public_config_fields(catalog_config)
    price_template   = pub_config["price_label_template"]
    price_on_request = pub_config["price_on_request"]

    items = _fetch_visible_items(db, org_id)

    # Pattern 33 — Python-side case-insensitive search
    q_lower = q.lower()
    matched = [
        i for i in items
        if q_lower in (i.get("title") or "").lower()
        or q_lower in (i.get("description") or "").lower()
    ]

    return {
        "org_name":      org.get("name"),
        "catalog_config": pub_config,
        "wa_number":     org.get("org_whatsapp_number"),
        "items":         [_public_item_fields(i, price_template, price_on_request) for i in matched],
        "count":         len(matched),
        "query":         q,
    }


@router.get("/public/catalog/{org_slug}")
async def list_catalog(
    org_slug: str,
    request:  Request,
):
    """
    List all visible catalog items for an org.
    Supports ?tag_key=value filters (e.g. ?health_conditions=Back+Pain).
    5-minute in-process cache per org_slug.
    No auth required.
    """
    _check_rate_limit(request)

    # Extract tag filters from query params (exclude FastAPI internals)
    raw_params = dict(request.query_params)

    # Cache — keyed by org_slug + sorted query string for filter variants
    cache_key = f"{org_slug}:{sorted(raw_params.items())}"
    cached = _cache_get(_list_cache, cache_key, _LIST_TTL)
    if cached:
        return cached

    db = get_supabase()
    org = _fetch_org_by_slug(db, org_slug)
    org_id = org["id"]
    catalog_config = org.get("catalog_config") or {}
    pub_config = _public_config_fields(catalog_config)
    price_template   = pub_config["price_label_template"]
    price_on_request = pub_config["price_on_request"]

    items = _fetch_visible_items(db, org_id)

    # Tag filtering — Pattern 33 Python-side
    if raw_params:
        tag_dimensions = pub_config.get("tag_dimensions") or []
        valid_tag_keys = {d["key"] for d in tag_dimensions}
        active_filters = {
            k: v for k, v in raw_params.items()
            if k in valid_tag_keys
        }
        if active_filters:
            def _matches(item: dict) -> bool:
                item_tags = item.get("tags") or {}
                for tag_key, tag_value in active_filters.items():
                    item_tag_val = item_tags.get(tag_key)
                    if item_tag_val is None:
                        return False
                    # single_select: direct match
                    # multi_select: tag value is a list — check membership
                    if isinstance(item_tag_val, list):
                        if tag_value not in item_tag_val:
                            return False
                    else:
                        if str(item_tag_val).lower() != tag_value.lower():
                            return False
                return True
            items = [i for i in items if _matches(i)]

    response = {
        "org_name":        org.get("name"),
        "catalog_config":  pub_config,
        "wa_number":       org.get("org_whatsapp_number"),
        "wizard_questions": _extract_wizard_questions(org.get("qualification_flow")),
        "items":           [_public_item_fields(i, price_template, price_on_request) for i in items],
        "count":           len(items),
    }
    _cache_set(_list_cache, cache_key, response)
    return response


@router.get("/public/catalog/{org_slug}/{item_slug}")
async def get_catalog_item(
    org_slug:  str,
    item_slug: str,
    request:   Request,
):
    """
    Single catalog item by slug.
    Increments catalog_views counter fire-and-forget.
    2-minute in-process cache per item.
    404 if org_slug unknown, item_slug unknown, or catalog_visible=False.
    No auth required.
    """
    _check_rate_limit(request)

    cache_key = f"{org_slug}/{item_slug}"
    cached = _cache_get(_item_cache, cache_key, _ITEM_TTL)
    if cached:
        # Still fire view increment even on cache hit — visitor is real
        asyncio.create_task(
            _increment_catalog_views(cached["_org_id"], cached["item"]["id"])
        )
        return {k: v for k, v in cached.items() if not k.startswith("_")}

    db = get_supabase()
    org = _fetch_org_by_slug(db, org_slug)
    org_id = org["id"]
    catalog_config = org.get("catalog_config") or {}
    pub_config = _public_config_fields(catalog_config)
    price_template   = pub_config["price_label_template"]
    price_on_request = pub_config["price_on_request"]

    result = (
        db.table("products")
        .select(
            "id, title, slug, description, catalog_description, price, catalog_images, "
            "extra_catalog_images, tags, custom_fields, available, catalog_views, variants"
        )
        .eq("org_id", org_id)
        .eq("slug", item_slug)
        .eq("catalog_visible", True)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found.")

    item = rows[0]
    pub_item = _public_item_fields(item, price_template, price_on_request)

    response = {
        "org_name":       org.get("name"),
        "catalog_config": pub_config,
        "wa_number":     org.get("org_whatsapp_number"),
        "item":           pub_item,
    }

    # Cache with internal org_id for view increment (stripped before return)
    _cache_set(_item_cache, cache_key, {**response, "_org_id": org_id})

    # Fire-and-forget view increment — never blocks response
    asyncio.create_task(_increment_catalog_views(org_id, item["id"]))

    return response
