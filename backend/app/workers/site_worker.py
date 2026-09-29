"""
app/workers/site_worker.py
-----------------------------
SITE-1B §7.7 — one consolidated Celery beat task covering the timers that
actually have something to act on today:

  • Brief reminder       — a chat stuck mid-brief for 20h+ gets one nudge
                            (before the 24h free-messaging window closes).
  • Unfinished form      — a brief-form link opened but never submitted for
    reminder               3+ days gets one nudge (asks them to request a
                            fresh link via FORM/the dashboard button, since
                            spec §18 never persists the raw token to resend).
  • Form expiry          — brief-form links past their expires_at flip to
                            'expired' even if nobody ever revisits them
                            (routers/public_forms.py only expires lazily,
                            on next visit — this is the proactive sweep).
  • Preview expiry       — non-live sites past their preview_expires_at lose
                            their rendered_html and drop back to
                            'brief_complete', forcing a fresh render.

SITE-3 part 2 addition — a SECOND, separately-scheduled task in this same
file (same domain owner, different required cadence):

  • run_hosting_job_sla_check — spec §11.4 step 4. Standard hosting jobs
    (site_hosting_jobs) turn amber 12 hours before their sla_due_at and red
    once overdue, with a push alert to Trust and the job's assignee, then
    escalate every 2 hours while it stays overdue. This needs a much finer
    cadence (every 15 minutes, mirroring sla_worker.py's ticket check) than
    the 4-hourly run_site_builder_timers below, so it's registered as its
    own beat entry rather than folded into that sweep.

Deliberately NOT built here (spec lists it, but nothing exists yet for it
to act on — building it now would be dead code):
  • Renewal reminders — needs hosting/domain renewal dates (SITE-3/SITE-5).
  Opsra's existing generic renewal_worker already covers the non-site-engine
  case; a site-specific version lands with SITE-5.

Runs every 4 hours (not more often — see reasoning in the beat_schedule
comment in celery_app.py): frequent enough that the 20h brief reminder
still lands inside the 24h free-messaging window, infrequent enough that
this barely registers as load on the one existing worker dyno.

S13: no external payloads here (a beat task, not a webhook) — nothing to validate.
S14: each step has its own try/except; within per-row loops, each row also
     has its own try/except, so one bad record never stops the rest of the sweep.
Pattern 29: load_dotenv() at module level. Pattern 1: get_supabase() inside the task.

Dry-run (Windows CMD, one line each):
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.site_worker import run_site_builder_timers; print(run_site_builder_timers())"
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.site_worker import run_hosting_job_sla_check; print(run_hosting_job_sla_check())"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.workers.org_gates import is_org_active  # noqa: E402
from app.services.monitoring_service import write_worker_log  # noqa: E402
from app.services.site_chat_service import _send_text  # noqa: E402
from app.services.funnel_service import _get_manager_ids  # noqa: E402 — Pattern 48 manager lookup, reused as-is

logger = logging.getLogger(__name__)

_BRIEF_REMINDER_AFTER_HOURS = 20
_FORM_REMINDER_AFTER_DAYS = 3
_SLA_AMBER_BEFORE_HOURS = 12   # spec §11.4 — "turns amber at 12 hours" == 12h before the 24h SLA is due
_SLA_ESCALATE_EVERY_HOURS = 2  # spec §11.4 — "escalation continues every 2 hours while it stays overdue"
# site_hosting_jobs.status CHECK allows only queued / in_progress / blocked / done — a finished job is "done".
_OPEN_JOB_STATUSES_EXCLUDE = ("done",)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _org_cache(db):
    """Small per-run cache so N rows for the same org only look up the org
    row and its site_builder WhatsApp number once each, not N times."""
    orgs: dict[str, dict] = {}
    numbers: dict[str, Optional[dict]] = {}

    def org_active(org_id: str) -> bool:
        if org_id not in orgs:
            orgs[org_id] = _one(
                (db.table("organisations").select("id, subscription_status").eq("id", org_id).limit(1).execute()).data
            ) or {}
        return is_org_active(orgs[org_id])

    def number_row(org_id: str) -> Optional[dict]:
        if org_id not in numbers:
            numbers[org_id] = _one(
                (db.table("whatsapp_numbers").select("*").eq("org_id", org_id)
                 .eq("wa_sales_mode", "site_builder").limit(1).execute()).data
            )
        return numbers[org_id]

    return org_active, number_row


# ─────────────────────────────── Brief reminder ───────────────────────────────

def _send_brief_reminders(db, now: datetime) -> int:
    cutoff = (now - timedelta(hours=_BRIEF_REMINDER_AFTER_HOURS)).isoformat()
    rows = (
        db.table("site_chats").select("*")
        .eq("state", "briefing").eq("reminder_count", 0).eq("opted_out", False)
        .lte("last_inbound_at", cutoff).execute()
    ).data or []
    if not rows:
        return 0

    org_active, number_row = _org_cache(db)
    sent = 0
    for chat in rows:
        try:
            org_id = chat["org_id"]
            if not org_active(org_id):
                continue
            number = number_row(org_id)
            if not number:
                continue
            _send_text(
                db, org_id, number, chat["phone_number"],
                "Still there? Your site brief is unfinished — reply to any of the questions above to "
                "carry on, or type MENU to start over.",
            )
            db.table("site_chats").update({"reminder_count": 1, "updated_at": _now_iso()}).eq("id", chat["id"]).execute()
            sent += 1
        except Exception:  # S14
            logger.exception("[site_worker] brief reminder failed chat=%s", chat.get("id"))
    return sent


# ─────────────────────────────── Unfinished form reminder ───────────────────────────────

def _send_form_reminders(db, now: datetime) -> int:
    cutoff = (now - timedelta(days=_FORM_REMINDER_AFTER_DAYS)).isoformat()
    rows = (
        db.table("site_brief_forms").select("*")
        .eq("status", "open").is_("form_reminder_sent_at", "null")
        .not_.is_("opened_at", "null").lte("opened_at", cutoff).execute()
    ).data or []
    if not rows:
        return 0

    org_active, number_row = _org_cache(db)
    sent = 0
    for form in rows:
        try:
            org_id = form["org_id"]
            if not org_active(org_id):
                continue
            number = number_row(org_id)
            if not number:
                continue
            builder = _one((db.table("site_builders").select("phone_number").eq("id", form["builder_id"]).execute()).data)
            if not builder or not builder.get("phone_number"):
                continue
            # The raw token was only ever shown once (spec §18) and isn't stored — so the
            # reminder can't resend the old link; it points back to whatever gets a fresh one.
            if form["audience"] == "client":
                label = form.get("client_label") or "Your client"
                text = f"{label}'s form is still open, unfinished. Reply FORM here for a fresh link if this one's gone stale."
            else:
                text = "Your brief form is still open, unfinished. Reply FORM here for a fresh link if this one's gone stale."
            _send_text(db, org_id, number, builder["phone_number"], text)
            db.table("site_brief_forms").update({"form_reminder_sent_at": _now_iso(), "updated_at": _now_iso()}).eq("id", form["id"]).execute()
            sent += 1
        except Exception:  # S14
            logger.exception("[site_worker] form reminder failed form=%s", form.get("id"))
    return sent


# ─────────────────────────────── Expiry sweeps (bulk, no per-row loop) ───────────────────────────────

def _expire_forms(db, now: datetime) -> int:
    res = (
        db.table("site_brief_forms").update({"status": "expired", "updated_at": _now_iso()})
        .eq("status", "open").lt("expires_at", now.isoformat()).execute()
    )
    return len(res.data or [])


def _expire_previews(db, now: datetime) -> int:
    res = (
        db.table("sites").update({"rendered_html": None, "status": "brief_complete", "updated_at": _now_iso()})
        .eq("status", "preview_ready").lt("preview_expires_at", now.isoformat()).execute()
    )
    return len(res.data or [])


# ─────────────────────────────── Hosting job SLA (SITE-3 part 2, spec §11.4 step 4) ───────────────────────────────

def _notify_hosting_job(db, org_id: str, job: dict, title: str, body: str, notif_type: str) -> None:
    """Push notification to Trust (every manager) and the job's assignee, if set.
    Pattern 48 rule 2 (resource_type/resource_id, no metadata column)."""
    recipients = set(_get_manager_ids(db, org_id))
    if job.get("assigned_to"):
        recipients.add(job["assigned_to"])
    now_iso = _now_iso()
    for uid in recipients:
        try:
            db.table("notifications").insert({
                "org_id": org_id, "user_id": uid, "title": title[:200], "body": body[:1000],
                "type": notif_type, "resource_type": "site_hosting_job", "resource_id": job["id"],
                "is_read": False, "created_at": now_iso,
            }).execute()
        except Exception:  # S14
            logger.exception("[site_worker] hosting job notify failed job=%s user=%s", job.get("id"), uid)


def _check_hosting_job_sla(db, now: datetime) -> int:
    """
    One pass over every open Standard hosting job:
      - not yet 12h before due, not alerted     → nothing yet
      - within 12h of due, not yet alerted      → amber alert, alerted_12h = True
      - now >= sla_due_at, never alerted overdue→ red alert, alerted_overdue = True,
                                                    last_escalated_at = now
      - now >= sla_due_at, already alerted, and
        >= _SLA_ESCALATE_EVERY_HOURS since the last escalation → re-alert,
                                                    last_escalated_at = now
    Returns the number of jobs that got an alert this pass.
    """
    rows = (
        db.table("site_hosting_jobs").select("*")
        .not_.in_("status", list(_OPEN_JOB_STATUSES_EXCLUDE))
        .not_.is_("sla_due_at", "null").execute()
    ).data or []
    if not rows:
        return 0

    acted = 0
    for job in rows:
        try:
            due = _parse_iso(job.get("sla_due_at"))
            if not due:
                continue
            org_id = job["org_id"]
            label = job.get("domain_used") or "a hosting job"

            if now >= due:
                if not job.get("alerted_overdue"):
                    _notify_hosting_job(db, org_id, job, "Hosting job overdue",
                                         f"{label} is past its 24h SLA.", "hosting_job_overdue")
                    db.table("site_hosting_jobs").update({
                        "alerted_overdue": True, "last_escalated_at": _now_iso(), "updated_at": _now_iso(),
                    }).eq("id", job["id"]).execute()
                    acted += 1
                else:
                    last = _parse_iso(job.get("last_escalated_at")) or due
                    if (now - last) >= timedelta(hours=_SLA_ESCALATE_EVERY_HOURS):
                        _notify_hosting_job(db, org_id, job, "Hosting job still overdue",
                                             f"{label} is still overdue — please check on it.", "hosting_job_overdue")
                        db.table("site_hosting_jobs").update({
                            "last_escalated_at": _now_iso(), "updated_at": _now_iso(),
                        }).eq("id", job["id"]).execute()
                        acted += 1
            elif not job.get("alerted_12h") and (due - now) <= timedelta(hours=_SLA_AMBER_BEFORE_HOURS):
                _notify_hosting_job(db, org_id, job, "Hosting job due soon",
                                     f"{label} is due within 12 hours.", "hosting_job_amber")
                db.table("site_hosting_jobs").update({
                    "alerted_12h": True, "updated_at": _now_iso(),
                }).eq("id", job["id"]).execute()
                acted += 1
        except Exception:  # S14
            logger.exception("[site_worker] hosting job SLA check failed job=%s", job.get("id"))
    return acted


@celery_app.task(name="app.workers.site_worker.run_hosting_job_sla_check")
def run_hosting_job_sla_check() -> dict:
    db = get_supabase()
    started = _now()
    total = {"alerted": 0, "failed": 0}
    try:
        total["alerted"] = _check_hosting_job_sla(db, started)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] hosting job SLA check failed: %s", exc)

    write_worker_log(
        db, worker_name="site_worker.hosting_job_sla", status="failed" if total["failed"] else "passed",
        items_processed=total["alerted"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


# ─────────────────────────────── Entry point ───────────────────────────────

@celery_app.task(name="app.workers.site_worker.run_site_builder_timers")
def run_site_builder_timers() -> dict:
    db = get_supabase()
    started = _now()
    total = {"brief_reminders": 0, "form_reminders": 0, "forms_expired": 0, "previews_expired": 0, "failed": 0}

    for key, fn in (
        ("brief_reminders", lambda: _send_brief_reminders(db, started)),
        ("form_reminders", lambda: _send_form_reminders(db, started)),
        ("forms_expired", lambda: _expire_forms(db, started)),
        ("previews_expired", lambda: _expire_previews(db, started)),
    ):
        try:
            total[key] = fn()
        except Exception as exc:  # S14 — one step failing never stops the others
            total["failed"] += 1
            logger.warning("[site_worker] step %s failed: %s", key, exc)

    write_worker_log(
        db, worker_name="site_worker", status="failed" if total["failed"] else "passed",
        items_processed=total["brief_reminders"] + total["form_reminders"] + total["forms_expired"] + total["previews_expired"],
        items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total
