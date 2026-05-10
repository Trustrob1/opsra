"""
app/workers/ai_resume_worker.py
---------------------------------
Celery task that automatically resumes AI mode for contacts left in
Human Mode after 15 minutes of rep inactivity.

When a rep sends a message from Opsra, ai_paused is set to True.
If the rep forgets to Resume AI, this task flips it back automatically.

Logic:
  - Runs every 5 minutes via beat schedule.
  - Queries all leads and customers where ai_paused = True.
  - For each, finds the most recent outbound message sent by a human
    (sent_by IS NOT NULL — excludes system/AI messages).
  - If that message is older than 15 minutes → calls set_ai_paused(False).
  - Fallback: if no human outbound message exists at all, uses the
    record's updated_at as the reference timestamp.
  - S14: any exception per contact is logged and skipped — never
    blocks the rest of the batch.
"""

import logging
from datetime import datetime, timezone, timedelta

from celery import shared_task

from app.database import get_supabase
from app.services.whatsapp_service import set_ai_paused

logger = logging.getLogger(__name__)

# Auto-resume threshold — 15 minutes of rep inactivity
AI_RESUME_AFTER_MINUTES = 15


def _get_last_human_sent_at(db, contact_field: str, contact_id: str) -> datetime | None:
    """
    Returns the created_at timestamp of the most recent outbound message
    sent by a human (sent_by IS NOT NULL) for this lead or customer.
    Returns None if no such message exists.
    """
    try:
        result = (
            db.table("whatsapp_messages")
            .select("created_at")
            .eq(contact_field, contact_id)
            .eq("direction", "outbound")
            .not_.is_("sent_by", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        raw = rows[0].get("created_at")
        if not raw:
            return None
        # Parse ISO timestamp from Supabase
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return ts
    except Exception as exc:
        logger.warning("_get_last_human_sent_at failed for %s %s: %s", contact_field, contact_id, exc)
        return None


def _process_contacts(db, table: str, contact_type: str, contact_field: str, now: datetime) -> int:
    """
    Finds all paused contacts in the given table, checks inactivity,
    and auto-resumes AI where threshold is exceeded.
    Returns count of contacts resumed.
    """
    resumed = 0
    threshold = now - timedelta(minutes=AI_RESUME_AFTER_MINUTES)

    try:
        result = (
            db.table(table)
            .select("id, org_id, updated_at")
            .eq("ai_paused", True)
            .is_("deleted_at", None)
            .execute()
        )
        contacts = result.data or []
    except Exception as exc:
        logger.warning("ai_resume_worker: failed to fetch paused %s: %s", table, exc)
        return 0

    for contact in contacts:
        try:
            contact_id = contact["id"]
            org_id     = contact["org_id"]

            # Find when the rep last sent a message to this contact
            last_human_sent = _get_last_human_sent_at(db, contact_field, contact_id)

            if last_human_sent is not None:
                reference_time = last_human_sent
            else:
                # No human outbound message found — use updated_at as fallback
                # (updated_at changes when ai_paused was set to True)
                raw_updated = contact.get("updated_at")
                if not raw_updated:
                    continue
                reference_time = datetime.fromisoformat(raw_updated.replace("Z", "+00:00"))

            if reference_time <= threshold:
                set_ai_paused(db, org_id, contact_type, contact_id, False)
                logger.info(
                    "ai_resume_worker: auto-resumed AI for %s %s "
                    "(last human message: %s, threshold: %s)",
                    contact_type, contact_id, reference_time, threshold,
                )
                resumed += 1

        except Exception as exc:
            logger.warning(
                "ai_resume_worker: error processing %s %s: %s",
                contact_type, contact.get("id"), exc,
            )
            continue

    return resumed


@shared_task(name="app.workers.ai_resume_worker.run_ai_auto_resume")
def run_ai_auto_resume() -> None:
    """
    Main Celery task — runs every 5 minutes.
    Auto-resumes AI for all contacts in Human Mode with no rep reply
    for more than 15 minutes.
    """
    db  = get_supabase()
    now = datetime.now(timezone.utc)

    leads_resumed     = _process_contacts(db, "leads",     "lead",     "lead_id",     now)
    customers_resumed = _process_contacts(db, "customers", "customer", "customer_id", now)

    total = leads_resumed + customers_resumed
    if total > 0:
        logger.info(
            "ai_resume_worker: auto-resumed AI for %d contact(s) "
            "(%d leads, %d customers)",
            total, leads_resumed, customers_resumed,
        )
    else:
        logger.info("ai_resume_worker: no contacts required auto-resume this run")