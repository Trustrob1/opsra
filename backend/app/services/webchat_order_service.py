"""
webchat_order_service.py
ORDER-PAID-1: a team member confirms, from the web chat conversation, that a held order has been paid (bank transfer or a
link paid outside the chat). The order is the one ORDER-CONFIRM-1 keeps in the chat's state (pending_order).
Staff only; the business always comes from the login. Marking is once only.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)


def _money(v: float) -> str:
    return f"₦{float(v or 0):,.0f}"


def order_view(db, org_id: str, lead_id: str) -> Optional[dict]:
    """The order waiting on this contact's latest web chat, or None. {status, total, summary, at, paid_at?, paid_by?}"""
    s = wc.latest_session_for_lead(db, org_id, lead_id)
    po = ((s or {}).get("state") or {}).get("pending_order")
    if not po:
        return None
    return {k: po.get(k) for k in ("status", "total", "summary", "at", "paid_at", "paid_by_name") if po.get(k) is not None}


def mark_paid(db, org_id: str, lead_id: str, user_id: str, user_name: str = "") -> dict:
    """Mark the held order paid. Raises LookupError (no order), ValueError (already paid). Returns the order view."""
    s = wc.latest_session_for_lead(db, org_id, lead_id)
    po = ((s or {}).get("state") or {}).get("pending_order")
    if not s or not po:
        raise LookupError("no order waiting")
    if po.get("status") == "paid":
        raise ValueError("already paid")
    total = float(po.get("total") or 0)
    now = wc._iso(wc._now())
    wc.set_state(db, s, pending_order={**po, "status": "paid", "paid_at": now, "paid_by": user_id, "paid_by_name": (user_name or "")[:60]})
    ref = ((s.get("state") or {}).get("last_checkout") or {}).get("reference")
    wc.log_event(db, org_id, s["id"], "paid", s.get("source"), ref=ref, value_kobo=int(round(total * 100)))
    try:
        from app.services import lead_service
        lead_service.write_timeline_event(db, org_id, lead_id, event_type="webchat_order_paid", actor_id=user_id,
                                          description=f"Web chat order marked as paid by {user_name or 'a team member'}: {_money(total)}",
                                          metadata={"total": total, "manual": True})
    except Exception as exc:
        logger.warning("webchat order paid timeline failed: %s", exc)
    try:    # tell the customer in the chat (rep_send also reaches them by email or WhatsApp if they have left)
        wc.rep_send(db, org_id, lead_id, f"Thank you. We have received your payment of {_money(total)}. We will be in touch here about your order.", user_id)
    except Exception as exc:
        logger.warning("webchat order paid message failed: %s", exc)
    return order_view(db, org_id, lead_id) or {}
