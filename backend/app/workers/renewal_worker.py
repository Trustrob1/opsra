"""
app/workers/renewal_worker.py
Celery tasks for Module 04 — Renewal & Upsell Engine.

9E-D D1: is_org_active() gate applied at top of per-org loop in all four tasks.
D2/D3 not applied — renewal reminders queue for human approval (no direct send).

All other logic unchanged from pre-9E-D version.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv

from app.database import get_supabase
from app.workers.celery_app import celery_app
from app.utils.org_gates import is_org_active  # 9E-D D1

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_REMINDER_DAYS: list[int] = [60, 30, 14, 7]
_DEFAULT_GRACE_PERIOD_DAYS: int = 7
_WIN_BACK_DAYS: list[int] = [14, 30, 60]
_PAYMENT_PENDING_HOURS: int = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_org_reminder_days(db: Any, org_id: str) -> list[int]:
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
    """Return all organisations. D1 gate applied per-org in each task."""
    try:
        result = (
            db.table("organisations")
            .select("id, subscription_status")  # include subscription_status for D1
            .execute()
        )
        data = result.data or []
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("renewal_worker: failed to fetch organisations — %s", exc)
        return []


def _claim_subscription(db: Any, sub_id: str, now_iso: str) -> bool:
    try:
        result = (
            db.table("subscriptions")
            .update({"processing_at": now_iso})
            .eq("id", sub_id)
            .is_("processing_at", "null")
            .execute()
        )
        return bool(result.data)
    except Exception as exc:
        logger.warning(
            "renewal_worker: _claim_subscription failed sub=%s: %s", sub_id, exc
        )
        return False


def _release_stale_claims(db: Any, stale_threshold: str) -> None:
    try:
        db.table("subscriptions").update(
            {"processing_at": None}
        ).lt("processing_at", stale_threshold).execute()
    except Exception as exc:
        logger.warning(
            "renewal_worker: failed to release stale claims: %s", exc
        )


def _send_renewal_reminder(
    db: Any,
    org_id: str,
    subscription: dict,
    days_until_renewal: int,
) -> None:
    customer_id  = subscription.get("customer_id")
    sub_id       = subscription.get("id")
    renewal_date = subscription.get("current_period_end")

    logger.info(
        "renewal_worker: queuing reminder for subscription %s "
        "(org %s, customer %s) — %d days until renewal %s",
        sub_id, org_id, customer_id, days_until_renewal, renewal_date,
    )

    try:
        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       None,
            "action":        "subscription.renewal_reminder_queued",
            "resource_type": "subscription",
            "resource_id":   sub_id,
            "new_value": {
                "days_until_renewal": days_until_renewal,
                "renewal_date":       renewal_date,
                "customer_id":        customer_id,
            },
        }).execute()
    except Exception as exc:
        logger.warning(
            "renewal_worker: failed to write audit log for reminder — %s", exc
        )


def _enter_grace_period(db: Any, org_id: str, subscription: dict) -> None:
    sub_id    = subscription.get("id")
    today     = date.today()
    grace_ends = today + timedelta(days=_DEFAULT_GRACE_PERIOD_DAYS)

    try:
        db.table("subscriptions").update({
            "status":               "grace_period",
            "grace_period_ends_at": grace_ends.isoformat(),
            "updated_at":           f"{today.isoformat()}T00:00:00+00:00",
        }).eq("id", sub_id).eq("org_id", org_id).execute()

        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       None,
            "action":        "subscription.grace_period_started",
            "resource_type": "subscription",
            "resource_id":   sub_id,
            "new_value":     {"grace_period_ends_at": grace_ends.isoformat()},
        }).execute()

        logger.info(
            "renewal_worker: subscription %s (org %s) entered grace period "
            "— expires %s", sub_id, org_id, grace_ends,
        )
    except Exception as exc:
        logger.error(
            "renewal_worker: failed to set grace_period for subscription %s — %s",
            sub_id, exc,
        )


def _expire_subscription(db: Any, org_id: str, subscription: dict) -> None:
    sub_id = subscription.get("id")
    try:
        db.table("subscriptions").update({
            "status":     "expired",
            "updated_at": date.today().isoformat() + "T00:00:00+00:00",
        }).eq("id", sub_id).eq("org_id", org_id).execute()

        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       None,
            "action":        "subscription.expired",
            "resource_type": "subscription",
            "resource_id":   sub_id,
            "old_value":     {"status": "grace_period"},
            "new_value":     {"status": "expired"},
        }).execute()

        logger.info(
            "renewal_worker: subscription %s (org %s) expired", sub_id, org_id
        )
    except Exception as exc:
        logger.error(
            "renewal_worker: failed to expire subscription %s — %s", sub_id, exc
        )


@celery_app.task(name="app.workers.renewal_worker.send_renewal_reminders")
def send_renewal_reminders() -> dict:
    db = get_supabase()
    today             = date.today()
    now_iso           = _now_iso()
    processed         = 0
    reminded          = 0
    skipped_claimed   = 0
    skipped_inactive  = 0

    stale_threshold = (
        datetime.now(timezone.utc) - timedelta(hours=20)
    ).isoformat()
    _release_stale_claims(db, stale_threshold)

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            logger.info(
                "renewal_worker: org %s skipped — subscription_status=%s",
                org_id, org_row.get("subscription_status"),
            )
            skipped_inactive += 1
            continue

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
            period_end_str = sub.get("current_period_end")
            if not period_end_str:
                continue
            try:
                period_end = date.fromisoformat(str(period_end_str)[:10])
            except (ValueError, TypeError):
                continue

            days_remaining = (period_end - today).days

            if days_remaining in reminder_days:
                if not _claim_subscription(db, sub["id"], now_iso):
                    skipped_claimed += 1
                    continue
                processed += 1
                _send_renewal_reminder(db, org_id, sub, days_remaining)
                reminded += 1

            elif days_remaining < 0:
                if not _claim_subscription(db, sub["id"], now_iso):
                    skipped_claimed += 1
                    continue
                processed += 1
                _enter_grace_period(db, org_id, sub)

    logger.info(
        "renewal_worker.send_renewal_reminders: processed=%d reminded=%d "
        "skipped_claimed=%d skipped_inactive=%d",
        processed, reminded, skipped_claimed, skipped_inactive,
    )
    return {
        "processed":        processed,
        "reminded":         reminded,
        "skipped_claimed":  skipped_claimed,
        "skipped_inactive": skipped_inactive,
    }


@celery_app.task(name="app.workers.renewal_worker.check_trial_expiry")
def check_trial_expiry() -> dict:
    db = get_supabase()
    today            = date.today()
    now_iso          = _now_iso()
    processed        = 0
    actioned         = 0
    skipped_claimed  = 0
    skipped_inactive = 0

    stale_threshold = (
        datetime.now(timezone.utc) - timedelta(hours=20)
    ).isoformat()
    _release_stale_claims(db, stale_threshold)

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            skipped_inactive += 1
            continue

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
            trial_ends_str = sub.get("trial_ends_at") or sub.get("current_period_end")
            if not trial_ends_str:
                continue
            try:
                trial_ends = date.fromisoformat(str(trial_ends_str)[:10])
            except (ValueError, TypeError):
                continue

            days_remaining = (trial_ends - today).days

            if days_remaining < 0:
                if not _claim_subscription(db, sub["id"], now_iso):
                    skipped_claimed += 1
                    continue
                processed += 1
                _enter_grace_period(db, org_id, sub)
                actioned += 1

            elif days_remaining in (3, 7):
                if not _claim_subscription(db, sub["id"], now_iso):
                    skipped_claimed += 1
                    continue
                processed += 1
                logger.info(
                    "renewal_worker: trial conversion prompt — subscription %s "
                    "org %s — %d days remaining",
                    sub.get("id"), org_id, days_remaining,
                )
                actioned += 1

    logger.info(
        "renewal_worker.check_trial_expiry: processed=%d actioned=%d "
        "skipped_claimed=%d skipped_inactive=%d",
        processed, actioned, skipped_claimed, skipped_inactive,
    )
    return {
        "processed":        processed,
        "actioned":         actioned,
        "skipped_claimed":  skipped_claimed,
        "skipped_inactive": skipped_inactive,
    }


@celery_app.task(name="app.workers.renewal_worker.schedule_win_back")
def schedule_win_back() -> dict:
    db = get_supabase()
    today            = date.today()
    processed        = 0
    queued           = 0
    skipped_inactive = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            skipped_inactive += 1
            continue

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
            churn_date_str = (
                sub.get("cancelled_at") or sub.get("grace_period_ends_at")
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
        "renewal_worker.schedule_win_back: processed=%d queued=%d "
        "skipped_inactive=%d",
        processed, queued, skipped_inactive,
    )
    return {"processed": processed, "queued": queued,
            "skipped_inactive": skipped_inactive}


@celery_app.task(name="app.workers.renewal_worker.monitor_payment_failures")
def monitor_payment_failures() -> dict:
    db = get_supabase()
    processed        = 0
    actioned         = 0
    skipped_inactive = 0

    orgs = _get_active_orgs(db)
    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            skipped_inactive += 1
            continue

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
            try:
                created_at   = datetime.fromisoformat(
                    str(created_str).replace("Z", "+00:00")
                )
                now          = datetime.now(timezone.utc)
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
        "renewal_worker.monitor_payment_failures: processed=%d actioned=%d "
        "skipped_inactive=%d",
        processed, actioned, skipped_inactive,
    )
    return {"processed": processed, "actioned": actioned,
            "skipped_inactive": skipped_inactive}
