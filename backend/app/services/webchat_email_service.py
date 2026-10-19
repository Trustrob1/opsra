"""
app/services/webchat_email_service.py
-------------------------------------
WEBCHAT-4 — email follow-ups for web chat visitors (Resend, the same sender the site emails use).

What is sent, and only to a visitor who gave an email AND ticked the consent box:
  * "<Business> replied" when the team writes and the visitor has left the page (with a "continue your chat" link)
  * "Your chat with <Business>" (transcript + link) when the visitor asks to be emailed their chat
  * booking confirmation and the payment link / order summary from the shop

Rules
  * Never to an address the visitor did not give; never after "Stop emails" (state.email_optout).
  * At most one "team replied" email per chat per 30 minutes; only when the visitor has been away 8+ minutes.
  * The continue link is a fresh one-time hand-off for the SAME session (7 days); opening it signs the visitor back in
    to their own chat only.
  * Switched off per business with config.email_followups = false.
S14: nothing here raises; a failed email never breaks a chat action. WhatsApp is not used as a fallback here:
a template send costs Meta fees, so it stays a deliberate choice of the business.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

AWAY_MIN = 8
REPLY_EMAIL_COOLDOWN_MIN = 30
RESUME_HOURS = 24 * 7
TRANSCRIPT_MESSAGES = 30


def _parse(ts) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def can_email(s: dict, cfg: dict) -> bool:
    return bool(cfg.get("email_followups", True) and s.get("contact_email") and s.get("consent_at")
                and not (s.get("state") or {}).get("email_optout"))


def _send(to: str, subject: str, body: str) -> bool:
    try:
        from app.services.site_addon_billing_service import _send_email
        return bool(_send_email(to, subject, body))
    except Exception as exc:
        logger.warning("webchat email failed: %s", exc)
        return False


def resume_link(db, s: dict) -> Optional[str]:
    """Arm a fresh one-time link into THIS session. None if it cannot be made."""
    try:
        key = wc.get_or_create_key(db, s["org_id"])
        token = wc.new_token()
        wc.update_session(db, s, {"handoff_hash": wc.hash_token(token), "handoff_used_at": None,
                                  "handoff_expires_at": wc._iso(wc._now() + timedelta(hours=RESUME_HOURS))})
        return f"{wc.public_base()}/c/{key}?h={token}"
    except Exception as exc:
        logger.warning("webchat resume link failed: %s", exc)
        return None


def _footer(cfg: dict) -> str:
    return (f"\n\nYou are getting this because you asked {cfg.get('business_name') or 'us'} to contact you by email "
            "on our web chat. To stop these emails, open your chat and tap Stop follow-ups.")


def _first(s: dict) -> str:
    return (s.get("contact_name") or "").strip().split(" ")[0] or "there"


def notify_rep_reply(db, s: dict, cfg: dict, text: str) -> bool:
    """Called after a team message is stored. True if an email went out."""
    try:
        if not can_email(s, cfg):
            return False
        last = _parse(s.get("last_activity_at"))
        if last and wc._now() - last < timedelta(minutes=AWAY_MIN):
            return False                                   # visitor is probably still on the page
        sent = _parse((s.get("state") or {}).get("email_reply_at"))
        if sent and wc._now() - sent < timedelta(minutes=REPLY_EMAIL_COOLDOWN_MIN):
            return False
        link = resume_link(db, s)
        if not link:
            return False
        name = cfg.get("business_name") or "the team"
        snippet = wc._clean_text(text, 400)
        body = (f"Hi {_first(s)},\n\n{name} replied to your chat:\n\n\"{snippet}\"\n\nContinue your chat here:\n{link}"
                + _footer(cfg))
        ok = _send(s["contact_email"], f"{name} replied to your chat", body)
        if ok:
            wc.set_state(db, s, email_reply_at=wc._iso(wc._now()))
        return ok
    except Exception as exc:
        logger.warning("webchat reply email failed: %s", exc)
        return False


def send_transcript(db, s: dict, cfg: dict) -> bool:
    try:
        if not can_email(s, cfg):
            return False
        msgs = wc.list_messages(db, s)[-TRANSCRIPT_MESSAGES:]
        who = {"visitor": "You", "bot": cfg.get("business_name") or "Assistant", "rep": f"{cfg.get('business_name') or 'Team'} team"}
        lines = "\n\n".join(f"{who.get(m['role'], 'Assistant')}: {m['text']}" for m in msgs) or "(no messages yet)"
        link = resume_link(db, s)
        body = (f"Hi {_first(s)},\n\nHere is your chat with {cfg.get('business_name') or 'us'}:\n\n{lines}"
                + (f"\n\nContinue your chat here:\n{link}" if link else "") + _footer(cfg))
        return _send(s["contact_email"], f"Your chat with {cfg.get('business_name') or 'us'}", body)
    except Exception as exc:
        logger.warning("webchat transcript email failed: %s", exc)
        return False


def send_booking_confirmation(db, s: dict, cfg: dict, summary: str) -> bool:
    try:
        if not can_email(s, cfg):
            return False
        name = cfg.get("business_name") or "us"
        body = (f"Hi {_first(s)},\n\nWe have your booking request with {name}:\n\n{summary[:500]}\n\n"
                "We will confirm the time with you shortly." + _footer(cfg))
        return _send(s["contact_email"], f"Booking request received by {name}", body)
    except Exception as exc:
        logger.warning("webchat booking email failed: %s", exc)
        return False


def send_order_link(db, s: dict, cfg: dict, summary: str, url: str) -> bool:
    try:
        if not can_email(s, cfg) or not url:
            return False
        name = cfg.get("business_name") or "us"
        body = (f"Hi {_first(s)},\n\nYour order with {name}:\n\n{summary[:800]}\n\nPay securely here:\n{url}" + _footer(cfg))
        return _send(s["contact_email"], f"Your order with {name}", body)
    except Exception as exc:
        logger.warning("webchat order email failed: %s", exc)
        return False


def save_email(db, s: dict, cfg: dict, email: Optional[str], consent: bool) -> dict:
    """Visitor taps 'Email me this chat'. Needs contact details first. Stores the email only with consent."""
    if not s.get("lead_id"):
        return {"error": "Please share your contact details first."}
    if not cfg.get("email_followups", True):
        return {"error": "Email is not available for this chat."}
    addr = wc._clean_text(email, 200).lower() or s.get("contact_email")
    if not addr or not wc._EMAIL_RE.match(addr):
        return {"error": "That email does not look right."}
    if not consent:
        return {"error": "Please tick the box so we can email you."}
    changes = {"contact_email": addr}
    if not s.get("consent_at"):
        changes["consent_at"] = wc._iso(wc._now())
    wc.update_session(db, s, changes)
    wc.set_state(db, s, email_optout=False)
    try:
        db.table("leads").update({"email": addr}).eq("id", s["lead_id"]).eq("org_id", s["org_id"]).is_("email", "null").execute()
    except Exception as exc:
        logger.warning("webchat lead email patch failed: %s", exc)
    sent = send_transcript(db, s, cfg)
    text = (f"Done. We have emailed this chat to {addr}." if sent
            else f"Saved {addr}. We could not send the email just now, but we will use it to reach you.")
    return {"messages": [wc.append_message(db, s, "bot", text)], "emailed": sent}


def opt_out(db, s: dict) -> dict:
    wc.set_state(db, s, email_optout=True, wa_optout=True)
    return {"messages": [wc.append_message(db, s, "bot", "Done. We will not send you follow-ups from this chat again.")]}
