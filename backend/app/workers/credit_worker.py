"""
app/workers/credit_worker.py
----------------------------
CREDITS-1 — nightly credit housekeeping. Runs 02:00 UTC (03:00 WAT).

  1. Expire credit lots past their 12-month life (SQL function credit_expire).
  2. Reconcile: for every wallet, balance_kobo must equal the sum of the
     ledger and the sum of the live lots. Any difference is reported to
     Sentry and the worker log; nothing is corrected automatically.

dry_run=True counts and reports without writing anything.
S14: one org's failure never stops the others.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


def reconcile_wallets(db) -> list[dict]:
    """Return one dict per wallet whose balance disagrees with its ledger or lots."""
    problems: list[dict] = []
    wallets = db.table("credit_wallets").select("org_id, balance_kobo").execute().data or []
    for w in wallets:
        org_id = w["org_id"]
        try:
            ledger = db.table("credit_ledger").select("amount_kobo").eq("org_id", org_id).execute().data or []
            lots = db.table("credit_lots").select("remaining_kobo").eq("org_id", org_id).execute().data or []
            ledger_sum = sum(int(r["amount_kobo"]) for r in ledger)
            lots_sum = sum(int(r["remaining_kobo"]) for r in lots)
            bal = int(w["balance_kobo"])
            if bal != ledger_sum or bal != lots_sum:
                problems.append({"org_id": org_id, "balance": bal, "ledger_sum": ledger_sum, "lots_sum": lots_sum})
        except Exception as exc:
            logger.warning("credit reconcile failed for org %s: %s", org_id, exc)
    return problems


def run_credit_housekeeping(db, dry_run: bool = False) -> dict:
    expired = db.rpc("credit_expire", {"p_dry_run": dry_run}).execute().data
    problems = reconcile_wallets(db)
    for p in problems:
        sentry_sdk.capture_message(f"Credit wallet mismatch: {p}", level="error")
    return {"dry_run": dry_run, "lots_expired": int(expired or 0), "mismatches": problems}


@celery_app.task(name="app.workers.credit_worker.run_credit_housekeeping_task")
def run_credit_housekeeping_task(dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = get_supabase()
    try:
        result = run_credit_housekeeping(db, dry_run=dry_run)
        write_worker_log(
            db, worker_name="credit_housekeeping",
            status="failed" if result["mismatches"] else "success",
            items_processed=result["lots_expired"], items_failed=len(result["mismatches"]),
            run_duration_ms=int((time.monotonic() - t0) * 1000), started_at=started,
        )
        return result
    except Exception as exc:
        logger.error("credit housekeeping failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        write_worker_log(db, worker_name="credit_housekeeping", status="failed",
                         error_message=str(exc)[:500], started_at=started)
        return {"error": str(exc)}
