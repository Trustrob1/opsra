"""
app/services/instagram_service.py
UNIFIED-INBOX-1A — Instagram DM two-way messaging service.

Mirrors the pattern of whatsapp_service.py:
  - _get_org_instagram_credentials() → (page_id, access_token)
  - _call_instagram_send()           → calls Meta Graph API
  - send_instagram_message()         → full send + persist to whatsapp_messages
  - _is_instagram_window_open()      → 24-hour window check for Instagram

All functions S14: never raise to caller unless documented.
No PII in any log statement (no full names, phone numbers, or message content).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException

from app.models.common import ErrorCode

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ---------------------------------------------------------------------------
# Credentials helper
# ---------------------------------------------------------------------------

def _get_org_instagram_credentials(db, org_id: str) -> tuple[Optional[str], Optional[str]]:
    """
    Return (instagram_page_id, instagram_access_token) for the given org.
    Reads from organisations table.

    Returns (None, None) if not configured or on any error.
    S14: never raises.
    """
    try:
        result = (
            db.table("organisations")
            .select("instagram_page_id, instagram_access_token")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        row = data or {}

        page_id      = row.get("instagram_page_id") or None
        access_token = row.get("instagram_access_token") or None

        if not access_token:
            logger.warning(
                "_get_org_instagram_credentials: org %s has no instagram_access_token — "
                "Instagram integration not configured.",
                org_id,
            )
            return None, None

        if not page_id:
            logger.warning(
                "_get_org_instagram_credentials: org %s has no instagram_page_id — "
                "Instagram integration not configured.",
                org_id,
            )
            return None, None

        return page_id, access_token

    except Exception as exc:
        logger.warning(
            "_get_org_instagram_credentials failed for org %s: %s", org_id, exc
        )
        return None, None


# ---------------------------------------------------------------------------
# Meta Graph API caller
# ---------------------------------------------------------------------------

def _call_instagram_send(
    meta_payload: dict,
    access_token: str,
    timeout: float = 15.0,
) -> dict:
    """
    Send an Instagram DM via the Meta Graph API.
    POST /v18.0/me/messages

    Returns the Meta API response dict.
    Raises RuntimeError on non-2xx or network failure so the caller
    can handle gracefully (S14 at the caller level).
    """
    url = f"{GRAPH_API_BASE}/me/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=meta_payload, headers=headers)
        if resp.status_code not in (200, 201):
            if resp.status_code in (401, 403):
                logger.error(
                    "_call_instagram_send: token invalid or expired — HTTP %s. "
                    "Regenerate Instagram access token and update organisations table.",
                    resp.status_code,
                )
            else:
                logger.warning(
                    "_call_instagram_send: Meta returned %s — body: %s",
                    resp.status_code, resp.text[:300],
                )
            raise RuntimeError(
                f"Meta Instagram API returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()
    except RuntimeError:
        raise
    except httpx.RequestError as exc:
        logger.warning("_call_instagram_send: network error — %s", exc)
        raise RuntimeError(f"Network error calling Meta Instagram API: {exc}") from exc


# ---------------------------------------------------------------------------
# 24-hour window check
# ---------------------------------------------------------------------------

def _is_instagram_window_open(db, org_id: str, lead_id: str) -> bool:
    """
    Return True if the Instagram 24-hour messaging window is open for this lead.

    Instagram enforces the same 24-hour window as WhatsApp — free-form replies
    are only allowed within 24 hours of the last inbound message.

    Checks the most recent inbound whatsapp_messages row for this lead
    where channel = 'instagram'.

    S14: returns False on any failure.
    """
    try:
        result = (
            db.table("whatsapp_messages")
            .select("created_at, window_expires_at")
            .eq("org_id", org_id)
            .eq("lead_id", lead_id)
            .eq("channel", "instagram")
            .eq("direction", "inbound")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
        if not rows:
            return False

        msg = rows[0]

        # Primary: window_expires_at
        expires_raw = msg.get("window_expires_at")
        if expires_raw:
            if isinstance(expires_raw, str):
                expires_dt = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            else:
                expires_dt = expires_raw
            return expires_dt > datetime.now(timezone.utc)

        # Fallback: created_at < 24 hours ago
        created_raw = msg.get("created_at")
        if created_raw:
            if isinstance(created_raw, str):
                created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            else:
                created_dt = created_raw
            age_seconds = (datetime.now(timezone.utc) - created_dt).total_seconds()
            return age_seconds < 86_400

        return False

    except Exception as exc:
        logger.warning(
            "_is_instagram_window_open failed org=%s lead=%s: %s", org_id, lead_id, exc
        )
        return False


# ---------------------------------------------------------------------------
# Outbound send
# ---------------------------------------------------------------------------

def send_instagram_message(
    db,
    org_id: str,
    lead_id: str,
    instagram_scoped_id: str,
    text: str,
    sent_by: Optional[str] = None,
) -> dict:
    """
    Send an outbound Instagram DM to a lead and persist it to whatsapp_messages.

    Args:
        db                  : Supabase client
        org_id              : Organisation UUID (from JWT — never from request body)
        lead_id             : Lead UUID — must exist and belong to org
        instagram_scoped_id : Recipient's Instagram-scoped user ID
        text                : Message body (max 1000 chars enforced by Meta)
        sent_by             : User UUID of the rep sending (None = system)

    Returns:
        The inserted whatsapp_messages row dict.

    Raises:
        HTTPException 400  — conversation window is closed
        HTTPException 422  — missing credentials or instagram_scoped_id
        HTTPException 503  — Meta API failure
    """
    if not instagram_scoped_id:
        raise HTTPException(
            status_code=422,
            detail="instagram_scoped_id is required to send an Instagram DM",
        )

    # Check 24-hour window
    if not _is_instagram_window_open(db, org_id, lead_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Instagram conversation window is closed. "
                "You can only reply within 24 hours of the last inbound message."
            ),
        )

    # Fetch credentials
    page_id, access_token = _get_org_instagram_credentials(db, org_id)
    if not access_token:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{ErrorCode.INTEGRATION_ERROR} — "
                "Instagram integration not configured for this organisation"
            ),
        )

    # Truncate text to Meta's 1000-char limit
    text = text[:1000]

    # Build Meta payload
    meta_payload = {
        "recipient": {"id": instagram_scoped_id},
        "message":   {"text": text},
        "messaging_type": "RESPONSE",
    }

    # Call Meta API
    try:
        _call_instagram_send(meta_payload, access_token)
    except RuntimeError as exc:
        logger.warning(
            "send_instagram_message: Meta call failed org=%s lead=%s: %s",
            org_id, lead_id, exc,
        )
        raise HTTPException(
            status_code=503,
            detail=f"{ErrorCode.INTEGRATION_ERROR} — {exc}",
        )

    # Persist to whatsapp_messages
    now_ts = datetime.now(timezone.utc).isoformat()
    window_expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    row: dict = {
        "org_id":              org_id,
        "lead_id":             lead_id,
        "channel":             "instagram",
        "direction":           "outbound",
        "message_type":        "text",
        "content":             text,
        "status":              "sent",
        "instagram_scoped_id": instagram_scoped_id,
        "window_open":         True,
        "window_expires_at":   window_expires,
        "sent_by":             sent_by,
        "created_at":          now_ts,
    }

    try:
        insert_result = db.table("whatsapp_messages").insert(row).execute()
        inserted = insert_result.data
        if isinstance(inserted, list):
            inserted = inserted[0] if inserted else row
        return inserted if inserted else row
    except Exception as exc:
        logger.warning(
            "send_instagram_message: DB insert failed org=%s lead=%s: %s",
            org_id, lead_id, exc,
        )
        # Message was sent to Meta successfully — return the row even if DB write failed
        return row


# ---------------------------------------------------------------------------
# Org lookup by instagram_page_id (used by webhook worker)
# ---------------------------------------------------------------------------

def lookup_org_by_instagram_page_id(db, page_id: str) -> Optional[str]:
    """
    Return org_id for the given Instagram page_id, or None if not found.
    Used by the Instagram webhook worker to route inbound messages.
    S14: returns None on any failure.
    """
    if not page_id:
        return None
    try:
        result = (
            db.table("organisations")
            .select("id")
            .eq("instagram_page_id", page_id)
            .eq("is_live", True)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        return (data or {}).get("id") or None
    except Exception as exc:
        logger.warning(
            "lookup_org_by_instagram_page_id failed page_id=%s: %s", page_id, exc
        )
        return None
