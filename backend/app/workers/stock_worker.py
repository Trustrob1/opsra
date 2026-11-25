"""
app/workers/stock_worker.py
---------------------------
STOCK-3.
  release_web_holds   every 15 minutes: website checkouts not paid within 2 hours give their stock back
  low_stock_alert     daily 08:00 WAT (07:00 UTC): notification + owner email for items at or below reorder level

Manual run:
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.stock_worker import low_stock_alert; print(low_stock_alert())"
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import sentry_sdk

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services import stock_alert_service, web_order_stock_service
from app.services.monitoring_service import write_worker_log

logger = logging.getLogger(__name__)


def _run(name: str, fn, count) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = get_supabase()
    try:
        result = fn(db)
        write_worker_log(db, worker_name=name, status="passed", items_processed=count(result), items_failed=0,
                         run_duration_ms=int((time.monotonic() - t0) * 1000), started_at=started)
        return result
    except Exception as exc:
        logger.error("%s failed: %s", name, exc)
        sentry_sdk.capture_exception(exc)
        try:
            write_worker_log(db, worker_name=name, status="failed", error_message=str(exc)[:500], started_at=started)
        except Exception:
            pass
        return {"error": str(exc)}


@celery_app.task(name="app.workers.stock_worker.release_web_holds")
def release_web_holds() -> dict:
    return _run("stock_web_holds", web_order_stock_service.expire_holds, lambda r: r["released"] + r["removed"])


@celery_app.task(name="app.workers.stock_worker.low_stock_alert")
def low_stock_alert() -> dict:
    return _run("stock_low_alert", stock_alert_service.alert_all, lambda r: r["low"])
