"""
backend/app/services/webchat_contact_service.py
WEBCHAT-CONTACT-1: asking for the visitor's details inside the chat, in Chioma's voice, instead of a pop-up form.

A short fixed script (no AI is involved, so the name and number are never sent to the AI): name -> WhatsApp number (or email)
-> a Yes / No consent question -> the same handle_contact the form uses (lead creation, consent record, the waiting question
answered). Rules that keep it safe:
  - the number is checked with the same normaliser the form uses; the visitor's number is shown in the transcript only as
    its last 3 digits, so it never sits in the chat text the AI reads;
  - two failed tries on any step hands over to the short form, so nobody gets stuck;
  - tapping a menu option abandons the script (the visitor moved on);
  - consent needs an explicit Yes; anything else is asked again, and No ends it politely.
State lives in session.state: contact_step ('name' | 'phone' | 'consent'), contact_tries, contact_tmp.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

MAX_TRIES = 2
_YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "fine", "alright", "please", "go ahead", "yes please", "of course", "i agree", "agreed"}
_NO = {"no", "n", "nope", "nah", "no thanks", "no thank you", "dont", "do not", "not now"}
_LEAD_IN = re.compile(r"^(?:my name is|my name's|name is|i am|i'm|im|this is|it is|it's|its|call me)\s+", re.I)
_QUESTION_WORDS = {"what", "how", "do", "does", "can", "is", "are", "where", "when", "why", "which", "who", "price", "much"}


# why the visitor needs to give details (a button they tapped) -> (what Chioma says first, what she says once they are done)
INTROS = {
    "callback": ("I will need a couple of details before the team can call you back.", "Tap the call button again to ask for your call back."),
    "file": ("I just need a couple of details before you send a file.", "You can send your file now."),
    "voice": ("I just need a couple of details before you send a voice note.", "You can record your voice note now."),
    "checkout": ("I just need a couple of details first, so we can confirm your order.", "Tap Cart to check out."),
}
DEFAULT_INTRO = ("I just need a couple of details first.", "")


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("contact_in_chat", True))


def step_of(s: dict) -> Optional[str]:
    v = (s.get("state") or {}).get("contact_step")
    return v if v in ("name", "phone", "consent") else None


def _clear(db, s: dict) -> None:
    wc.set_state(db, s, contact_step=None, contact_tries=0, contact_tmp={}, contact_optional=False, contact_after="")


def start_for(db, s: dict, cfg: dict, why: str) -> dict:
    """The visitor tapped something that needs their details (call back, file, voice note, check out): ask in the chat."""
    intro, after = INTROS.get(why, DEFAULT_INTRO)
    msg = start(db, s, cfg, intro)
    wc.set_state(db, s, contact_after=after)
    return msg


def start(db, s: dict, cfg: dict, intro: str, optional: bool = False) -> dict:
    """Open the script with one bot message; returns that message. optional=True is the gentle ask after a first answer:
    if the visitor carries on with something else instead of giving a name, the script drops quietly."""
    wc.set_state(db, s, contact_step="name", contact_tries=0, contact_tmp={}, contact_optional=optional)
    return wc.append_message(db, s, "bot", f"{intro} What name should I use?")


def _clean_name(text: str) -> Optional[str]:
    name = _LEAD_IN.sub("", wc._clean_text(text, 80)).strip(" .,!")
    words = name.split()
    if (len(name) < 2 or "?" in name or "@" in name or any(c.isdigit() for c in name) or len(words) > 4
            or (words and words[0].lower() in _QUESTION_WORDS)):
        return None
    return name


def drops_quietly(s: dict, text: str) -> bool:
    """True when the gentle ask is open, the visitor has not answered it with a name, and so the message is handled normally."""
    return step_of(s) == "name" and bool((s.get("state") or {}).get("contact_optional")) and _clean_name(text) is None


def shown_text(s: dict, text: str) -> str:
    """What is stored in the transcript for the visitor's reply: the number or email is never kept in the chat text."""
    if step_of(s) != "phone":
        return text
    t = (text or "").strip()
    if "@" in t:
        return "My email address"
    d = re.sub(r"\D", "", t)
    return f"My WhatsApp number (ends {d[-3:]})" if len(d) >= 3 else text


def _first(name: str) -> str:
    return (name or "").split(" ")[0][:30]


def step(db, s: dict, cfg: dict, text: str, finish: Callable[..., dict]) -> dict:
    """Handle one typed reply while the script is open. Returns {'messages', 'ask_contact', 'form', 'cards', 'contact_step'}."""
    st = s.get("state") or {}
    cur = step_of(s)
    tmp = dict(st.get("contact_tmp") or {})
    tries = int(st.get("contact_tries") or 0)
    out: list = []

    def say(t: str) -> None:
        out.append(wc.append_message(db, s, "bot", t))

    def reply(**extra) -> dict:
        base = {"messages": out, "ask_contact": False, "form": None, "cards": [], "contact_step": step_of(s)}
        base.update(extra)
        return base

    def fail(msg: str) -> dict:
        n = tries + 1
        if n >= MAX_TRIES:
            _clear(db, s)
            say("Let us do this with a short form instead.")
            return reply(ask_contact=True, contact_step=None)
        wc.set_state(db, s, contact_tries=n)
        say(msg)
        return reply()

    t = (text or "").strip()
    if cur == "name":
        name = _clean_name(t)
        if not name:
            return fail("I did not catch a name there. What should I call you?")
        tmp["name"] = name
        wc.set_state(db, s, contact_step="phone", contact_tmp=tmp, contact_tries=0)
        say(f"Nice to meet you, {_first(name)}. What is your WhatsApp number? You can give an email instead.")
        return reply()

    if cur == "phone":
        if "@" in t:
            email = t.lower().strip(" .,")
            if not wc._EMAIL_RE.match(email):
                return fail("That email does not look right. Please check it, or send your WhatsApp number instead.")
            tmp["email"], tmp["phone"], shown = email, None, "that email"
        else:
            phone = wc.normalise_phone(t)
            if not phone:
                return fail("That number does not look right. Please send it like 0803 123 4567, or give an email instead.")
            tmp["phone"], tmp["email"], shown = phone, None, f"the number ending {phone[-3:]}"
        wc.set_state(db, s, contact_step="consent", contact_tmp=tmp, contact_tries=0)
        say(f"Thank you. Is it okay for {cfg.get('business_name') or 'the team'} to contact you on {shown} about your enquiry? Reply Yes or No.")
        return reply()

    if cur == "consent":
        low = re.sub(r"[^a-z ]", "", t.lower()).strip()
        if low in _NO or low.startswith("no "):
            _clear(db, s)
            say("No problem, I will not keep your details. You can still tap Menu, or ask me anything and I will share what I can.")
            return reply(contact_step=None)
        if low in _YES or low.startswith("yes"):
            res = finish(db, s, cfg, name=tmp.get("name"), phone=tmp.get("phone"), email=tmp.get("email"), consent=True)
            if res.get("error"):
                _clear(db, s)
                say("Let us finish this with a short form instead.")
                return reply(ask_contact=True, contact_step=None)
            _clear(db, s)
            return reply(messages=out + (res.get("messages") or []), form=res.get("form"), cards=res.get("cards") or [], contact_step=None)
        return fail("Please reply Yes or No.")

    return reply(contact_step=None)
