"""
app/routers/push_notifications.py
PWA-1: Push notification token endpoint + send utility.
Uses Supabase client (not SQLAlchemy) — consistent with rest of backend.
"""

import os
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.database import get_supabase
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["push_notifications"])

VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_SUBJECT     = os.getenv("VAPID_SUBJECT", "mailto:ops@opsra.io")


class PushTokenRequest(BaseModel):
    token:    str
    platform: str = "web"


@router.post("/push-token")
async def save_push_token(
    body:         PushTokenRequest,
    db=Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    if not body.token or not body.token.strip():
        raise HTTPException(status_code=422, detail="token is required")

    if len(body.token) > 512:
        raise HTTPException(status_code=422, detail="token exceeds maximum length")

    user_id = current_user.id

    try:
        db.table("users").update(
            {"push_token": body.token.strip()}
        ).eq("id", user_id).execute()
    except Exception as e:
        logger.error(f"[push-token] Failed to save push token for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save push token")

    return {"success": True, "message": "Push token saved"}


def send_push_notification(
    db,
    user_id: str,
    title:   str,
    body:    str,
    data:    dict | None = None,
    url:     str | None  = None,
) -> None:
    """
    Sends a Web Push notification to the given user if they have a push_token.
    S14: never raises — all exceptions are caught and logged.
    """
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return

    try:
        row = db.table("users").select("push_token").eq("id", user_id).maybe_single().execute()
        push_token = (row.data or {}).get("push_token")

        if not push_token:
            return

        try:
            subscription_info = json.loads(push_token)
        except json.JSONDecodeError:
            logger.warning(f"[push] Invalid push_token JSON for user {user_id} — clearing")
            db.table("users").update({"push_token": None}).eq("id", user_id).execute()
            return

        payload = {"title": title, "body": body}
        if data:
            payload["data"] = data
        if url:
            payload["data"] = {**(payload.get("data") or {}), "url": url}

        from pywebpush import webpush
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        logger.info(f"[push] Sent to user {user_id}: {title}")

    except Exception as e:
        logger.warning(f"[push] Send failed for user {user_id} (non-critical): {e}")