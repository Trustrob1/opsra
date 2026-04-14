"""
app/workers/lead_nurture_worker.py
Daily worker — M01-10a Lead Nurture Engine

For each org with nurture_track_enabled=true, sends the next nurture
sequence message to every lead whose send window has elapsed.

Beat schedule: daily 08:00 WAT (07:00 UTC).
S14: one lead failure never stops the loop.
Pattern 48: get_supabase not get_db.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task
from dotenv import load_dotenv

from app.database import get_supabase  # Pattern 42 — module-level so patch() can target it
from app.services.nurture_service import send_nurture_message

load_dotenv()  # Pattern 29

logger = logging.getLogger(__name__)


@shared_task(name="app.workers.lead_nurture_worker.run_lead_nurture_send")
def run_lead_nurture_send() -> dict:
    """
    Daily worker — sends the next nurture sequence message to due leads.

    For each org with nurture_track_enabled=true:
      Find leads where nurture_track=true AND (
        last_nurture_sent_at IS NULL
        OR last_nurture_sent_at <= now() - nurture_interval_days
      )
      For each due lead: generate and send the next message in the sequence.

    Returns summary dict:
      {orgs_processed, leads_checked, sent, failed}
    S14: per-lead failures increment 'failed' and never abort the loop.
    """
    db     = get_supabase()
    now_ts = datetime.now(timezone.utc).isoformat()
    now_dt = datetime.now(timezone.utc)

    orgs_processed = 0
    leads_checked  = 0
    sent           = 0
    failed         = 0

    # 1 — Load orgs with nurture enabled, including sequence config
    try:
        orgs_result = (
            db.table("organisations")
            .select(
                "id, name, nurture_track_enabled, nurture_interval_days, "
                "nurture_sequence, whatsapp_phone_id"
            )
            .eq("nurture_track_enabled", True)
            .execute()
        )
        orgs = orgs_result.data or []
    except Exception as exc:
        logger.error("Nurture worker: failed to load orgs: %s", exc)
        return {
            "orgs_processed": 0,
            "leads_checked":  0,
            "sent":           0,
            "failed":         1,
        }

    for org in orgs:
        org_id        = org["id"]
        interval_days = org.get("nurture_interval_days") or 7
        sequence      = org.get("nurture_sequence") or []

        if not sequence:
            logger.info(
                "Nurture worker: org %s has empty nurture_sequence — skipping", org_id
            )
            orgs_processed += 1
            continue

        # Leads whose last send is older than the interval (or never sent)
        cutoff_ts = (now_dt - timedelta(days=interval_days)).isoformat()

        lead_select = (
            "id, full_name, phone, whatsapp, business_name, problem_stated, "
            "assigned_to, nurture_sequence_position, last_nurture_sent_at"
        )

        try:
            # Two queries — null last_nurture_sent_at, and overdue — then deduplicate
            null_result = (
                db.table("leads")
                .select(lead_select)
                .eq("org_id", org_id)
                .eq("nurture_track", True)
                .eq("nurture_opted_out", False)
                .is_("last_nurture_sent_at", "null")
                .is_("deleted_at", "null")
                .execute()
            )
            overdue_result = (
                db.table("leads")
                .select(lead_select)
                .eq("org_id", org_id)
                .eq("nurture_track", True)
                .eq("nurture_opted_out", False)
                .lte("last_nurture_sent_at", cutoff_ts)
                .is_("deleted_at", "null")
                .execute()
            )
            seen:      set[str]   = set()
            due_leads: list[dict] = []
            for row in (null_result.data or []) + (overdue_result.data or []):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    due_leads.append(row)

        except Exception as exc:
            logger.error(
                "Nurture worker: failed to load due leads for org %s: %s", org_id, exc
            )
            failed += 1
            continue

        orgs_processed += 1

        for lead in due_leads:
            lead_id = lead["id"]
            leads_checked += 1
            try:
                result = send_nurture_message(
                    db=db,
                    org_id=org_id,
                    lead_id=lead_id,
                    lead_data=lead,
                    sequence=sequence,
                    org_data=org,
                    now_ts=now_ts,
                )
                if result.get("sent"):
                    sent += 1

            except Exception as exc:  # S14 — never abort the loop
                logger.error(
                    "Nurture worker: send failed for lead %s: %s", lead_id, exc
                )
                failed += 1

    summary = {
        "orgs_processed": orgs_processed,
        "leads_checked":  leads_checked,
        "sent":           sent,
        "failed":         failed,
    }
    logger.info("Lead nurture worker complete: %s", summary)
    return summary