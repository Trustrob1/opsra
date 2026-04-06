"""
backend/app/services/notifications_service.py
Notifications service — Phase 9.

Three public functions:
  list_notifications  — paginated list for a single user, includes unread_count
  mark_read           — mark one notification read by id
  mark_all_read       — bulk-mark all unread notifications for a user

Security:
  S1  — user_id and org_id always from JWT-derived org dict (passed in by router)
  S13 — no hard deletes; notifications are marked is_read=True, never removed

Pattern 33: all filtering is done Python-side after a broad .eq() fetch because
  the notifications table is user-scoped (not high volume per user).
  order("created_at", desc=True) is a PostgREST sort — safe to use server-side.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _one(data) -> Optional[dict]:
    """Normalise list-or-dict result from .maybe_single()."""
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ============================================================
# list_notifications
# ============================================================

def list_notifications(
    user_id: str,
    org_id: str,
    db,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Returns a paginated list of notifications for ``user_id`` within ``org_id``.
    Newest first.  Includes ``unread_count`` — total unread across ALL pages,
    not just the current page — so the topbar bell badge stays accurate.

    Pagination is Python-side (Pattern 33).
    Ordering (created_at desc) is server-side — safe PostgREST sort.
    """
    result = (
        db.table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    all_items: list = result.data or []

    # Unread count across ALL items — not just current page
    unread_count = sum(1 for n in all_items if not n.get("is_read"))

    # Paginate Python-side
    total = len(all_items)
    start = (page - 1) * page_size
    items = all_items[start: start + page_size]

    return {
        "items":        items,
        "total":        total,
        "page":         page,
        "page_size":    page_size,
        "has_more":     (start + page_size) < total,
        "unread_count": unread_count,
    }


# ============================================================
# mark_read
# ============================================================

def mark_read(
    notification_id: str,
    user_id: str,
    org_id: str,
    db,
) -> dict:
    """
    Mark a single notification as read.
    Scoped to user_id + org_id — cannot mark another user's notification.
    Raises 404 if not found or out of scope.
    """
    check = (
        db.table("notifications")
        .select("id, is_read, title, type, resource_type, resource_id, created_at")
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    record = _one(check.data)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Notification not found"},
        )

    if record.get("is_read"):
        # Already read — return without a write
        return record

    result = (
        db.table("notifications")
        .update({"is_read": True})
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {**record, "is_read": True}


# ============================================================
# mark_all_read
# ============================================================

def mark_all_read(user_id: str, org_id: str, db) -> None:
    """
    Bulk-mark all unread notifications for ``user_id`` as read.
    No-ops silently if there are no unread notifications.
    Never raises — failures are logged and swallowed (non-critical operation).
    """
    try:
        (
            db.table("notifications")
            .update({"is_read": True})
            .eq("user_id", user_id)
            .eq("org_id", org_id)
            .eq("is_read", False)
            .execute()
        )
    except Exception as exc:  # pragma: no cover
        logger.error("mark_all_read failed for user %s: %s", user_id, exc)
