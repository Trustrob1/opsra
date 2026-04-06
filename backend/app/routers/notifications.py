"""
app/routers/notifications.py
Notifications router — Phase 9.

Routes:
  GET    /api/v1/notifications             — paginated list + unread_count
  PATCH  /api/v1/notifications/read-all   — mark all read  ← static FIRST
  PATCH  /api/v1/notifications/{id}/read  — mark one read  ← parameterised AFTER

⚠️ Static route /read-all MUST be registered before /{id}/read.
   If the order is reversed FastAPI treats "read-all" as a notification UUID
   and routes it to the parameterised handler — causing a 404 or DB error.

Pattern 28: get_current_org on every route.
S1: user_id and org_id always from JWT — never from request body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from app.services import notifications_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── GET /api/v1/notifications ─────────────────────────────────────────────────

@router.get("")
async def list_notifications(
    page:      int = Query(1,  ge=1),
    page_size: int = Query(20, ge=1, le=100),
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns paginated notifications for the current user, newest first.
    Response data includes ``unread_count`` (total unread, all pages)
    so the topbar bell badge can be updated from a single API call.
    """
    result = notifications_service.list_notifications(
        user_id=org["id"],
        org_id=org["org_id"],
        db=db,
        page=page,
        page_size=page_size,
    )
    return ok(data=result)


# ── PATCH /api/v1/notifications/read-all — STATIC (must be before /{id}) ─────

@router.patch("/read-all")
async def mark_all_read(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Bulk-marks all unread notifications for the current user as read.
    Idempotent — safe to call when there are no unread notifications.
    """
    notifications_service.mark_all_read(
        user_id=org["id"],
        org_id=org["org_id"],
        db=db,
    )
    return ok(data={"message": "All notifications marked as read"})


# ── PATCH /api/v1/notifications/{id}/read — PARAMETERISED (after static) ─────

@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Marks a single notification as read.
    Scoped to the current user — cannot mark another user's notification.
    Returns 404 if not found or out of scope.
    """
    result = notifications_service.mark_read(
        notification_id=notification_id,
        user_id=org["id"],
        org_id=org["org_id"],
        db=db,
    )
    return ok(data=result)
