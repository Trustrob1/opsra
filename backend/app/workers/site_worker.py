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

Deliberately NOT built here (spec lists them, but nothing exists yet for
either to act on — building them now would be dead code):
  • SLA alerts     — needs an approval/order queue (SITE-3).
  • Renewal reminders — needs hosting/domain renewal dates (SITE-3/SITE-5).
  Opsra's existing generic sla_worker/renewal_worker already cover the
  non-site-engine cases; site-specific versions land with SITE-3/SITE-5.

Runs every 4 hours (not more often — see reasoning in the beat_schedule
comment in celery_app.py): frequent enough that the 20h brief reminder
still lands inside the 24h free-messaging window, infrequent enough that
this barely registers as load on the one existing worker dyno.

S13: no external payloads here (a beat task, not a webhook) — nothing to validate.
S14: each of the 4 steps has its own try/except; within the two reminder
     steps, each row also has its own try/except, so one bad record never
     stops the rest of the sweep.
Pattern 29: load_dotenv() at module level. Pattern 1: get_supabase() inside the task.

Dry-run (Windows CMD, one line):
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.site_worker import run_site_builder_timers; print(run_site_builder_timers())"
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

logger = logging.getLogger(__name__)

_BRIEF_REMINDER_AFTER_HOURS = 20
_FORM_REMINDER_AFTER_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


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
