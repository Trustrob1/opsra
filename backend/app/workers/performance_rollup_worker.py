"""
app/workers/performance_rollup_worker.py
CPM-1B Gap 1 — Auto End-of-Month KPI Actual Rollup

Celery task: rollup_daily_performance_logs
Schedule: Daily 01:00 UTC

For each active contractor:
  - Calculate their current contract month boundaries (contract-relative, 30-day periods)
  - If today is the LAST day of a contract month (day 30 relative to contract_start):
    - Sum up daily logs per KPI for that month
    - Write as contractor_kpi_actuals ONLY if no actual already exists (skip = manager wins)
  - S14: per-contractor failure never stops the loop

logged_by uses a sentinel org owner user_id — worker acts on behalf of the org.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def rollup_daily_performance_logs() -> dict:
    """
    Auto-promote daily log totals to monthly KPI actuals at end of each
    contract month. Skips KPIs where an actual already exists (never overwrites).

    Returns summary dict:
      { contractors_checked, contractors_rolled_up, actuals_written, skipped_existing, failed }
    """
    from app.database import get_supabase

    db = get_supabase()
    today = date.today()

    summary = {
        "contractors_checked": 0,
        "contractors_rolled_up": 0,
        "actuals_written": 0,
        "skipped_existing": 0,
        "failed": 0,
    }

    # Fetch all active contractors that have a contract_start and log_token
    try:
        contractors_res = (
            db.table("contractors")
            .select("id, org_id, full_name, contract_start, kpi_targets, log_token")
            .eq("status", "active")
            .is_("deleted_at", "null")
            .not_.is_("contract_start", "null")
            .execute()
        )
        contractors = contractors_res.data or []
    except Exception as exc:
        logger.error("rollup_daily_performance_logs: failed to fetch contractors: %s", exc)
        summary["failed"] += 1
        return summary

    for contractor in contractors:
        try:
            summary["contractors_checked"] += 1
            contractor_id = contractor["id"]
            org_id = contractor["org_id"]
            contract_start_str = contractor.get("contract_start")
            kpi_targets = contractor.get("kpi_targets") or []

            if not contract_start_str or not kpi_targets:
                continue

            contract_start = date.fromisoformat(contract_start_str)
            days_since_start = (today - contract_start).days

            if days_since_start < 0:
                # Contract hasn't started yet
                continue

            # Which 30-day period are we in?
            period_index = days_since_start // 30
            # Day number within the current period (0-based)
            day_in_period = days_since_start % 30

            # Only roll up on the LAST day of a period (day 29, i.e. day 30 of 30)
            if day_in_period != 29:
                continue

            # This contractor is on the last day of their contract month — roll up
            month_start = contract_start + timedelta(days=period_index * 30)
            month_end = contract_start + timedelta(days=(period_index + 1) * 30 - 1)
            month_label = f"Month {period_index + 1}"
            now_iso = datetime.now(timezone.utc).isoformat()

            # Fetch daily logs for this contract month
            logs_res = (
                db.table("performance_daily_logs")
                .select("kpi_key, value")
                .eq("entity_id", contractor_id)
                .eq("org_id", org_id)
                .eq("entity_type", "contractor")
                .gte("log_date", month_start.isoformat())
                .lte("log_date", month_end.isoformat())
                .execute()
            )
            logs = logs_res.data or []

            if not logs:
                logger.info(
                    "rollup: no daily logs for contractor %s month %s — skipping",
                    contractor_id, month_label,
                )
                continue

            # Sum totals per kpi_key
            totals: dict[str, float] = {}
            for log in logs:
                k = log.get("kpi_key")
                v = log.get("value")
                if k and v is not None:
                    totals[k] = totals.get(k, 0.0) + float(v)

            # Fetch org owner to use as logged_by
            owner_res = (
                db.table("users")
                .select("id")
                .eq("org_id", org_id)
                .limit(1)
                .execute()
            )
            owner_rows = owner_res.data or []
            logged_by = owner_rows[0]["id"] if owner_rows else None
            if not logged_by:
                logger.warning("rollup: no owner found for org %s — skipping contractor %s", org_id, contractor_id)
                summary["failed"] += 1
                continue

            rolled_up = False

            for kpi in kpi_targets:
                kpi_key = kpi.get("key", "")
                kpi_type = kpi.get("kpi_type", "manual")

                # Skip manual KPIs — no numeric total to promote
                if kpi_type == "manual":
                    continue

                running_total = totals.get(kpi_key)
                if running_total is None:
                    # No logs for this KPI this month
                    continue

                try:
                    # Check if actual already exists — skip if so (manager wins)
                    existing_res = (
                        db.table("contractor_kpi_actuals")
                        .select("id")
                        .eq("contractor_id", contractor_id)
                        .eq("month_label", month_label)
                        .eq("kpi_key", kpi_key)
                        .limit(1)
                        .execute()
                    )
                    existing = existing_res.data or []

                    if existing:
                        logger.info(
                            "rollup: actual already exists for contractor %s kpi %s month %s — skipping",
                            contractor_id, kpi_key, month_label,
                        )
                        summary["skipped_existing"] += 1
                        continue

                    # Insert the rollup actual
                    insert_row = {
                        "org_id":        org_id,
                        "contractor_id": contractor_id,
                        "month_label":   month_label,
                        "month_start":   month_start.isoformat(),
                        "kpi_key":       kpi_key,
                        "actual_value":  round(running_total, 4),
                        "actual_label":  None,
                        "notes":         f"Auto-rolled up from daily logs ({running_total} logged)",
                        "logged_by":     logged_by,
                        "created_at":    now_iso,
                        "updated_at":    now_iso,
                    }
                    db.table("contractor_kpi_actuals").insert(insert_row).execute()
                    summary["actuals_written"] += 1
                    rolled_up = True

                    logger.info(
                        "rollup: wrote actual for contractor %s kpi %s month %s value %s",
                        contractor_id, kpi_key, month_label, running_total,
                    )

                except Exception as kpi_exc:
                    # S14: per-KPI failure never stops the loop
                    logger.error(
                        "rollup: failed to write actual for contractor %s kpi %s: %s",
                        contractor_id, kpi_key, kpi_exc,
                    )
                    summary["failed"] += 1

            if rolled_up:
                summary["contractors_rolled_up"] += 1

        except Exception as exc:
            # S14: per-contractor failure never stops the loop
            logger.error(
                "rollup_daily_performance_logs: failed for contractor %s: %s",
                contractor.get("id", "unknown"), exc,
            )
            summary["failed"] += 1

    logger.info("rollup_daily_performance_logs complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Celery task registration
# Optional guard — allows standalone dry-run without Celery broker.
# ---------------------------------------------------------------------------
try:
    from app.workers.celery_app import celery_app

    @celery_app.task(name="rollup_daily_performance_logs")
    def rollup_daily_performance_logs_task() -> dict:
        return rollup_daily_performance_logs()

except Exception:
    pass
