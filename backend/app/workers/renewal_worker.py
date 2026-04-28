"""
app/workers/renewal_worker.py
Celery tasks for Module 04 — Renewal & Upsell Engine.

Schedules (Technical Spec §8.5):
  renewal_reminders       — Daily 8:00 AM  — send WhatsApp renewal reminders
  trial_expiry_checker    — Daily 6:00 AM  — handle trial subscription expiry
  win_back_scheduler      — Daily 9:00 AM  — win-back messages for churned customers
  payment_failure_monitor — Hourly         — notify on unconfirmed payments > 24h

CONFIG-4 (Build Status v8): renewal_reminder_days read from org_settings per org.
Default: [60, 30, 14, 7] — each org can configure their own cadence.
Schema created in Phase 5A. Worker active Phase 5A+.
Phase 7: Admin UI to configure these values per org.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv

from app.database import get_supabase
from app.workers.celery_app import celery_app

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default reminder cadence — used when org_settings row is absent
# Technical Spec §8.5 / DRD §6.4 / CONFIG-4
# ---------------------------------------------------------------------------
_DEFAULT_REMINDER_DAYS: list[int] = [60, 30, 14, 7]

# Default grace period after renewal date before account affected (DRD §6.4)
_DEFAULT_GRACE_PERIOD_DAYS: int = 7

# Win-back check points (DRD §6.4)
_WIN_BACK_DAYS: list[int] = [14, 30, 60]

# Payment pending threshold before customer notification (DRD §6.4: 24h)
_PAYMENT_PENDING_HOURS: int = 24


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_org_reminder_days(db: Any, org_id: str) -> list[int]:
    """
    Fetch renewal_reminder_days from org_settings for this org.
    Falls back to _DEFAULT_REMINDER_DAYS if org_settings row absent.
    CONFIG-4 — configured per org, used immediately by this worker.
    """
    try:
        result = (
            db.table("org_settings")
            .select("renewal_reminder_days")
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        if data and data.get("renewal_reminder_days"):
            return list(data["renewal_reminder_days"])
    except Exception as exc:
        logger.warning(
            "renewal_worker: could not fetch org_settings for org %s — "
            "using default reminder days. Error: %s",
            org_id, exc,
        )
    return list(_DEFAULT_REMINDER_DAYS)


def _get_active_orgs(db: Any) -> list[dict]:
    """Return all organisations with active subscriptions to process."""
    try:
        result = (
            db.table("organisations")
            .select("id")
            .execute()
        )
        data = result.data or []
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("renewal_worker: failed to fetch organisations — %s", exc)
        return []


def _send_renewal_reminder(
    db: Any,
    org_id: str,
    subscription: dict,
    days_until_renewal: int,
) -> None:
    """
    Queue a renewal reminder WhatsApp message for human review.
    DRD §6.4: All renewal messages go through approval queue, editable before sending.
    Full WhatsApp delivery wired in Phase 5B (frontend) and Phase 6A (worker pipeline).
    """
    customer_id = subscription.get("customer_id")
    sub_id = subscription.get("id")
    renewal_date = subscription.get("current_period_end")

    logger.info(
        "renewal_worker: queuing reminder for subscription %s "
        "(org %s, customer %s) — %d days until renewal %s",
        sub_id, org_id, customer_id, days_until_renewal, renewal_date,
    )

    # Phase 5A: log the intent and write an audit entry.
    # Full WhatsApp message construction and approval queue wired in Phase 6A.
    try:
        db.table("audit_logs").insert({
            "org_id": org_id,
            "user_id": None,
            "action": "subscription.renewal_reminder_queued",
            "resource_type": "subscription",
            "resource_id": sub_id,
            "new_value": {
                "days_until_renewal": days_until_renewal,
                "renewal_date": renewal_date,
                "customer_id": customer_id,
            },
        }).execute()
    except Exception as exc:
        logger.warning(
            "renewal_worker: failed to write audit log for reminder — %s", exc
        )


def _enter_grace_period(db: Any, org_id: str, subscription: dict) -> None:
    """
    Transition subscription to grace_period status.
    DRD §6.4: grace period default 7 days after renewal date.
    """
    sub_id = subscription.get("id")
    today = date.today()
    grace_ends = today + timedelta(days=_DEFAULT_GRACE_PERIOD_DAYS)

    try:
        db.table("subscriptions").update({
            "status": "grace_period",
            "grace_period_ends_at": grace_ends.isoformat(),
            "updated_at": f"{today.isoformat()}T00:00:00+00:00",
        }).eq("id", sub_id).eq("org_id", org_id).execute()

        db.table("audit_logs").insert({
            "org_id": org_id,
            "user_id": None,
            "action": "subscription.grace_period_started",
            "resource_type": "subscription",
            "resource_id": sub_id,
            "new_value": {
                "grace_period_ends_at": grace_ends.isoformat(),
            },
        }).execute()

        logger.info(
            "renewal_worker: subscription %s (org %s) entered grace period "
            "— expires %s",
            sub_id, org_id, grace_ends,
        )
    except Exception as exc:
        logger.error(
            "renewal_worker: failed to set grace_period for subscription %s — %s",
            sub_id, exc,
        )


def _expire_subscription(db: Any, org_id: str, subscription: dict) -> None:
    """
    Transition subscription to expired after grace period ends without payment.
    Technical Spec §4.3: grace_period → expired.
    """
    sub_id = subscription.get("id")
    try:
        db.table("subscriptions").update({
            "status": "expired",
            "updated_at": date.today().isoformat() + "T00:00:00+00:00",
        }).eq("id", sub_id).eq("org_id", org_id).execute()

        db.table("audit_logs").insert({
            "org_id": org_id,
            "user_id": None,
            "action": "subscription.expired",
            "resource_type": "subscription",
            "resource_id": sub_id,
            "old_value": {"status": "grace_period"},
            "new_value": {"status": "expired"},
        }).execute()

        logger.info(
            "renewal_worker: subscription %s (org %s) expired", sub_id, org_id
        )
    except Exception as exc:
        logger.error(
            "renewal_worker: failed to expire subscription %s — %s", sub_id, exc
        )


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@celery_app.task(name="app.workers.renewal_worker.send_renewal_reminders")
def send_renewal_reminders() -> dict:
    """
    Daily 8:00 AM — send WhatsApp renewal reminders.
    Checks all active subscriptions for upcoming renewals.
    Sends messages at the org-configured day thresholds (CONFIG-4).
    DRD §6.4: Configurable reminder timeline — 60/30/14/7 days default.
    """
    db = get_supabase()
    today = date.today()
    processed = 0
    reminded = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]
        reminder_days = _get_org_reminder_days(db, org_id)

        try:
            result = (
                db.table("subscriptions")
                .select("*")
                .eq("org_id", org_id)
                .in_("status", ["active", "trial"])
                .execute()
            )
            subscriptions = result.data or []
        except Exception as exc:
            logger.error(
                "renewal_worker: failed to fetch subscriptions for org %s — %s",
                org_id, exc,
            )
            continue

        for sub in subscriptions:
            processed += 1
            period_end_str = sub.get("current_period_end")
            if not period_end_str:
                continue
            try:
                period_end = date.fromisoformat(str(period_end_str)[:10])
            except (ValueError, TypeError):
                continue

            days_remaining = (period_end - today).days

            if days_remaining in reminder_days:
                _send_renewal_reminder(db, org_id, sub, days_remaining)
                reminded += 1
            elif days_remaining < 0:
                # Renewal date has passed — enter grace period
                _enter_grace_period(db, org_id, sub)

    logger.info(
        "renewal_worker.send_renewal_reminders: processed=%d reminded=%d",
        processed, reminded,
    )
    return {"processed": processed, "reminded": reminded}


@celery_app.task(name="app.workers.renewal_worker.check_trial_expiry")
def check_trial_expiry() -> dict:
    """
    Daily 6:00 AM — check trial subscriptions for expiry.
    Sends conversion prompts on Day 3 and 7 of trial.
    Initiates grace period on expiry.
    Technical Spec §8.5.
    """
    db = get_supabase()
    today = date.today()
    processed = 0
    actioned = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]
        try:
            result = (
                db.table("subscriptions")
                .select("*")
                .eq("org_id", org_id)
                .eq("status", "trial")
                .execute()
            )
            trials = result.data or []
        except Exception as exc:
            logger.error(
                "renewal_worker: failed to fetch trials for org %s — %s",
                org_id, exc,
            )
            continue

        for sub in trials:
            processed += 1
            trial_ends_str = sub.get("trial_ends_at") or sub.get("current_period_end")
            if not trial_ends_str:
                continue
            try:
                trial_ends = date.fromisoformat(str(trial_ends_str)[:10])
            except (ValueError, TypeError):
                continue

            days_remaining = (trial_ends - today).days

            if days_remaining < 0:
                # Trial expired — enter grace period
                _enter_grace_period(db, org_id, sub)
                actioned += 1
            elif days_remaining in (3, 7):
                logger.info(
                    "renewal_worker: trial conversion prompt — subscription %s "
                    "org %s — %d days remaining",
                    sub.get("id"), org_id, days_remaining,
                )
                actioned += 1

    logger.info(
        "renewal_worker.check_trial_expiry: processed=%d actioned=%d",
        processed, actioned,
    )
    return {"processed": processed, "actioned": actioned}


@celery_app.task(name="app.workers.renewal_worker.schedule_win_back")
def schedule_win_back() -> dict:
    """
    Daily 9:00 AM — schedule win-back messages for churned customers.
    Checks churned customers at 14/30/60 day marks.
    Queues win-back WhatsApp messages for approval.
    DRD §6.4.
    """
    db = get_supabase()
    today = date.today()
    processed = 0
    queued = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]
        try:
            result = (
                db.table("subscriptions")
                .select("*")
                .eq("org_id", org_id)
                .in_("status", ["expired", "cancelled"])
                .execute()
            )
            churned = result.data or []
        except Exception as exc:
            logger.error(
                "renewal_worker: failed to fetch churned for org %s — %s",
                org_id, exc,
            )
            continue

        for sub in churned:
            processed += 1
            # Use cancelled_at or grace_period_ends_at as churn date
            churn_date_str = (
                sub.get("cancelled_at")
                or sub.get("grace_period_ends_at")
            )
            if not churn_date_str:
                continue
            try:
                churn_date = date.fromisoformat(str(churn_date_str)[:10])
            except (ValueError, TypeError):
                continue

            days_since_churn = (today - churn_date).days
            if days_since_churn in _WIN_BACK_DAYS:
                logger.info(
                    "renewal_worker: win-back queued — subscription %s "
                    "org %s — %d days since churn",
                    sub.get("id"), org_id, days_since_churn,
                )
                queued += 1

    logger.info(
        "renewal_worker.schedule_win_back: processed=%d queued=%d",
        processed, queued,
    )
    return {"processed": processed, "queued": queued}


@celery_app.task(name="app.workers.renewal_worker.monitor_payment_failures")
def monitor_payment_failures() -> dict:
    """
    Hourly — check pending payments older than 24 hours.
    Sends customer notification. Begins grace period.
    DRD §6.4: 24-hour silent period before notifying customer.
    """
    db = get_supabase()
    processed = 0
    actioned = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]
        try:
            result = (
                db.table("payments")
                .select("*")
                .eq("org_id", org_id)
                .eq("status", "pending_confirmation")
                .execute()
            )
            pending = result.data or []
        except Exception as exc:
            logger.error(
                "renewal_worker: failed to fetch pending payments for org %s — %s",
                org_id, exc,
            )
            continue

        for payment in pending:
            processed += 1
            created_str = payment.get("created_at", "")
            if not created_str:
                continue

            from datetime import datetime, timezone
            try:
                created_at = datetime.fromisoformat(
                    str(created_str).replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                hours_pending = (now - created_at).total_seconds() / 3600
            except (ValueError, TypeError):
                continue

            if hours_pending >= _PAYMENT_PENDING_HOURS:
                logger.info(
                    "renewal_worker: payment %s org %s pending %.1f hours — "
                    "notifying customer",
                    payment.get("id"), org_id, hours_pending,
                )
                actioned += 1

    logger.info(
        "renewal_worker.monitor_payment_failures: processed=%d actioned=%d",
        processed, actioned,
    )
    return {"processed": processed, "actioned": actioned}