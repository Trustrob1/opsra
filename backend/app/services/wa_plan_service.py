"""
app/services/wa_plan_service.py
-------------------------------
ACCOUNT-PLANS AP-5a - what the organisation's plan allows on WhatsApp for people who message the business first.
The ONE place the inbound WhatsApp code asks the plan.

  wa_leads   a first message from someone new is saved as a lead   (Capture)
  wa_menu    the WhatsApp menu with set answers is sent             (Capture)

Safety (same rules as account_entitlement_service)
  * A business that has not been switched on (organisations.plans_enforced false) gets "allowed", exactly as before.
  * A message is NEVER lost: it is saved to Conversations before either check runs. When a feature is off the team gets
    an in-app note instead, at most once every 30 minutes per sender.
  * People who are already leads or customers are never affected: only the first-contact lead capture and the menus.
  * If the check itself breaks unexpectedly the live business keeps working (allowed); the entitlement service
    already fails closed for enforced accounts on its own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import account_entitlement_service as acc

logger = logging.getLogger(__name__)

NOTE_COOLDOWN_MIN = 30
NOTE_TYPE = "wa_plan_off"


def _on(db, org_id: str, key: str) -> bool:
    try:
        return bool(acc.has_feature(db, key, org_id=org_id))
    except Exception as exc:  # has_feature never raises; this is a second belt so a bug cannot drop live messages
        logger.warning("wa_plan: check failed org=%s key=%s - allowing: %s", org_id, key, exc)
        return True


def leads_on(db, org_id: str) -> bool:
    return _on(db, org_id, "wa_leads")


def menu_on(db, org_id: str) -> bool:
    return _on(db, org_id, "wa_menu")


def tell_team(db, org_id: str, phone: str, name: Optional[str], text: Optional[str]) -> None:
    """In-app note that someone new wrote in and the plan has no automatic lead capture. Never raises."""
    try:
        title = f"New WhatsApp message from {name or phone}"
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=NOTE_COOLDOWN_MIN)).isoformat()
        try:
            seen = (db.table("notifications").select("id").eq("org_id", org_id).eq("type", NOTE_TYPE)
                    .eq("title", title).gte("created_at", cutoff).limit(1).execute().data)
            if seen:
                return
        except Exception:
            pass
        body = ((text or "(media)")[:200] + " - your plan doesn't save new WhatsApp contacts as leads. "
                "Reply from Conversations, or open Billing to see the plans.")
        from app.services import funnel_service
        funnel_service.notify_managers(db, org_id, title, body, NOTE_TYPE, None)
    except Exception as exc:
        logger.warning("wa_plan: tell_team failed org=%s: %s", org_id, exc)
