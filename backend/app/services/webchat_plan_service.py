"""
app/services/webchat_plan_service.py
------------------------------------
ACCOUNT-PLANS AP-4 - what the organisation's plan allows in the web chat. The ONE place web chat asks the plan.

  webchat_basic      the chat page, menu answers, contact capture, booking  (Capture)
  webchat_insights   insights, tagged links and QR codes                    (Capture)
  ai_assistant       AI answers; each AI answer also uses the monthly ai_messages allowance (Convert)
  payment_links      the shop and payment links inside the chat             (Convert)
  webchat_followups  email and WhatsApp follow-ups to visitors              (Convert)

Safety
  * A business that has not been switched on (organisations.plans_enforced false) gets "allowed" for everything and
    nothing is counted, exactly as before this existed (account_entitlement_service rules).
  * A switched-on business with no live plan loses only these features. Its login, data and the rest of Opsra stay.
  * A payment already made is never undone: payment confirmation hooks are not gated.
  * An error while checking an enforced plan means OFF (S14, fail closed).
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services import account_entitlement_service as acc

logger = logging.getLogger(__name__)

PLAN_MESSAGE = "Your plan doesn't include this. Open Billing to see the plans."


def allowed(db, org_id: str, key: str) -> bool:
    return acc.has_feature(db, key, org_id=org_id)


def chat_allowed(db, org_id: str) -> bool:
    return allowed(db, org_id, "webchat_basic")


def apply(db, org_id: str, cfg: dict) -> Optional[dict]:
    """The chat settings visitors actually get. None = the plan does not include the web chat at all.
    Otherwise a COPY with AI, the shop and follow-ups switched off where the plan lacks them (never saved)."""
    if not chat_allowed(db, org_id):
        return None
    out = dict(cfg)
    if out.get("ai_enabled") and not allowed(db, org_id, "ai_assistant"):
        out["ai_enabled"] = False
    if out.get("shop_enabled") and not allowed(db, org_id, "payment_links"):
        out["shop_enabled"] = False
    if not allowed(db, org_id, "webchat_followups"):
        out["email_followups"] = False
        out["wa_followups"] = False
    return out


def use_ai_allowance(db, org_id: str) -> bool:
    """Take one AI answer from the plan's monthly allowance. Not switched on -> True and nothing counted."""
    return acc.consume(db, "ai_assistant", org_id=org_id, n=1)
