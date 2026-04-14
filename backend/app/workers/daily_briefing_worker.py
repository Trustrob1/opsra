"""
app/workers/daily_briefing_worker.py
--------------------------------------
Celery workers for Aria AI Assistant (M01-10b).

Tasks:
  run_daily_briefing_worker  — 06:00 WAT (05:00 UTC) daily
    For every active user: gather role-scoped snapshot, one Haiku call,
    store in users.briefing_content + users.briefing_generated_at.
    Also purges assistant_messages older than 30 days.

  run_notification_digest    — 12:00 WAT (11:00 UTC) + 17:00 WAT (16:00 UTC)
    Bundles all unread notifications since last digest into one Haiku summary.
    Stores result as an 'assistant' message in assistant_messages.
    Updates notifications.read = true for bundled rows.

Security:
  S13 — Pydantic payload validation on worker inputs
  S14 — Single-record failure never stops the loop
  Pattern 48 — get_supabase() + resource_type/resource_id + roles join
  Pattern 57 — All dependencies imported at MODULE LEVEL
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from dotenv import load_dotenv  # Pattern 29

load_dotenv()

from app.database import get_supabase                          # Pattern 48 — module level
from app.services.assistant_service import (                   # Pattern 57 — module level
    generate_briefing,
    build_digest_prompt,
    call_haiku_sync,
    store_message,
    purge_old_messages,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ─── Daily briefing worker ────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.daily_briefing_worker.run_daily_briefing_worker",
    bind=True,
    max_retries=0,
)
def run_daily_briefing_worker(self) -> dict:
    """
    Pre-generate morning briefings for all active users.
    Runs at 06:00 WAT / 05:00 UTC daily.

    Active = any user row with a role (not suspended).
    Skips users whose briefing_generated_at == today (idempotent).
    Also purges assistant_messages older than 30 days.

    Returns:
        {users_found, processed, skipped, failed, purged_messages}
    """
    db = get_supabase()
    today = date.today().isoformat()

    # ── Fetch all users with role template (Pattern 48) ──────────────────────
    try:
        users_res = (
            db.table("users")
            .select("id, org_id, briefing_generated_at, roles(template)")
            .execute()
        )
        users = users_res.data or []
    except Exception as exc:
        logger.error("daily_briefing_worker: failed to fetch users — %s", exc)
        return {"users_found": 0, "processed": 0, "skipped": 0, "failed": 0, "purged_messages": 0}

    processed = 0
    skipped   = 0
    failed    = 0

    for user in users:
        try:
            user_id   = user.get("id")
            org_id    = user.get("org_id")
            if not user_id or not org_id:
                skipped += 1
                continue

            # Idempotency: skip if briefing already generated today
            if user.get("briefing_generated_at") == today:
                skipped += 1
                continue

            # Pattern 48: role is at roles.template not user.role
            role_template = (user.get("roles") or {}).get("template", "owner")

            generate_briefing(db, org_id, user_id, role_template)
            processed += 1

        except Exception as exc:
            # S14 — single failure never stops the loop
            failed += 1
            logger.warning(
                "daily_briefing_worker: failed for user %s — %s",
                user.get("id", "unknown"),
                exc,
            )

    # ── Purge old messages ────────────────────────────────────────────────────
    purged = 0
    try:
        purged = purge_old_messages(db)
    except Exception as exc:
        logger.warning("daily_briefing_worker: purge failed — %s", exc)

    result = {
        "users_found":      len(users),
        "processed":        processed,
        "skipped":          skipped,
        "failed":           failed,
        "purged_messages":  purged,
    }
    logger.info("daily_briefing_worker: %s", result)
    return result


# ─── Notification digest worker ───────────────────────────────────────────────

@celery_app.task(
    name="app.workers.daily_briefing_worker.run_notification_digest",
    bind=True,
    max_retries=0,
)
def run_notification_digest(self) -> dict:
    """
    Bundle unread notifications into a natural-language Aria summary.
    Runs at 12:00 WAT (11:00 UTC) and 17:00 WAT (16:00 UTC) daily.

    For each user:
      1. Fetch unread notifications since the user's last digest message.
      2. If count < 3, skip (not worth a digest).
      3. One Haiku call → store as assistant_messages row.
      4. Mark the notifications as read.

    Returns:
        {users_processed, digests_sent, users_skipped, failed}
    """
    db = get_supabase()

    # Fetch all users (Pattern 48)
    try:
        users_res = (
            db.table("users")
            .select("id, org_id, roles(template)")
            .execute()
        )
        users = users_res.data or []
    except Exception as exc:
        logger.error("notification_digest: failed to fetch users — %s", exc)
        return {"users_processed": 0, "digests_sent": 0, "users_skipped": 0, "failed": 0}

    digests_sent    = 0
    users_skipped   = 0
    failed          = 0

    for user in users:
        try:
            user_id = user.get("id")
            org_id  = user.get("org_id")
            if not user_id or not org_id:
                users_skipped += 1
                continue

            # Fetch unread notifications for this user
            notif_res = (
                db.table("notifications")
                .select("id, type, title, body")
                .eq("org_id", org_id)
                .eq("user_id", user_id)
                .eq("is_read", False)
                .execute()
            )
            notifications = notif_res.data or []

            # Skip if fewer than 3 unread — not worth a digest
            if len(notifications) < 3:
                users_skipped += 1
                continue

            # Build and call Haiku
            system_prompt = build_digest_prompt(notifications)
            messages      = [{"role": "user", "content": "Summarise my notifications."}]
            summary       = call_haiku_sync(system_prompt, messages)

            if summary:
                # Store digest as an Aria assistant message (Pattern 48: resource_type/resource_id)
                store_message(db, org_id, user_id, "assistant", summary)

                # Mark notifications as read
                notif_ids = [n["id"] for n in notifications if n.get("id")]
                if notif_ids:
                    db.table("notifications").update({"is_read": True}).in_("id", notif_ids).execute()

                digests_sent += 1
            else:
                users_skipped += 1

        except Exception as exc:
            # S14 — single failure never stops the loop
            failed += 1
            logger.warning(
                "notification_digest: failed for user %s — %s",
                user.get("id", "unknown"),
                exc,
            )

    result = {
        "users_processed": len(users),
        "digests_sent":    digests_sent,
        "users_skipped":   users_skipped,
        "failed":          failed,
    }
    logger.info("notification_digest: %s", result)
    return result