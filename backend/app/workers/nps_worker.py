"""
app/workers/nps_worker.py
--------------------------
9E-D gates added:
  D1: is_org_active() — top of per-org loop.
  D2: is_quiet_hours() — hold NPS message (send_after, quiet_hours_held=true).
  D3: has_exceeded_daily_limit() — skip customer if daily cap reached.

All other logic unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.utils.org_gates import (
    is_org_active,
    is_quiet_hours,
    get_quiet_hours_end_utc,
    get_daily_customer_limit,
    has_exceeded_daily_limit,
)
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)

_NPS_INTERVAL_DAYS  = 90
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
    D1/D2/D3 gates applied.
    """
    logger.info("nps_worker: run_nps_scheduler starting.")
    db  = get_supabase()
    queued   = 0
    skipped  = 0
    now_utc  = datetime.now(timezone.utc)
    _started_at = now_utc

    try:
        now             = now_utc
        nps_threshold   = (now - timedelta(days=_NPS_INTERVAL_DAYS)).isoformat()
        event_threshold = (now - timedelta(days=_EVENT_COOLDOWN_DAYS)).isoformat()

        # Include gate fields in org select
        orgs = (
            db.table("organisations")
            .select(
                "id, subscription_status, quiet_hours_start, "
                "quiet_hours_end, timezone, daily_customer_message_limit"
            )
            .execute()
            .data or []
        )

        for org_row in orgs:
            org_id: str = org_row["id"]

            # ── D1: Subscription gate ─────────────────────────────────────
            if not is_org_active(org_row):
                logger.info(
                    "nps_worker: org %s skipped — subscription_status=%s",
                    org_id, org_row.get("subscription_status"),
                )
                continue

            daily_limit = get_daily_customer_limit(org_row)

            try:
                customers = (
                    db.table("customers")
                    .select(
                        "id, full_name, whatsapp, phone, "
                        "last_nps_sent_at, nps_event_sent_at, whatsapp_opted_out"
                    )
                    .eq("org_id", org_id)
                    .eq("status", "active")
                    .execute()
                    .data or []
                )

                for customer in customers:
                    cust_id:    str = customer["id"]
                    last_sent:  str = customer.get("last_nps_sent_at") or ""
                    event_sent: str = customer.get("nps_event_sent_at") or ""
                    phone:      str = (
                        customer.get("whatsapp") or customer.get("phone") or ""
                    )

                    if not phone:
                        continue
 
                    # I1: Never send NPS to contacts who have opted out.
                    if customer.get("whatsapp_opted_out"):
                        logger.info(
                            "nps_worker: customer %s skipped — whatsapp_opted_out",
                            cust_id,
                        )
                        skipped += 1
                        continue
 
                    if last_sent and last_sent > nps_threshold:
                        continue

                    if event_sent and event_sent > event_threshold:
                        continue

                    # ── D3: Daily customer message limit ──────────────────
                    if has_exceeded_daily_limit(db, org_id, cust_id, daily_limit):
                        logger.info(
                            "nps_worker: customer %s skipped — daily limit %d reached",
                            cust_id, daily_limit,
                        )
                        skipped += 1
                        continue

                    first_name = (customer.get("full_name") or "there").split()[0]
                    body       = _NPS_TEMPLATE.format(name=first_name)

                    try:
                        # ── D2: Quiet hours — hold message ────────────────
                        if is_quiet_hours(org_row, now_utc):
                            send_after = get_quiet_hours_end_utc(org_row, now_utc)
                            db.table("whatsapp_messages").insert({
                                "org_id":           org_id,
                                "customer_id":      cust_id,
                                "direction":        "outbound",
                                "message_type":     "nps",
                                "content":          body,
                                "status":           "queued",
                                "send_after":       send_after.isoformat(),
                                "quiet_hours_held": True,
                                "created_at":       _now_iso(),
                            }).execute()
                        else:
                            db.table("whatsapp_messages").insert({
                                "org_id":       org_id,
                                "customer_id":  cust_id,
                                "direction":    "outbound",
                                "message_type": "nps",
                                "content":      body,
                                "status":       "queued",
                                "created_at":   _now_iso(),
                            }).execute()

                        db.table("customers").update(
                            {"last_nps_sent_at": _now_iso()}
                        ).eq("id", cust_id).execute()

                        queued += 1

                    except Exception as exc:
                        logger.warning(
                            "nps_worker: failed to queue NPS for customer %s — %s",
                            cust_id, exc,
                        )

            except Exception as exc:
                logger.error(
                    "nps_worker: NPS scheduler failed for org %s — %s", org_id, exc
                )

        logger.info(
            "nps_worker: run_nps_scheduler done. Queued %d, Skipped %d.",
            queued, skipped,
        )
        write_worker_log(
            db,
            worker_name="nps_worker",
            status="passed",
            items_processed=queued + skipped,
            items_failed=0,
            items_skipped=skipped,
            started_at=_started_at,
        )

    except Exception as exc:
        logger.error("nps_worker: run_nps_scheduler fatal — %s", exc)
        write_worker_log(
            db,
            worker_name="nps_worker",
            status="failed",
            error_message=str(exc)[:500],
            started_at=_started_at,
        )
        raise self.retry(exc=exc, countdown=60)
