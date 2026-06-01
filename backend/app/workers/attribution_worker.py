"""
backend/app/workers/attribution_worker.py
------------------------------------------
ATTRIB-1 Session 2 — Auto-confirm attribution after 24 hours.

Runs every hour via Celery beat.
Finds all leads where pending_attribution = TRUE and updated_at is more than
24 hours ago (i.e. ops manager did not act within the window).
For each such lead: calls _propose_attribution(), writes the top proposal as
confirmed, sets stage = converted, and runs the full post-conversion side effects.

Security:
  S1  — org_id always from the leads row (never from request context)
  S14 — one lead failure never stops the loop; all failures logged and swallowed

Pattern 48: uses get_supabase() directly (worker context, no FastAPI Depends).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)

# 24-hour window — if ops manager has not confirmed attribution within this
# period, the system auto-confirms the proposed primary rep with 100% credit.
_AUTO_CONFIRM_HOURS = 24


@celery_app.task(name="app.workers.attribution_worker.run_attribution_auto_confirm")
def run_attribution_auto_confirm() -> None:
    """
    Celery beat task: runs every hour.
    Auto-confirms attribution for leads where ops manager did not act within 24h.
    """
    db = get_supabase()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=_AUTO_CONFIRM_HOURS)
    ).isoformat()

    try:
        res = (
            db.table("leads")
            .select("id, org_id, full_name, phone, whatsapp, email, business_name, business_type, location, branches, assigned_to, updated_at")
            .eq("pending_attribution", True)
            .lt("updated_at", cutoff)
            .is_("deleted_at", "null")
            .execute()
        )
        pending_leads: list[dict] = res.data or []
    except Exception as exc:
        logger.error("attribution_worker: failed to fetch pending leads — %s", exc)
        return

    if not pending_leads:
        logger.info("attribution_worker: no leads pending auto-confirm")
        return

    logger.info("attribution_worker: auto-confirming attribution for %d lead(s)", len(pending_leads))

    from app.services.lead_service import (
        _propose_attribution,
        confirm_attribution,
    )

    for lead in pending_leads:
        lead_id = lead.get("id")
        org_id  = lead.get("org_id")
        if not lead_id or not org_id:
            continue
        try:
            _auto_confirm_one(db, org_id, lead_id, lead)
        except Exception as exc:
            # S14: one lead failure never stops the loop
            logger.error(
                "attribution_worker: auto-confirm failed for lead %s — %s", lead_id, exc
            )


def _auto_confirm_one(db: Any, org_id: str, lead_id: str, lead_row: dict) -> None:
    """
    Auto-confirm attribution for a single lead.
    Uses _propose_attribution() to determine primary rep.
    Sets attribution_confirmed_by = NULL (system-confirmed, not a human user).
    """
    from app.services.lead_service import _propose_attribution

    proposal = _propose_attribution(db, org_id, lead_id)
    primary_uid = proposal.get("primary_user_id")

    if not primary_uid:
        # Cannot auto-confirm without a primary rep — leave pending and log
        logger.warning(
            "attribution_worker: no primary rep found for lead %s — skipping auto-confirm",
            lead_id,
        )
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    # Write attribution + convert directly (bypass confirm_attribution service
    # to avoid re-validating pending_attribution flag which is already True here,
    # and to set attribution_confirmed_by = NULL for system auto-confirm)
    db.table("leads").update({
        "stage":                    "converted",
        "converted_at":             now_iso,
        "updated_at":               now_iso,
        "last_activity_at":         now_iso,
        "pending_attribution":      False,
        "attributed_to":            primary_uid,
        "attributed_to_secondary":  None,
        "attribution_split_pct":    100,
        "attribution_confirmed_by": None,       # NULL = system auto-confirmed
        "attribution_confirmed_at": now_iso,
        "attribution_note":         "Auto-confirmed by system after 24h review window expired.",
    }).eq("id", lead_id).eq("org_id", org_id).execute()

    # Customer stub — full fields matching confirm_attribution path
    customer_data: dict = {
        "org_id":              org_id,
        "lead_id":             lead_id,
        "full_name":           lead_row.get("full_name", ""),
        "phone":               lead_row.get("phone"),
        "whatsapp":            lead_row.get("whatsapp") or lead_row.get("phone") or "",
        "email":               lead_row.get("email"),
        "business_name":       lead_row.get("business_name", ""),
        "business_type":       lead_row.get("business_type"),
        "location":            lead_row.get("location"),
        "branches":            lead_row.get("branches"),
        "assigned_to":         lead_row.get("assigned_to"),
        "whatsapp_opt_in":     True,
        "onboarding_complete": False,
        "churn_risk":          "low",
    }
    customer_data = {k: v for k, v in customer_data.items() if v is not None}

    try:
        customer_result = db.table("customers").insert(customer_data).execute()
        customer = customer_result.data[0] if customer_result.data else {}
        customer_id = customer.get("id", "")
    except Exception as exc:
        logger.warning("attribution_worker: customer stub failed for lead %s — %s", lead_id, exc)
        customer_id = ""

    # Subscription stub
    try:
        db.table("subscriptions").insert({
            "org_id":               org_id,
            "customer_id":          customer_id,
            "plan_name":            "Starter Plan",
            "plan_tier":            "starter",
            "amount":               0,
            "currency":             "NGN",
            "billing_cycle":        "monthly",
            "status":               "trial",
            "current_period_start": datetime.now(timezone.utc).date().isoformat(),
            "current_period_end":   datetime.now(timezone.utc).date().isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("attribution_worker: subscription stub failed for lead %s — %s", lead_id, exc)

    # Commission — primary rep
    if customer_id:
        try:
            from app.services.commissions_service import auto_create_commission
            auto_create_commission(
                db=db,
                org_id=org_id,
                affiliate_user_id=primary_uid,
                event_type="lead_converted",
                lead_id=lead_id,
                customer_id=customer_id,
            )
        except Exception as exc:
            logger.warning("attribution_worker: commission failed for lead %s — %s", lead_id, exc)

    # Timeline event
    try:
        from app.services.lead_service import write_timeline_event, write_audit_log
        write_timeline_event(
            db, org_id, lead_id,
            event_type="stage_changed",
            actor_id=None,
            description="Lead converted — attribution auto-confirmed by system (24h window expired)",
            metadata={
                "from_stage":      "proposal_sent",
                "to_stage":        "converted",
                "customer_id":     customer_id,
                "attributed_to":   primary_uid,
                "auto_confirmed":  True,
            },
        )
        write_audit_log(
            db, org_id, None,
            action="lead.attribution_auto_confirmed",
            resource_type="lead",
            resource_id=lead_id,
            old_value={"pending_attribution": True},
            new_value={
                "stage":          "converted",
                "attributed_to":  primary_uid,
                "auto_confirmed": True,
            },
        )
    except Exception as exc:
        logger.warning("attribution_worker: timeline/audit failed for lead %s — %s", lead_id, exc)

    logger.info(
        "attribution_worker: auto-confirmed lead %s → attributed_to=%s", lead_id, primary_uid
    )
