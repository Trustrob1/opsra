"""
app/services/webchat_handover_service.py
----------------------------------------
ONLY-1c-DOWN: what a visitor is told, and offered, when Chioma has no answer (AI off, API error, no credit, rate limit,
plan allowance used up, unreadable reply). Pure functions plus one email helper. No AI, no credit.

The visitor always gets a way forward:
  * inside the business's hours: open the menu, chat with the team now, or call;
  * after hours: open the menu, leave a message (the team replies when back), or ask for a call back.
A business that wrote its own fallback / hand-over wording keeps it (it still gets the buttons).

`choices` are sent to the chat page with the reply: [{"id": "menu" | "human" | "call", "label": "..."}].
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

TEAM_OPEN, TEAM_CLOSED, TEAM_UNKNOWN = "open", "closed", "unknown"


def team_state(cfg: dict) -> tuple[str, str]:
    """(state, reopens in words). 'unknown' when the business has set no hours at all. Never raises."""
    try:
        from app.services import webchat_call_service as call
        org = cfg.get("_call_org") or {}
        st = call.open_state(org.get("business_hours"), org.get("timezone"))
        if st.get("no_hours"):
            return TEAM_UNKNOWN, ""
        if st.get("open"):
            return TEAM_OPEN, ""
        return TEAM_CLOSED, (call._opens_words(st.get("opens_at"), org.get("timezone")) if st.get("opens_at") else "")
    except Exception as exc:
        logger.warning("handover team_state failed: %s", exc)
        return TEAM_UNKNOWN, ""


def _call_on(cfg: dict) -> bool:
    try:
        from app.services import webchat_call_service as call
        return bool(call.status(cfg))
    except Exception:
        return False


def _has_human_item(cfg: dict) -> bool:
    return any(m.get("action") == "human" for m in (cfg.get("menu") or []))


def team_choice(cfg: dict) -> Optional[dict]:
    """The button that reaches a person: Talk to the team inside hours, Leave a message after hours. None when the menu has no team item."""
    if not _has_human_item(cfg):
        return None
    state, _ = team_state(cfg)
    return {"id": "human", "label": "Leave a message" if state == TEAM_CLOSED else "Talk to the team"}


_MENTIONS_TEAM = re.compile(r"\b(?:talk to (?:the )?team|talk to us|leave a message|speak (?:to|with) (?:the )?team)\b", re.I)
_MENTIONS_MENU = re.compile(r"\b(?:tap|press|click|open|use|select)\b[^.!?]{0,30}\bmenu\b", re.I)


def reply_choices(cfg: dict, reply: str, offer_team: bool = False) -> list:
    """Buttons to show under an AI reply. Chioma cannot see the screen, so any button she names (or the team, when she offers it) is put
    on screen with the reply: she never points at something the visitor cannot find."""
    out: list = []
    if _MENTIONS_MENU.search(reply or "") and cfg.get("menu"):
        out.append({"id": "menu", "label": "Open menu"})
    if offer_team or _MENTIONS_TEAM.search(reply or ""):
        t = team_choice(cfg)
        if t:
            out.append(t)
    return out


_WHERE_TEAM = re.compile(
    r"\b(?:where|how)\b[^.?!]{0,30}\b(?:tap|click|press|find|see|get to|reach|open|use|locate)\b[^.?!]{0,40}\b(?:talk to (?:the |a )?team|talk to us|the team button|team button|the team)\b", re.I)


_WHERE_IS_TEAM_BUTTON = re.compile(r"\b(?:where|how)\b[^.?!]{0,25}\b(?:is|are)\b[^.?!]{0,15}\b(?:talk to (?:the )?team|talk to us|(?:the )?team button|(?:the )?talk button)\b", re.I)


def asks_where_team(text: str) -> bool:
    """'Where do I tap Talk to the team?' is a question about the screen, not a request to hand over."""
    return bool(_WHERE_TEAM.search(text or "") or _WHERE_IS_TEAM_BUTTON.search(text or ""))


def where_team(cfg: dict) -> Optional[dict]:
    """{'text', 'choices'}: point the visitor at the button by showing it. None when there is no team item in the menu."""
    t = team_choice(cfg)
    if not t:
        return None
    state, reopens = team_state(cfg)
    if state == TEAM_CLOSED:
        away = f" until {reopens}" if reopens else ""
        text = f"The team is away{away}, but you can leave them a message with the button below and they will reply here."
    else:
        text = "Here it is: tap the button below to chat with the team. You will also always find it as the first option in the Menu."
    choices = [t]
    if cfg.get("menu"):
        choices.insert(0, {"id": "menu", "label": "Open menu"})
    return {"text": text, "choices": choices}


def no_answer(cfg: dict) -> dict:
    """{'text', 'choices'} for a visitor Chioma cannot answer. Never raises."""
    state, reopens = team_state(cfg)
    call_on = _call_on(cfg)
    team_here = state == TEAM_OPEN
    custom = (cfg.get("fallback") or "").strip() and cfg.get("fallback") != wc.DEFAULT_CONFIG["fallback"]

    if custom:
        text = cfg["fallback"]
    elif team_here:
        text = ("I am unable to answer that at the moment. Please tap Menu to see the available options, tap Talk to the team to chat with someone now"
                + (", or tap Call us." if call_on else "."))
        if not call_on:
            text = ("I am unable to answer that at the moment. Please tap Menu to see the available options, "
                    "or tap Talk to the team to chat with someone now.")
    else:
        away = f" and our team is away until {reopens}" if reopens else ""
        back = "when they are back" if reopens else "as soon as they can"
        text = (f"I am unable to answer that at the moment{away}. Please tap Menu to see the available options, "
                f"or tap Leave a message and the team will reply {back}."
                + (" You can also tap Request a call back." if call_on else ""))

    choices = []
    if cfg.get("menu"):
        choices.append({"id": "menu", "label": "Open menu"})
    if _has_human_item(cfg):
        choices.append({"id": "human", "label": "Talk to the team" if team_here else "Leave a message"})
    if call_on:
        choices.append({"id": "call", "label": "Call us" if team_here else "Request a call back"})
    return {"text": text, "choices": choices}


def human_reply(cfg: dict) -> str:
    """The confirmation after a visitor taps Talk to the team / Leave a message. Custom wording is kept."""
    stock = wc.DEFAULT_CONFIG["human_reply"]
    mine = cfg.get("human_reply") or stock
    if mine != stock:
        return mine
    state, reopens = team_state(cfg)
    if state == TEAM_CLOSED and reopens:
        return f"Thanks. Our team is away until {reopens}. Your message is saved, and they will reply here when they are back."
    return stock


def email_owner(db, s: dict, cfg: dict, why: str) -> int:
    """Email the business owner(s) that a visitor is waiting. Returns how many were sent. Never raises.
    The caller (flow._notify_human) already limits this to once per 10 minutes per chat."""
    sent = 0
    try:
        from app.services import chat_pause_service as pause
        from app.services import site_addon_billing_service as sab
        who = s.get("contact_name") or "A web chat visitor"
        reach = " / ".join(x for x in (s.get("contact_phone"), s.get("contact_email")) if x) or "not shared yet"
        state, reopens = team_state(cfg)
        when = {"open": "Your team is inside business hours now.", "closed": "Your team is outside business hours" + (f" until {reopens}." if reopens else "."),
                "unknown": ""}[state]
        text = (f"{who} is waiting on your web chat.\n\nTheir message: {why[:500]}\n\nHow to reach them: {reach}\n{when}\n\n"
                "Open Opsra and go to Conversations to reply. They will see your answer in the chat.")
        for email in pause._owner_emails(db, s["org_id"]):
            if sab._send_email(email, f"{who} is waiting on your web chat", text):
                sent += 1
    except Exception as exc:
        logger.warning("handover email_owner failed org=%s: %s", s.get("org_id"), exc)
    return sent
