"""
app/services/webchat_followup_service.py
----------------------------------------
WEBCHAT-4 / 4b — chooses the channel for a follow-up to a web chat visitor.

Order: email first (free-ish), then WhatsApp if the business opted in; or WhatsApp first when the business set
config.wa_followup_mode = 'prefer'. Exactly ONE channel is used per team reply. The "visitor has left the page" and
"not more than one per 30 minutes" checks happen once, here, so two channels can never both fire.
S14: never raises.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from app.services import webchat_email_service as em
from app.services import webchat_service as wc
from app.services import webchat_whatsapp_service as wa

logger = logging.getLogger(__name__)


def _plan_on(db, s: dict) -> bool:
    """ACCOUNT-PLANS AP-4: follow-ups are part of the plan. Not switched on -> always True."""
    from app.services import webchat_plan_service as plan
    return plan.allowed(db, s.get("org_id"), "webchat_followups")


def _gate(s: dict) -> bool:
    last = em._parse(s.get("last_activity_at"))
    if last and wc._now() - last < timedelta(minutes=em.AWAY_MIN):
        return False
    sent = em._parse((s.get("state") or {}).get("followup_reply_at"))
    return not (sent and wc._now() - sent < timedelta(minutes=em.REPLY_EMAIL_COOLDOWN_MIN))


def notify_rep_reply(db, s: dict, cfg: dict, text: str) -> Optional[str]:
    """Returns 'email' | 'whatsapp' | None."""
    try:
        if not _plan_on(db, s):
            return None
        want_email, want_wa = em.can_email(s, cfg), wa.can_whatsapp(s, cfg)
        if not (want_email or want_wa) or not _gate(s):
            return None
        order = ["whatsapp", "email"] if cfg.get("wa_followup_mode") == "prefer" else ["email", "whatsapp"]
        for channel in order:
            if channel == "email" and want_email and em.notify_rep_reply(db, s, cfg, text):
                used = "email"
            elif channel == "whatsapp" and want_wa:
                link = em.resume_link(db, s)
                used = "whatsapp" if link and wa.notify_rep_reply(db, s, cfg, text, link) else None
            else:
                used = None
            if used:
                wc.set_state(db, s, followup_reply_at=wc._iso(wc._now()))
                return used
        return None
    except Exception as exc:
        logger.warning("webchat follow-up failed: %s", exc)
        return None


def send_booking_confirmation(db, s: dict, cfg: dict, summary: str) -> None:
    try:
        if not _plan_on(db, s):
            return
        sent = em.send_booking_confirmation(db, s, cfg, summary)
        if not sent:
            name = cfg.get("business_name") or "us"
            wa.send_in_window(db, s, cfg, f"We have your booking request with {name}: {summary[:400]}. We will confirm shortly.")
    except Exception as exc:
        logger.warning("webchat booking follow-up failed: %s", exc)


def send_order_link(db, s: dict, cfg: dict, summary: str, url: str) -> None:
    try:
        if not _plan_on(db, s):
            return
        sent = em.send_order_link(db, s, cfg, summary, url)
        if not sent:
            wa.send_in_window(db, s, cfg, f"Your order with {cfg.get('business_name') or 'us'}:\n{summary[:600]}", cta=("Pay now", url))
    except Exception as exc:
        logger.warning("webchat order follow-up failed: %s", exc)
