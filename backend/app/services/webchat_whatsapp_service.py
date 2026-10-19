"""
app/services/webchat_whatsapp_service.py
----------------------------------------
WEBCHAT-4b — OPT-IN WhatsApp follow-ups for web chat visitors.

Off for every business until its owner switches it on (config.wa_followups) AND names a Meta-approved template
(config.wa_template_name). A WhatsApp template message costs a Meta fee, so this is a choice for businesses that
can afford it; it is never a silent default.

What it sends, only to a visitor who gave a WhatsApp number (consent ticked, or the number was proven by a WhatsApp
message) and has not tapped Stop follow-ups:
  * Team replied (visitor away): inside the visitor's 24-hour WhatsApp window a normal message with a Continue
    button (free); outside it the business's approved template, body variables [first name, business name, link].
  * Booking confirmation / payment link: ONLY inside the 24-hour window (free text). No template is used for these.

Cost guards: per-business monthly cap (config.wa_monthly_cap, default 100 templates), at most 3 templates per chat,
the shared 30-minute spacing from the follow-up orchestrator, and nothing is sent when the business's credit wallet is
metered and empty. The Meta fee itself is captured later from the message status webhook (meta_message_id) and billed
by the existing credit rules. Sent from the business's OWN WhatsApp number (the redirect number if it has one).
S14: never raises; returns False when nothing was sent.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

MAX_TEMPLATES_PER_CHAT = 3
WINDOW_HOURS = 24
SUGGESTED_TEMPLATE = "Hi {{1}}, {{2}} has replied to your chat. Tap here to continue: {{3}}"


def can_whatsapp(s: dict, cfg: dict) -> bool:
    return bool(cfg.get("wa_followups") and cfg.get("wa_template_name") and s.get("contact_phone")
                and (s.get("consent_at") or s.get("phone_verified"))
                and not (s.get("state") or {}).get("wa_optout"))


def _number(db, org_id: str) -> Optional[dict]:
    from app.services import funnel_messaging
    rows = db.table("whatsapp_numbers").select("*").eq("org_id", org_id).execute().data or []
    usable = [r for r in rows if all(funnel_messaging._creds(r))]
    usable.sort(key=lambda r: 0 if r.get("wa_sales_mode") == "webchat_redirect" else 1)
    return usable[0] if usable else None


def window_open(db, s: dict) -> bool:
    """True when the visitor messaged this business on WhatsApp in the last 24 hours (free-form messages allowed)."""
    try:
        rows = (db.table("whatsapp_messages").select("created_at").eq("org_id", s["org_id"]).eq("lead_id", s["lead_id"])
                .eq("direction", "inbound").eq("channel", "whatsapp").order("created_at", desc=True).limit(1).execute().data or [])
        if not rows:
            return False
        from datetime import datetime
        last = datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
        return wc._now() - last < timedelta(hours=WINDOW_HOURS)
    except Exception as exc:
        logger.warning("webchat wa window check failed: %s", exc)
        return False


def _first(s: dict) -> str:
    return (s.get("contact_name") or "").strip().split(" ")[0] or "there"


def _wallet_ok(db, org_id: str) -> bool:
    try:
        from app.services import credit_service
        w = credit_service.get_wallet(db, org_id)
        if credit_service.metering_on(w) and int((w or {}).get("balance_kobo") or 0) <= 0:
            return False
    except Exception:
        pass
    return True


def _monthly_ok(org_id: str, cfg: dict) -> bool:
    try:
        cap = max(1, min(int(cfg.get("wa_monthly_cap") or 100), 5000))
    except (TypeError, ValueError):
        cap = 100
    stamp = wc._now().strftime("%Y%m")
    return not wc.rate_limited(f"wa:tpl:{org_id}:{stamp}", cap, 32 * 86400)


def send_in_window(db, s: dict, cfg: dict, text: str, cta: Optional[tuple] = None) -> bool:
    """Free-form message, only while the visitor's 24-hour window is open. Never uses a template."""
    try:
        if not can_whatsapp(s, cfg) or not window_open(db, s):
            return False
        number = _number(db, s["org_id"])
        to = wc.normalise_phone(s.get("contact_phone"))
        if not number or not to:
            return False
        from app.services import funnel_messaging
        if cta:
            return bool(funnel_messaging.send_cta_url(db, s["org_id"], number, to, text, cta[0], cta[1], s.get("lead_id")))
        return bool(funnel_messaging.send_text(db, s["org_id"], number, to, text, s.get("lead_id")))
    except Exception as exc:
        logger.warning("webchat wa in-window send failed: %s", exc)
        return False


def notify_rep_reply(db, s: dict, cfg: dict, text: str, link: str) -> bool:
    """Team replied and the visitor is away (the orchestrator already checked that). True if a message went out."""
    try:
        if not can_whatsapp(s, cfg):
            return False
        number = _number(db, s["org_id"])
        to = wc.normalise_phone(s.get("contact_phone"))
        if not number or not to or not link:
            return False
        from app.services import funnel_messaging
        name = cfg.get("business_name") or "the team"
        if window_open(db, s):
            snippet = wc._clean_text(text, 300)
            return bool(funnel_messaging.send_cta_url(db, s["org_id"], number, to, f"{name} replied: \"{snippet}\"",
                                                      "Continue chat", link, s.get("lead_id")))
        state = s.get("state") or {}
        if int(state.get("wa_count") or 0) >= MAX_TEMPLATES_PER_CHAT:
            return False
        if not _wallet_ok(db, s["org_id"]) or not _monthly_ok(s["org_id"], cfg):
            logger.info("webchat wa template skipped (wallet or monthly cap) org=%s", s["org_id"])
            return False
        ok = funnel_messaging.send_template(db, s["org_id"], number, to, cfg["wa_template_name"],
                                            [_first(s), name, link], language=cfg.get("wa_template_lang") or "en",
                                            lead_id=s.get("lead_id"))
        if ok:
            wc.set_state(db, s, wa_count=int(state.get("wa_count") or 0) + 1)
        return bool(ok)
    except Exception as exc:
        logger.warning("webchat wa reply notify failed: %s", exc)
        return False


def send_test(db, org_id: str, cfg: dict, phone: str) -> dict:
    """Admin 'send a test' to check the template is approved. Counts against nothing but costs one Meta message."""
    if not cfg.get("wa_template_name"):
        return {"error": "Enter the template name first and save."}
    to = wc.normalise_phone(phone)
    if not to:
        return {"error": "That phone number does not look right."}
    number = _number(db, org_id)
    if not number:
        return {"error": "This business has no connected WhatsApp number."}
    from app.services import funnel_messaging
    link = f"{wc.public_base()}/c/test"
    ok = funnel_messaging.send_template(db, org_id, number, to, cfg["wa_template_name"],
                                        ["Test", cfg.get("business_name") or "Your business", link],
                                        language=cfg.get("wa_template_lang") or "en")
    if not ok:
        return {"error": "Meta did not accept the message. Check the template name, language and that it is approved."}
    return {"sent": True}
