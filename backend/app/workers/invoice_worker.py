"""
app/workers/invoice_worker.py
-----------------------------
INV-5 - daily 10:00 Lagos (09:00 UTC): overdue invoice reminders (businesses that turned them on) and a task when a
quote expires. The work is in services/invoice_followup_service.run(). dry_run=True counts without sending or writing.
S14: never raises.

Dry run (Windows CMD, in backend, one line):
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.invoice_worker import run_invoice_followup; print(run_invoice_followup(dry_run=True))"
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services import invoice_followup_service
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.invoice_worker.run_invoice_followup")
def run_invoice_followup(dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = get_supabase()
    try:
        result = invoice_followup_service.run(db, dry_run=dry_run)
        if not dry_run:
            write_worker_log(db, worker_name="invoice_followup", status="passed",
                             items_processed=result["reminders_sent"] + result["quotes_expired"],
                             items_failed=result["failed"], run_duration_ms=int((time.monotonic() - t0) * 1000),
                             started_at=started)
        return result
    except Exception as exc:
        logger.error("invoice follow-up failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        try:
            write_worker_log(db, worker_name="invoice_followup", status="failed", error_message=str(exc)[:500],
                             started_at=started)
        except Exception:
            pass
        return {"error": str(exc)}
