"""
app/services/webchat_redirect_service.py
----------------------------------------
WEBCHAT-2 — WhatsApp numbers in wa_sales_mode 'webchat_redirect'.

First message from a person: ONE automatic WhatsApp reply carrying the org's own text and a
link to the web chat (the link holds a one-time hand-off token, so the number is already proven).
After that: no automatic replies at all (so no Meta fee), the team is told in-app instead.
At most one redirect reply per phone per 24 hours.

If the org has not switched its web chat on, the number simply records the message and tells the
team — it never leaves a customer waiting on a silent bot without anyone being alerted.

Called from routers/webhooks.py._handle_inbound_message with the same early-return pattern as the
ai_agent / site_builder / event_funnel blocks. The org is ALWAYS the number's own org (XORG-safe).
S14: never raises past handle_inbound().
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

REDIRECT_COOLDOWN_H = 24
NOTIFY_COOLDOWN_MIN = 10
DEFAULT_TEXT = "Hi {name}! To get your answer fastest, please continue here: {link}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _save_inbound(db, org_id: str, lead_id: Optional[str], msg_type: str, content: Optional[str], msg_id: Optional[str]) -> None:
    try:
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id, "direction": "inbound",
            "message_type": msg_type if msg_type in ("text", "image") else "text", "channel": "whatsapp",
            "content": content, "status": "delivered", "meta_message_id": msg_id or None,
            "window_open": True, "window_expires_at": (_now() + timedelta(hours=24)).isoformat(),
            "sent_by": None, "created_at": _now().isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("[WEBCHAT-2] inbound save failed org=%s: %s", org_id, exc)


def compose_text(cfg: dict, name: Optional[str], link: str) -> str:
    first = (name or "").strip().split(" ")[0] or "there"
    template = (cfg.get("redirect_text") or "").strip() or DEFAULT_TEXT
    body = template.replace("{name}", first)
    body = body.replace("{link}", link) if "{link}" in body else f"{body}\n{link}"
    if cfg.get("redirect_mode") == "menu_first" and cfg.get("menu"):
        labels = "\n".join(f"• {m['label']}" for m in cfg["menu"][:8])
        body = body.replace(link, f"You can:\n{labels}\n{link}") if link in body else body
    return body[:1500]


def _redirect_row(db, org_id: str, phone: str) -> Optional[dict]:
    rows = db.table("webchat_redirects").select("*").eq("org_id", org_id).eq("phone", phone).limit(1).execute().data
    return rows[0] if rows else None


def _notify_team(db, org_id: str, lead_id: Optional[str], name: Optional[str], phone: str, text: str, row: Optional[dict]) -> None:
    last = _parse((row or {}).get("last_notified_at"))
    if last and _now() - last < timedelta(minutes=NOTIFY_COOLDOWN_MIN):
        return
    wc.notify_managers(db, org_id, f"WhatsApp message from {name or phone}",
                       (text or "(media)")[:300], lead_id, "webchat_message")
    try:
        db.table("webchat_redirects").update({"last_notified_at": _now().isoformat()}).eq("org_id", org_id).eq("phone", phone).execute()
    except Exception:
        pass


def handle_inbound(db, number_row: dict, sender_phone: str, contact_name: Optional[str], msg_type: str,
                   content: Optional[str], msg_id: Optional[str]) -> None:
    org_id = number_row.get("org_id")
    try:
        from app.services import funnel_service
        phone = wc.normalise_phone(sender_phone) or sender_phone
        lead_id = funnel_service._get_or_create_lead(db, org_id, phone, contact_name, content if msg_type == "text" else None, None, {})
        _save_inbound(db, org_id, lead_id, msg_type, content, msg_id)

        cfg = wc.get_config(db, org_id)
        row = _redirect_row(db, org_id, phone)
        sent_at = _parse((row or {}).get("last_sent_at"))
        recently = bool(sent_at and _now() - sent_at < timedelta(hours=REDIRECT_COOLDOWN_H))
        if recently or not cfg.get("enabled"):
            if not row:
                db.table("webchat_redirects").insert({"org_id": org_id, "phone": phone, "sent_count": 0,
                                                      "last_sent_at": (_now() - timedelta(days=3)).isoformat()}).execute()
                row = None
            _notify_team(db, org_id, lead_id, contact_name, phone, content or "", row)
            return

        key = wc.get_or_create_key(db, org_id)
        link = wc.create_handoff(db, org_id, lead_id=lead_id, phone=phone, name=contact_name, key=key)
        text = compose_text(cfg, contact_name, link)
        from app.services.whatsapp_service import send_agent_text_message
        send_agent_text_message(
            db=db, org_id=org_id, phone_number=sender_phone, lead_id=lead_id, message=text,
            phone_id=number_row.get("phone_id"), access_token=number_row.get("access_token"),
        )
        now_iso = _now().isoformat()
        if row:
            db.table("webchat_redirects").update({"last_sent_at": now_iso, "sent_count": int(row.get("sent_count") or 0) + 1}) \
                .eq("org_id", org_id).eq("phone", phone).execute()
        else:
            db.table("webchat_redirects").insert({"org_id": org_id, "phone": phone, "last_sent_at": now_iso, "sent_count": 1}).execute()
        wc.log_event(db, org_id, None, "redirect_sent", "whatsapp")
    except Exception:
        logger.exception("[WEBCHAT-2] handle_inbound failed org=%s phone=%s", org_id, sender_phone)
