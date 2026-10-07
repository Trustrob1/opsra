"""
app/workers/site_import_worker.py
----------------------------------
SITE-IMPORT 2 - the Celery side of "Make editable" (spec section 20). The route marks the import design 'running' and queues
run_make_editable(design_id); everything slow (the Claude call, the proof) happens here.

Tasks:
  * run_make_editable(design_id)  - one import design. Hard time limit 9 minutes. Never raises.

A design left 'running' by a dead worker is marked failed by the next start for that site (site_import_editable_service.sweep_stale),
so no beat task is needed.

Pattern 29: load_dotenv() at module level. Pattern 1: get_supabase() inside the task. S14: never raises.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.services.monitoring_service import write_worker_log  # noqa: E402

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="app.workers.site_import_worker.run_make_editable", soft_time_limit=480, time_limit=540)
def run_make_editable(design_id: str) -> dict:
    from app.services import site_import_editable_service as svc
    db = get_supabase()
    started = _now()
    try:
        out = svc.run(db, design_id)
    except Exception as exc:  # S14 - run never raises; this covers a soft time limit or an import error
        logger.exception("[site_import_worker] make-editable crashed design=%s", design_id)
        out = {"ok": False, "design_id": design_id, "outcome": "crashed", "errors": [type(exc).__name__]}
    failed = 0 if out.get("ok") or out.get("outcome") in ("level1", "already_running", "not_found", "superseded") else 1
    write_worker_log(
        db, worker_name="site_import_worker.make_editable", status="failed" if failed else "passed",
        items_processed=1, items_failed=failed, error_message=None if not failed else str(out.get("errors"))[:300],
        started_at=started, run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return out
