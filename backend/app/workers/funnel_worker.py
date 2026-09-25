"""
app/workers/funnel_worker.py
-----------------------------
FUNNEL-1A — Celery task:

  run_funnel_sequence — every 5 minutes.
    For every ACTIVE event funnel:
      • load the funnel's WhatsApp number (its own credentials),
      • load its new/paid registrations (paginated — Supabase Max Rows),
      • for each registration, plan ONE next step (funnel_service.plan_next_step)
        and execute it (claim via unique funnel_events row → send).

Gates:
  D1: is_org_active() — suspended/read_only orgs skipped entirely.
  D2: is_quiet_hours() — steps wait (they are not lost; staleness rule applies).
  Pause after a reply, daily cap after the early price, stale-step skip — in plan_next_step.

S13: funnel config (messages/sequence/settings) validated via app.models.funnels.
S14: one registration (or one funnel) failing never stops the loop.
Pattern 29: load_dotenv() at module level. Pattern 1: get_supabase() inside the task.

Dry-run (Windows CMD, one line):
  python -c "from dotenv import load_dotenv; load_dotenv(); from app.workers.funnel_worker import run_funnel_sequence; print(run_funnel_sequence())"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.services import funnel_service  # noqa: E402
from app.utils.org_gates import is_org_active, is_quiet_hours  # noqa: E402
from app.services.monitoring_service import write_worker_log  # noqa: E402

logger = logging.getLogger(__name__)


def _sent_counts_last_24h(db, funnel_id: str, now: datetime) -> dict[str, int]:
    since = (now - timedelta(hours=24)).isoformat()
    rows = funnel_service._fetch_all(
        lambda: db.table("funnel_events").select("registration_id")
        .eq("funnel_id", funnel_id).eq("type", "step_sent").gte("created_at", since)
    )
    counts: dict[str, int] = {}
    for r in rows:
        rid = r.get("registration_id")
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    return counts


def process_funnel(db, funnel: dict, now: datetime) -> dict:
    """Process one funnel. Returns {"sent","skipped","waiting","failed"}."""
    summary = {"sent": 0, "skipped": 0, "waiting": 0, "failed": 0}
    org_id = funnel["org_id"]

    org = funnel_service._one(
        (db.table("organisations")
         .select("id, subscription_status, quiet_hours_start, quiet_hours_end, timezone")
         .eq("id", org_id).limit(1).execute()).data
    ) or {}
    if not is_org_active(org):
        summary["skipped"] += 1
        return summary

    number_row = funnel_service._number_row_by_id(db, org_id, funnel.get("whatsapp_number_id"))
    if not number_row or number_row.get("wa_sales_mode") != "event_funnel":
        logger.warning("funnel_worker: funnel %s has no event_funnel number — skipped", funnel.get("id"))
        summary["skipped"] += 1
        return summary

    steps = funnel_service.funnel_sequence(funnel)
    if not steps:
        return summary
    quiet = is_quiet_hours(org, now)
    sent_24h = _sent_counts_last_24h(db, funnel["id"], now)

    regs = funnel_service._fetch_all(
        lambda: db.table("funnel_registrations").select("*")
        .eq("org_id", org_id).eq("funnel_id", funnel["id"])
        .in_("status", list(funnel_service.ACTIVE_REG_STATUSES)).order("created_at")
    )
    for reg in regs:
        try:
            plan = funnel_service.plan_next_step(
                funnel, reg, steps, now,
                sent_last_24h=sent_24h.get(reg["id"], 0), quiet=quiet,
            )
            if plan.action == "none":
                continue
            if plan.action == "wait":
                summary["waiting"] += 1
                continue
            result = funnel_service.execute_step(db, funnel, number_row, reg, plan, now)
            if result == "sent":
                summary["sent"] += 1
            elif result == "failed":
                summary["failed"] += 1
            else:
                summary["skipped"] += 1
        except Exception as exc:  # S14
            summary["failed"] += 1
            logger.warning("funnel_worker: registration %s failed: %s", reg.get("id"), exc)
    return summary


@celery_app.task(name="app.workers.funnel_worker.run_funnel_sequence")
def run_funnel_sequence() -> dict:
    db = get_supabase()
    started = datetime.now(timezone.utc)
    total = {"funnels": 0, "sent": 0, "skipped": 0, "waiting": 0, "failed": 0}
    try:
        funnels = (db.table("event_funnels").select("*").eq("status", "active").execute()).data or []
        for funnel in funnels:
            total["funnels"] += 1
            try:
                s = process_funnel(db, funnel, datetime.now(timezone.utc))
                for k in ("sent", "skipped", "waiting", "failed"):
                    total[k] += s[k]
            except Exception as exc:  # S14
                total["failed"] += 1
                logger.warning("funnel_worker: funnel %s failed: %s", funnel.get("id"), exc)
        write_worker_log(
            db, worker_name="funnel_worker", status="passed",
            items_processed=total["sent"] + total["skipped"], items_failed=total["failed"],
            items_skipped=total["skipped"], started_at=started,
            run_duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        )
    except Exception as exc:
        logger.error("funnel_worker: run failed: %s", exc)
        total["failed"] += 1
        write_worker_log(db, worker_name="funnel_worker", status="failed",
                         error_message=str(exc)[:500], started_at=started)
    return total
