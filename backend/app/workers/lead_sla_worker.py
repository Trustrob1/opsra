"""
backend/app/workers/lead_sla_worker.py
M01-6 — Lead Response SLA & Speed Alerts
CONFIG-3 — SLA Business Hours awareness

Runs every 15 minutes via Celery beat.
For each org, finds leads where:
  - score is set (hot / warm / cold) and != 'unscored'
  - first_contacted_at IS NULL   (never contacted yet)
  - assigned_to IS NOT NULL      (has an owner responsible)
  - deleted_at IS NULL

CONFIG-3: Elapsed time is now measured in BUSINESS HOURS only, using the
org's sla_business_hours config. The SLA clock does not tick outside
configured working hours. Falls back to raw wall-clock hours if no
business hours config is set (preserves existing behaviour for orgs
that haven't configured it yet).

  At 1× threshold  → notify assigned rep   (type=lead_sla_breach)
  At 2× threshold  → notify assigned rep + escalate to manager (type=lead_sla_escalation)

Notifications are inserted directly into the notifications table —
notifications_service has no create_notification function (Pattern 28 note).

Module-level imports kept at module level so patch() works correctly (Pattern 42).
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta, date as date_type
from typing import Optional

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)

# ── Notification type constants ───────────────────────────────────────────────
_NOTIF_BREACH     = "lead_sla_breach"
_NOTIF_ESCALATION = "lead_sla_escalation"

# Score tiers that have SLA targets
_SLA_TIERS = {"hot", "warm", "cold"}

# Day name → weekday index (Monday=0)
_DAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


# ── CONFIG-3: Business hours elapsed calculation ──────────────────────────────

def _parse_hhmm(t: Optional[str]) -> Optional[tuple[int, int]]:
    """Parse 'HH:MM' string → (hour, minute) tuple. Returns None on failure."""
    if not t:
        return None
    try:
        h, m = t.split(":")
        return int(h), int(m)
    except Exception:
        return None


def _business_hours_elapsed(
    created_at: datetime,
    now: datetime,
    biz_hours_config: Optional[dict],
) -> float:
    """
    CONFIG-3: Return elapsed business hours between created_at and now.

    biz_hours_config shape:
      {
        "timezone": "Africa/Lagos",   # informational only — we work in UTC
        "days": {
          "monday": {"enabled": True, "open": "08:00", "close": "18:00"},
          ...
        }
      }

    Algorithm: walk minute-by-minute is too slow. Instead we:
      1. Build a list of (day_open_dt, day_close_dt) windows that fall between
         created_at and now.
      2. Clip each window to [created_at, now].
      3. Sum the clipped durations.

    Falls back to raw wall-clock seconds if config is absent/invalid.
    S14: any exception returns raw elapsed (safe degradation).
    """
    raw_elapsed = (now - created_at).total_seconds() / 3600

    if not biz_hours_config:
        return raw_elapsed

    try:
        days_cfg: dict = biz_hours_config.get("days") or {}
        if not days_cfg:
            return raw_elapsed

        # Build a quick lookup: weekday_int → (open_h, open_m, close_h, close_m) | None
        schedule: dict[int, Optional[tuple[int, int, int, int]]] = {}
        for day_name, cfg in days_cfg.items():
            idx = _DAY_INDEX.get(day_name.lower())
            if idx is None:
                continue
            if not cfg.get("enabled"):
                schedule[idx] = None
                continue
            open_hm  = _parse_hhmm(cfg.get("open"))
            close_hm = _parse_hhmm(cfg.get("close"))
            if open_hm and close_hm:
                schedule[idx] = (open_hm[0], open_hm[1], close_hm[0], close_hm[1])
            else:
                schedule[idx] = None

        # Ensure both datetimes are UTC-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if now <= created_at:
            return 0.0

        total_seconds: float = 0.0

        # Walk day-by-day from the date of created_at to the date of now
        start_date = created_at.date()
        end_date   = now.date()

        current_date = start_date
        while current_date <= end_date:
            weekday = current_date.weekday()  # Monday=0
            window  = schedule.get(weekday)   # None = day off

            if window is not None:
                oh, om, ch, cm = window
                # Build UTC datetimes for window open/close on this calendar date
                day_open  = datetime(
                    current_date.year, current_date.month, current_date.day,
                    oh, om, 0, tzinfo=timezone.utc
                )
                day_close = datetime(
                    current_date.year, current_date.month, current_date.day,
                    ch, cm, 0, tzinfo=timezone.utc
                )
                # Clip the window to [created_at, now]
                clipped_start = max(day_open,  created_at)
                clipped_end   = min(day_close, now)
                if clipped_end > clipped_start:
                    total_seconds += (clipped_end - clipped_start).total_seconds()

            current_date += timedelta(days=1)

        return total_seconds / 3600

    except Exception as exc:
        logger.warning(
            "lead_sla_worker: business hours calculation failed, "
            "falling back to wall-clock: %s", exc
        )
        return raw_elapsed


# ── Helper — fetch org SLA config ─────────────────────────────────────────────

def _get_org_sla(db, org_id: str) -> dict:
    """Return sla_hot_hours / sla_warm_hours / sla_cold_hours for one org."""
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
    """Return the first active Owner or Admin user id for the org."""
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

def _process_lead(
    db,
    lead: dict,
    sla_hours: dict,
    biz_hours_config: Optional[dict] = None,
) -> dict:
    """
    Returns {"breach": bool, "escalation": bool, "skipped": bool}.

    CONFIG-3: elapsed is now measured in business hours when biz_hours_config
    is provided. Falls back to wall-clock hours if not configured.
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
        now = datetime.now(timezone.utc)

        # CONFIG-3: use business hours elapsed, not raw wall-clock
        elapsed_hours = _business_hours_elapsed(created_at, now, biz_hours_config)

        threshold_1 = threshold_hours
        threshold_2 = threshold_hours * 2

        if elapsed_hours < threshold_1:
            result["skipped"] = True
            return result

        org_id    = lead["org_id"]
        lead_id   = lead["id"]
        rep_id    = lead.get("assigned_to")
        lead_name = lead.get("full_name") or "Unknown Lead"
        tier_label = score.capitalize()
        elapsed_display = int(elapsed_hours)

        if elapsed_hours >= threshold_2:
            # ── 2× threshold: breach + escalation ─────────────────────────
            if rep_id:
                _insert_notification(
                    db, org_id, rep_id, _NOTIF_BREACH,
                    title=f"⚠️ SLA Breach: {lead_name}",
                    body=(
                        f"{tier_label} lead '{lead_name}' has not been contacted. "
                        f"SLA target was {threshold_hours}h business hours — "
                        f"{elapsed_display}h business hours elapsed."
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
                        f"{tier_label} lead '{lead_name}' is {elapsed_display}h business hours old "
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
                        f"SLA target: {threshold_hours}h business hours — "
                        f"{elapsed_display}h business hours elapsed."
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

    CONFIG-3: fetches sla_business_hours per org and passes to _process_lead().
    Falls back to wall-clock if column is null (backward compatible).

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

        # CONFIG-3: include sla_business_hours in org fetch
        orgs_result = (
            db.table("organisations")
            .select(
                "id, sla_hot_hours, sla_warm_hours, sla_cold_hours, "
                "sla_business_hours"
            )
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
            # CONFIG-3: None = no config → _business_hours_elapsed falls back to wall-clock
            biz_hours_config = org.get("sla_business_hours") or None

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
                result = _process_lead(db, lead, sla_hours, biz_hours_config)
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