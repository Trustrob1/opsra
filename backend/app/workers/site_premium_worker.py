"""
app/workers/site_premium_worker.py
------------------------------------
SITE-PREMIUM P2 - the Celery side of Premium generation (spec section 4: "runs in a Celery worker, 1 to 4
minutes, never in a request"). The route inserts a site_designs row (status 'generating') and queues
run_premium_generation(design_id); everything slow happens here.

Tasks:
  * run_premium_generation(design_id)  - the design pipeline for one site. Hard time limit 9 minutes.
  * run_premium_stale_sweep()          - beat, every 10 minutes. A generation row left 'generating' or
                                          'checking' for 20+ minutes (a worker died) is marked failed so the
                                          site is never blocked. Safe to run any time; this is the dry-run.

Pattern 29: load_dotenv() at module level. Pattern 1: get_supabase() inside the task. S14: never raises.

Dry-run (Windows CMD, one line):
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.site_premium_worker import run_premium_stale_sweep; print(run_premium_stale_sweep())"
  Expected: {'swept': 0, 'failed': 0}
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


@celery_app.task(name="app.workers.site_premium_worker.run_premium_generation", soft_time_limit=480, time_limit=540)
def run_premium_generation(design_id: str) -> dict:
    from app.services import site_premium_generation_service as gen
    db = get_supabase()
    started = _now()
    try:
        out = gen.run_generation(db, design_id)
    except Exception as exc:  # S14 - run_generation never raises, this covers a soft time limit or an import error
        logger.exception("[site_premium_worker] generation crashed design=%s", design_id)
        out = {"ok": False, "design_id": design_id, "outcome": "crashed", "errors": [type(exc).__name__]}
    failed = 0 if out.get("ok") or out.get("outcome") in ("fallback_standard", "already_running", "not_found", "superseded") else 1
    write_worker_log(
        db, worker_name="site_premium_worker.generation", status="failed" if failed else "passed",
        items_processed=1, items_failed=failed, error_message=None if not failed else str(out.get("errors"))[:300],
        started_at=started, run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return out


@celery_app.task(name="app.workers.site_premium_worker.run_premium_stale_sweep")
def run_premium_stale_sweep() -> dict:
    from app.services import site_premium_generation_service as gen
    db = get_supabase()
    started = _now()
    out = {"swept": 0, "failed": 0}
    try:
        out["swept"] = gen.sweep_stale(db)
    except Exception as exc:  # S14
        out["failed"] += 1
        logger.warning("[site_premium_worker] stale sweep failed: %s", exc)
    write_worker_log(
        db, worker_name="site_premium_worker.stale_sweep", status="failed" if out["failed"] else "passed",
        items_processed=out["swept"], items_failed=out["failed"], started_at=started,
        run_duration_ms=int((_now() - started).total_seconds() * 1000),
    )
    return out
