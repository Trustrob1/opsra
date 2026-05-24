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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_current_org, get_supabase
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
router = APIRouter()

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


class CatalogItemUpdate(BaseModel):
    tags:                  Optional[Dict[str, Any]] = None
    custom_fields:         Optional[Dict[str, Any]] = None
    catalog_visible:       Optional[bool]           = None
    slug:                  Optional[str]            = Field(None, max_length=200)
    catalog_images:        Optional[List[str]]      = None
    extra_catalog_images:  Optional[List[str]]      = None
    catalog_description:   Optional[str]            = Field(None, max_length=20000)
    available:             Optional[bool]           = None   # non-Shopify only
    inventory_count:       Optional[int]            = None   # non-Shopify only

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
    available:       bool           = True
    inventory_count: Optional[int]  = None


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
    return {"catalog_config": config}


@router.patch("/config")
async def patch_config(
    body: CatalogConfigUpdate,
    current_org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    _require_catalog_role(current_org)
    # model_dump() in Pydantic v2 serialises nested models to plain dicts
    updates = body.model_dump(exclude_none=True)
    try:
        config = update_catalog_config(db, current_org["org_id"], updates)
        return {"catalog_config": config}
    except Exception as exc:
        logger.warning("patch_config failed org=%s: %s", current_org["org_id"], exc)
        raise HTTPException(status_code=500, detail="Failed to update catalog config.")


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

    # Guard: Shopify orgs cannot manually override availability/inventory
    if "available" in updates or "inventory_count" in updates:
        config = get_catalog_config(db, org_id)
        if (config.get("external_sync") or "none") == "shopify":
            raise HTTPException(
                status_code=403,
                detail="Availability and inventory are managed by Shopify sync for this org.",
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
