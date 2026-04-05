"""
app/workers/nps_worker.py
--------------------------
Celery task:

  run_nps_scheduler  — Daily 09:00 WAT (08:00 UTC)
    Checks every active customer across every org.
    Queues a WhatsApp NPS check-in if 90+ days since last scheduled NPS
    and no event-triggered NPS within the past 14 days.

    Eligibility (Python-side filter — Pattern 33):
      last_nps_sent_at IS NULL  OR  last_nps_sent_at < (now - 90 days)
      AND (nps_event_sent_at IS NULL OR nps_event_sent_at < (now - 14 days))
      AND customer has a phone / whatsapp field

    On success:
      • INSERT into whatsapp_messages (status = 'queued')
      • UPDATE customers.last_nps_sent_at = now

NOTE: last_nps_sent_at and nps_event_sent_at columns are expected on the
      customers table.  If the column is absent the query will still succeed
      (PostgREST returns NULL for missing columns in SELECT *) and the
      eligibility check treats NULL as always-eligible.
      A schema migration is noted in Phase 6A smoke-test checklist.

Pattern 29: load_dotenv() at module level.
Pattern 1:  get_supabase() called inside task body.
Pattern 33: Python-side filtering — no server-side ILIKE / date-filter queries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402

logger = logging.getLogger(__name__)

_NPS_INTERVAL_DAYS = 90
_EVENT_COOLDOWN_DAYS = 14

_NPS_TEMPLATE = (
    "Hi {name}! \U0001f44b Quick question: on a scale of 1\u20135, how likely "
    "are you to recommend us to a friend or colleague? "
    "1 = Not at all \u2022 5 = Absolutely! Just reply with a number."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_nps_scheduler(self):
    """
    Daily 09:00 WAT — Check quarterly NPS eligibility for all active customers.
    Queues WhatsApp NPS message and updates last_nps_sent_at on eligibility.
    """
    logger.info("nps_worker: run_nps_scheduler starting.")
    db = get_supabase()  # Pattern 1
    queued = 0

    try:
        now = datetime.now(timezone.utc)
        nps_threshold = (now - timedelta(days=_NPS_INTERVAL_DAYS)).isoformat()
        event_threshold = (now - timedelta(days=_EVENT_COOLDOWN_DAYS)).isoformat()

        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                # Broad select — Python-side eligibility filter (Pattern 33)
                customers = (
                    db.table("customers")
                    .select(
                        "id, full_name, whatsapp, phone, "
                        "last_nps_sent_at, nps_event_sent_at"
                    )
                    .eq("org_id", org_id)
                    .eq("status", "active")
                    .execute()
                    .data or []
                )

                for customer in customers:
                    cust_id: str = customer["id"]
                    last_sent: str = customer.get("last_nps_sent_at") or ""
                    event_sent: str = customer.get("nps_event_sent_at") or ""
                    phone: str = customer.get("whatsapp") or customer.get("phone") or ""

                    if not phone:
                        continue  # No contact channel

                    # Eligibility: 90-day interval not yet met → skip
                    if last_sent and last_sent > nps_threshold:
                        continue

                    # Event-triggered cooldown: recent NPS → skip
                    if event_sent and event_sent > event_threshold:
                        continue

                    # Compose personalised message
                    first_name = (customer.get("full_name") or "there").split()[0]
                    body = _NPS_TEMPLATE.format(name=first_name)

                    try:
                        # Queue outbound NPS in whatsapp_messages
                        # NOTE: column names (direction, body) match Phase 3A schema.
                        # Verify during smoke test if column names differ.
                        db.table("whatsapp_messages").insert(
                            {
                                "org_id": org_id,
                                "customer_id": cust_id,
                                "direction": "outbound",
                                "message_type": "nps",
                                "body": body,
                                "status": "queued",
                                "created_at": _now_iso(),
                            }
                        ).execute()

                        # Update last send timestamp
                        db.table("customers").update(
                            {"last_nps_sent_at": _now_iso()}
                        ).eq("id", cust_id).execute()

                        queued += 1

                    except Exception as exc:
                        logger.warning(
                            "nps_worker: failed to queue NPS for customer %s — %s",
                            cust_id,
                            exc,
                        )

            except Exception as exc:
                logger.error(
                    "nps_worker: NPS scheduler failed for org %s — %s", org_id, exc
                )

        logger.info("nps_worker: run_nps_scheduler done. Queued %d NPS messages.", queued)

    except Exception as exc:
        logger.error("nps_worker: run_nps_scheduler fatal — %s", exc)
        raise self.retry(exc=exc, countdown=60)