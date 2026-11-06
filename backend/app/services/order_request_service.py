"""
app/services/order_request_service.py
-------------------------------------
ORDER-GATE-1 - only leads that are ready to buy are given to a sales rep.

When a business has organisations.assign_on_order switched on:
  * a new WhatsApp enquiry is created but NOT auto-assigned (lead_assignment_service gate);
  * "I know what I want" sends the catalogue link instead of connecting the customer to a rep;
  * when the customer picks a product on the catalogue page and taps "Order via WhatsApp", the message that arrives
    carries an [ord:...] tag. That is the ready-to-buy signal: this module then
      1. finds or creates the lead,
      2. assigns it to the rep on shift (the normal shift / least-loaded rules),
      3. gives the rep a task + notification: confirm the product is available (10 minutes),
      4. replies to the customer once (free: they just messaged us),
      5. schedules a check that tells the owner / ops manager if nobody has replied after 10 minutes.
The rep confirms availability and sends the payment details themselves, in the normal chat.
S14: never raises into the webhook.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"\[ord:([^\]]*)\]")
CONFIRM_MINUTES = 10


def parse_order_tag(text: Optional[str]) -> tuple[str, Optional[str]]:
    """(text without the tag, tag value or None). Never raises."""
    try:
        m = TAG_RE.search(text or "")
        if not m:
            return (text or ""), None
        return TAG_RE.sub("", text).strip(), (m.group(1) or "order")
    except Exception:
        return (text or ""), None


def gate_on(db, org_id: Optional[str]) -> bool:
    try:
        if not org_id:
            return False
        rows = (db.table("organisations").select("assign_on_order").eq("id", org_id).limit(1).execute().data) or []
        return bool(rows and rows[0].get("assign_on_order"))
    except Exception:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _product_from_text(text: str) -> str:
    t = re.sub(r"^\s*hi,?\s*", "", text or "", flags=re.I)
    t = re.sub(r"^(i'?d like to order|i'?m interested in)\s+(the\s+)?", "", t, flags=re.I)
    return (t.strip() or "a product")[:160]


def handle(db, number_row: dict, sender_phone: str, contact_name: Optional[str], text: str,
           lead_id: Optional[str], msg_id: Optional[str]) -> bool:
    """True when the order request was handled (the webhook should stop); False to fall through. Never raises."""
    try:
        org_id = number_row.get("org_id")
        product = _product_from_text(text)
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service
        from app.services.lead_assignment_service import auto_assign_lead

        # 1 - lead
        if not lead_id:
            try:
                lead = lead_service.create_lead(
                    db=db, org_id=org_id, user_id=None, entry_path="whatsapp",
                    payload=LeadCreate(full_name=(contact_name or "").strip() or sender_phone, phone=sender_phone,
                                       whatsapp=sender_phone, source=LeadSource.whatsapp_inbound.value,
                                       problem_stated=text[:500]))
                lead_id = lead["id"]
            except Exception as exc:
                logger.warning("order_request: lead create failed org=%s: %s", org_id, exc)
                return False

        # 2 - save the customer's message so it shows in the chat
        try:
            db.table("whatsapp_messages").insert({
                "org_id": org_id, "lead_id": lead_id, "direction": "inbound", "message_type": "text", "channel": "whatsapp",
                "content": text, "status": "delivered", "meta_message_id": msg_id or None, "window_open": True,
                "window_expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "sent_by": None, "created_at": _now()}).execute()
        except Exception as exc:
            logger.warning("order_request: message save failed lead=%s: %s", lead_id, exc)

        # 3 - assign to the rep on shift (keeps the current rep if the lead already has one)
        row = (db.table("leads").select("assigned_to, full_name, ai_owned").eq("id", lead_id).limit(1).execute().data) or [{}]
        rep_id = row[0].get("assigned_to")
        if not rep_id or row[0].get("ai_owned"):
            rep_id = auto_assign_lead(db, org_id, lead_id, "ready_to_buy", None) or rep_id
        try:
            db.table("leads").update({"product_interest": product}).eq("id", lead_id).eq("org_id", org_id).execute()
        except Exception:
            pass

        # 4 - rep: task + notification
        if rep_id:
            try:
                db.table("tasks").insert({
                    "id": str(uuid.uuid4()), "org_id": org_id,
                    "title": f"Confirm availability: {product}"[:200],
                    "description": f"{contact_name or sender_phone} wants to order this. Confirm it is in stock within "
                                   f"{CONFIRM_MINUTES} minutes, then send the payment details.",
                    "task_type": "system_event", "source_module": "leads", "source_record_id": lead_id,
                    "assigned_to": rep_id, "priority": "high", "status": "open",
                    "created_at": _now(), "updated_at": _now()}).execute()
            except Exception as exc:
                logger.warning("order_request: task failed lead=%s: %s", lead_id, exc)
            try:
                db.table("notifications").insert({
                    "org_id": org_id, "user_id": rep_id, "type": "order_request",
                    "title": "Ready to buy - confirm availability",
                    "body": f"{contact_name or sender_phone}: {product}. Confirm stock in {CONFIRM_MINUTES} min, then send payment details.",
                    "resource_type": "lead", "resource_id": lead_id}).execute()
            except Exception as exc:
                logger.warning("order_request: notification failed lead=%s: %s", lead_id, exc)

        try:
            from app.services.lead_service import write_timeline_event
            write_timeline_event(db, org_id, lead_id, event_type="order_request", actor_id=None,
                                 description=f"Customer asked to order: {product}", metadata={"rep": rep_id})
        except Exception:
            pass

        # 5 - one reply to the customer
        try:
            from app.services import funnel_messaging
            first = ((contact_name or "").strip().split(" ") or [""])[0]
            funnel_messaging.send_text(
                db, org_id, number_row, sender_phone,
                f"Thanks{(' ' + first) if first else ''}! 🙏 We're confirming that {product} is available. "
                f"A consultant will message you within {CONFIRM_MINUTES} minutes with the next steps.",
                lead_id=lead_id)
        except Exception as exc:
            logger.warning("order_request: customer reply failed lead=%s: %s", lead_id, exc)

        # 6 - 10 minute check
        try:
            from app.workers.order_confirm_worker import check_order_confirmed
            check_order_confirmed.apply_async(args=[org_id, lead_id, _now(), product], countdown=CONFIRM_MINUTES * 60)
        except Exception as exc:
            logger.warning("order_request: check not scheduled lead=%s: %s", lead_id, exc)
        return True
    except Exception as exc:
        logger.warning("order_request.handle failed: %s", exc)
        return False


def team_replied_since(db, lead_id: str, since_iso: str) -> bool:
    rows = (db.table("whatsapp_messages").select("id").eq("lead_id", lead_id).eq("direction", "outbound")
            .not_.is_("sent_by", "null").gte("created_at", since_iso).limit(1).execute().data) or []
    return bool(rows)


def notify_managers(db, org_id: str, lead_id: str, product: str) -> int:
    n = 0
    users = (db.table("users").select("id, roles(template)").eq("org_id", org_id).execute().data) or []
    for u in users:
        r = u.get("roles") or {}
        if isinstance(r, list):
            r = r[0] if r else {}
        tpl = (r.get("template") or "").lower()
        if tpl in ("owner", "ops_manager"):
            try:
                db.table("notifications").insert({
                    "org_id": org_id, "user_id": u["id"], "type": "order_request_late",
                    "title": f"Order not confirmed after {CONFIRM_MINUTES} min",
                    "body": f"A customer asked to order {product} and nobody has replied yet.",
                    "resource_type": "lead", "resource_id": lead_id}).execute()
                n += 1
            except Exception:
                pass
    return n
