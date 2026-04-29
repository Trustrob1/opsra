"""
app/workers/meta_token_worker.py
---------------------------------
9E-A — Observability: Meta WhatsApp token validity checker.

Runs daily at 07:00 WAT (06:00 UTC).

For every active org that has a WhatsApp access token configured:
  1. Calls GET https://graph.facebook.com/v17.0/me?access_token={token}
  2. If the token is invalid (401/403 or any exception) → creates an
     in-app notification for the org owner so they can update it before
     WhatsApp messages stop working silently.
  3. Logs a Sentry warning for each invalid token found.

S14: a per-org failure never stops the loop.
PII rule: org_id and last 4 chars of token only — never log the full token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token validity check — called from worker and importable for tests
# ---------------------------------------------------------------------------

def check_meta_token_validity(db, org_id: str) -> bool:
    """
    Validate the org's WhatsApp access token by calling the Meta Graph API.

    Returns:
        True  — token is valid (HTTP 200)
        False — token is invalid (HTTP 401/403) or any exception occurred

    S14: never raises. Returns False on any exception.
    PII: logs only the last 4 characters of the token, never the full value.
    """
    try:
        result = (
            db.table("organisations")
            .select("whatsapp_access_token")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        token: str = (data or {}).get("whatsapp_access_token") or ""

        if not token:
            # No token configured — treat as not applicable, not invalid.
            return True

        url = f"https://graph.facebook.com/v17.0/me?access_token={token}"

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)

        if response.status_code == 200:
            return True

        # 401 / 403 → token invalid or revoked
        logger.warning(
            "Meta token invalid for org=%s — HTTP %s (token ...%s)",
            org_id,
            response.status_code,
            token[-4:],
        )
        sentry_sdk.capture_message(
            f"Meta WhatsApp token invalid for org {org_id}",
            level="warning",
        )
        return False

    except Exception as exc:
        logger.warning(
            "check_meta_token_validity failed for org=%s: %s", org_id, exc
        )
        sentry_sdk.capture_exception(exc)
        return False


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def _notify_owner(db, org_id: str) -> None:
    """
    Insert an in-app notification for the org owner warning about the
    invalid WhatsApp token.

    S14: never raises.
    """
    try:
        # Find the org owner
        owner_result = (
            db.table("users")
            .select("id")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        users = owner_result.data or []

        # Find owner by checking their role permissions
        # Fetch roles to identify owner role
        roles_result = (
            db.table("roles")
            .select("id, name")
            .eq("org_id", org_id)
            .execute()
        )
        roles = roles_result.data or []
        owner_role_ids = {
            r["id"] for r in roles
            if (r.get("name") or "").lower() == "owner"
        }

        owner_ids: list[str] = []
        if owner_role_ids:
            for user in users:
                role_check = (
                    db.table("user_roles")
                    .select("role_id")
                    .eq("user_id", user["id"])
                    .execute()
                )
                user_role_ids = {
                    ur["role_id"] for ur in (role_check.data or [])
                }
                if user_role_ids & owner_role_ids:
                    owner_ids.append(user["id"])

        if not owner_ids:
            logger.warning(
                "_notify_owner: no owner found for org=%s — skipping notification",
                org_id,
            )
            return

        now = datetime.now(timezone.utc).isoformat()
        notifications = [
            {
                "org_id": org_id,
                "user_id": owner_id,
                "type": "whatsapp_token_invalid",
                "title": "WhatsApp Token Invalid",
                "body": (
                    "Your WhatsApp access token is invalid or has expired. "
                    "All outbound WhatsApp messages are currently failing. "
                    "Please update your token in Settings → WhatsApp."
                ),
                "link": "/admin/settings/whatsapp",
                "channel": "inapp",
                "is_read": False,
                "created_at": now,
            }
            for owner_id in owner_ids
        ]

        db.table("notifications").insert(notifications).execute()

    except Exception as exc:
        logger.warning(
            "_notify_owner failed for org=%s: %s", org_id, exc
        )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.meta_token_worker.run_meta_token_check")
def run_meta_token_check() -> dict:
    """
    Daily task — 07:00 WAT (06:00 UTC).

    Iterates over every active org that has a WhatsApp access token set.
    Validates each token. If invalid, notifies the org owner via in-app
    notification.

    Returns a summary dict: {orgs_checked, invalid_tokens, notified, failed}
    S14: per-org failure never stops the loop.
    """
    db = get_supabase()
    summary = {"orgs_checked": 0, "invalid_tokens": 0, "notified": 0, "failed": 0}

    try:
        # Fetch all active orgs with a token configured.
        # Pattern 66: organisations has no deleted_at — filter by is_live.
        result = (
            db.table("organisations")
            .select("id, whatsapp_access_token")
            .eq("is_live", True)
            .not_.is_("whatsapp_access_token", "null")
            .neq("whatsapp_access_token", "")
            .execute()
        )
        orgs = result.data or []
    except Exception as exc:
        logger.warning("run_meta_token_check: failed to fetch orgs — %s", exc)
        sentry_sdk.capture_exception(exc)
        return summary

    for org in orgs:
        org_id: str = org.get("id", "")
        if not org_id:
            continue

        try:
            summary["orgs_checked"] += 1
            valid = check_meta_token_validity(db, org_id)

            if not valid:
                summary["invalid_tokens"] += 1
                _notify_owner(db, org_id)
                summary["notified"] += 1
                logger.warning(
                    "run_meta_token_check: invalid token detected org=%s — owner notified",
                    org_id,
                )
            else:
                logger.info(
                    "run_meta_token_check: token valid org=%s", org_id
                )

        except Exception as exc:
            # S14: per-org failure never stops the loop
            summary["failed"] += 1
            logger.warning(
                "run_meta_token_check: unhandled error for org=%s — %s", org_id, exc
            )
            sentry_sdk.capture_exception(exc)

    logger.info("run_meta_token_check complete: %s", summary)
    return summary
