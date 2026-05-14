"""
app/services/messenger_service.py
----------------------------------
UNIFIED-INBOX-1B — Facebook Messenger two-way integration.

Covers:
  - _get_org_messenger_credentials()  — per-org Page ID + Page Access Token
  - get_org_by_messenger_page_id()    — org lookup by Facebook Page ID
  - is_messenger_window_open()        — 24-hour window check (Messenger-channel messages)
  - send_messenger_message()          — outbound text via Graph API /me/messages

All credentials are stored per-org in organisations:
  messenger_page_id            — Facebook Page ID (e.g. "123456789")
  messenger_page_access_token  — Long-lived Page Access Token

Pages API: POST https://graph.facebook.com/v18.0/me/messages?access_token={token}

S14: _get_org_messenger_credentials() and get_org_by_messenger_page_id() never raise.
     send_messenger_message() raises HTTPException on hard failure (so the route
     can return a meaningful error code to the frontend).

Pattern 48: workers must use get_supabase() directly — never import db from here.
Pattern 68 (extended): credentials always fetched from DB, never from env vars.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ---------------------------------------------------------------------------
# Credentials helper
# ---------------------------------------------------------------------------

def _get_org_messenger_credentials(db, org_id: str) -> tuple[Optional[str], Optional[str]]:
    """
    Return (page_id, page_access_token) for the given org.
    Reads messenger_page_id and messenger_page_access_token from organisations.

    S14: never raises. Returns (None, None) on any exception or missing config.
    """
    try:
        result = (
            db.table("organisations")
            .select("messenger_page_id, messenger_page_access_token")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        row = data or {}

        page_id      = row.get("messenger_page_id") or None
        access_token = row.get("messenger_page_access_token") or None

        if not access_token:
            logger.warning(
                "_get_org_messenger_credentials: org %s has no "
                "messenger_page_access_token — Messenger integration not configured.",
                org_id,
            )
            return None, None

        return page_id, access_token

    except Exception as exc:
        logger.warning(
            "_get_org_messenger_credentials failed org=%s: %s", org_id, exc
        )
        return None, None


# ---------------------------------------------------------------------------
# Org lookup by Facebook Page ID
# ---------------------------------------------------------------------------

def get_org_by_messenger_page_id(db, page_id: str) -> Optional[str]:
    """
    Return the org_id whose messenger_page_id matches page_id.
    Used by the webhook worker to route inbound events to the correct org.

    S14: returns None on any failure.
    """
    if not page_id:
        return None
    try:
        result = (
            db.table("organisations")
            .select("id, messenger_page_id")
            .execute()
        )
        for row in (result.data or []):
            stored = (row.get("messenger_page_id") or "").strip()
            if stored and stored == page_id.strip():
                return row["id"]
    except Exception as exc:
        logger.warning(
            "get_org_by_messenger_page_id failed page_id=%s: %s", page_id, exc
        )
    return None


# ---------------------------------------------------------------------------
# 24-hour conversation window check
# ---------------------------------------------------------------------------

def is_messenger_window_open(db, org_id: str, lead_id: str) -> bool:
    """
    Return True if the 24-hour Messenger conversation window is open.

    Checks whatsapp_messages where channel='messenger' for this lead.
    Primary:  window_expires_at
    Fallback: created_at age < 24 hours

    S14: returns False on any exception.
    """
    try:
        result = (
            db.table("whatsapp_messages")
            .select("window_open, window_expires_at, created_at")
            .eq("org_id", org_id)
            .eq("lead_id", lead_id)
            .eq("channel", "messenger")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else (
            [result.data] if result.data else []
        )
        if not rows:
            return False

        msg = rows[0]

        # Primary: window_expires_at
        expires_raw = msg.get("window_expires_at")
        if expires_raw:
            if isinstance(expires_raw, str):
                expires_dt = datetime.fromisoformat(
                    expires_raw.replace("Z", "+00:00")
                )
            else:
                expires_dt = expires_raw
            return expires_dt > datetime.now(timezone.utc)

        # Fallback: created_at age
        created_raw = msg.get("created_at")
        if created_raw:
            if isinstance(created_raw, str):
                created_dt = datetime.fromisoformat(
                    created_raw.replace("Z", "+00:00")
                )
            else:
                created_dt = created_raw
            age_seconds = (
                datetime.now(timezone.utc) - created_dt
            ).total_seconds()
            return age_seconds < 86400  # 24 hours

        return False

    except Exception:
        return False


# ---------------------------------------------------------------------------
# Outbound send
# ---------------------------------------------------------------------------

def send_messenger_message(
    db,
    org_id: str,
    lead_id: str,
    psid: str,
    text: str,
    sent_by: Optional[str] = None,
) -> dict:
    """
    Send an outbound text message to a Messenger user via the Graph API.

    Parameters:
        psid     — Facebook-scoped Page-Scoped User ID (stored as messenger_psid
                   on the leads table; populated on first inbound message)
        sent_by  — user UUID of the rep sending, or None for system sends

    Returns the whatsapp_messages row that was inserted.

    Raises HTTPException(503) on Meta API failure or missing credentials.
    Auto-pauses AI (set_ai_paused) when sent_by is a human rep. S14.

    Window enforcement is done at the route level before calling this function.
    """
    from fastapi import HTTPException

    page_id, access_token = _get_org_messenger_credentials(db, org_id)
    if not access_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "No Facebook Messenger credentials configured for this org. "
                "Admin must set messenger_page_access_token via Admin → Integrations."
            ),
        )

    # Graph API send endpoint — uses Page Access Token as query param (standard)
    url = f"{GRAPH_API_BASE}/me/messages"
    meta_payload = {
        "recipient":      {"id": psid},
        "message":        {"text": text},
        "messaging_type": "RESPONSE",  # reply within 24h window
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                json=meta_payload,
                params={"access_token": access_token},
            )
        if resp.status_code not in (200, 201):
            logger.warning(
                "send_messenger_message: Meta returned %s org=%s — %s",
                resp.status_code, org_id, resp.text,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Meta Messenger API error {resp.status_code}: {resp.text}",
            )
        meta_response = resp.json()

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "send_messenger_message: network error org=%s: %s", org_id, exc
        )
        raise HTTPException(
            status_code=503,
            detail="Messenger API network error — please try again",
        )

    # Persist to whatsapp_messages (channel='messenger')
    now_ts = datetime.now(timezone.utc).isoformat()
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()

    row: dict = {
        "org_id":            org_id,
        "lead_id":           lead_id,
        "direction":         "outbound",
        "message_type":      "text",
        "channel":           "messenger",
        "content":           text,
        "status":            "sent",
        "meta_message_id":   meta_response.get("message_id"),
        "window_open":       True,
        "window_expires_at": window_expires,
        "sent_by":           sent_by,
        "created_at":        now_ts,
    }

    insert_result = db.table("whatsapp_messages").insert(row).execute()
    msg_data = insert_result.data
    if isinstance(msg_data, list):
        msg_data = msg_data[0] if msg_data else row

    # Auto-pause AI when a human rep sends from the Conversations module.
    # S14 — never blocks the send response.
    try:
        if sent_by:
            from app.services.whatsapp_service import set_ai_paused
            set_ai_paused(
                db=db,
                org_id=org_id,
                contact_type="lead",
                contact_id=lead_id,
                paused=True,
            )
    except Exception as exc:
        logger.warning(
            "send_messenger_message: auto-pause AI failed lead=%s: %s",
            lead_id, exc,
        )

    return msg_data
