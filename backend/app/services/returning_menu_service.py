"""
backend/app/services/returning_menu_service.py
RETURN-MENU-1 - show the WhatsApp menu again to leads and customers who already exist.

Before this, only a brand-new number ever saw the menu. A known lead who said "hi" (or asked something the knowledge base could not
answer) just got "a team member will contact you", and a customer got nothing.

Which menu a returning contact sees (first one that has items wins):
  lead     : returning_contact_menu  ->  the original ("unknown") menu
  customer : known_customer_menu     ->  customer menu  ->  the original menu
When it shows: a greeting / "menu" / "help", or when the knowledge base had no answer (the team is still told, as before).
When it does not: the org switched it off (organisations.returning_menu_enabled), the plan has no WhatsApp menu, a team member replied in
the last 24 hours (never interrupt a live chat), the contact is already mid-way through another WhatsApp flow, or AI is paused.
A "book" item is only offered while the org has booking set up (plan feature, Online booking on, at least one open service).
Taps are handled by the existing menu handlers; only "book" is new (opens the WhatsApp time picker).
S14: nothing here raises.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MENU_WORDS = {
    "menu", "help", "options", "start", "main menu", "hi", "hello", "hey", "hiya", "hola", "yo", "good morning", "good afternoon",
    "good evening", "good day", "morning", "afternoon", "evening", "hi there", "hello there", "hey there",
}
_GREETERS = {"hi", "hello", "hey", "hiya", "hola", "morning", "afternoon", "evening"}

# menu key -> section name understood by triage_service.handle_session_message
_SECTION = {"returning_contact_menu": "returning_lead", "known_customer_menu": "known_customer", "unknown": "unknown", "customer": "customer"}
_ORDER = {"lead": ("returning_contact_menu", "unknown"), "customer": ("known_customer_menu", "customer", "unknown")}


def is_menu_request(content: Optional[str]) -> bool:
    """A bare greeting or an ask for the menu. 'Hello, I want a refund' is a real message, not a menu request."""
    words = re.sub(r"[^a-z0-9' ]", " ", (content or "").lower()).split()
    if not words:
        return False
    if " ".join(words) in _MENU_WORDS:
        return True
    return len(words) <= 3 and words[0] in _GREETERS and "?" not in (content or "")


def _org(db, org_id: str) -> dict:
    rows = (db.table("organisations").select("whatsapp_triage_config, returning_menu_enabled").eq("id", org_id).limit(1).execute().data or [])
    return rows[0] if rows else {}


def booking_available(db, org_id: str) -> bool:
    try:
        from app.services import plan_gate_service
        from app.services import booking_service as bk
        if not plan_gate_service.allowed(db, org_id, "selling_booking"):
            return False
        if not bk.get_settings(db, org_id).get("native_enabled"):
            return False
        return bool(bk.list_services(db, org_id, active_only=True))
    except Exception:
        return False


def pick_menu(db, org_id: str, cfg: dict, kind: str) -> tuple[Optional[str], list, dict]:
    """(menu key, usable items, menu config). Items needing booking are dropped when booking is not set up."""
    book_ok = None
    for key in _ORDER.get(kind, ("unknown",)):
        section = cfg.get(key) or {}
        items = [i for i in (section.get("items") or []) if i.get("id") and i.get("label")]
        if any(i.get("action") == "book" for i in items):
            if book_ok is None:
                book_ok = booking_available(db, org_id)
            if not book_ok:
                items = [i for i in items if i.get("action") != "book"]
        if items:
            return key, items[:10], section
    return None, [], {}


def _rep_replied_recently(db, org_id: str, lead_id: Optional[str], customer_id: Optional[str]) -> bool:
    try:
        col, val = ("lead_id", lead_id) if lead_id else ("customer_id", customer_id)
        if not val:
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = (db.table("whatsapp_messages").select("id").eq("org_id", org_id).eq(col, val).eq("direction", "outbound")
                .not_.is_("sent_by", "null").gte("created_at", cutoff).limit(1).execute().data or [])
        return bool(rows)
    except Exception:
        return False


def show(db, org_id: str, phone: str, contact_name: Optional[str], kind: str, lead_id: Optional[str] = None,
         customer_id: Optional[str] = None, prefix: Optional[str] = None) -> bool:
    """Send the returning-contact menu. True only if it was actually sent."""
    try:
        from app.services import triage_service, wa_plan_service
        from app.services.whatsapp_service import _call_meta_send, _get_org_wa_credentials, _personalise_greeting
        org = _org(db, org_id)
        if not org.get("returning_menu_enabled", True) or not wa_plan_service.menu_on(db, org_id):
            return False
        if _rep_replied_recently(db, org_id, lead_id, customer_id):
            return False
        existing = triage_service.get_active_session(db, org_id, phone)
        if existing and (existing.get("session_state") or "") != "triage_sent":
            return False            # mid-way through another flow (qualification, purchase, ticket ...)
        key, items, section = pick_menu(db, org_id, org.get("whatsapp_triage_config") or {}, kind)
        if not key:
            return False
        phone_id, token, _ = _get_org_wa_credentials(db, org_id)
        if not (phone_id or "").strip() or not token:
            return False
        greeting = _personalise_greeting(section.get("greeting") or "How can we help you today?", contact_name)
        body = f"{prefix.strip()}\n\n{greeting}" if prefix else greeting
        payload = {
            "messaging_product": "whatsapp", "to": phone, "type": "interactive",
            "interactive": {"type": "list", "body": {"text": body[:1024]},
                            "action": {"button": "See options", "sections": [{
                                "title": (section.get("section_title") or "Choose an option")[:24],
                                "rows": [{"id": i["id"], "title": i["label"][:24], "description": (i.get("description") or "")[:72]} for i in items]}]}},
        }
        _call_meta_send(phone_id.strip(), payload, token=token)
        now = datetime.now(timezone.utc)
        try:
            row = {"org_id": org_id, "direction": "outbound", "message_type": "interactive", "content": f"[Menu] {body[:200]}", "status": "sent",
                   "window_open": True, "window_expires_at": (now + timedelta(hours=24)).isoformat(), "sent_by": None, "created_at": now.isoformat()}
            row["lead_id" if lead_id else "customer_id"] = lead_id or customer_id
            db.table("whatsapp_messages").insert(row).execute()
        except Exception as exc:
            logger.warning("returning menu: message save failed: %s", exc)
        sess = triage_service.get_or_create_session(db, org_id, phone, customer_id=customer_id)
        if sess:
            data = dict(sess.get("session_data") or {})
            data["returning_menu"] = key
            if customer_id:
                data["customer_id"] = customer_id
            triage_service.update_session(db, sess["id"], "triage_sent", session_data=data)
        return True
    except Exception as exc:
        logger.warning("returning menu show failed org=%s: %s", org_id, exc)
        return False


def section_for(session: Optional[dict], default: str) -> str:
    """The section name the existing menu handler should use for a tap on a menu we sent."""
    key = ((session or {}).get("session_data") or {}).get("returning_menu")
    return _SECTION.get(key, default)


def run_book_action(db, org_id: str, phone: str, session_id: str) -> None:
    """A menu item with action 'book' was tapped: open the WhatsApp time picker, or hand over to the team if booking is not available."""
    try:
        from app.services import triage_service, booking_wa_service
        from app.services.whatsapp_service import _call_meta_send, _get_org_wa_credentials
        triage_service.update_session(db, session_id, "active", selected_action="book", expected_state="triage_sent")
        lead_id = _lead_for_phone(db, org_id, phone)
        started = {}
        if lead_id and booking_available(db, org_id):
            started = booking_wa_service.start_picker(db, org_id, lead_id)
        if not started.get("started") and not started.get("fallback"):
            phone_id, token, _ = _get_org_wa_credentials(db, org_id)
            if (phone_id or "").strip() and token:
                _call_meta_send(phone_id.strip(), {"messaging_product": "whatsapp", "to": phone, "type": "text",
                                                   "text": {"body": "Thanks! Booking isn't available right now, so a member of our team will help you arrange a time."}}, token=token)
    except Exception as exc:
        logger.warning("returning menu book action failed org=%s: %s", org_id, exc)


def _lead_for_phone(db, org_id: str, phone: str) -> Optional[str]:
    for col in ("whatsapp", "phone"):
        rows = (db.table("leads").select("id").eq("org_id", org_id).eq(col, phone).is_("deleted_at", "null").order("created_at", desc=True).limit(1).execute().data or [])
        if rows:
            return rows[0]["id"]
    return None
