"""
backend/app/workers/lead_sla_worker.py
M01-6 — Lead Response SLA & Speed Alerts

Runs every 15 minutes via Celery beat.
For each org, finds leads where:
  - score is set (hot / warm / cold) and != 'unscored'
  - first_contacted_at IS NULL   (never contacted yet)
  - assigned_to IS NOT NULL      (has an owner responsible)
  - deleted_at IS NULL

Compares elapsed time since created_at against the org's per-tier SLA target.
  At 1× threshold  → notify assigned rep   (type=lead_sla_breach)
  At 2× threshold  → notify assigned rep + escalate to manager (type=lead_sla_escalation)

Notifications are inserted directly into the notifications table —
notifications_service has no create_notification function (Pattern 28 note).

Module-level imports of db and datetime utilities kept at module level so
patch() works correctly in tests (Pattern 42).
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)

# ── Notification type constants ───────────────────────────────────────────────
_NOTIF_BREACH     = "lead_sla_breach"
_NOTIF_ESCALATION = "lead_sla_escalation"

# Score tiers that have SLA targets (excludes 'unscored' and 'converted'/'lost')
_SLA_TIERS = {"hot", "warm", "cold"}


# ── Helper — fetch org SLA config ─────────────────────────────────────────────

def _get_org_sla(db, org_id: str) -> dict:
    """Return sla_hot_hours / sla_warm_hours / sla_cold_hours for one org.
    Falls back to DRD defaults if columns somehow missing."""
    row = (
        db.table("organisations")
        .select("sla_hot_hours, sla_warm_hours, sla_cold_hours")
        .eq("id", org_id)
        .single()
        .execute()
    )
    data = row.data or {}
    return {
        "hot":  int(data.get("sla_hot_hours")  or 1),
        "warm": int(data.get("sla_warm_hours") or 4),
        "cold": int(data.get("sla_cold_hours") or 24),
    }


# ── Helper — find manager for an org ─────────────────────────────────────────

def _get_org_manager_id(db, org_id: str, exclude_user_id: str | None = None) -> str | None:
    """Return the first active Owner or Admin user id for the org (not the rep).
    Role is stored via FK join to roles table — users has no flat role column (Pattern 37).
    Filter by template in Python after fetch — no ILIKE/filter on joined columns (Pattern 33).
    """
    q = (
        db.table("users")
        .select("id, is_active, roles(template)")
        .eq("org_id", org_id)
        .eq("is_active", True)
    )
    if exclude_user_id:
        q = q.neq("id", exclude_user_id)
    result = q.execute()
    rows = result.data or []
    for row in rows:
        roles_data = row.get("roles") or {}
        template = (roles_data.get("template") or "").lower() if isinstance(roles_data, dict) else ""
        if template in ("owner", "admin", "ops_manager"):
            return row["id"]
    return None


# ── Helper — insert one notification row directly ────────────────────────────

def _insert_notification(db, org_id: str, user_id: str, notif_type: str,
                         title: str, body: str, lead_id: str) -> None:
    db.table("notifications").insert({
        "id":            str(uuid.uuid4()),
        "org_id":        org_id,
        "user_id":       user_id,
        "type":          notif_type,
        "title":         title,
        "body":          body,
        "resource_type": "lead",
        "resource_id":   lead_id,
        "is_read":       False,
        "created_at":    datetime.now(timezone.utc).isoformat(),
    }).execute()


# ── Helper — check and alert one lead ────────────────────────────────────────

def _process_lead(db, lead: dict, sla_hours: dict) -> dict:
    """
    Returns {"breach": bool, "escalation": bool, "skipped": bool}.
    S14: exceptions are caught so one bad lead never blocks others.
    """
    result = {"breach": False, "escalation": False, "skipped": False}
    try:
        score = (lead.get("score") or "").lower()
        if score not in _SLA_TIERS:
            result["skipped"] = True
            return result

        threshold_hours = sla_hours[score]
        created_at_str  = lead.get("created_at")
        if not created_at_str:
            result["skipped"] = True
            return result

        created_at = datetime.fromisoformat(
            created_at_str.replace("Z", "+00:00")
        )
        now         = datetime.now(timezone.utc)
        elapsed     = now - created_at
        threshold_1 = timedelta(hours=threshold_hours)
        threshold_2 = timedelta(hours=threshold_hours * 2)

        if elapsed < threshold_1:
            # Not yet overdue
            result["skipped"] = True
            return result

        org_id   = lead["org_id"]
        lead_id  = lead["id"]
        rep_id   = lead.get("assigned_to")
        lead_name = lead.get("full_name") or "Unknown Lead"
        tier_label = score.capitalize()

        if elapsed >= threshold_2:
            # ── 2× threshold: breach + escalation ─────────────────────────
            if rep_id:
                _insert_notification(
                    db, org_id, rep_id, _NOTIF_BREACH,
                    title=f"⚠️ SLA Breach: {lead_name}",
                    body=(
                        f"{tier_label} lead '{lead_name}' has not been contacted. "
                        f"SLA target was {threshold_hours}h — now {int(elapsed.total_seconds() // 3600)}h elapsed."
                    ),
                    lead_id=lead_id,
                )
                result["breach"] = True

            manager_id = _get_org_manager_id(db, org_id, exclude_user_id=rep_id)
            if manager_id:
                _insert_notification(
                    db, org_id, manager_id, _NOTIF_ESCALATION,
                    title=f"🚨 SLA Escalation: {lead_name}",
                    body=(
                        f"{tier_label} lead '{lead_name}' is {int(elapsed.total_seconds() // 3600)}h old "
                        f"and has not been contacted (2× SLA threshold reached). "
                        f"Assigned rep has been notified."
                    ),
                    lead_id=lead_id,
                )
                result["escalation"] = True

        else:
            # ── 1× threshold: breach alert to rep only ────────────────────
            if rep_id:
                _insert_notification(
                    db, org_id, rep_id, _NOTIF_BREACH,
                    title=f"⏰ Contact Required: {lead_name}",
                    body=(
                        f"{tier_label} lead '{lead_name}' has not been contacted. "
                        f"SLA target: {threshold_hours}h — {int(elapsed.total_seconds() // 3600)}h elapsed."
                    ),
                    lead_id=lead_id,
                )
                result["breach"] = True
            else:
                result["skipped"] = True

    except Exception as exc:  # S14 — never stop the loop
        logger.exception("lead_sla_worker: error processing lead %s: %s", lead.get("id"), exc)
        result["skipped"] = True

    return result


# ── Main Celery task ──────────────────────────────────────────────────────────

@celery_app.task(name="lead_sla_worker.run_lead_sla_check", bind=True, max_retries=3)
def run_lead_sla_check(self):
    """
    Celery beat task — runs every 15 minutes.
    Scans all active orgs for leads that have breached their SLA contact window.
    Returns summary dict: {orgs_processed, leads_checked, breaches, escalations, skipped, failed}
    """
    summary = {
        "orgs_processed": 0,
        "leads_checked":  0,
        "breaches":       0,
        "escalations":    0,
        "skipped":        0,
        "failed":         0,
    }

    try:
        db = get_supabase()

        # Fetch all active orgs
        orgs_result = (
            db.table("organisations")
            .select("id, sla_hot_hours, sla_warm_hours, sla_cold_hours")
            .execute()
        )
        orgs = orgs_result.data or []

        for org in orgs:
            org_id = org["id"]
            sla_hours = {
                "hot":  int(org.get("sla_hot_hours")  or 1),
                "warm": int(org.get("sla_warm_hours") or 4),
                "cold": int(org.get("sla_cold_hours") or 24),
            }

            # Fetch uncontacted, scored, assigned leads for this org
            leads_result = (
                db.table("leads")
                .select("id, org_id, full_name, score, assigned_to, created_at")
                .eq("org_id", org_id)
                .is_("first_contacted_at", "null")
                .is_("deleted_at", "null")
                .not_.in_("score", ["unscored", "converted", "lost"])
                .not_.is_("assigned_to", "null")
                .execute()
            )
            leads = leads_result.data or []
            summary["orgs_processed"] += 1

            for lead in leads:
                summary["leads_checked"] += 1
                result = _process_lead(db, lead, sla_hours)
                if result["breach"]:
                    summary["breaches"] += 1
                if result["escalation"]:
                    summary["escalations"] += 1
                if result["skipped"]:
                    summary["skipped"] += 1

        logger.info("lead_sla_worker: %s", summary)

    except Exception as exc:
        logger.exception("lead_sla_worker: fatal error: %s", exc)
        summary["failed"] += 1
        raise self.retry(exc=exc, countdown=30)

    return summary
