"""
app/workers/churn_worker.py
----------------------------
Celery tasks:

  run_daily_churn_scoring   — Daily 06:00 WAT (05:00 UTC)
    Score every active customer from NPS, support, SLA, and renewal signals.
    Upsert churn_scores table. Update customers.churn_risk.
    Create notifications on High / Critical escalations.

  run_lead_aging_checker    — Daily 08:00 WAT (07:00 UTC)
    Flag leads with no activity for 3+ days. Notify assigned rep.

  run_anomaly_detector      — Daily 06:00 WAT (05:00 UTC)
    Compare current vs previous week: ≥50% lead drop or ≥50% ticket spike.
    Notify owner/admin users.

  run_re_engagement_queue   — Daily 08:00 WAT (07:00 UTC)
    Find leads where reengagement_date == today.
    Move stage → 'new'. Notify assigned rep.

Pattern 29: load_dotenv() called at module level.
Pattern 1:  get_supabase() called inside task body (never at import time).
Pattern 33: no ILIKE/filter server-side — Python-side filtering only.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.services.monitoring_service import write_worker_log  # noqa: E402

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalise(data) -> Optional[dict]:
    """Return first element of a list, or the value as-is, or None."""
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ── Churn scoring model ───────────────────────────────────────────────────────


def _calculate_churn_score(
    customer: dict,
    tickets: list,
    subscription: Optional[dict],
) -> tuple[float, str, dict]:
    """
    Compute a churn score 0-100 from four weighted signals.

    Signal weights:
      NPS signal:       0–30 pts  (last_nps_score on customers table)
      Support signal:   0–25 pts  (count of open/in-progress tickets)
      SLA breach:       0–15 pts  (any sla_breached ticket)
      Renewal signal:   0–30 pts  (subscription status / days until expiry)

    Risk bands:
      0–25  → Low
      26–50 → Medium
      51–75 → High
      76–100 → Critical

    Returns (score, risk_level, signals_dict).
    """
    score = 0.0
    signals: dict = {}

    # ── NPS signal ─────────────────────────────────────────────────────────
    nps = customer.get("last_nps_score")
    if nps is not None:
        if nps <= 2:
            score += 30
            signals["nps"] = {"value": nps, "risk": "high"}
        elif nps == 3:
            score += 15
            signals["nps"] = {"value": nps, "risk": "medium"}
        else:
            signals["nps"] = {"value": nps, "risk": "low"}
    else:
        score += 10  # No NPS data → mild concern
        signals["nps"] = {"value": None, "risk": "unknown"}

    # ── Support signal ──────────────────────────────────────────────────────
    open_count = sum(
        1
        for t in tickets
        if t.get("status") in ("open", "in_progress", "awaiting_customer")
    )
    if open_count >= 3:
        score += 25
        signals["support"] = {"open_tickets": open_count, "risk": "high"}
    elif open_count == 2:
        score += 15
        signals["support"] = {"open_tickets": open_count, "risk": "medium"}
    elif open_count == 1:
        score += 5
        signals["support"] = {"open_tickets": open_count, "risk": "low"}
    else:
        signals["support"] = {"open_tickets": 0, "risk": "none"}

    # ── SLA breach signal ───────────────────────────────────────────────────
    sla_breached = any(t.get("sla_breached") for t in tickets)
    if sla_breached:
        score += 15
    signals["sla_breach"] = sla_breached

    # ── Renewal / subscription signal ──────────────────────────────────────
    if subscription:
        status = subscription.get("status", "")
        if status in ("expired", "cancelled"):
            score += 30
            signals["renewal"] = {"status": status, "risk": "critical"}
        elif status == "grace_period":
            score += 20
            signals["renewal"] = {"status": status, "risk": "high"}
        elif status == "suspended":
            score += 15
            signals["renewal"] = {"status": status, "risk": "medium"}
        elif status in ("active", "trial"):
            period_end = subscription.get("current_period_end")
            if period_end:
                try:
                    expiry = datetime.fromisoformat(
                        period_end.replace("Z", "+00:00")
                    )
                    days_left = (expiry - datetime.now(timezone.utc)).days
                    if days_left <= 7:
                        score += 20
                        signals["renewal"] = {
                            "status": status,
                            "days_left": days_left,
                            "risk": "high",
                        }
                    elif days_left <= 30:
                        score += 10
                        signals["renewal"] = {
                            "status": status,
                            "days_left": days_left,
                            "risk": "medium",
                        }
                    else:
                        signals["renewal"] = {
                            "status": status,
                            "days_left": days_left,
                            "risk": "low",
                        }
                except (ValueError, AttributeError):
                    signals["renewal"] = {"status": status, "risk": "low"}
            else:
                signals["renewal"] = {"status": status, "risk": "low"}
        else:
            signals["renewal"] = {"status": status, "risk": "none"}
    else:
        score += 10  # No subscription → mild concern
        signals["renewal"] = {"status": None, "risk": "unknown"}

    final_score = min(score, 100.0)

    if final_score >= 76:
        risk_level = "Critical"
    elif final_score >= 51:
        risk_level = "High"
    elif final_score >= 26:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return final_score, risk_level, signals


def _create_churn_notification(
    db,
    org_id: str,
    customer: dict,
    prev_risk: str,
    new_risk: str,
) -> None:
    """
    Create in-app notification(s) AND a task when churn risk escalates
    to High or Critical.
    High     → notify + task for assigned rep
    Critical → notify + task for rep, also notify owner/admin users
    """
    if new_risk not in ("High", "Critical"):
        return
    if prev_risk == new_risk:
        return  # No escalation

    customer_name = customer.get("full_name", "A customer")
    customer_id   = customer.get("id")
    assigned_to   = customer.get("assigned_to")
    title         = f"Churn Risk {new_risk}: {customer_name}"
    body          = (
        f"{customer_name}'s churn risk has escalated to {new_risk}. "
        "Immediate follow-up recommended."
    )

    notified_ids: set = set()

    if assigned_to:
        # Notification
        try:
            db.table("notifications").insert({
                "org_id":        org_id,
                "user_id":       assigned_to,
                "title":         title,
                "body":          body,
                "type":          "churn_alert",
                "resource_type": "customer",
                "resource_id":   customer_id,
                "is_read":       False,
                "created_at":    _now_iso(),
            }).execute()
            notified_ids.add(assigned_to)
        except Exception as exc:
            logger.warning("churn_worker: notification failed for rep %s — %s", assigned_to, exc)

        # Task — one per escalation event, assigned to the rep
        try:
            db.table("tasks").insert({
                "org_id":           org_id,
                "assigned_to":      assigned_to,
                "title":            f"Churn intervention — {customer_name} ({new_risk} risk)",
                "description":      body,
                "task_type":        "system_event",
                "source_module":    "renewal",
                "source_record_id": customer_id,
                "priority":         "critical" if new_risk == "Critical" else "high",
                "status":           "open",
                "created_at":       _now_iso(),
                "updated_at":       _now_iso(),
            }).execute()
        except Exception as exc:
            logger.warning("churn_worker: task creation failed for rep %s — %s", assigned_to, exc)

    if new_risk == "Critical":
        try:
            users_result = (
                db.table("users").select("id, role").eq("org_id", org_id).execute()
            )
            for user in users_result.data or []:
                uid = user.get("id")
                if uid and uid not in notified_ids and (
                    user.get("role") or ""
                ).lower() in ("owner", "admin"):
                    db.table("notifications").insert({
                        "org_id":        org_id,
                        "user_id":       uid,
                        "title":         title,
                        "body":          body,
                        "type":          "churn_alert",
                        "resource_type": "customer",
                        "resource_id":   customer_id,
                        "is_read":       False,
                        "created_at":    _now_iso(),
                    }).execute()
        except Exception as exc:
            logger.warning(
                "churn_worker: critical escalation notifications failed — %s", exc
            )


# ── Tasks ─────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_daily_churn_scoring(self):
    """
    Daily 06:00 WAT — Calculate churn risk for every active customer per org.
    Upserts churn_scores. Updates customers.churn_risk. Fires escalation alerts.
    """
    logger.info("churn_worker: run_daily_churn_scoring starting.")
    db = get_supabase()  # Pattern 1
    scored = 0
    _started_at = datetime.now(timezone.utc)
    try:
        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                all_customers = (
                    db.table("customers")
                    .select("id, full_name, assigned_to, last_nps_score, churn_risk, deleted_at")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )
                # Active = not soft-deleted (customers table has no status column)
                customers = [c for c in all_customers if not c.get("deleted_at")]

                for customer in customers:
                    cust_id: str = customer["id"]
                    prev_risk: str = customer.get("churn_risk") or "Low"

                    # Fetch open tickets for this customer
                    tickets = (
                        db.table("tickets")
                        .select("id, status, sla_breached")
                        .eq("org_id", org_id)
                        .eq("customer_id", cust_id)
                        .execute()
                        .data or []
                    )

                    # Fetch customer's most relevant subscription
                    sub_rows = (
                        db.table("subscriptions")
                        .select("id, status, current_period_end")
                        .eq("org_id", org_id)
                        .eq("customer_id", cust_id)
                        .execute()
                        .data or []
                    )
                    # Python-side: prefer active/trial/grace over expired (Pattern 33)
                    _PREFERRED = ("active", "trial", "grace_period")
                    subscription: Optional[dict] = next(
                        (s for s in sub_rows if s.get("status") in _PREFERRED),
                        sub_rows[0] if sub_rows else None,
                    )

                    score, risk_level, signals = _calculate_churn_score(
                        customer, tickets, subscription
                    )

                    # Upsert: check for existing row first
                    existing = (
                        db.table("churn_scores")
                        .select("id")
                        .eq("org_id", org_id)
                        .eq("customer_id", cust_id)
                        .execute()
                        .data or []
                    )
                    row = {
                        "org_id": org_id,
                        "customer_id": cust_id,
                        "score": score,
                        "risk_level": risk_level,
                        "signals": signals,  # ← actual column name confirmed
                        "scored_at": _now_iso(),
                    }
                    existing_row = _normalise(existing)
                    if existing_row:
                        db.table("churn_scores").update(row).eq(
                            "id", existing_row["id"]
                        ).execute()
                    else:
                        db.table("churn_scores").insert(row).execute()

                    # Sync customers.churn_risk
                    db.table("customers").update(
                        {"churn_risk": risk_level}
                    ).eq("id", cust_id).execute()

                    # Fire alert if risk escalated
                    _create_churn_notification(db, org_id, customer, prev_risk, risk_level)
                    scored += 1

            except Exception as exc:
                logger.error(
                    "churn_worker: scoring failed for org %s — %s", org_id, exc
                )

        logger.info(
            "churn_worker: run_daily_churn_scoring done. Scored %d customers.", scored
        )
        write_worker_log(
            db,
            worker_name="churn_worker",
            status="passed",
            items_processed=scored,
            started_at=_started_at,
        )

    except Exception as exc:
        logger.error("churn_worker: run_daily_churn_scoring fatal — %s", exc)
        write_worker_log(
            db,
            worker_name="churn_worker",
            status="failed",
            error_message=str(exc)[:500],
            started_at=_started_at,
        )
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_lead_aging_checker(self):
    """
    Daily 08:00 WAT — Flag leads with no activity for 3+ days.
    Creates an in-app notification for the assigned rep.
    """
    logger.info("churn_worker: run_lead_aging_checker starting.")
    db = get_supabase()
    flagged = 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                leads = (
                    db.table("leads")
                    .select("id, full_name, assigned_to, last_activity_at, stage")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )

                # Python-side filter (Pattern 33)
                aged = [
                    l
                    for l in leads
                    if l.get("stage") not in ("won", "lost")
                    and (l.get("last_activity_at") or "") <= cutoff
                ]

                for lead in aged:
                    assigned_to = lead.get("assigned_to")
                    if not assigned_to:
                        continue
                    try:
                        # Notification
                        db.table("notifications").insert(
                            {
                                "org_id": org_id,
                                "user_id": assigned_to,
                                "title": f"Lead needs attention: {lead.get('full_name', 'Unknown')}",
                                "body": "No activity recorded for 3+ days. Please follow up.",
                                "type": "lead_aging",
                                "resource_type": "lead",
                                "resource_id": lead["id"],
                                "is_read": False,
                                "created_at": _now_iso(),
                            }
                        ).execute()
                        # Task — system_event so it appears on the Task Board
                        db.table("tasks").insert({
                            "org_id":           org_id,
                            "assigned_to":      assigned_to,
                            "title":            f"Follow up: {lead.get('full_name', 'Lead')} — no activity for 3+ days",
                            "task_type":        "system_event",
                            "source_module":    "leads",
                            "source_record_id": lead["id"],
                            "priority":         "medium",
                            "status":           "open",
                            "created_at":       _now_iso(),
                            "updated_at":       _now_iso(),
                        }).execute()
                        flagged += 1
                    except Exception as exc:
                        logger.warning(
                            "churn_worker: lead-aging notification failed for %s — %s",
                            lead["id"],
                            exc,
                        )

            except Exception as exc:
                logger.error(
                    "churn_worker: lead aging failed for org %s — %s", org_id, exc
                )

        logger.info(
            "churn_worker: run_lead_aging_checker done. Flagged %d leads.", flagged
        )

    except Exception as exc:
        logger.error("churn_worker: run_lead_aging_checker fatal — %s", exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_anomaly_detector(self):
    """
    Daily 06:00 WAT — Compare current vs previous week metrics.
    Flags ≥50% drop in new leads or ≥50% spike in new tickets.
    Notifies owner/admin users of each org.
    """
    logger.info("churn_worker: run_anomaly_detector starting.")
    db = get_supabase()
    anomalies_found = 0
    try:
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).isoformat()
        two_weeks_start = (now - timedelta(days=14)).isoformat()
        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                # Leads week-over-week (Python-side filter — Pattern 33)
                all_leads = (
                    db.table("leads")
                    .select("id, created_at")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )
                curr_leads = sum(
                    1 for l in all_leads if l.get("created_at", "") >= week_start
                )
                prev_leads = sum(
                    1
                    for l in all_leads
                    if two_weeks_start <= l.get("created_at", "") < week_start
                )

                # Tickets week-over-week
                all_tickets = (
                    db.table("tickets")
                    .select("id, created_at")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )
                curr_tickets = sum(
                    1 for t in all_tickets if t.get("created_at", "") >= week_start
                )
                prev_tickets = sum(
                    1
                    for t in all_tickets
                    if two_weeks_start <= t.get("created_at", "") < week_start
                )

                anomalies: list[str] = []

                if prev_leads > 0:
                    pct = (curr_leads - prev_leads) / prev_leads * 100
                    if pct <= -50:
                        anomalies.append(
                            f"New leads dropped {abs(pct):.0f}% week-over-week "
                            f"({prev_leads} \u2192 {curr_leads})."
                        )

                if prev_tickets > 0:
                    pct = (curr_tickets - prev_tickets) / prev_tickets * 100
                    if pct >= 50:
                        anomalies.append(
                            f"Support tickets spiked {pct:.0f}% week-over-week "
                            f"({prev_tickets} \u2192 {curr_tickets})."
                        )

                if not anomalies:
                    continue

                # Notify owner/admin users of this org
                users = (
                    db.table("users")
                    .select("id, role")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )
                admins = [
                    u
                    for u in users
                    if (u.get("role") or "").lower() in ("owner", "admin")
                ]
                for user in admins:
                    for msg in anomalies:
                        try:
                            db.table("notifications").insert(
                                {
                                    "org_id": org_id,
                                    "user_id": user["id"],
                                    "title": "\u26a0\ufe0f Anomaly Detected",
                                    "body": msg,
                                    "type": "anomaly",
                                    "resource_type": None,
                                    "resource_id": None,
                                    "is_read": False,
                                    "created_at": _now_iso(),
                                }
                            ).execute()
                            anomalies_found += 1
                        except Exception as exc:
                            logger.warning(
                                "churn_worker: anomaly notification failed — %s", exc
                            )

            except Exception as exc:
                logger.error(
                    "churn_worker: anomaly detection failed for org %s — %s",
                    org_id,
                    exc,
                )

        logger.info(
            "churn_worker: run_anomaly_detector done. %d anomaly notifications sent.",
            anomalies_found,
        )

    except Exception as exc:
        logger.error("churn_worker: run_anomaly_detector fatal — %s", exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def run_re_engagement_queue(self):
    """
    Daily 08:00 WAT — Find leads where reengagement_date == today.
    Move stage → 'new', clear reengagement_date, notify assigned rep.
    """
    logger.info("churn_worker: run_re_engagement_queue starting.")
    db = get_supabase()
    reengaged = 0
    try:
        today = _today_iso()
        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                leads = (
                    db.table("leads")
                    .select("id, full_name, assigned_to, reengagement_date, stage")
                    .eq("org_id", org_id)
                    .execute()
                    .data or []
                )

                # Python-side date comparison (Pattern 33)
                due_today = [
                    l
                    for l in leads
                    if (l.get("reengagement_date") or "")[:10] == today
                ]

                for lead in due_today:
                    try:
                        db.table("leads").update(
                            {"stage": "new", "reengagement_date": None}
                        ).eq("id", lead["id"]).execute()

                        assigned_to = lead.get("assigned_to")
                        if assigned_to:
                            db.table("notifications").insert(
                                {
                                    "org_id": org_id,
                                    "user_id": assigned_to,
                                    "title": f"Re-engage: {lead.get('full_name', 'Lead')}",
                                    "body": "This lead is scheduled for re-engagement today.",
                                    "type": "re_engagement",
                                    "resource_type": "lead",
                                    "resource_id": lead["id"],
                                    "is_read": False,
                                    "created_at": _now_iso(),
                                }
                            ).execute()
                        reengaged += 1
                    except Exception as exc:
                        logger.warning(
                            "churn_worker: re-engagement update failed for lead %s — %s",
                            lead["id"],
                            exc,
                        )

            except Exception as exc:
                logger.error(
                    "churn_worker: re-engagement queue failed for org %s — %s",
                    org_id,
                    exc,
                )

        logger.info(
            "churn_worker: run_re_engagement_queue done. Re-engaged %d leads.",
            reengaged,
        )

    except Exception as exc:
        logger.error("churn_worker: run_re_engagement_queue fatal — %s", exc)
        raise self.retry(exc=exc, countdown=30)