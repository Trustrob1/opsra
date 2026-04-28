"""
app/workers/sla_worker.py
--------------------------
Celery task:

  run_sla_monitor  — Every 15 minutes
    Checks all open tickets across every org for SLA compliance.

    Actions:
      • sla_resolve_due_at or sla_response_due_at has passed
        → Set sla_breached = True
        → Notify assigned rep
        → Notify supervisor/admin users
      • Due within _PRE_BREACH_WARN_MINUTES (30)
        → Send pre-breach warning to assigned rep

Pattern 29: load_dotenv() at module level.
Pattern 1:  get_supabase() called inside task body.
Pattern 33: Python-side comparisons only — no ILIKE / server-side filter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402

logger = logging.getLogger(__name__)

_PRE_BREACH_WARN_MINUTES = 30
_OPEN_STATUSES = ("open", "in_progress", "awaiting_customer")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_sla_monitor(self):
    """
    Every 15 minutes — check open tickets for SLA compliance.
    Sends pre-breach alerts and marks sla_breached = True on overdue tickets.
    """
    logger.info("sla_worker: run_sla_monitor starting.")
    db = get_supabase()  # Pattern 1
    pre_breach_count = 0
    breached_count = 0

    try:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        warn_threshold = (now + timedelta(minutes=_PRE_BREACH_WARN_MINUTES)).isoformat()

        orgs = (db.table("organisations").select("id").execute().data or [])

        for org_row in orgs:
            org_id: str = org_row["id"]
            try:
                tickets = (
                    db.table("tickets")
                    .select(
                        "id, title, assigned_to, status, "
                        "sla_resolution_due_at, sla_response_due_at, sla_breached"
                    )
                    .eq("org_id", org_id)
                    .in_("status", list(_OPEN_STATUSES))
                    .execute()
                    .data or []
                )

                for ticket in tickets:
                    ticket_id: str = ticket["id"]
                    assigned_to = ticket.get("assigned_to")

                    if ticket.get("sla_breached"):
                        continue  # Already processed

                    # Choose the most pressing due timestamp (Pattern 33)
                    resolve_due = ticket.get("sla_resolution_due_at")
                    response_due = ticket.get("sla_response_due_at")
                    due_at = resolve_due or response_due
                    if not due_at:
                        continue

                    if due_at <= now_iso:
                        # ── SLA Breached ──────────────────────────────────
                        try:
                            db.table("tickets").update(
                                {"sla_breached": True}
                            ).eq("id", ticket_id).execute()
                            breached_count += 1
                        except Exception as exc:
                            logger.warning(
                                "sla_worker: failed to mark breach on ticket %s — %s",
                                ticket_id,
                                exc,
                            )
                            continue

                        # Notify assigned rep
                        if assigned_to:
                            _safe_notify(
                                db,
                                org_id=org_id,
                                user_id=assigned_to,
                                title="\U0001f6a8 SLA Breached",
                                body=(
                                    f"Ticket \u2018{ticket.get('title', ticket_id)}\u2019 "
                                    "has breached its SLA."
                                ),
                                ntype="sla_breach",
                                resource_id=ticket_id,
                            )
                            # Task — rep must action the breached ticket
                            try:
                                db.table("tasks").insert({
                                    "org_id":           org_id,
                                    "assigned_to":      assigned_to,
                                    "title":            f"SLA breached — resolve ticket: {ticket.get('title', ticket_id)}",
                                    "task_type":        "system_event",
                                    "source_module":    "support",
                                    "source_record_id": ticket_id,
                                    "priority":         "critical",
                                    "status":           "open",
                                    "created_at":       _now_iso(),
                                    "updated_at":       _now_iso(),
                                }).execute()
                            except Exception as exc:
                                logger.warning(
                                    "sla_worker: task creation failed for ticket %s — %s",
                                    ticket_id, exc,
                                )

                        # Notify supervisors and admins
                        try:
                            users = (
                                db.table("users")
                                .select("id, role")
                                .eq("org_id", org_id)
                                .execute()
                                .data or []
                            )
                            for user in users:
                                uid = user.get("id")
                                if (user.get("role") or "").lower() in (
                                    "owner",
                                    "admin",
                                    "supervisor",
                                ) and uid != assigned_to:
                                    _safe_notify(
                                        db,
                                        org_id=org_id,
                                        user_id=uid,
                                        title="\U0001f6a8 SLA Breach \u2014 Supervisor Alert",
                                        body=(
                                            f"Ticket \u2018{ticket.get('title', ticket_id)}\u2019 "
                                            "SLA has been breached and requires escalation."
                                        ),
                                        ntype="sla_breach_supervisor",
                                        resource_id=ticket_id,
                                    )
                        except Exception as exc:
                            logger.warning(
                                "sla_worker: supervisor notifications failed for %s — %s",
                                ticket_id,
                                exc,
                            )

                    elif due_at <= warn_threshold:
                        # ── Pre-breach warning ────────────────────────────
                        if assigned_to:
                            _safe_notify(
                                db,
                                org_id=org_id,
                                user_id=assigned_to,
                                title="\u26a0\ufe0f SLA Approaching",
                                body=(
                                    f"Ticket \u2018{ticket.get('title', ticket_id)}\u2019 "
                                    f"SLA is due within {_PRE_BREACH_WARN_MINUTES} minutes."
                                ),
                                ntype="sla_warning",
                                resource_id=ticket_id,
                            )
                            pre_breach_count += 1

            except Exception as exc:
                logger.error(
                    "sla_worker: SLA check failed for org %s — %s", org_id, exc
                )

        logger.info(
            "sla_worker: run_sla_monitor done. "
            "Pre-breach warnings: %d, breaches marked: %d.",
            pre_breach_count,
            breached_count,
        )
        return {"pre_breach_warnings": pre_breach_count, "breaches": breached_count, "failed": 0}

    except Exception as exc:
        logger.error("sla_worker: run_sla_monitor fatal — %s", exc)
        raise self.retry(exc=exc, countdown=60)


def _safe_notify(
    db,
    *,
    org_id: str,
    user_id: str,
    title: str,
    body: str,
    ntype: str,
    resource_id: str,
) -> None:
    """Insert a notification row, swallowing any DB error."""
    try:
        db.table("notifications").insert(
            {
                "org_id": org_id,
                "user_id": user_id,
                "title": title,
                "body": body,
                "type": ntype,
                "resource_type": "ticket",
                "resource_id": resource_id,
                "is_read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as exc:
        logger.warning("sla_worker: notification insert failed — %s", exc)