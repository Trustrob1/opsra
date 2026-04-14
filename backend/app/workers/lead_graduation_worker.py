"""
app/workers/lead_graduation_worker.py
Daily worker — M01-10a Lead Nurture Engine

Finds leads that have been stale in a conversion-eligible stage for
conversion_attempt_days without any human-actor activity, and graduates
them to the nurture track.

Beat schedule: daily 06:00 WAT (05:00 UTC).
S14: one lead failure never stops the loop.
Pattern 48: get_supabase not get_db; users join roles(template).
Pattern 55: actor_id=None for system timeline events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import shared_task
from dotenv import load_dotenv
from pydantic import BaseModel

from app.database import get_supabase  # Pattern 42 — module-level so patch() can target it
from app.services.nurture_service import (
    NURTURE_STAGES,
    check_human_activity_since,
    graduate_stale_lead,
)

load_dotenv()  # Pattern 29

logger = logging.getLogger(__name__)


class GraduationPayload(BaseModel):
    """S13 — Celery payload schema for validated task dispatch."""
    org_id: str
    dry_run: bool = False


@shared_task(name="app.workers.lead_graduation_worker.run_lead_graduation_check")
def run_lead_graduation_check() -> dict:
    """
    Daily worker — graduates stale leads to the nurture track.

    For each org with nurture_track_enabled=true:
      1. Find leads in a conversion-eligible stage with nurture_track=false.
      2. Check each lead for human-actor activity in the last
         conversion_attempt_days days.
      3. If no activity found: graduate the lead (stage→not_ready,
         nurture_track=true, sequence_position=0).

    Returns summary dict:
      {orgs_processed, leads_checked, graduated, failed}
    S14: per-lead failures increment 'failed' and never abort the loop.
    """
    db     = get_supabase()
    now_ts = datetime.now(timezone.utc).isoformat()

    orgs_processed = 0
    leads_checked  = 0
    graduated      = 0
    failed         = 0

    # 1 — Load orgs with nurture enabled
    try:
        orgs_result = (
            db.table("organisations")
            .select("id, nurture_track_enabled, conversion_attempt_days, nurture_sequence")
            .eq("nurture_track_enabled", True)
            .execute()
        )
        orgs = orgs_result.data or []
    except Exception as exc:
        logger.error("Graduation worker: failed to load orgs: %s", exc)
        return {
            "orgs_processed": 0,
            "leads_checked":  0,
            "graduated":      0,
            "failed":         1,
        }

    for org in orgs:
        org_id          = org["id"]
        conversion_days = org.get("conversion_attempt_days") or 14
        sequence        = org.get("nurture_sequence") or []

        # GAP-3: Do not graduate leads into a track with no messages to send.
        # If the sequence is empty, warn the org owner and skip this org entirely.
        if not sequence:
            logger.warning(
                "Graduation worker: org %s has empty nurture_sequence — "
                "skipping graduation, notifying owner",
                org_id,
            )
            try:
                owner_rows = (
                    db.table("users")
                    .select("id, roles(template)")
                    .eq("org_id", org_id)
                    .execute()
                )
                for row in (owner_rows.data or []):
                    template = ((row.get("roles") or {}).get("template") or "").lower()
                    if template == "owner":
                        db.table("notifications").insert({
                            "org_id":        org_id,
                            "user_id":       row["id"],
                            "title":         "Nurture sequence is empty",
                            "body":          (
                                "Nurture is enabled but your sequence is empty. "
                                "Configure a sequence in Admin → Nurture Engine."
                            ),
                            "type":          "nurture_config_warning",
                            "resource_type": "organisation",
                            "resource_id":   org_id,
                            "is_read":       False,
                            "created_at":    now_ts,
                        }).execute()
                        break  # One warning per org per run is enough
            except Exception as exc:
                logger.warning(
                    "Graduation worker: failed to notify owner for empty sequence "
                    "org %s: %s", org_id, exc,
                )
            continue  # Do not graduate any leads for this org

        # 2 — Load candidate leads: nurture-eligible stage, not already on track
        try:
            leads_result = (
                db.table("leads")
                .select(
                    "id, stage, assigned_to, nurture_track, "
                    "first_contacted_at"
                )
                .eq("org_id", org_id)
                .in_("stage", list(NURTURE_STAGES))
                .eq("nurture_track", False)
                .eq("nurture_opted_out", False)
                .is_("deleted_at", "null")
                .execute()
            )
            candidates = leads_result.data or []
        except Exception as exc:
            logger.error(
                "Graduation worker: failed to load leads for org %s: %s", org_id, exc
            )
            failed += 1
            continue

        orgs_processed += 1

        for lead in candidates:
            lead_id = lead["id"]
            leads_checked += 1
            try:
                # 3 — Skip if recent human or inbound WA activity exists
                if check_human_activity_since(db, lead_id, conversion_days):
                    continue

                # 4 — Compute graduation reason
                if not lead.get("assigned_to"):
                    graduation_reason = "unassigned"
                elif not lead.get("first_contacted_at"):
                    graduation_reason = "no_contact"
                else:
                    graduation_reason = "lead_unresponsive"

                # 5 — Graduate
                graduate_stale_lead(
                    db=db,
                    org_id=org_id,
                    lead_id=lead_id,
                    lead_data=lead,
                    conversion_attempt_days=conversion_days,
                    graduation_reason=graduation_reason,
                    now_ts=now_ts,
                )
                graduated += 1

            except Exception as exc:  # S14 — never abort the loop
                logger.error(
                    "Graduation worker: failed for lead %s: %s", lead_id, exc
                )
                failed += 1

    summary = {
        "orgs_processed": orgs_processed,
        "leads_checked":  leads_checked,
        "graduated":      graduated,
        "failed":         failed,
    }
    logger.info("Lead graduation worker complete: %s", summary)
    return summary