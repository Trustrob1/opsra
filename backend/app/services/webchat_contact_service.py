"""
backend/app/services/webchat_contact_service.py
WEBCHAT-CONTACT-1: asking for the visitor's details inside the chat, in Chioma's voice, instead of a pop-up form.

A short fixed script (no AI is involved, so the name and number are never sent to the AI): name -> WhatsApp number
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


NAME_Q = "So the team knows who they are replying to, may I have your first name?"
PHONE_Q = "What is your WhatsApp number?"

# why the visitor needs to give details (a button they tapped) -> (what Chioma says first, what she says once they are done)
INTROS = {
    "callback": ("Happy to arrange a call back.", "Tap the call button again to ask for your call back."),
    "file": ("Happy to take your file.", "You can send your file now."),
    "voice": ("Happy to take your voice note.", "You can record your voice note now."),
    "checkout": ("Happy to get your order moving.", "Tap Cart to check out."),
}
DEFAULT_INTRO = ("", "")


_YES_LEAD = re.compile(r"^(?:y|yes|yeah|yea|yep|yup|ya|ok|okay|sure|alright|please|pls|abeg|definitely|absolutely|of course|go ahead|why not|i would|i do|i agree|agreed|fine)\b")
_NO_LEAD = re.compile(r"^(?:n|no|nope|nah|not now|no thanks|no thank you|maybe later|later|dont|do not)\b")


def is_yes(text: str) -> bool:
    """A short reply that says yes in any of the usual ways ('yes', 'yeah sure', 'ok please', 'yes I would'). Never a long message."""
    if "?" in (text or ""):
        return False
    low = re.sub(r"[^a-z ]", " ", (text or "").lower()).split()
    return 0 < len(low) <= 5 and bool(_YES_LEAD.match(" ".join(low))) and not _NO_LEAD.match(" ".join(low))


def is_no(text: str) -> bool:
    low = re.sub(r"[^a-z ]", " ", (text or "").lower()).split()
    return 0 < len(low) <= 5 and bool(_NO_LEAD.match(" ".join(low)))


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("contact_in_chat", True))


def step_of(s: dict) -> Optional[str]:
    v = (s.get("state") or {}).get("contact_step")
    return v if v in ("name", "phone", "consent") else None


def _clear(db, s: dict) -> None:
    wc.set_state(db, s, contact_step=None, contact_tries=0, contact_tmp={}, contact_optional=False, contact_after="", contact_deflected=0)


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
    return wc.append_message(db, s, "bot", f"{intro} {NAME_Q}" if intro else NAME_Q)


# Words that are never part of a person's name. Names that are also ordinary words (Will, Mark, Grace, Joy, Hope, Faith, Bill...) are
# deliberately NOT here. NOT_NAME_ALONE is checked on one-word replies; NOT_NAME_ANYWHERE on every word of a longer reply.
NOT_NAME_ANYWHERE = {
    "i", "id", "ill", "ive", "im", "we", "you", "your", "yours", "my", "our", "me", "us", "he", "she", "they", "it", "its",
    "the", "a", "an", "and", "or", "but", "if", "so", "to", "of", "in", "on", "at", "for", "with", "from", "by", "as", "about",
    "is", "are", "was", "were", "am", "be", "been", "do", "does", "did", "done", "can", "could", "would", "should", "shall", "may", "might", "must",
    "want", "wants", "wanted", "need", "needs", "needed", "like", "likes", "looking", "look", "buy", "sell", "selling", "get", "got", "give", "send",
    "have", "has", "had", "make", "making", "tell", "show", "know", "think", "see", "come", "go", "going", "call", "talk", "speak", "chat", "ask", "asking",
    "how", "what", "whats", "when", "where", "why", "which", "who", "whom", "whose", "much", "many", "any", "some", "all", "more", "less",
    "price", "prices", "cost", "costs", "pay", "payment", "order", "available", "stock", "delivery", "info", "information", "details", "help", "service", "services",
    "please", "pls", "plz", "thanks", "thank", "thx", "hello", "hi", "hey", "hiya", "yo", "yes", "yeah", "yep", "no", "nope", "nah", "ok", "okay", "sure",
    "not", "nothing", "none", "skip", "never", "mind", "anything", "something", "everything", "this", "that", "these", "those", "there", "here",
    "morning", "afternoon", "evening", "night", "good", "bad", "great", "fine", "well", "just", "only", "also", "too", "very", "really", "now", "later", "today", "tomorrow",
    "website", "websites", "phone", "phones", "product", "products", "business", "company", "team", "someone", "somebody", "person", "human", "agent", "chioma",
    "name", "names", "called", "whatsapp", "number", "email", "mail", "link", "app", "online", "store", "shop", "price", "quote", "booking", "book",
}
NOT_NAME_ALONE = NOT_NAME_ANYWHERE | {"asdf", "asdfg", "qwert", "zxcv", "hjkl", "lol", "haha", "hahaha", "test", "testing", "asdf", "qwerty", "xxx", "anonymous", "unknown", "nobody", "private", "secret", "admin"}
_TRAILING = re.compile(r"[\s,.!]+(?:here|speaking|thanks|thank you|please|pls)$", re.I)
_LEAD_FILLER = re.compile(r"^(?:(?:hi|hello|hey|hiya|good\s+(?:morning|afternoon|evening))\b[\s,.!:-]*)+", re.I)
_LEAD_IN2 = re.compile(r"^(?:(?:you\s+can|they|people|everyone|everybody)\s+call\s+me|the\s+name\s+is|my\s+names?\s+is|my\s+name's|my\s+name\s+is|name\s+is|name's|names|i\s+am|i'm|i\s+m|im|this\s+is|it\s+is|it's|its|call\s+me|am)\s+", re.I)
_NAME_WORD = re.compile(r"^[^\W\d_]+(?:['\u2019.-][^\W\d_]+)*\.?$", re.UNICODE)      # letters (any language), with ' - . inside
QUESTION_STARTERS = {"what", "whats", "how", "do", "does", "did", "can", "could", "would", "will", "is", "are", "where", "when", "why", "which", "who",
                     "price", "much", "any", "tell", "show", "i", "we", "please", "pls", "i'd", "i'll", "ill", "id"}


def _clean_name(text: str) -> Optional[str]:
    """The visitor's first name from a free-typed reply, or None when the reply is not a name (a question, a greeting, a sentence,
    a number, an address, a link, an emoji, junk). Stripping 'my name is', 'hi, I am' and a trailing 'here/speaking' is allowed."""
    raw = wc._clean_text(text, 80)
    if not raw or "?" in raw or "@" in raw or re.search(r"https?:|www\.|\.(?:com|ng|org|net|co)\b", raw, re.I):
        return None
    name = raw
    for _ in range(3):                                           # 'hi, my name is Ada' -> 'Ada'
        before = name
        name = _LEAD_FILLER.sub("", name).strip()
        name = _LEAD_IN2.sub("", name).strip()
        name = _TRAILING.sub("", name).strip(" .,!;:-")
        if name == before:
            break
    words = name.replace(",", " ").split()
    if not words or len(words) > 4 or len(name) < 2 or len(name) > 60:
        return None
    for w in words:
        if (not _NAME_WORD.match(w) or len(w.strip(".")) > 24 or re.search(r"(.)\1{3,}", w.lower())
                or re.fullmatch(r"(.{3,5})\1+", w.strip(".").lower())):          # 'aaaa', 'asdfasdf', 'abcabc': keyboard mashing
            return None
    low = [w.strip(".").lower() for w in words]
    if len(words) == 1:
        if low[0] in NOT_NAME_ALONE or len(low[0]) < 2:
            return None
    else:
        if any(w in NOT_NAME_ANYWHERE for w in low) or any(len(w) < 2 and not w.endswith(".") for w in words):
            return None
    fixed = [w if (not w.islower() and not w.isupper()) else w.capitalize() for w in words]         # keep McDonald; fix 'ada' and 'ADA'
    return " ".join(fixed)


def looks_like_question(text: str) -> bool:
    """True when a reply that is not a name reads as a real question or request (so the visitor deserves an answer, not a second ask)."""
    t = (text or "").strip()
    words = re.sub(r"[^\w\s'\u2019]", " ", t.lower()).split()
    return bool(t) and ("?" in t or len(words) >= 4 or (bool(words) and words[0] in QUESTION_STARTERS and len(words) >= 2))


def drops_quietly(s: dict, text: str) -> bool:
    """True when the gentle ask is open, the visitor has not answered it with a name, and so the message is handled normally."""
    return step_of(s) == "name" and bool((s.get("state") or {}).get("contact_optional")) and _clean_name(text) is None


def can_deflect(s: dict, text: str) -> bool:
    """The REQUIRED ask is open (a person was asked for details so the team can help) and the visitor typed a real question instead of
    an answer: it deserves an answer first, then the ask once more. Only once per ask; after that a wrong reply counts as a failed try."""
    st = s.get("state") or {}
    cur = step_of(s)
    if not cur or st.get("contact_optional") or int(st.get("contact_deflected") or 0) >= 1:
        return False
    if cur == "name":
        return _clean_name(text) is None and looks_like_question(text)
    if cur == "phone":
        return wc.normalise_phone((text or "").strip()) is None and looks_like_question(text)
    return not is_yes(text) and not is_no(text) and looks_like_question(text)


def reask(db, s: dict, cfg: dict) -> Optional[dict]:
    """After a deflected question has been answered: say the open step's question again (once), keeping the script open."""
    cur = step_of(s)
    if not cur:
        return None
    wc.set_state(db, s, contact_deflected=1, contact_tries=0)
    if cur == "name":
        q = "Now, " + NAME_Q[0].lower() + NAME_Q[1:]
    elif cur == "phone":
        q = "Now, " + PHONE_Q[0].lower() + PHONE_Q[1:]
    else:
        tmp = (s.get("state") or {}).get("contact_tmp") or {}
        ph = tmp.get("phone") or ""
        q = f"Back to your details: is it okay for {cfg.get('business_name') or 'the team'} to contact you on the number ending {ph[-3:]} about your enquiry?"
    return wc.append_message(db, s, "bot", q)


def shown_text(s: dict, text: str) -> str:
    """What is stored in the transcript for the visitor's reply: the number or email is never kept in the chat text."""
    if step_of(s) != "phone":
        return text
    t = (text or "").strip()
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
            return fail("Sorry, I did not catch a first name there. What should I call you?")
        tmp["name"] = name
        wc.set_state(db, s, contact_step="phone", contact_tmp=tmp, contact_tries=0)
        say(f"Nice to meet you, {_first(name)}. {PHONE_Q}")
        return reply()

    if cur == "phone":
        phone = wc.normalise_phone(t)
        if not phone:
            return fail("That number does not look right. Please send your WhatsApp number, like 0803 123 4567.")
        tmp["phone"], tmp["email"], shown = phone, None, f"the number ending {phone[-3:]}"
        wc.set_state(db, s, contact_step="consent", contact_tmp=tmp, contact_tries=0)
        say(f"Thank you. Is it okay for {cfg.get('business_name') or 'the team'} to contact you on {shown} about your enquiry?")
        return reply(choices=[{"id": "say", "label": "Yes"}, {"id": "say", "label": "No"}])

    if cur == "consent":
        if is_no(t):
            _clear(db, s)
            say("No problem, I will not keep your details. You can still tap Menu, or ask me anything and I will share what I can."
                if cfg.get("ai_enabled") else "No problem, I will not keep your details. You can still tap Menu to see what I can help with.")
            return reply(contact_step=None)
        if is_yes(t):
            res = finish(db, s, cfg, name=tmp.get("name"), phone=tmp.get("phone"), email=tmp.get("email"), consent=True)
            if res.get("error"):
                _clear(db, s)
                say("Let us finish this with a short form instead.")
                return reply(ask_contact=True, contact_step=None)
            _clear(db, s)
            return reply(messages=out + (res.get("messages") or []), form=res.get("form"), cards=res.get("cards") or [], contact_step=None,
                         **({"choices": res["choices"]} if res.get("choices") else {}))
        n = tries + 1
        if n >= MAX_TRIES:
            return fail("Please reply Yes or No.")
        wc.set_state(db, s, contact_tries=n)
        say("Sorry, I need a yes or no here.")
        return reply(choices=[{"id": "say", "label": "Yes"}, {"id": "say", "label": "No"}])

    return reply(contact_step=None)
