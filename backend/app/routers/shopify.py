"""
app/routers/shopify.py
-----------------------
SHOP-1A: Shopify Integration — admin routes.

Routes:
  GET    /api/v1/admin/shopify/status      — connection status + product count
  POST   /api/v1/admin/shopify/connect     — save credentials + trigger initial sync
  DELETE /api/v1/admin/shopify/disconnect  — clear credentials
  POST   /api/v1/admin/shopify/sync        — trigger manual product re-sync

RBAC: Owner + ops_manager only for all write routes.
      GET /status is readable by all authenticated org members.
Pattern 28 — get_current_org via Depends.
Pattern 62 — db via Depends(get_supabase).
S1 — org_id from JWT only.
S3 — Pydantic on all inputs.
S14 — service calls wrapped in try/except.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.routers.admin import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter()

_OWNER_ROLES = {"owner", "ops_manager"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ShopifyConnectRequest(BaseModel):
    shop_domain: str = Field(..., min_length=3, max_length=255,
        description="e.g. my-store.myshopify.com")
    access_token: str = Field(..., min_length=10, max_length=500)
    webhook_secret: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_owner(org: dict) -> None:
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in _OWNER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Only owners and ops managers can manage Shopify integration.",
                    "field": None,
                },
            },
        )


def _get_shopify_org(db, org_id: str) -> dict:
    result = (
        db.table("organisations")
        .select(
            "shopify_connected, shopify_shop_domain, shopify_last_sync_at"
        )
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    return data or {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/shopify/status")
def get_shopify_status(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    SHOP-1A: Return Shopify connection status + product count for this org.
    Readable by all authenticated org members.
    """
    org_data = _get_shopify_org(db, org["org_id"])
    connected = org_data.get("shopify_connected") or False
    shop_domain = org_data.get("shopify_shop_domain") or None
    last_sync_at = org_data.get("shopify_last_sync_at") or None

    product_count = 0
    if connected:
        try:
            count_r = (
                db.table("products")
                .select("id", count="exact")
                .eq("org_id", org["org_id"])
                .eq("is_active", True)
                .execute()
            )
            product_count = count_r.count or 0
        except Exception as exc:
            logger.warning("get_shopify_status: product count failed: %s", exc)

    return ok(data={
        "connected":    connected,
        "shop_domain":  shop_domain,
        "product_count": product_count,
        "last_sync_at": last_sync_at,
    })


@router.post("/shopify/connect", status_code=status.HTTP_200_OK)
def connect_shopify(
    payload: ShopifyConnectRequest,
    background_tasks: BackgroundTasks,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    SHOP-1A: Save Shopify credentials and trigger initial product sync.
    Owner + ops_manager only.
    """
    _require_owner(org)

    # Normalise domain — strip https:// if user includes it
    shop_domain = payload.shop_domain.strip().lower()
    shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/")

    now = datetime.now(timezone.utc).isoformat()
    db.table("organisations").update({
        "shopify_shop_domain":    shop_domain,
        "shopify_access_token":   payload.access_token.strip(),
        "shopify_webhook_secret": (payload.webhook_secret or "").strip() or None,
        "shopify_connected":      True,
        "updated_at":             now,
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="shopify.connected",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"shop_domain": shop_domain},
    )

    # Trigger initial product sync in background
    background_tasks.add_task(
        _run_bulk_sync,
        org_id=org["org_id"],
        access_token=payload.access_token.strip(),
        shop_domain=shop_domain,
    )

    return ok(
        data={"connected": True, "shop_domain": shop_domain},
        message="Shopify connected. Product sync started in the background.",
    )


@router.delete("/shopify/disconnect", status_code=status.HTTP_200_OK)
def disconnect_shopify(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    SHOP-1A: Clear Shopify credentials and mark as disconnected.
    Owner + ops_manager only.
    Does NOT delete synced products — they remain as a historical record.
    """
    _require_owner(org)

    now = datetime.now(timezone.utc).isoformat()
    db.table("organisations").update({
        "shopify_shop_domain":    None,
        "shopify_access_token":   None,
        "shopify_webhook_secret": None,
        "shopify_connected":      False,
        "updated_at":             now,
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="shopify.disconnected",
        resource_type="organisation", resource_id=org["org_id"],
    )

    return ok(data={"connected": False}, message="Shopify disconnected.")


@router.post("/shopify/sync", status_code=status.HTTP_200_OK)
def trigger_shopify_sync(
    background_tasks: BackgroundTasks,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    SHOP-1A: Trigger a manual product re-sync from Shopify.
    Owner + ops_manager only.
    Returns immediately — sync runs in background.
    """
    _require_owner(org)

    org_data = _get_shopify_org(db, org["org_id"])
    if not org_data.get("shopify_connected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Shopify is not connected for this organisation.",
                    "field": None,
                },
            },
        )

    # Fetch credentials for the sync task
    creds_r = (
        db.table("organisations")
        .select("shopify_access_token, shopify_shop_domain")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    creds_d = creds_r.data
    if isinstance(creds_d, list):
        creds_d = creds_d[0] if creds_d else None
    creds = creds_d or {}

    access_token = creds.get("shopify_access_token") or ""
    shop_domain = creds.get("shopify_shop_domain") or ""

    if not access_token or not shop_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Shopify credentials are incomplete. Please reconnect.",
                    "field": None,
                },
            },
        )

    background_tasks.add_task(
        _run_bulk_sync,
        org_id=org["org_id"],
        access_token=access_token,
        shop_domain=shop_domain,
    )

    return ok(
        data={"sync_started": True},
        message="Product sync started. Check back shortly.",
    )


# ---------------------------------------------------------------------------
# Background sync task
# ---------------------------------------------------------------------------

def _run_bulk_sync(org_id: str, access_token: str, shop_domain: str) -> None:
    """
    Background task: fetch a fresh db connection and run bulk_sync_products.
    S14 — never raises.
    """
    try:
        from app.database import get_supabase as _get_db
        from app.services.shopify_service import bulk_sync_products
        db = _get_db()
        result = bulk_sync_products(
            db=db,
            org_id=org_id,
            access_token=access_token,
            shop_domain=shop_domain,
        )
        logger.info(
            "_run_bulk_sync complete org=%s synced=%d failed=%d",
            org_id, result.get("synced", 0), result.get("failed", 0),
        )
    except Exception as exc:
        logger.warning("_run_bulk_sync failed org=%s: %s", org_id, exc)
