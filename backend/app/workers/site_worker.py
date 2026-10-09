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

SITE-3 leftover — a THIRD task in this file:

  • run_approval_summary — spec §6.2 / §19. At 08:00 WAT (07:00 UTC) every
    managers-level user gets ONE in-app notification plus a push listing the
    orders still waiting in `awaiting_approval` (count, total, domains, and
    how long until the earliest 24h SLA deadline). Orders paid between 23:00
    and 08:00 wait for the approval window, and this is what tells Trust they
    are there. Nothing is sent when nothing is waiting. A 20-hour dedup guard
    stops a beat restart from sending it twice.

SITE-4 part A — a FOURTH task in this file:

  • run_renewal_cycle — daily at 06:30 UTC (07:30 WAT). Persists domain/site
    status (active / expiring / lapsed), sends the builder's 30/14/7-day renewal
    reminders with a payment link, WhatsApps the client at <= 5 days when the
    renewal is still unpaid, and alerts once when a domain lapses. All the logic
    lives in services/site_renewal_service.py.

SITE-4 part B — two more tasks in this file (services/site_care_plan_service.py):

  • run_care_cycle   — daily 06:45 UTC (07:45 WAT). Care plans move active -> grace -> ended, and a plan
    within 5 days of its end gets one payment link by WhatsApp (retried like renewals).
  • run_asset_cleanup — daily 03:00 UTC. Uploaded images of sites cancelled, or lapsed, for 90 days are
    deleted (storage + site_assets rows; text and the site record stay). Managers are warned 7 days before.

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
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.site_worker import run_approval_summary; print(run_approval_summary())"
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


def _push(db, user_id: str, title: str, body: str) -> None:
    """PWA push to one user (PWA-1). S14: never raises, and a missing push token is simply a no-op."""
    try:
        from app.routers.push_notifications import send_push_notification
        send_push_notification(db=db, user_id=user_id, title=title[:200], body=body[:500])
    except Exception:  # S14
        logger.exception("[site_worker] push failed user=%s", user_id)


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
        _push(db, uid, title, body)


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


# ─────────────────────────────── Morning approval summary (SITE-3 leftover, spec §6.2 / §19) ───────────────────────────────

_APPROVAL_SUMMARY_TYPE = "site_approval_summary"
_APPROVAL_SUMMARY_DEDUP_HOURS = 20      # a daily job: a beat restart inside this window must not send it twice
_SUMMARY_MAX_DOMAINS_LISTED = 3


def _naira(n) -> str:
    try:
        return f"\u20a6{round(float(n)):,}"
    except (TypeError, ValueError):
        return "\u20a60"


def _summarise_waiting_orders(orders: list, now: datetime) -> tuple[str, str]:
    """(title, body) for the orders sitting in awaiting_approval."""
    count = len(orders)
    total = sum(float(o.get("amount") or 0) for o in orders)
    title = f"{count} order{'s' if count != 1 else ''} waiting for approval"

    domains = [o.get("domain") for o in orders if o.get("domain")]
    listed = ", ".join(domains[:_SUMMARY_MAX_DOMAINS_LISTED])
    if len(domains) > _SUMMARY_MAX_DOMAINS_LISTED:
        listed += f" +{len(domains) - _SUMMARY_MAX_DOMAINS_LISTED} more"

    parts = [f"{_naira(total)} paid"]
    if listed:
        parts.append(listed)

    dues = [d for d in (_parse_iso(o.get("sla_due_at")) for o in orders) if d]
    if dues:
        earliest = min(dues)
        if earliest <= now:
            parts.append("the earliest is already past its 24h deadline")
        else:
            mins = int((earliest - now).total_seconds() // 60)
            parts.append(f"earliest deadline in {mins // 60}h {mins % 60:02d}m")

    body = ". ".join(parts) + ". Open Sites \u2192 Orders to approve."
    return title, body


def _send_approval_summary(db, now: datetime) -> dict:
    """
    One summary per org that has orders in awaiting_approval, to every manager (in-app + push).
    Returns {"orgs": orgs notified, "orders": orders summarised, "failed": orgs that errored}.
    """
    rows = (
        db.table("site_orders").select("id, org_id, domain, amount, sla_due_at, created_at")
        .eq("status", "awaiting_approval").execute()
    ).data or []
    result = {"orgs": 0, "orders": 0, "failed": 0}
    if not rows:
        return result

    by_org: dict[str, list] = {}
    for row in rows:
        by_org.setdefault(row["org_id"], []).append(row)

    org_active, _ = _org_cache(db)
    cutoff = (now - timedelta(hours=_APPROVAL_SUMMARY_DEDUP_HOURS)).isoformat()
    now_iso = _now_iso()

    for org_id, orders in by_org.items():
        try:
            if not org_active(org_id):
                continue
            already = (
                db.table("notifications").select("id").eq("org_id", org_id)
                .eq("type", _APPROVAL_SUMMARY_TYPE).gte("created_at", cutoff).limit(1).execute()
            ).data
            if already:
                continue
            orders.sort(key=lambda o: str(o.get("sla_due_at") or "9999"))
            title, body = _summarise_waiting_orders(orders, now)
            for uid in set(_get_manager_ids(db, org_id)):
                try:
                    db.table("notifications").insert({
                        "org_id": org_id, "user_id": uid, "title": title[:200], "body": body[:1000],
                        "type": _APPROVAL_SUMMARY_TYPE, "resource_type": "site_order",
                        "resource_id": orders[0]["id"], "is_read": False, "created_at": now_iso,
                    }).execute()
                except Exception:  # S14
                    logger.exception("[site_worker] approval summary notify failed org=%s user=%s", org_id, uid)
                _push(db, uid, title, body)
            result["orgs"] += 1
            result["orders"] += len(orders)
        except Exception:  # S14 — one org failing never stops the others
            result["failed"] += 1
            logger.exception("[site_worker] approval summary failed org=%s", org_id)
    return result


@celery_app.task(name="app.workers.site_worker.run_approval_summary")
def run_approval_summary() -> dict:
    db = get_supabase()
    started = _now()
    total = {"orgs": 0, "orders": 0, "failed": 0}
    try:
        total = _send_approval_summary(db, started)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] approval summary failed: %s", exc)

    write_worker_log(
        db, worker_name="site_worker.approval_summary", status="failed" if total["failed"] else "passed",
        items_processed=total["orders"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


@celery_app.task(name="app.workers.site_worker.run_renewal_cycle")
def run_renewal_cycle() -> dict:
    from app.services import site_renewal_service
    db = get_supabase()
    started = _now()
    total = {"checked": 0, "status_updates": 0, "reminders": 0, "client_contacts": 0,
             "lapsed": 0, "needs_attention": 0, "failed": 0}
    try:
        org_active, _ = _org_cache(db)
        total = site_renewal_service.run_cycle(db, started, org_active)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] renewal cycle failed: %s", exc)

    write_worker_log(
        db, worker_name="site_worker.renewal_cycle", status="failed" if total["failed"] else "passed",
        items_processed=total["checked"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


@celery_app.task(name="app.workers.site_worker.run_care_cycle")
def run_care_cycle() -> dict:
    from app.services import site_care_plan_service
    db = get_supabase()
    started = _now()
    total = {"checked": 0, "status_updates": 0, "reminders": 0, "ended": 0, "needs_attention": 0, "failed": 0}
    try:
        org_active, _ = _org_cache(db)
        total = site_care_plan_service.run_cycle(db, started, org_active)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] care cycle failed: %s", exc)
    write_worker_log(
        db, worker_name="site_worker.care_cycle", status="failed" if total["failed"] else "passed",
        items_processed=total["checked"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


@celery_app.task(name="app.workers.site_worker.run_giveaway_deadlines")
def run_giveaway_deadlines() -> dict:
    """GIVEAWAY-2: hourly. Unpaid winners get a reminder, then at the pay-by time the slot is freed and the normal rate applies (lapsed); after the extra days the site is taken down (released)."""
    from app.services import site_giveaway_service
    db = get_supabase()
    started = _now()
    total = {"checked": 0, "reminded": 0, "lapsed": 0, "released": 0, "failed": 0}
    try:
        total = site_giveaway_service.run_deadlines(db, started)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] giveaway deadlines failed: %s", exc)
    write_worker_log(
        db, worker_name="site_worker.giveaway_deadlines", status="failed" if total["failed"] else "passed",
        items_processed=total["checked"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


@celery_app.task(name="app.workers.site_worker.run_asset_cleanup")
def run_asset_cleanup() -> dict:
    from app.services import site_care_plan_service
    db = get_supabase()
    started = _now()
    total = {"checked": 0, "warned": 0, "cleaned_sites": 0, "files_removed": 0, "failed": 0}
    try:
        org_active, _ = _org_cache(db)
        total = site_care_plan_service.run_cleanup(db, started, org_active)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[site_worker] asset cleanup failed: %s", exc)
    write_worker_log(
        db, worker_name="site_worker.asset_cleanup", status="failed" if total["failed"] else "passed",
        items_processed=total["cleaned_sites"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return total


# ─────────────────────────────── Offsite backup (SITE-BACKUP) ───────────────────────────────

_BACKUP_ALERT_TYPE = "site_backup_alert"
_BACKUP_ALERT_DEDUP_HOURS = 20


def _alert_backup_problem(db, now: datetime, title: str, body: str) -> int:
    """In-app notification + push to the managers of every org that has site orders.
    One alert per org per 20 hours, so the run alert and the morning watchdog don't both fire.
    Returns the number of orgs alerted. S14: never raises."""
    alerted = 0
    try:
        org_ids = {r["org_id"] for r in (db.table("site_orders").select("org_id").limit(1000).execute()).data or []
                   if r.get("org_id")}
    except Exception:  # S14
        logger.exception("[site_worker] backup alert: org lookup failed")
        return 0
    cutoff = (now - timedelta(hours=_BACKUP_ALERT_DEDUP_HOURS)).isoformat()
    for org_id in org_ids:
        try:
            try:
                already = (db.table("notifications").select("id").eq("org_id", org_id)
                           .eq("type", _BACKUP_ALERT_TYPE).gte("created_at", cutoff).limit(1).execute()).data
            except Exception:  # S14 — a slow or failed lookup must never swallow the alert; better twice than never
                logger.warning("[site_worker] backup alert dedup lookup failed org=%s; sending anyway", org_id)
                already = None
            if already:
                continue
            for uid in set(_get_manager_ids(db, org_id)):
                try:
                    db.table("notifications").insert({
                        "org_id": org_id, "user_id": uid, "title": title[:200], "body": body[:1000],
                        "type": _BACKUP_ALERT_TYPE, "resource_type": "site_backup_run", "resource_id": None,
                        "is_read": False, "created_at": now.isoformat(),
                    }).execute()
                except Exception:  # S14
                    logger.exception("[site_worker] backup alert notify failed org=%s user=%s", org_id, uid)
                _push(db, uid, title, body)
            alerted += 1
        except Exception:  # S14
            logger.exception("[site_worker] backup alert failed org=%s", org_id)
    return alerted


@celery_app.task(name="app.workers.site_worker.run_site_backup")
def run_site_backup() -> dict:
    from app.services import site_backup_service
    db = get_supabase()
    started = _now()
    total = {"status": "failed", "domains_total": 0, "domains_backed_up": 0, "domains_unchanged": 0,
             "domains_failed": 0, "files_copied": 0, "snapshots_pruned": 0, "error": None}
    try:
        total = site_backup_service.run_backup(db, now=started)
        if total["status"] in ("failed", "partial"):
            title = "Site backup failed" if total["status"] == "failed" else "Site backup incomplete"
            _alert_backup_problem(db, started, title, total.get("error") or "See the backup run record.")
    except Exception as exc:  # S14
        total["status"] = "failed"
        total["error"] = str(exc)[:500]
        logger.exception("[site_worker] site backup crashed")
        _alert_backup_problem(db, started, "Site backup failed", total["error"])

    failed = 1 if total["status"] in ("failed", "partial") else 0
    write_worker_log(
        db, worker_name="site_worker.site_backup", status="failed" if failed else "passed",
        items_processed=total.get("domains_backed_up", 0) + total.get("domains_unchanged", 0),
        items_failed=total.get("domains_failed", 0) or failed, error_message=total.get("error"),
        started_at=started, run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return {k: total.get(k) for k in ("status", "domains_total", "domains_backed_up", "domains_unchanged",
                                      "domains_failed", "files_copied", "snapshots_pruned", "error")}


@celery_app.task(name="app.workers.site_worker.prepare_backup_host")
def prepare_backup_host(domain: str = None, snapshot_date: str = None) -> dict:
    """SITE-STANDBY — run by hand (Render Shell) when a site must be served from the standby host."""
    from app.services import site_backup_service
    started = _now()
    try:
        out = site_backup_service.prepare_backup_host(domain, snapshot_date)
    except Exception as exc:  # S14
        logger.exception("[site_worker] prepare_backup_host crashed")
        out = {"ok": False, "results": [], "failed": [{"domain": domain or "*", "status": "failed", "error": str(exc)[:300]}]}
    write_worker_log(
        get_supabase(), worker_name="site_worker.prepare_backup_host",
        status="passed" if out["ok"] else "failed", items_processed=len(out["results"]),
        items_failed=len(out["failed"]), error_message=(out["failed"][0]["error"] if out["failed"] else None),
        started_at=started, run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return out


@celery_app.task(name="app.workers.site_worker.run_site_backup_watchdog")
def run_site_backup_watchdog() -> dict:
    from app.services import site_backup_service
    db = get_supabase()
    started = _now()
    result = {"problem": None, "alerted_orgs": 0, "failed": 0}
    try:
        # Nothing to back up (and nobody to tell) until the site engine has at least one order.
        has_sites = bool((db.table("site_orders").select("id").limit(1).execute()).data)
        if has_sites:
            problem = site_backup_service.backup_problem(db, started)
            if problem:
                result["problem"] = problem
                result["alerted_orgs"] = _alert_backup_problem(db, started, "Site backups need attention", problem)
    except Exception as exc:  # S14
        result["failed"] += 1
        logger.warning("[site_worker] backup watchdog failed: %s", exc)
    write_worker_log(
        db, worker_name="site_worker.site_backup_watchdog", status="failed" if result["failed"] else "passed",
        items_processed=1, items_failed=result["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return result


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
