"""
app/workers/health_score_worker.py
------------------------------------
PERF-1C Celery worker — recalculates and caches org health scores.

Beat schedule: every 30 minutes (registered in celery_app.py).
Pattern 48  — uses get_supabase() not get_db().
S14         — per-org failure never stops the loop; logged and skipped.
Pattern 57  — all imports at module level.

Dry-run verification:
    python -c "
    from unittest.mock import MagicMock, patch
    import app.workers.health_score_worker as w
    with patch('app.workers.health_score_worker.get_supabase') as mock_db, \
         patch('app.workers.health_score_worker.asyncio') as mock_async:
        mock_db.return_value = MagicMock()
        mock_async.get_event_loop.return_value.run_until_complete.return_value = {'health_score': 80}
        result = w.run_health_score_recalc()
        print(result)
    "
    Expected: {'processed': N, 'failed': 0}
"""
from __future__ import annotations

import asyncio
import logging

from app.workers.celery_app import celery_app
from app.database import get_supabase
import app.services.performance_service as perf_svc

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.health_score_worker.run_health_score_recalc")
def run_health_score_recalc() -> dict:
    """
    Fetch all active orgs and recalculate health score for each.
    S14: per-org failure is caught and logged — loop always continues.
    """
    db = get_supabase()

    # Fetch all active orgs — only id needed (E4: selective columns)
    orgs_res = db.table("organisations").select("id").eq("is_live", True).execute()
    orgs = orgs_res.data or []

    processed = 0
    failed = 0

    loop = asyncio.new_event_loop()
    try:
        for org in orgs:
            org_id = org["id"]
            try:
                # Invalidate cache first so fresh data is computed and stored
                perf_svc._cache_delete(f"perf:health:{org_id}")
                loop.run_until_complete(perf_svc.get_health_score(db, org_id))
                processed += 1
                logger.info("health_score_recalc: org=%s ok", org_id)
            except Exception as exc:
                # S14 — never let one org failure kill the whole run
                failed += 1
                logger.error("health_score_recalc: org=%s failed: %s", org_id, exc)
    finally:
        loop.close()

    logger.info(
        "health_score_recalc complete: processed=%d failed=%d",
        processed, failed,
    )
    return {"processed": processed, "failed": failed}
