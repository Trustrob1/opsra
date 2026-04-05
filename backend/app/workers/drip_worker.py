"""
app/workers/drip_worker.py
---------------------------
Celery task:

  run_drip_scheduler  — Daily 08:00 WAT (07:00 UTC)
    Fetch pending drip_sends where scheduled_for <= today.
    Apply pause rules before sending.
    Queue outbound message in whatsapp_messages.
    Update drip_sends.status to sent / paused / skipped / failed.

Pause rules (evaluated in order):
  1. Customer status != 'active'       → status = 'skipped'
  2. Customer has an open/in-progress ticket → status = 'paused'
  3. drip_message row not found        → status = 'failed'

On success:
  • INSERT into whatsapp_messages (status = 'queued')
  • UPDATE drip_sends SET status = 'sent', sent_at = now()

NOTE: whatsapp_messages column names (direction, body, message_type) are
      expected to match Phase 3A schema. Verify during smoke test.

Pattern 29: load_dotenv() at module level.
Pattern 1:  get_supabase() called inside task body.
Pattern 33: Python-side date comparison — no server-side date filter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalise(data) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_drip_scheduler(self):
    """
    Daily 08:00 WAT — Process all pending drip sends due today or earlier.
    Applies pause/skip rules. Queues approved sends to whatsapp_messages.
    """
    logger.info("drip_worker: run_drip_scheduler starting.")
    db = get_supabase()  # Pattern 1
    processed = 0
    skipped = 0

    try:
        today = _today_iso()
        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                all_pending = (
                    db.table("drip_sends")
                    .select("id, customer_id, drip_message_id, scheduled_for, status")
                    .eq("org_id", org_id)
                    .eq("status", "pending")
                    .execute()
                    .data or []
                )

                # Python-side filter: scheduled_for <= today (Pattern 33)
                due = [
                    s
                    for s in all_pending
                    if (s.get("scheduled_for") or "")[:10] <= today
                ]

                for send in due:
                    send_id: str = send["id"]
                    customer_id: str = send["customer_id"]
                    message_id: Optional[str] = send.get("drip_message_id")

                    try:
                        # ── Pause rule 1: customer not active → skip ────────
                        customer = _normalise(
                            db.table("customers")
                            .select("id, status, whatsapp, phone, full_name")
                            .eq("id", customer_id)
                            .execute()
                            .data
                        )

                        if not customer or customer.get("status") != "active":
                            _set_status(db, send_id, "skipped")
                            skipped += 1
                            continue

                        # ── Pause rule 2: open ticket → pause ───────────────
                        open_tickets = (
                            db.table("tickets")
                            .select("id")
                            .eq("org_id", org_id)
                            .eq("customer_id", customer_id)
                            .in_("status", ["open", "in_progress"])
                            .execute()
                            .data or []
                        )
                        if open_tickets:
                            _set_status(db, send_id, "paused")
                            skipped += 1
                            continue

                        # ── Fetch drip message content ──────────────────────
                        if not message_id:
                            _set_status(db, send_id, "failed")
                            logger.warning(
                                "drip_worker: send %s has no drip_message_id", send_id
                            )
                            continue

                        message = _normalise(
                            db.table("drip_messages")
                            .select("id, body, message_type")
                            .eq("id", message_id)
                            .execute()
                            .data
                        )
                        if not message:
                            _set_status(db, send_id, "failed")
                            logger.warning(
                                "drip_worker: drip_message %s not found", message_id
                            )
                            continue

                        # ── Queue outbound WhatsApp message ─────────────────
                        # NOTE: verify column names against whatsapp_messages
                        #       schema during smoke test.
                        db.table("whatsapp_messages").insert(
                            {
                                "org_id": org_id,
                                "customer_id": customer_id,
                                "direction": "outbound",
                                "message_type": message.get("message_type", "drip"),
                                "body": message.get("body", ""),
                                "status": "queued",
                                "created_at": _now_iso(),
                            }
                        ).execute()

                        # ── Mark send as sent ────────────────────────────────
                        db.table("drip_sends").update(
                            {"status": "sent", "sent_at": _now_iso()}
                        ).eq("id", send_id).execute()
                        processed += 1

                    except Exception as exc:
                        logger.warning(
                            "drip_worker: send %s failed — %s", send_id, exc
                        )
                        _set_status(db, send_id, "failed")

            except Exception as exc:
                logger.error(
                    "drip_worker: drip scheduler failed for org %s — %s", org_id, exc
                )

        logger.info(
            "drip_worker: run_drip_scheduler done. Sent: %d, Skipped/Paused: %d.",
            processed,
            skipped,
        )

    except Exception as exc:
        logger.error("drip_worker: run_drip_scheduler fatal — %s", exc)
        raise self.retry(exc=exc, countdown=30)


def _set_status(db, send_id: str, status: str) -> None:
    """Update drip_sends.status, swallowing any DB error."""
    try:
        db.table("drip_sends").update({"status": status}).eq("id", send_id).execute()
    except Exception as exc:
        logger.warning(
            "drip_worker: failed to set status=%s for send %s — %s",
            status,
            send_id,
            exc,
        )