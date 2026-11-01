"""
COEXIST-1 - messages a rep sends from the WhatsApp Business *phone app*.

With WhatsApp coexistence, Meta mirrors every message sent from the phone app
to our webhook as the `smb_message_echoes` field. Without handling it, Opsra
never sees those replies: the thread looks one-sided, `first_contacted_at`
stays empty and the bot keeps talking over the rep.

For each echo we:
  1. store it as an outbound row in whatsapp_messages (idempotent on
     meta_message_id), tagged meta_category = 'phone_app', not billable;
  2. stamp the lead as contacted (first_contacted_at / response time);
  3. pause the bot (ai_paused) for that lead / customer, same as a rep reply
     sent from the Conversations screen;
  4. bump the lead's last_activity_at.

Echoes to numbers that are not a lead or customer are ignored (no lead is
created here). S14: nothing in this module raises.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

PHONE_APP_CATEGORY = "phone_app"


def _ts(raw) -> str:
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _body(echo: dict) -> tuple:
    """(message_type, content) for an echo."""
    mtype = (echo.get("type") or "text").lower()
    if mtype == "text":
        return "text", ((echo.get("text") or {}).get("body") or "")
    node = echo.get(mtype) or {}
    caption = node.get("caption") or ""
    return mtype, caption or f"[{mtype}]"


def handle_echoes(db, org_id: str, value: dict) -> int:
    """Process value['message_echoes']. Returns how many were stored."""
    stored = 0
    for echo in (value.get("message_echoes") or []):
        try:
            if _one(db, org_id, echo):
                stored += 1
        except Exception as exc:  # S14
            logger.warning("phone_app_echo: failed org=%s id=%s: %s",
                           org_id, (echo or {}).get("id"), exc)
    return stored


def _one(db, org_id: str, echo: dict) -> bool:
    from app.routers.webhooks import _lookup_record_by_phone

    msg_id: str = echo.get("id") or ""
    to_phone: str = echo.get("to") or ""
    if not to_phone:
        return False

    if msg_id:
        dup = (db.table("whatsapp_messages").select("id").eq("org_id", org_id)
               .eq("meta_message_id", msg_id).limit(1).execute().data or [])
        if dup:
            return False

    _org, customer_id, lead_id, _assigned = _lookup_record_by_phone(db, to_phone, org_id)
    if not (customer_id or lead_id):
        return False

    mtype, content = _body(echo)
    created = _ts(echo.get("timestamp"))
    row = {
        "org_id": org_id,
        "direction": "outbound",
        "message_type": mtype,
        "content": content,
        "status": "sent",
        "meta_message_id": msg_id or None,
        "window_open": True,
        "sent_by": None,
        "channel": "whatsapp",
        "meta_category": PHONE_APP_CATEGORY,
        "meta_billable": False,
        "created_at": created,
        "sent_at": created,
    }
    if customer_id:
        row["customer_id"] = customer_id
    else:
        row["lead_id"] = lead_id
    db.table("whatsapp_messages").insert(row).execute()

    _after_effects(db, org_id, lead_id, customer_id)
    return True


def _after_effects(db, org_id: str, lead_id: Optional[str], customer_id: Optional[str]) -> None:
    try:
        from app.services.whatsapp_service import set_ai_paused
        if customer_id:
            set_ai_paused(db=db, org_id=org_id, contact_type="customer",
                          contact_id=customer_id, paused=True)
        elif lead_id:
            set_ai_paused(db=db, org_id=org_id, contact_type="lead",
                          contact_id=lead_id, paused=True)
    except Exception as exc:
        logger.warning("phone_app_echo: pause failed: %s", exc)
    if lead_id and not customer_id:
        try:
            from app.services.lead_service import stamp_first_contacted
            stamp_first_contacted(db, org_id, lead_id)
        except Exception as exc:
            logger.warning("phone_app_echo: stamp failed: %s", exc)
        try:
            db.table("leads").update(
                {"last_activity_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", lead_id).eq("org_id", org_id).execute()
        except Exception as exc:
            logger.warning("phone_app_echo: last_activity failed: %s", exc)
