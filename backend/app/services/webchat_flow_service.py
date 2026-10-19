"""
app/services/webchat_flow_service.py
------------------------------------
WEBCHAT-1 — the scripted chat: menu → fixed answer → link → booking form → lead + alert.

Pure Python, no model. Everything a visitor can be told comes from the org's own
settings (webchat_config), so a web chat message costs nothing but the database write.

Rules (Trust, 18 Oct 2026):
  • After the first answer the page asks for contact (name + WhatsApp number and/or email +
    consent). A visitor who came from WhatsApp already has a proven number, so only an
    optional email is asked.
  • Booking needs contact first.
  • Once a rep takes over (or the visitor taps Talk to us) the script stops answering;
    messages are stored and the team is told.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import webchat_service as wc
from app.services import webchat_ai_service
from app.services import webchat_shop_service


logger = logging.getLogger(__name__)

HUMAN_NOTIFY_EVERY_MIN = 10
MAX_TURNS_PER_SESSION = 200


def _has_contact(s: dict) -> bool:
    return bool(s.get("lead_id"))


def _match_item(cfg: dict, text: str) -> Optional[dict]:
    """Keyword / label match for typed text. First item with the most keyword hits wins; no hits → None."""
    t = f" {re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower())} "
    best, best_hits = None, 0
    for it in cfg["menu"]:
        hits = 0
        for kw in it.get("keywords") or []:
            if kw and f" {kw} " in t or (kw and len(kw) >= 4 and kw in t):
                hits += 1
        label = re.sub(r"[^a-z0-9 ]", " ", it["label"].lower()).strip()
        if label and label in t:
            hits += 2
        if hits > best_hits:
            best, best_hits = it, hits
    return best


def _answer_text(item: dict) -> str:
    text = item.get("answer") or ""
    link = item.get("link")
    if link and link.get("url"):
        text = (text + "\n" if text else "") + f"{link.get('label') or 'Open'}: {link['url']}"
    return text or "Thanks for asking."


def _notify_human(db, s: dict, cfg: dict, why: str) -> None:
    """Tell the team a visitor wants a person; at most once every 10 minutes per session."""
    state = s.get("state") or {}
    last = state.get("notified_at")
    now = datetime.now(timezone.utc)
    try:
        if last and now - datetime.fromisoformat(last) < timedelta(minutes=HUMAN_NOTIFY_EVERY_MIN):
            return
    except Exception:
        pass
    name = s.get("contact_name") or "A web chat visitor"
    wc.notify_managers(db, s["org_id"], f"{name} is waiting on web chat", why[:300], s.get("lead_id"), "webchat_message")
    wc.set_state(db, s, notified_at=now.isoformat())


def handle_message(db, s: dict, cfg: dict, *, kind: str, menu_id: Optional[str] = None,
                   text: Optional[str] = None) -> dict:
    """
    One visitor action. kind = 'menu' (tapped an option) or 'text'.
    Returns {messages, ask_contact, ask_email, form, human}; `messages` are the new messages in order
    (the visitor's own first), already stored.
    """
    if int(s.get("turn_count") or 0) >= MAX_TURNS_PER_SESSION:
        return {"messages": [wc.append_message(db, s, "bot", "This chat has reached its limit. Please use Talk to us or contact us directly.")],
                "ask_contact": False, "ask_email": False, "form": None, "human": True}

    item = None
    if kind == "menu":
        item = next((m for m in cfg["menu"] if m["id"] == menu_id), None)
        if not item:
            return {"messages": [], "ask_contact": False, "ask_email": False, "form": None, "human": wc.is_human(s, cfg)}
        visitor_text = item["label"]
    else:
        visitor_text = wc._clean_text(text, wc.MAX_TEXT)
        if not visitor_text:
            return {"messages": [], "ask_contact": False, "ask_email": False, "form": None, "human": wc.is_human(s, cfg)}

    out = [wc.append_message(db, s, "visitor", visitor_text)]
    wc.update_session(db, s, {"turn_count": int(s.get("turn_count") or 0) + 1})
    if int(s.get("turn_count") or 0) == 1:
        wc.log_event(db, s["org_id"], s["id"], "started", s.get("source"))

    state = s.get("state") or {}
    if state.get("human"):
        taps_option = kind == "menu" and item is not None and item.get("action") != "human"
        if wc.is_human(s, cfg) and not taps_option:
            _notify_human(db, s, cfg, visitor_text)
            return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True}
        wc.set_state(db, s, human=False)      # team quiet for a while, or the visitor chose an option: the bot is back

    if item is None:
        item = _match_item(cfg, visitor_text)

    form = None
    cards: list = []
    if item and item.get("action") == "human":
        wc.set_human(db, s)
        out.append(wc.append_message(db, s, "bot", cfg["human_reply"]))
        _notify_human(db, s, cfg, "Asked to talk to the team.")
        return {"messages": out, "ask_contact": not _has_contact(s), "ask_email": False, "form": None, "human": True}

    if item and item.get("action") == "booking":
        if not _has_contact(s):
            out.append(wc.append_message(db, s, "bot", "Happy to help you book. First, " + cfg["contact_prompt"][0].lower() + cfg["contact_prompt"][1:]))
            wc.set_state(db, s, pending="booking")
            return {"messages": out, "ask_contact": True, "ask_email": False, "form": None, "human": False}
        out.append(wc.append_message(db, s, "bot", "Great. Fill in the details below and we will confirm."))
        form = "booking"
    elif item:
        out.append(wc.append_message(db, s, "bot", _answer_text(item)))
        wc.set_state(db, s, answers=int(state.get("answers") or 0) + 1)
    elif kind == "text" and cfg.get("ai_enabled") and not _has_contact(s):
        # WEBCHAT-3: AI needs a contact first, so ask for one instead of the generic fallback
        out.append(wc.append_message(db, s, "bot", "Happy to help with that. First, " + cfg["contact_prompt"][0].lower() + cfg["contact_prompt"][1:]))
        wc.set_state(db, s, pending_question=visitor_text[:300])
        return {"messages": out, "ask_contact": True, "ask_email": False, "form": None, "human": False}
    else:
        ai = webchat_ai_service.answer(db, s, cfg, visitor_text) if kind == "text" else None
        if ai:
            out.append(wc.append_message(db, s, "bot", ai["reply"]))
            if cfg.get("shop_enabled") and ai.get("products"):
                cards = webchat_shop_service.cards_for(db, s["org_id"], ai["products"])
            if ai["handoff"]:
                wc.set_human(db, s)
                _notify_human(db, s, cfg, "The assistant could not answer: " + visitor_text)
                return {"messages": out, "ask_contact": False, "ask_email": False, "form": None, "human": True, "cards": cards}
        else:
            out.append(wc.append_message(db, s, "bot", cfg["fallback"]))

    state = s.get("state") or {}
    answered = int(state.get("answers") or 0) >= 1
    ask_contact = answered and not _has_contact(s)
    ask_email = (answered and _has_contact(s) and s.get("phone_verified") and not s.get("contact_email")
                 and not state.get("email_asked"))
    if ask_email:
        wc.set_state(db, s, email_asked=True)
    return {"messages": out, "ask_contact": ask_contact, "ask_email": bool(ask_email), "form": form, "human": False, "cards": cards}


def handle_contact(db, s: dict, cfg: dict, *, name, phone, email, consent: bool) -> dict:
    """Validate, create/find the lead, flush earlier messages, and carry on with anything that was waiting."""
    verified = bool(s.get("phone_verified")) and bool(s.get("lead_id"))
    clean, err = wc.validate_contact(name or s.get("contact_name"), phone or (s.get("contact_phone") if verified else None),
                                     email, consent, require_name=not verified)
    if err:
        return {"error": err}
    s = wc.save_contact(db, s, clean)
    out, form, cards = [], None, []
    pending = (s.get("state") or {}).get("pending")
    if pending == "booking":
        wc.set_state(db, s, pending=None)
        out.append(wc.append_message(db, s, "bot", "Thank you. Now tell us what you need and we will confirm."))
        form = "booking"
    else:
        out.append(wc.append_message(db, s, "bot", "Thank you. We have your details."))
        waiting = (s.get("state") or {}).get("pending_question")
        if waiting:
            wc.set_state(db, s, pending_question=None)
            ai = webchat_ai_service.answer(db, s, cfg, waiting)   # WEBCHAT-3: answer what they asked before the form
            if ai:
                out.append(wc.append_message(db, s, "bot", ai["reply"]))
                if cfg.get("shop_enabled") and ai.get("products"):
                    cards = webchat_shop_service.cards_for(db, s["org_id"], ai["products"])
                if ai["handoff"]:
                    wc.set_human(db, s)
                    _notify_human(db, s, cfg, "The assistant could not answer: " + waiting)
    return {"messages": out, "form": form, "cards": cards}


def handle_booking(db, s: dict, cfg: dict, fields: dict) -> dict:
    if not _has_contact(s):
        return {"error": "Please share your contact details first."}
    clean: dict = {}
    for f in cfg["booking_fields"]:
        v = wc._clean_text((fields or {}).get(f["key"]), 300)
        if f.get("required", True) and not v:
            return {"error": f"Please fill in: {f['label']}"}
        if v:
            clean[f["key"]] = v
    summary = "; ".join(f"{next((f['label'] for f in cfg['booking_fields'] if f['key'] == k), k)}: {v}" for k, v in clean.items())
    out = [wc.append_message(db, s, "visitor", "Booking request — " + summary)]
    try:
        from app.services import lead_service
        lead_service.write_timeline_event(db, s["org_id"], s["lead_id"], event_type="webchat_booking", actor_id=None,
                                          description="Booking request from web chat: " + summary[:500], metadata=clean)
    except Exception as exc:
        logger.warning("webchat booking timeline failed: %s", exc)
    wc.notify_managers(db, s["org_id"], f"Booking request: {s.get('contact_name') or 'web chat visitor'}", summary[:500],
                       s["lead_id"], "webchat_booking")
    wc.log_event(db, s["org_id"], s["id"], "booked", s.get("source"))
    out.append(wc.append_message(db, s, "bot", cfg["booking_done"]))
    return {"messages": out}
