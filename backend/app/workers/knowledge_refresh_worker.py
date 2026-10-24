"""
app/workers/knowledge_refresh_worker.py
---------------------------------------
WA-AUTO-4c - daily sweep that re-reads website and Google Doc knowledge sources about once a week. Runs 02:30 UTC (03:30 WAT).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.knowledge_refresh_worker.run_knowledge_refresh")
def run_knowledge_refresh() -> dict:
    from app.services import knowledge_refresh_service
    db = get_supabase()
    started = datetime.now(timezone.utc)
    total = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0, "skipped": 0}
    try:
        total = knowledge_refresh_service.run_due(db)
    except Exception as exc:  # S14
        total["failed"] += 1
        logger.warning("[knowledge_refresh_worker] run failed: %s", exc)
    write_worker_log(
        db, worker_name="knowledge_refresh_worker.run", status="failed" if total["failed"] else "passed",
        items_processed=total["checked"], items_failed=total["failed"], started_at=started,
        run_duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    )
    return total
