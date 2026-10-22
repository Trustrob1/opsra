"""
app/routers/catalog.py
-----------------------
CATALOG-2A: Authenticated catalog admin routes.
All routes: org_id from JWT only (S1). Owner/ops_manager RBAC required.
Pattern 53: static routes registered before parameterised routes.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_current_org, get_supabase
from app.services import catalog_storefront_service as storefront   # STORE-1
from app.services import catalog_category_service as categories     # STORE-1b
from app.services.catalog_service import (
    SlugConflictError,
    create_catalog_item,
    delete_catalog_image,
    delete_extra_catalog_image,
    get_catalog_config,
    get_catalog_item,
    get_catalog_items,
    update_catalog_config,
    update_catalog_item,
    upload_catalog_image,
    upload_extra_catalog_image,
)

logger = logging.getLogger(__name__)
from app.services import plan_gate_service as _plan_gate  # AP-5: the plan decides whether this screen is available
router = APIRouter(dependencies=[Depends(_plan_gate.require("selling_catalog"))])

_CATALOG_ROLES  = {"owner", "ops_manager"}
_MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 5 MB — S10
_ALLOWED_MIME   = {"image/jpeg", "image/png", "image/webp"}


# ---------------------------------------------------------------------------
# RBAC helper
# ---------------------------------------------------------------------------

def _require_catalog_role(current_org: dict) -> None:
    """Raise 403 if the requesting user is not owner or ops_manager."""
    roles_obj = current_org.get("roles") or {}
    template = (roles_obj.get("template") or "").lower()
    if template not in _CATALOG_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Catalog management requires owner or ops_manager role.",
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AvailabilityLabels(BaseModel):
    available:   str = Field(..., max_length=50)
    unavailable: str = Field(..., max_length=50)


class CTAButton(BaseModel):
    id:    str = Field(..., max_length=50)
    label: str = Field(..., max_length=24)

    @field_validator("id")
    @classmethod
    def id_alphanumeric(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Button ID must contain only letters, numbers, and underscores.")
        return v


class TagDimension(BaseModel):
    key:        str       = Field(..., max_length=50)
    label:      str       = Field(..., max_length=50)
    type:       str       = Field(..., pattern=r'^(single_select|multi_select)$')
    filterable: bool      = True
    options:    List[str] = Field(..., max_length=20)

    @field_validator("key")
    @classmethod
    def key_alphanumeric(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Tag dimension key must contain only letters, numbers, and underscores.")
        return v


class CatalogConfigUpdate(BaseModel):
    catalog_item_label:        Optional[str]                 = Field(None, max_length=50)
    catalog_item_label_plural: Optional[str]                 = Field(None, max_length=50)
    price_label_template:      Optional[str]                 = Field(None, max_length=50)
    price_on_request:          Optional[bool]                = None
    availability_labels:       Optional[AvailabilityLabels]  = None
    cta_buttons:               Optional[List[CTAButton]]     = Field(None, min_length=2, max_length=3)
    tag_dimensions:            Optional[List[TagDimension]]  = Field(None, max_length=10)
    # STORE-1: Storefront look (template needs the catalog_storefront plan feature to be set to "storefront")
    template:                  Optional[Literal["classic", "storefront"]] = None
    announcement:              Optional[str]                 = Field(None, max_length=storefront.ANNOUNCEMENT_MAX)
    trust_points:              Optional[List[str]]           = Field(None, max_length=storefront.TRUST_POINTS_MAX)
    accent:                    Optional[str]                 = Field(None, pattern=r'^(#[0-9a-fA-F]{6})?$')
    logo_url:                  Optional[str]                 = Field(None, max_length=storefront.LOGO_URL_MAX)

    @field_validator("trust_points")
    @classmethod
    def trust_points_short(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        out = [" ".join(str(p or "").split()) for p in v]
        if any(len(p) > storefront.TRUST_POINT_CHARS for p in out):
            raise ValueError(f"Each point must be {storefront.TRUST_POINT_CHARS} characters or fewer.")
        return [p for p in out if p]

    @field_validator("logo_url")
    @classmethod
    def logo_https(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if storefront.clean_https_url(v) is None:
            raise ValueError("Logo link must start with https:// and contain no spaces.")
        return v


class CatalogItemUpdate(BaseModel):
    tags:                  Optional[Dict[str, Any]]       = None
    custom_fields:         Optional[Dict[str, Any]]       = None
    catalog_visible:       Optional[bool]                 = None
    slug:                  Optional[str]                  = Field(None, max_length=200)
    catalog_images:        Optional[List[str]]            = None
    extra_catalog_images:  Optional[List[str]]            = None
    catalog_description:   Optional[str]                  = Field(None, max_length=20000)
    available:             Optional[bool]                 = None                           # non-Shopify only
    inventory_count:       Optional[int]                  = None                           # non-Shopify only
    title:                 Optional[str]                  = Field(None, max_length=500)    # non-Shopify only
    description:           Optional[str]                  = Field(None, max_length=5000)   # non-Shopify only
    price:                 Optional[float]                = None                           # non-Shopify only
    variants:              Optional[List[Dict[str, Any]]] = None                           # non-Shopify only

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r'^[a-z0-9-]+$', v):
            raise ValueError("Slug must be lowercase letters, numbers, and hyphens only.")
        return v


class CatalogItemCreate(BaseModel):
    title:           str            = Field(..., max_length=500)
    price:           Optional[float]= None
    description:     Optional[str]  = Field(None, max_length=5000)  # S4
    tags:            Optional[Dict[str, Any]] = None
    custom_fields:   Optional[Dict[str, Any]] = None
    available:       bool                           = True
    inventory_count: Optional[int]                  = None
    variants:        Optional[List[Dict[str, Any]]] = None   # non-Shopify only


# ---------------------------------------------------------------------------
# Routes — Pattern 53: static routes before parameterised
# ---------------------------------------------------------------------------

# ── Config (fully static) ───────────────────────────────────────────────────

@router.get("/config")
async def get_config(
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    config = get_catalog_config(db, current_org["org_id"])
    return {"catalog_config": config, "storefront_allowed": storefront.storefront_allowed(db, current_org["org_id"])}


@router.patch("/config")
async def patch_config(
    body: CatalogConfigUpdate,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    # model_dump() in Pydantic v2 serialises nested models to plain dicts
    updates = body.model_dump(exclude_none=True)
    # STORE-1: only a plan that includes the Storefront look can switch it on (switching back to classic is always allowed)
    if updates.get("template") == "storefront" and not storefront.storefront_allowed(db, current_org["org_id"]):
        raise _plan_gate.http_error()
    # STORE-1b: the generic tag editor can never drop or change the category group
    if "tag_dimensions" in updates:
        updates["tag_dimensions"] = categories.keep_category(
            get_catalog_config(db, current_org["org_id"]).get("tag_dimensions"), updates["tag_dimensions"])
    try:
        config = update_catalog_config(db, current_org["org_id"], updates)
        return {"catalog_config": config, "storefront_allowed": storefront.storefront_allowed(db, current_org["org_id"])}
    except Exception as exc:
        logger.warning("patch_config failed org=%s: %s", current_org["org_id"], exc)
        raise HTTPException(status_code=500, detail="Failed to update catalog config.")


# ── Categories (STORE-1b) — static routes ──────────────────────────────────

class CategoryEntry(BaseModel):
    name: str = Field(..., max_length=200)
    was:  Optional[str] = Field(None, max_length=200)      # the old name, when this is a rename


class CategoriesSave(BaseModel):
    categories:   List[CategoryEntry] = Field(..., max_length=categories.MAX_CATEGORIES)
    show_in_menu: Optional[bool] = None


class CategoryAdd(BaseModel):
    name: str = Field(..., max_length=200)


class CategoryItems(BaseModel):
    item_ids: List[str] = Field(default_factory=list, max_length=2000)


def _category_call(fn, *args):
    try:
        return fn(*args)
    except categories.CategoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.warning("categories call failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update categories.")


@router.get("/categories")
async def get_categories(
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    return categories.list_categories(db, current_org["org_id"])


@router.put("/categories")
async def save_categories(
    body: CategoriesSave,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    return _category_call(categories.save_categories, db, current_org["org_id"],
                          [e.model_dump() for e in body.categories], body.show_in_menu)


@router.post("/categories", status_code=201)
async def add_category(
    body: CategoryAdd,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    return _category_call(categories.add_category, db, current_org["org_id"], body.name)


@router.put("/categories/{name}/items")
async def set_category_items(
    name: str,
    body: CategoryItems,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    return _category_call(categories.set_category_items, db, current_org["org_id"], name, body.item_ids)


# ── Items — fully static routes ─────────────────────────────────────────────

@router.get("/items")
async def list_items(
    visible_only:   bool            = Query(False),
    available_only: bool            = Query(False),
    search:         Optional[str]   = Query(None, max_length=200),
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    items = get_catalog_items(
        db, current_org["org_id"],
        visible_only=visible_only,
        available_only=available_only,
        search=search,
    )
    return {"items": items, "count": len(items)}


@router.post("/items", status_code=201)
async def create_item(
    body: CatalogItemCreate,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Create new catalog item — non-Shopify orgs only."""
    _require_catalog_role(current_org)
    org_id = current_org["org_id"]

    config = get_catalog_config(db, org_id)
    if (config.get("external_sync") or "none") == "shopify":
        raise HTTPException(
            status_code=403,
            detail="Shopify-connected orgs manage products via Shopify. Items are created automatically during sync.",
        )
    try:
        item = create_catalog_item(db, org_id, body.model_dump())
        return {"item": item}
    except Exception as exc:
        logger.warning("create_item failed org=%s: %s", org_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create catalog item.")


# ── Items — static sub-path routes (must come before /{item_id}) ────────────

@router.get("/items/{item_id}/stats")
async def get_item_stats(
    item_id: str,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    item = get_catalog_item(db, current_org["org_id"], item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {
        "catalog_views": item.get("catalog_views", 0),
        "created_at":    item.get("created_at"),
        "updated_at":    item.get("updated_at"),
    }


@router.post("/items/{item_id}/images", status_code=201)
async def upload_image(
    item_id: str,
    file: UploadFile = File(...),
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Upload image to catalog item. Max 5 MB. Allowed: jpeg, png, webp."""
    _require_catalog_role(current_org)
    org_id = current_org["org_id"]

    # S10: MIME validation
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: image/jpeg, image/png, image/webp.",
        )

    file_bytes = await file.read()

    # S10: Size validation
    if len(file_bytes) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds the 5 MB limit.")

    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    try:
        public_url = upload_catalog_image(
            db, org_id, item_id,
            file_bytes,
            file.filename or "image.jpg",
            file.content_type,
        )
        return {"url": public_url}
    except Exception as exc:
        logger.warning("upload_image failed org=%s item=%s: %s", org_id, item_id, exc)
        raise HTTPException(status_code=500, detail="Image upload failed.")


@router.delete("/items/{item_id}/images/{image_index}", status_code=204)
async def delete_image(
    item_id:     str,
    image_index: int,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    try:
        delete_catalog_image(db, current_org["org_id"], item_id, image_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning(
            "delete_image failed org=%s item=%s idx=%s: %s",
            current_org["org_id"], item_id, image_index, exc,
        )
        raise HTTPException(status_code=500, detail="Image deletion failed.")

@router.post("/items/{item_id}/extra-images", status_code=201)
async def upload_extra_image(
    item_id: str,
    file: UploadFile = File(...),
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Upload extra catalog-only image. Never overwritten by Shopify sync."""
    _require_catalog_role(current_org)
    org_id = current_org["org_id"]

    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: image/jpeg, image/png, image/webp.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds the 5 MB limit.")

    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    try:
        public_url = upload_extra_catalog_image(
            db, org_id, item_id,
            file_bytes,
            file.filename or "image.jpg",
            file.content_type,
        )
        return {"url": public_url}
    except Exception as exc:
        logger.warning("upload_extra_image failed org=%s item=%s: %s", org_id, item_id, exc)
        raise HTTPException(status_code=500, detail="Image upload failed.")


@router.delete("/items/{item_id}/extra-images/{image_index}", status_code=204)
async def delete_extra_image(
    item_id:     str,
    image_index: int,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    try:
        delete_extra_catalog_image(db, current_org["org_id"], item_id, image_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning(
            "delete_extra_image failed org=%s item=%s idx=%s: %s",
            current_org["org_id"], item_id, image_index, exc,
        )
        raise HTTPException(status_code=500, detail="Extra image deletion failed.")

# ── Items — fully parameterised (must come last) ─────────────────────────────

@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    item = get_catalog_item(db, current_org["org_id"], item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"item": item}


@router.patch("/items/{item_id}")
async def patch_item(
    item_id: str,
    body:    CatalogItemUpdate,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    org_id  = current_org["org_id"]
    updates = body.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    # Guard: Shopify orgs cannot manually override fields managed by sync
    _SHOPIFY_MANAGED = {"available", "inventory_count", "title", "description", "price", "variants"}
    if updates.keys() & _SHOPIFY_MANAGED:
        config = get_catalog_config(db, org_id)
        if (config.get("external_sync") or "none") == "shopify":
            raise HTTPException(
                status_code=403,
                detail="Title, description, price, variants, availability and inventory are managed by Shopify sync for this org.",
            )

    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    try:
        updated = update_catalog_item(db, org_id, item_id, updates)
        return {"item": updated}
    except SlugConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.warning("patch_item failed org=%s item=%s: %s", org_id, item_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update item.")


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Soft delete — sets catalog_visible=False. Non-Shopify orgs only."""
    _require_catalog_role(current_org)
    org_id = current_org["org_id"]

    config = get_catalog_config(db, org_id)
    if (config.get("external_sync") or "none") == "shopify":
        raise HTTPException(
            status_code=403,
            detail="Shopify-connected orgs cannot delete items from Opsra. Manage products in Shopify.",
        )

    item = get_catalog_item(db, org_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    try:
        from datetime import datetime, timezone
        db.table("products").update({
            "catalog_visible": False,
            "updated_at":      datetime.now(timezone.utc).isoformat(),
        }).eq("org_id", org_id).eq("id", item_id).execute()
    except Exception as exc:
        logger.warning("delete_item failed org=%s item=%s: %s", org_id, item_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete item.")
