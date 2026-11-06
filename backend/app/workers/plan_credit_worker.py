"""
app/workers/plan_credit_worker.py
---------------------------------
PLANS-3 - the credit a plan includes every month (Growth, Essential and Scale; Chat Basic includes none).

Runs daily at 02:30 UTC (03:30 WAT). For every business that has been switched on for plans (plans_enforced) and whose
tier is active, it adds the tier's included credit (site_entitlement_service tier["included_credit_ngn"], from Settings or
the defaults) to the wallet as ONE lot that expires at the end of the month (Lagos time). Lots are spent oldest-expiry
first, so the plan's credit is used before anything the business topped up.

Rules
  * Once per business per month: the ledger ref plangrant:<org>:<YYYY-MM> makes a re-run (or a late start) harmless.
  * Only wallets with metering on get credit - credit nobody can spend would only expire.
  * Yearly plans get the same amount each month (the tier row is live all year).
  * A plan in its grace period or paused gets nothing that month.
  * No pro-rating: a business that starts on the 25th gets the full month's amount, expiring on the 30th/31st.
  * S14: one business failing never stops the others; nothing here can touch a customer conversation.
dry_run=True counts without writing.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services import account_entitlement_service as acc
from app.services import credit_service as cs
from app.services import site_entitlement_service as ent
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)

REF_PREFIX = "plangrant"


def month_end_lagos(now: datetime) -> datetime:
    """First instant of next month in Lagos time (when this month's plan credit expires)."""
    start = ent.period_start(now)
    y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return datetime(y, m, 1, tzinfo=ent.LAGOS)


def grant_ref(org_id: str, now: datetime) -> str:
    s = ent.period_start(now)
    return f"{REF_PREFIX}:{org_id}:{s.year:04d}-{s.month:02d}"


def grant_for_org(db, org_id: str, now: datetime, dry_run: bool = False) -> Optional[dict]:
    """Returns {"tier","kobo","applied"} when a grant was due, else None. Never raises."""
    try:
        c = acc._compute(db, org_id, now)
        tier_row = next((r for r in c["rows"] if r.get("kind") == "tier" and r.get("effective_status") == "active"), None)
        if not tier_row:
            return None
        amount_ngn = int(((c["cfg"]["tiers"].get(tier_row["key"]) or {}).get("included_credit_ngn")) or 0)
        if amount_ngn <= 0:
            return None
        if not cs.metering_on(cs.get_wallet(db, org_id)):
            return None
        kobo = amount_ngn * 100
        if dry_run:
            return {"tier": tier_row["key"], "kobo": kobo, "applied": False}
        out = cs.add_credit(
            db, org_id, kobo, "adjust", grant_ref(org_id, now),
            meta={"reason": "plan_credit", "tier": tier_row["key"], "month": ent.period_start(now).isoformat()},
            expires_at=month_end_lagos(now).isoformat(),
        )
        return {"tier": tier_row["key"], "kobo": kobo, "applied": bool(out and out.get("applied"))}
    except Exception as exc:
        logger.warning("plan_credit: org=%s failed: %s", org_id, exc)
        return None


def ensure_wallet_and_grant(db, org_id: str, now: Optional[datetime] = None, require_enforced: bool = False) -> Optional[dict]:
    """Called the moment a plan starts (paid, or switched on by staff): if the plan includes monthly credit, make sure the
    business has a wallet (created with metering ON only when it did not exist; an existing wallet's setting is respected,
    so staff can still switch metering off) and add this month's credit now instead of waiting for the nightly run.
    Same ledger ref as the nightly run, so nothing is ever granted twice in a month. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        if require_enforced:
            org = (db.table("organisations").select("plans_enforced").eq("id", org_id).limit(1).execute().data) or []
            if not (org and org[0].get("plans_enforced")):
                return None
        res = grant_for_org(db, org_id, now, dry_run=True)
        if res is None and cs.get_wallet(db, org_id) is None:
            c = acc._compute(db, org_id, now)
            tier_row = next((r for r in c["rows"] if r.get("kind") == "tier" and r.get("effective_status") == "active"), None)
            amount = int(((c["cfg"]["tiers"].get(tier_row["key"]) or {}).get("included_credit_ngn")) or 0) if tier_row else 0
            if amount <= 0:
                return None
            db.table("credit_wallets").upsert({"org_id": org_id, "metering_enabled": True}, on_conflict="org_id", ignore_duplicates=True).execute()
            return grant_for_org(db, org_id, now)
        if res is None:
            return None
        return grant_for_org(db, org_id, now)
    except Exception as exc:
        logger.warning("plan_credit: ensure org=%s failed: %s", org_id, exc)
        return None


def run_plan_credit_grants(db, now: Optional[datetime] = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    orgs = (db.table("organisations").select("id").eq("plans_enforced", True).execute().data) or []
    granted = skipped = 0
    for o in orgs:
        res = grant_for_org(db, o["id"], now, dry_run=dry_run)
        if res and (res["applied"] or dry_run):
            granted += 1
        else:
            skipped += 1
    return {"dry_run": dry_run, "businesses": len(orgs), "granted": granted, "skipped": skipped}


@celery_app.task(name="app.workers.plan_credit_worker.run_plan_credit_grants_task")
def run_plan_credit_grants_task(dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = get_supabase()
    try:
        result = run_plan_credit_grants(db, dry_run=dry_run)
        write_worker_log(db, worker_name="plan_credit_grants", status="success", items_processed=result["granted"],
                         items_failed=0, run_duration_ms=int((time.monotonic() - t0) * 1000), started_at=started)
        return result
    except Exception as exc:
        logger.error("plan credit grants failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        write_worker_log(db, worker_name="plan_credit_grants", status="failed", error_message=str(exc)[:500], started_at=started)
        return {"error": str(exc)}
