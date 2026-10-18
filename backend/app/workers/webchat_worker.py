"""
app/workers/webchat_worker.py
-----------------------------
WEBCHAT-1 — hourly sweep: sessions past their (sliding 30-day) expiry are marked expired and their
pre-contact history is cleared. dry_run=True counts without writing.
S14: never raises.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services import webchat_service
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.webchat_worker.run_webchat_sweep")
def run_webchat_sweep(dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = get_supabase()
    try:
        result = webchat_service.sweep(db, dry_run=dry_run)
        write_worker_log(db, worker_name="webchat_sweep", status="success", items_processed=result["expired"],
                         run_duration_ms=int((time.monotonic() - t0) * 1000), started_at=started)
        return result
    except Exception as exc:
        logger.error("webchat sweep failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        write_worker_log(db, worker_name="webchat_sweep", status="failed", error_message=str(exc)[:500], started_at=started)
        return {"error": str(exc)}
