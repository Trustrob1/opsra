"""
app/workers/notification_retention_worker.py
--------------------------------------------
NOTIF-CLEANUP - daily 03:15 UTC. Deletes read notifications older than 90 days and any older than 180 days, in small batches
through the SQL function purge_old_notifications (so the table cannot grow without limit again).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)
BATCH = 5000
MAX_BATCHES = 10          # at most 50,000 rows a day; the table is small after the one-off cleanup


def purge(db, batch: int = BATCH, max_batches: int = MAX_BATCHES) -> dict:
    deleted, failed = 0, 0
    for _ in range(max_batches):
        try:
            res = db.rpc("purge_old_notifications", {"p_batch": batch}).execute()
            data = res.data
            n = int(data[0] if isinstance(data, list) and data else (data or 0))
        except Exception as exc:  # S14
            failed += 1
            logger.warning("notification_retention: batch failed: %s", exc)
            break
        deleted += n
        if n < batch:
            break
    return {"deleted": deleted, "failed": failed}


@celery_app.task(name="app.workers.notification_retention_worker.run_notification_retention")
def run_notification_retention() -> dict:
    db = get_supabase()
    started = datetime.now(timezone.utc)
    out = purge(db)
    write_worker_log(
        db, worker_name="notification_retention_worker.run", status="failed" if out["failed"] else "passed",
        items_processed=out["deleted"], items_failed=out["failed"], started_at=started,
        run_duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    )
    return out
