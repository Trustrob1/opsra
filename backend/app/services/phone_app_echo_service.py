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


# ---------------------------------------------------------------------------
# COEXIST-2 - history import, contact sync, account_update
# ---------------------------------------------------------------------------

_HISTORY_STATUS = {"DELIVERED": "delivered", "READ": "read", "PLAYED": "read",
                   "SENT": "sent", "ERROR": "failed", "PENDING": "sent"}


def _digits(p: str) -> str:
    return "".join(ch for ch in (p or "") if ch.isdigit())


def handle_history(db, org_id: str, value: dict) -> int:
    """Import past chats Meta sends after coexistence onboarding.

    Only for people who are already a lead/customer of this org (nobody new is
    created). Idempotent on meta_message_id. Does not pause the bot and does
    not stamp first_contacted (old replies would give a false response time).
    Returns messages stored. Never raises.
    """
    stored = 0
    try:
        from app.routers.webhooks import _lookup_record_by_phone
        own = _digits(((value.get("metadata") or {}).get("display_phone_number")) or "")
        for chunk in (value.get("history") or []):
            for thread in (chunk.get("threads") or []):
                try:
                    stored += _thread(db, org_id, thread, own, _lookup_record_by_phone)
                except Exception as exc:
                    logger.warning("phone_app_history: thread failed org=%s: %s", org_id, exc)
    except Exception as exc:
        logger.warning("phone_app_history: failed org=%s: %s", org_id, exc)
    return stored


def _thread(db, org_id, thread, own_digits, lookup) -> int:
    contact = thread.get("id") or ""
    if not contact:
        return 0
    _o, customer_id, lead_id, _a = lookup(db, contact, org_id)
    if not (customer_id or lead_id):
        return 0
    msgs = thread.get("messages") or []
    ids = [m.get("id") for m in msgs if m.get("id")]
    have = set()
    if ids:
        rows = (db.table("whatsapp_messages").select("meta_message_id").eq("org_id", org_id)
                .in_("meta_message_id", ids).execute().data or [])
        have = {r.get("meta_message_id") for r in rows}
    out = []
    for m in msgs:
        if m.get("id") in have:
            continue
        mtype, content = _body(m)
        inbound = _digits(m.get("from") or "") == _digits(contact) and _digits(contact) != own_digits
        ts = _ts(m.get("timestamp"))
        status = _HISTORY_STATUS.get(((m.get("history_context") or {}).get("status") or "").upper(), "sent")
        row = {
            "org_id": org_id,
            "direction": "inbound" if inbound else "outbound",
            "message_type": mtype, "content": content,
            "status": "received" if inbound else status,
            "meta_message_id": m.get("id") or None,
            "window_open": False, "sent_by": None, "channel": "whatsapp",
            "meta_category": PHONE_APP_CATEGORY, "meta_billable": False,
            "created_at": ts, "sent_at": ts,
        }
        if customer_id:
            row["customer_id"] = customer_id
        else:
            row["lead_id"] = lead_id
        out.append(row)
    if out:
        db.table("whatsapp_messages").insert(out).execute()
    return len(out)


def handle_state_sync(db, org_id: str, value: dict) -> int:
    """smb_app_state_sync: contacts saved in the phone app. Only fills a blank
    name on an existing lead; never creates or deletes anything. Never raises."""
    done = 0
    try:
        from app.routers.webhooks import _lookup_record_by_phone
        for item in (value.get("state_sync") or []):
            try:
                if item.get("type") != "contact" or item.get("action") == "remove":
                    continue
                c = item.get("contact") or {}
                name = (c.get("full_name") or c.get("first_name") or "").strip()
                phone = c.get("phone_number") or ""
                if not (name and phone):
                    continue
                _o, customer_id, lead_id, _a = _lookup_record_by_phone(db, phone, org_id)
                if customer_id or not lead_id:
                    continue
                cur = (db.table("leads").select("full_name").eq("id", lead_id).eq("org_id", org_id)
                       .limit(1).execute().data or [])
                if cur and not (cur[0].get("full_name") or "").strip():
                    db.table("leads").update({"full_name": name}).eq("id", lead_id).eq("org_id", org_id).execute()
                    done += 1
            except Exception as exc:
                logger.warning("phone_app_state_sync: item failed org=%s: %s", org_id, exc)
    except Exception as exc:
        logger.warning("phone_app_state_sync: failed org=%s: %s", org_id, exc)
    return done


COEXIST_ALERT_EVENTS = {"ACCOUNT_OFFBOARDED", "PARTNER_REMOVED", "ACCOUNT_RECONNECTED"}


def handle_account_update(value: dict) -> Optional[str]:
    """Coexistence lifecycle events: logged and sent to Sentry so a disconnect is noticed."""
    try:
        event = (value.get("event") or "").upper()
        if event not in COEXIST_ALERT_EVENTS:
            return None
        waba = ((value.get("waba_info") or {}).get("waba_id")) or ""
        logger.warning("whatsapp account_update %s waba=%s", event, waba)
        import sentry_sdk
        sentry_sdk.capture_message(f"WhatsApp coexistence {event} waba={waba}", level="warning")
        return event
    except Exception as exc:
        logger.warning("account_update handler failed: %s", exc)
        return None
