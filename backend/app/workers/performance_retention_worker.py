"""
app/workers/performance_retention_worker.py
CPM-1B — Monthly Performance Log Retention Archiver

Celery task: archive_old_performance_logs
Schedule: 1st of each month, 02:00 UTC
S14: per-contractor failure never stops the loop.

For each contractor: delete performance_daily_logs where
log_date < (today - log_retention_months).
Uses contractors.log_retention_months per contractor (default 6).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def archive_old_performance_logs() -> dict:
    """
    Delete performance_daily_logs older than each contractor's
    log_retention_months setting. S14: per-contractor failure
    never stops the loop.

    Returns summary dict with:
      { orgs_processed, contractors_processed, rows_deleted, failed }
    """
    from app.database import get_supabase

    db = get_supabase()
    summary = {
        "orgs_processed": 0,
        "contractors_processed": 0,
        "rows_deleted": 0,
        "failed": 0,
    }

    try:
        # Fetch all active contractors with log tokens configured
        contractors_res = (
            db.table("contractors")
            .select("id, org_id, full_name, log_retention_months")
            .is_("deleted_at", None)
            .not_.is_("log_token", None)
            .execute()
        )
        contractors = contractors_res.data or []
    except Exception as exc:
        logger.error("archive_old_performance_logs: failed to fetch contractors: %s", exc)
        summary["failed"] += 1
        return summary

    seen_orgs: set[str] = set()

    for contractor in contractors:
        try:
            org_id = contractor["org_id"]
            contractor_id = contractor["id"]
            retention_months = contractor.get("log_retention_months") or 6

            if org_id not in seen_orgs:
                seen_orgs.add(org_id)
                summary["orgs_processed"] += 1

            # Compute cutoff date
            today = date.today()
            # Approximate months as 30 days each for simplicity
            cutoff = today - timedelta(days=retention_months * 30)

            # Delete logs older than cutoff for this contractor
            del_res = (
                db.table("performance_daily_logs")
                .delete()
                .eq("entity_id", contractor_id)
                .lt("log_date", cutoff.isoformat())
                .execute()
            )
            deleted = len(del_res.data) if del_res.data else 0
            summary["rows_deleted"] += deleted
            summary["contractors_processed"] += 1

            if deleted > 0:
                logger.info(
                    "archive_old_performance_logs: deleted %d rows for contractor %s (cutoff %s)",
                    deleted, contractor_id, cutoff.isoformat(),
                )
        except Exception as exc:
            # S14: per-contractor failure never stops the loop
            logger.error(
                "archive_old_performance_logs: failed for contractor %s: %s",
                contractor.get("id", "unknown"), exc,
            )
            summary["failed"] += 1

    logger.info("archive_old_performance_logs complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Celery task registration
# Optional guard — allows standalone dry-run without Celery broker.
# ---------------------------------------------------------------------------
try:
    from app.workers.celery_app import celery_app

    @celery_app.task(name="archive_old_performance_logs")
    def archive_old_performance_logs_task() -> dict:
        return archive_old_performance_logs()

except Exception:
    pass
