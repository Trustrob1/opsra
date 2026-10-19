"""
app/workers/account_plan_worker.py
----------------------------------
ACCOUNT-PLANS AP-2 - daily sweep of organisation plans: active -> grace -> paused by their dates, renewal reminders to the
owner, and (for a business that has been switched on) the organisation status kept in step. Runs 07:10 UTC (08:10 WAT).
S14: one plan's failure never stops the others.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.account_plan_worker.run_plan_cycle")
def run_plan_cycle() -> dict:
    from app.services import account_plan_billing_service
    db = get_supabase()
    started = datetime.now(timezone.utc)
    total = {"checked": 0, "to_grace": 0, "paused": 0, "reminders": 0, "failed": 0}
    try:
        total = account_plan_billing_service.run_cycle(db, started)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[account_plan_worker] cycle failed: %s", exc)
    write_worker_log(
        db, worker_name="account_plan_worker.plan_cycle", status="failed" if total["failed"] else "passed",
        items_processed=total["checked"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    )
    return total
