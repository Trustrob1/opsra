"""
app/workers/demo_reminder_worker.py
-------------------------------------
M01-7 — Demo Scheduling & Management (Revised)
M01-9 — Post-Demo Nudge: rep check-in + manager escalation

Celery task: run_demo_reminder_check
    Runs every 15 minutes.

    Processes confirmed demos:
      - 24-hour reminder: when demo is 23–25h away and reminder_24h_sent=false
      - 1-hour reminder:  when demo is 0–2h away and reminder_1h_sent=false
      - Auto no-show:     30min grace past scheduled_at, outcome not logged

    M01-9 — also processes confirmed demos past their scheduled time
    where outcome is still not logged:
      - Rep nudge (T+2h):
          If scheduled_at passed by 2+ hours, outcome not logged,
          rep_nudge_sent_at is null → in-app notification to assigned rep.
          Fires ONCE only — rep_nudge_sent_at set after firing.

      - Manager escalation (T+4h, business hours respected):
          If scheduled_at passed by 4+ hours, outcome still not logged,
          manager_nudge_sent_at is null → in-app notification to all
          owner/admin/ops_manager users in the org.
          If T+4h lands outside business hours (08:00–18:00 Mon–Fri)
          → held until 09:00 next business day.
          Fires ONCE only — manager_nudge_sent_at set after firing.

    All WA reminders are AUTO-SENT directly via Meta Cloud API.
    Nudge notifications are IN-APP ONLY (no WhatsApp).

Pattern 29: load_dotenv() at module level.
Pattern 48 Rule 1: get_supabase() not get_db().
Pattern 48 Rule 2: notifications use resource_type/resource_id.
Pattern 48 Rule 3: roles(template) join, Python-side filter.
S14: per-demo exception handling — one failure never blocks others.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase           # noqa: E402

logger = logging.getLogger(__name__)

_NOSHOW_GRACE_MINUTES = 30

# M01-9 nudge thresholds
_REP_NUDGE_HOURS     = 2   # T+2h — notify rep
_MANAGER_NUDGE_HOURS = 4   # T+4h — notify managers

# Business hours: Mon–Fri 08:00–18:00 UTC
# Escalation held until 09:00 next business day if T+4h falls outside these hours
_BIZ_HOUR_START = 8   # 08:00 UTC
_BIZ_HOUR_END   = 18  # 18:00 UTC
_BIZ_DAYS       = {0, 1, 2, 3, 4}  # Monday=0 … Friday=4


# ── Business hours helpers ────────────────────────────────────────────────────

def _is_business_hours(dt: datetime) -> bool:
    """Return True if dt falls within Mon–Fri 08:00–18:00 UTC."""
    return dt.weekday() in _BIZ_DAYS and _BIZ_HOUR_START <= dt.hour < _BIZ_HOUR_END


def _next_business_day_morning(dt: datetime) -> datetime:
    """
    Return 09:00 UTC on the next business day after dt.
    e.g. Friday 21:00 → Monday 09:00
         Saturday 10:00 → Monday 09:00
    """
    candidate = dt.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while candidate.weekday() not in _BIZ_DAYS:
        candidate += timedelta(days=1)
    return candidate


def _escalation_due(scheduled_at: datetime, now: datetime) -> bool:
    """
    Return True if the manager escalation should fire right now.
    Conditions:
      1. scheduled_at + 4h has passed (T+4h threshold crossed)
      2. Current time is within business hours
         OR T+4h itself was within business hours (fire as soon as biz hours resume)
    """
    threshold = scheduled_at + timedelta(hours=_MANAGER_NUDGE_HOURS)
    if now < threshold:
        return False  # T+4h not crossed yet

    # T+4h has passed — fire if we're currently in business hours
    if _is_business_hours(now):
        return True

    # Outside business hours — check if we have already passed the hold point
    # (next business day morning after T+4h)
    hold_until = _next_business_day_morning(threshold)
    return now >= hold_until


# ── Shared helpers ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _auto_send_wa(db, org_id: str, lead_wa: str, phone_id: str, content: str,
                  lead_id: str) -> None:
    """Send directly via Meta API and log to whatsapp_messages. S14."""
    try:
        from app.services.whatsapp_service import _call_meta_send
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to": lead_wa, "type": "text",
            "text": {"body": content},
        })
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id,
            "direction": "outbound", "message_type": "text",
            "content": content, "status": "sent",
            "window_open": True,
            "window_expires_at": (_now() + timedelta(hours=24)).isoformat(),
            "sent_by": None, "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("demo_reminder_worker: WA send failed — %s", exc)


def _insert_notification(db, org_id: str, user_id: str, notif_type: str,
                         title: str, body: str, demo_id: str) -> None:
    """Pattern 48 Rule 2."""
    try:
        db.table("notifications").insert({
            "id": str(uuid.uuid4()), "org_id": org_id, "user_id": user_id,
            "type": notif_type, "title": title, "body": body,
            "resource_type": "lead_demo", "resource_id": demo_id,
            "is_read": False, "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("demo_reminder_worker: notification insert failed — %s", exc)


def _get_all_manager_ids(db, org_id: str) -> list[str]:
    """
    Pattern 48 Rule 3 + Pattern 37: join roles(template), filter in Python.
    Returns ALL active owner/admin/ops_manager IDs in the org.
    """
    try:
        rows = (
            db.table("users")
            .select("id, is_active, roles(template)")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute().data or []
        )
        manager_ids = []
        for row in rows:
            roles_data = row.get("roles") or {}
            template = (
                (roles_data.get("template") or "").lower()
                if isinstance(roles_data, dict) else ""
            )
            if template in ("owner", "admin", "ops_manager"):
                manager_ids.append(row["id"])
        return manager_ids
    except Exception as exc:
        logger.warning("demo_reminder_worker: _get_all_manager_ids failed — %s", exc)
        return []


def _get_user_name(db, user_id: str) -> str:
    try:
        res = (
            db.table("users").select("full_name")
            .eq("id", user_id).maybe_single().execute()
        )
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        return (data or {}).get("full_name") or ""
    except Exception:
        return ""


# ── Demo processor ────────────────────────────────────────────────────────────

def _process_demo(db, demo: dict, phone_id: str) -> dict:
    """
    Process one confirmed demo. Returns summary of actions taken.
    S14: all exceptions caught per demo.

    Checks in order:
      1. Auto no-show (T+30min grace, highest priority — stops further processing)
      2. Past demo nudges — M01-9 (T+2h rep, T+4h manager escalation)
      3. Pre-demo reminders (24h, 1h)
    """
    result = {
        "reminder_24h": False, "reminder_1h": False,
        "auto_noshow": False,
        "rep_nudge": False, "manager_nudge": False,
        "skipped": False,
    }
    try:
        demo_id     = demo["id"]
        org_id      = demo["org_id"]
        lead_id     = demo["lead_id"]
        assigned_to = demo.get("assigned_to")
        status_val  = demo.get("status", "")

        if status_val != "confirmed":
            result["skipped"] = True
            return result

        scheduled_str = demo.get("scheduled_at")
        if not scheduled_str:
            result["skipped"] = True
            return result

        scheduled_at = datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
        now          = _now()
        time_until   = scheduled_at - now
        time_since   = now - scheduled_at

        # Fetch lead details
        lead_res = (
            db.table("leads")
            .select("id, full_name, whatsapp, phone")
            .eq("id", lead_id).eq("org_id", org_id)
            .is_("deleted_at", "null").maybe_single().execute()
        )
        lead_data = lead_res.data
        if isinstance(lead_data, list):
            lead_data = lead_data[0] if lead_data else None
        if not lead_data:
            result["skipped"] = True
            return result

        lead_name = lead_data.get("full_name") or "Lead"
        wa_number = lead_data.get("whatsapp") or lead_data.get("phone") or ""
        formatted = scheduled_at.strftime("%A, %d %b %Y at %I:%M %p")

        # ── 1. Auto no-show ────────────────────────────────────────────────
        if (time_since >= timedelta(minutes=_NOSHOW_GRACE_MINUTES)
                and not demo.get("noshow_task_created")):
            try:
                from app.services.demo_service import log_outcome
                log_outcome(
                    db=db, org_id=org_id, lead_id=lead_id,
                    demo_id=demo_id, user_id="system",
                    outcome="no_show",
                    outcome_notes="Automatically marked — demo time passed with no outcome logged.",
                )
            except Exception as exc:
                logger.warning(
                    "demo_reminder_worker: auto no-show via log_outcome failed for %s — %s",
                    demo_id, exc,
                )
            result["auto_noshow"] = True
            return result  # no further processing once no-show logged

        # ── 2. M01-9 — Post-demo nudges (outcome not logged, past demo time) ──
        if time_since > timedelta(0):
            # Rep nudge — T+2h
            if (time_since >= timedelta(hours=_REP_NUDGE_HOURS)
                    and not demo.get("rep_nudge_sent_at")
                    and assigned_to):
                _insert_notification(
                    db, org_id, assigned_to,
                    notif_type="demo_outcome_nudge_rep",
                    title=f"📋 Log your demo outcome: {lead_name}",
                    body=(
                        f"Your demo with {lead_name} was scheduled for {formatted}. "
                        f"Please log the outcome — attended, no-show, or rescheduled. "
                        f"Your notes will also be used to generate an AI recap."
                    ),
                    demo_id=demo_id,
                )
                db.table("lead_demos").update({
                    "rep_nudge_sent_at": _now_iso(),
                    "updated_at": _now_iso(),
                }).eq("id", demo_id).eq("org_id", org_id).execute()
                result["rep_nudge"] = True
                logger.info(
                    "demo_reminder_worker: rep nudge sent for demo %s (rep %s)",
                    demo_id, assigned_to,
                )

            # Manager escalation — T+4h, business hours respected
            if (_escalation_due(scheduled_at, now)
                    and not demo.get("manager_nudge_sent_at")):
                manager_ids = _get_all_manager_ids(db, org_id)
                rep_name = _get_user_name(db, assigned_to) if assigned_to else "the rep"
                for mgr_id in manager_ids:
                    _insert_notification(
                        db, org_id, mgr_id,
                        notif_type="demo_outcome_nudge_manager",
                        title=f"⚠️ Demo outcome not logged: {lead_name}",
                        body=(
                            f"{rep_name}'s demo with {lead_name} "
                            f"(scheduled {formatted}) hasn't been logged yet. "
                            f"You may want to follow up with them."
                        ),
                        demo_id=demo_id,
                    )
                if manager_ids:
                    db.table("lead_demos").update({
                        "manager_nudge_sent_at": _now_iso(),
                        "updated_at": _now_iso(),
                    }).eq("id", demo_id).eq("org_id", org_id).execute()
                    result["manager_nudge"] = True
                    logger.info(
                        "demo_reminder_worker: manager escalation sent for demo %s "
                        "(%d managers notified)",
                        demo_id, len(manager_ids),
                    )

            # Past demo but nudges already sent (or within grace) — skip
            if not result["rep_nudge"] and not result["manager_nudge"]:
                result["skipped"] = True
            return result

        # ── 3. Pre-demo reminders (future demos only) ──────────────────────

        # 24-hour reminder
        if (timedelta(hours=23) <= time_until <= timedelta(hours=25)
                and not demo.get("reminder_24h_sent")):
            if wa_number and phone_id:
                _auto_send_wa(
                    db, org_id, wa_number, phone_id,
                    f"Hi {lead_name}! 👋 Just a reminder that your product demo "
                    f"is scheduled for tomorrow, {formatted}. "
                    f"We're excited to show you what we can do! See you then. 🎯",
                    lead_id,
                )
            if assigned_to:
                _insert_notification(
                    db, org_id, assigned_to,
                    notif_type="demo_reminder_24h",
                    title=f"Demo reminder sent: {lead_name}",
                    body=f"24-hour reminder sent to {lead_name} for demo on {formatted}.",
                    demo_id=demo_id,
                )
            db.table("lead_demos").update({
                "reminder_24h_sent": True,
                "reminder_24h_sent_at": _now_iso(),
                "updated_at": _now_iso(),
            }).eq("id", demo_id).eq("org_id", org_id).execute()
            result["reminder_24h"] = True

        # 1-hour reminder
        elif (timedelta(0) < time_until <= timedelta(hours=2)
              and not demo.get("reminder_1h_sent")):
            if wa_number and phone_id:
                _auto_send_wa(
                    db, org_id, wa_number, phone_id,
                    f"Hi {lead_name}! ⏰ Your demo starts in about 1 hour "
                    f"({formatted}). We're looking forward to speaking with you! 🚀",
                    lead_id,
                )
            if assigned_to:
                _insert_notification(
                    db, org_id, assigned_to,
                    notif_type="demo_reminder_1h",
                    title=f"Demo in 1 hour: {lead_name}",
                    body=f"Demo with {lead_name} starts at {formatted}. 1-hour reminder sent.",
                    demo_id=demo_id,
                )
            db.table("lead_demos").update({
                "reminder_1h_sent": True,
                "reminder_1h_sent_at": _now_iso(),
                "updated_at": _now_iso(),
            }).eq("id", demo_id).eq("org_id", org_id).execute()
            result["reminder_1h"] = True

        else:
            result["skipped"] = True

    except Exception as exc:  # S14
        logger.exception("demo_reminder_worker: error on demo %s: %s", demo.get("id"), exc)
        result["skipped"] = True

    return result


# ── Celery task ───────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.demo_reminder_worker.run_demo_reminder_check",
    bind=True, max_retries=3, default_retry_delay=30,
)
def run_demo_reminder_check(self):
    """
    Runs every 15 minutes.
    Scans confirmed demos for:
      - Pre-demo: 24h reminders, 1h reminders
      - At demo time: auto no-show (30min grace)
      - Post-demo M01-9: rep nudge (T+2h), manager escalation (T+4h, biz hours)
    """
    summary = {
        "orgs_processed": 0, "demos_checked": 0,
        "reminders_24h": 0, "reminders_1h": 0,
        "auto_noshows": 0,
        "rep_nudges": 0, "manager_nudges": 0,
        "skipped": 0, "failed": 0,
    }

    try:
        db = get_supabase()  # Pattern 48 Rule 1
        orgs = db.table("organisations").select("id, whatsapp_phone_id").execute().data or []

        for org_row in orgs:
            org_id   = org_row["id"]
            phone_id = (org_row.get("whatsapp_phone_id") or "").strip()
            summary["orgs_processed"] += 1

            try:
                now = _now()

                # Extended window — covers:
                #   future:  up to 26h ahead (24h + 2h buffer) for pre-demo reminders
                #   past:    up to 5 days back — catches any confirmed demo with
                #            outcome still not logged (nudges fire once only)
                window_start = (now - timedelta(days=5)).isoformat()
                window_end   = (now + timedelta(hours=26)).isoformat()

                demos = (
                    db.table("lead_demos")
                    .select(
                        "id, org_id, lead_id, assigned_to, scheduled_at, status, "
                        "reminder_24h_sent, reminder_1h_sent, noshow_task_created, "
                        "rep_nudge_sent_at, manager_nudge_sent_at"
                    )
                    .eq("org_id", org_id)
                    .eq("status", "confirmed")
                    .is_("deleted_at", "null")
                    .gte("scheduled_at", window_start)
                    .lte("scheduled_at", window_end)
                    .execute()
                    .data or []
                )

                for demo in demos:
                    summary["demos_checked"] += 1
                    res = _process_demo(db, demo, phone_id)
                    if res["reminder_24h"]:  summary["reminders_24h"]  += 1
                    if res["reminder_1h"]:   summary["reminders_1h"]   += 1
                    if res["auto_noshow"]:   summary["auto_noshows"]   += 1
                    if res["rep_nudge"]:     summary["rep_nudges"]     += 1
                    if res["manager_nudge"]: summary["manager_nudges"] += 1
                    if res["skipped"]:       summary["skipped"]        += 1

            except Exception as exc:
                logger.error("demo_reminder_worker: failed for org %s — %s", org_id, exc)
                summary["failed"] += 1

        logger.info("demo_reminder_worker: %s", summary)

    except Exception as exc:
        logger.exception("demo_reminder_worker: fatal — %s", exc)
        summary["failed"] += 1
        raise self.retry(exc=exc, countdown=30)

    return summary
