"""
app/services/funnel_messaging.py
---------------------------------
FUNNEL-1A — WhatsApp senders for Event Funnel numbers.

Every sender:
  • sends from the funnel number's OWN credentials (whatsapp_numbers.phone_id /
    access_token) — never the org's legacy number (spec F7/F8),
  • saves the outbound message to whatsapp_messages with lead_id so it shows
    in Conversations,
  • is S14-safe: returns True/False, never raises.

Message types used:
  text      — plain text (inside the 24h customer-service window)
  cta_url   — one URL button ("Pay ₦5,000") — Cloud API interactive type cta_url
  buttons   — up to 3 reply buttons (FAQ)
  template  — approved template (outside the 24h window)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

# Pattern 42: imported at module level so tests patch app.services.funnel_messaging._call_meta_send
from app.services.whatsapp_service import _call_meta_send  # noqa: E402

logger = logging.getLogger(__name__)

_BODY_MAX = 1024        # WhatsApp interactive/text body limit we enforce
_BUTTON_TITLE_MAX = 20  # reply button title limit
_CTA_TEXT_MAX = 20      # cta_url display_text limit


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _creds(number_row: dict) -> tuple[str, str]:
    return (
        (number_row.get("phone_id") or "").strip(),
        (number_row.get("access_token") or "").strip(),
    )


def _save_outbound(db, org_id: str, lead_id: Optional[str], content: str,
                   message_type: str = "text", meta_message_id: Optional[str] = None) -> None:
    try:
        db.table("whatsapp_messages").insert({
            "org_id":            org_id,
            "lead_id":           lead_id,
            "direction":         "outbound",
            "message_type":      message_type,
            "channel":           "whatsapp",
            "content":           content,
            "status":            "sent",
            "meta_message_id":   meta_message_id,
            "window_open":       True,
            "window_expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            "sent_by":           None,
            "created_at":        _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("funnel_messaging: outbound save failed org=%s: %s", org_id, exc)


def _meta_id(resp: dict) -> Optional[str]:
    try:
        return ((resp or {}).get("messages") or [{}])[0].get("id")
    except Exception:
        return None


def _send(db, org_id: str, number_row: dict, to: str, payload_body: dict,
          lead_id: Optional[str], log_content: str, message_type: str = "text") -> bool:
    phone_id, token = _creds(number_row)
    if not phone_id or not token:
        logger.warning("funnel_messaging: number has no credentials org=%s", org_id)
        return False
    try:
        payload = {"messaging_product": "whatsapp", "to": to}
        payload.update(payload_body)
        resp = _call_meta_send(phone_id, payload, token=token)
    except Exception as exc:
        logger.warning("funnel_messaging: send failed org=%s type=%s: %s", org_id, message_type, exc)
        return False
    # message_type is always stored as "text" (same as send_agent_confirm_buttons) —
    # whatsapp_messages.message_type values beyond text/image are unverified.
    _save_outbound(db, org_id, lead_id, log_content, "text", _meta_id(resp))
    return True


def send_text(db, org_id: str, number_row: dict, to: str, text: str,
              lead_id: Optional[str] = None) -> bool:
    text = (text or "").strip()[:4096]
    if not text:
        return False
    return _send(db, org_id, number_row, to,
                 {"type": "text", "text": {"body": text, "preview_url": True}},
                 lead_id, text)


def send_cta_url(db, org_id: str, number_row: dict, to: str, body: str,
                 button_text: str, url: str, lead_id: Optional[str] = None) -> bool:
    """One tappable URL button. Falls back to plain text with the link if the
    interactive send fails (older clients / API error)."""
    body = (body or "").strip()[:_BODY_MAX]
    ok = _send(db, org_id, number_row, to, {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": body},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": (button_text or "Pay now")[:_CTA_TEXT_MAX], "url": url},
            },
        },
    }, lead_id, f"{body}\n[{button_text}] {url}", "interactive")
    if ok:
        return True
    return send_text(db, org_id, number_row, to, f"{body}\n\n👉 {url}", lead_id)


def send_reply_buttons(db, org_id: str, number_row: dict, to: str, body: str,
                       buttons: list[dict], lead_id: Optional[str] = None) -> bool:
    """buttons: [{"id": "...", "title": "..."}] — max 3 (WhatsApp limit)."""
    btns = [
        {"type": "reply", "reply": {"id": str(b["id"])[:256], "title": str(b["title"])[:_BUTTON_TITLE_MAX]}}
        for b in (buttons or [])[:3] if b.get("id") and b.get("title")
    ]
    if not btns:
        return send_text(db, org_id, number_row, to, body, lead_id)
    return _send(db, org_id, number_row, to, {
        "type": "interactive",
        "interactive": {"type": "button", "body": {"text": (body or "")[:_BODY_MAX]},
                        "action": {"buttons": btns}},
    }, lead_id, body, "interactive")


def send_template(db, org_id: str, number_row: dict, to: str, template_name: str,
                  body_params: Optional[list[str]] = None, language: str = "en",
                  lead_id: Optional[str] = None) -> bool:
    tpl: dict = {"name": template_name, "language": {"code": language}}
    params = [str(p)[:1000] for p in (body_params or [])]
    if params:
        tpl["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        }]
    return _send(db, org_id, number_row, to, {"type": "template", "template": tpl},
                 lead_id, f"[template:{template_name}] " + " | ".join(params), "template")
