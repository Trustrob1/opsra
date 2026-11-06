"""
app/services/ad_question_service.py
-----------------------------------
AD-Q-1 - route the preset questions on a click-to-WhatsApp ad (Meta "ice breakers").

When someone taps one of the ad's questions, Meta sends that exact question as their first message. A business can list
those questions in organisations.ad_questions, each with what to do:
    {"question": "...", "action": "bot_catalog" | "rep", "reply": "text"}
  bot_catalog - the bot answers with `reply` plus the catalogue link; a lead is created but NOT given to a rep.
  rep         - the lead goes straight to the rep on shift, the question is saved in the chat, and the customer gets
                `reply` (if set) as a one-line acknowledgement.
Matching ignores case, punctuation and spacing. Existing customers are never intercepted. Anything that does not match
falls through to the normal flow. S14: nothing here raises into the webhook.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

ACTIONS = ("bot_catalog", "rep")


def norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def clean_rules(rules) -> list:
    """Validate what an admin saves. Raises ValueError with a plain message."""
    if rules is None:
        return []
    if not isinstance(rules, list) or len(rules) > 10:
        raise ValueError("Add up to 10 questions.")
    out = []
    for r in rules:
        q = str((r or {}).get("question") or "").strip()
        a = str((r or {}).get("action") or "").strip()
        if not q:
            continue
        if len(q) > 200:
            raise ValueError("A question is too long (200 characters at most).")
        if a not in ACTIONS:
            raise ValueError("Choose what happens for each question.")
        reply = str((r or {}).get("reply") or "").strip()
        if len(reply) > 1000:
            raise ValueError("A reply is too long (1000 characters at most).")
        out.append({"question": q, "action": a, "reply": reply})
    return out


def load_rules(db, org_id: Optional[str]) -> list:
    try:
        if not org_id:
            return []
        rows = (db.table("organisations").select("ad_questions").eq("id", org_id).limit(1).execute().data) or []
        rules = (rows[0].get("ad_questions") if rows else None) or []
        return rules if isinstance(rules, list) else []
    except Exception:
        return []


def match(rules: list, text: Optional[str]) -> Optional[dict]:
    t = norm(text)
    if not t:
        return None
    for r in rules or []:
        if norm(r.get("question")) == t:
            return r
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def handle(db, number_row: dict, sender_phone: str, contact_name: Optional[str], text: str,
           lead_id: Optional[str], msg_id: Optional[str], rule: dict) -> bool:
    """True when handled (the webhook stops), False to fall through. Never raises."""
    try:
        org_id = number_row.get("org_id")
        action = rule.get("action")
        reply = (rule.get("reply") or "").strip()
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service

        created = False
        if not lead_id:
            try:
                lead = lead_service.create_lead(
                    db=db, org_id=org_id, user_id=None, entry_path="whatsapp",
                    auto_assign=(action == "rep"),
                    payload=LeadCreate(full_name=(contact_name or "").strip() or sender_phone, phone=sender_phone,
                                       whatsapp=sender_phone, source=LeadSource.whatsapp_inbound.value,
                                       problem_stated=text[:500]))
                lead_id = lead["id"]
                created = True
            except Exception as exc:
                logger.warning("ad_question: lead create failed org=%s: %s", org_id, exc)
                return False

        try:
            db.table("whatsapp_messages").insert({
                "org_id": org_id, "lead_id": lead_id, "direction": "inbound", "message_type": "text", "channel": "whatsapp",
                "content": text, "status": "delivered", "meta_message_id": msg_id or None, "window_open": True,
                "window_expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "sent_by": None, "created_at": _now()}).execute()
        except Exception as exc:
            logger.warning("ad_question: message save failed lead=%s: %s", lead_id, exc)

        try:
            from app.services.lead_service import write_timeline_event
            write_timeline_event(db, org_id, lead_id, event_type="ad_question", actor_id=None,
                                 description=f"Asked from the ad: {text[:150]}", metadata={"action": action})
        except Exception:
            pass

        if action == "rep":
            row = (db.table("leads").select("assigned_to, ai_owned").eq("id", lead_id).limit(1).execute().data) or [{}]
            rep_id = row[0].get("assigned_to")
            if not rep_id or row[0].get("ai_owned"):
                from app.services.lead_assignment_service import auto_assign_lead
                rep_id = auto_assign_lead(db, org_id, lead_id, "ready_to_buy", None) or rep_id
            if rep_id and not created:      # a brand-new lead already notified its rep when it was assigned
                try:
                    db.table("notifications").insert({
                        "org_id": org_id, "user_id": rep_id, "type": "ad_question",
                        "title": "Customer asked a question from the ad",
                        "body": f"{contact_name or sender_phone}: {text[:140]}",
                        "resource_type": "lead", "resource_id": lead_id}).execute()
                except Exception:
                    pass
            if reply:
                from app.services import funnel_messaging
                funnel_messaging.send_text(db, org_id, number_row, sender_phone, reply, lead_id=lead_id)
            return True

        # bot_catalog: short answer + catalogue link, no rep
        from app.services import triage_service
        triage_service._action_browse_catalog(db, org_id, sender_phone, None, body=reply or None)
        return True
    except Exception as exc:
        logger.warning("ad_question.handle failed: %s", exc)
        return False
