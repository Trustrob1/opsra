"""
app/services/webchat_greeting_service.py
----------------------------------------
WEB-ONLY-1c-GREET - Chioma answers greetings, thanks and goodbyes herself, warmly, with no AI call and no credit.

A message counts only when ALL of it is a greeting, a thank-you or a goodbye (plus filler such as "o", "please", "ma", or the
business's own name). "Hi, how much is a website?" is a question, so it goes on to the normal flow (the AI is told to greet back).

Understands English, Nigerian Pidgin, Yoruba, Igbo, Hausa and salaam greetings, in any spelling (tone marks and stretched
letters are ignored: "Heyyy", "Ẹ káàárọ̀", "how you dey"). Pure functions: nothing here touches the database.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

LAGOS = ZoneInfo("Africa/Lagos")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))          # tone marks and dots: ẹ -> e, ọ -> o
    t = t.replace("'", "").replace("’", "")                        # what's -> whats
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"([a-z0-9])\1+", r"\1", t)                              # heyyy -> hey, hello -> helo (the tables are folded the same way)
    return " ".join(t.split())


# phrase -> tag. Folded with _norm below, so write them normally.
_GREET = {
    "hi": "", "hello": "", "hey": "", "hiya": "", "howdy": "", "yo": "", "hola": "", "hallo": "", "greetings": "", "sup": "",
    "wassup": "", "whats up": "", "what is up": "", "wats up": "", "bonjour": "", "salut": "", "hi there": "", "hello there": "",
    "hey there": "",
    "good morning": "morning", "morning": "morning", "gm": "morning", "good afternoon": "afternoon", "afternoon": "afternoon",
    "good evening": "evening", "evening": "evening", "good day": "",
    "how are you": "how", "how are you doing": "how", "how are you today": "how", "how r u": "how", "how are u": "how",
    "how are things": "how", "how is it going": "how", "hows it going": "how", "how do you do": "how", "how is your day": "how",
    "how was your day": "how", "how have you been": "how", "hope you are well": "how", "hope you are doing well": "how",
    "nice to meet you": "", "pleased to meet you": "", "good to meet you": "",
    # Pidgin
    "how far": "pidgin", "how far na": "pidgin", "how body": "pidgin", "body dey": "pidgin", "how you dey": "pidgin",
    "how una dey": "pidgin", "how e dey": "pidgin", "how e dey go": "pidgin", "how things": "pidgin", "wetin dey": "pidgin",
    "wetin dey happen": "pidgin", "how market": "pidgin", "how market dey": "pidgin", "i dey greet": "pidgin",
    "i dey greet you": "pidgin", "i greet you": "pidgin", "how family": "pidgin", "how work": "pidgin", "how the day": "pidgin",
    # Yoruba
    "e kaaro": "yoruba morning", "ekaaro": "yoruba morning", "e kaasan": "yoruba afternoon", "ekaasan": "yoruba afternoon",
    "e kaale": "yoruba evening", "ekaale": "yoruba evening", "bawo": "yoruba", "bawo ni": "yoruba", "bawo ni o": "yoruba",
    "e kabo": "yoruba", "ekabo": "yoruba", "pele": "yoruba", "e pele": "yoruba", "e n le": "yoruba",
    # Igbo
    # ("nnoo" folds to "no", so it is not listed)
    "ndewo": "igbo", "kedu": "igbo", "kedu ka i mere": "igbo how", "kedu ka i di": "igbo how", "kedu ka ihe di": "igbo",
    "ututu oma": "igbo morning", "ehihie oma": "igbo afternoon", "mgbede oma": "igbo evening",
    # Hausa
    "sannu": "hausa", "sannu da zuwa": "hausa", "ina kwana": "hausa morning", "ina wuni": "hausa afternoon", "ina kwanan ku": "hausa",
    "barka": "hausa", "barka da safiya": "hausa morning", "barka da rana": "hausa afternoon", "barka da yamma": "hausa evening",
    "lafiya": "hausa", "lafiya lau": "hausa", "kina lafiya": "hausa how", "kana lafiya": "hausa how", "yaya dai": "hausa",
    # salaam and others
    "salam": "salam", "salaam": "salam", "assalamu alaikum": "salam", "assalamualaikum": "salam", "asalam alaykum": "salam",
    "assalamu alaykum": "salam", "as salamu alaykum": "salam", "peace be upon you": "salam", "shalom": "",
    "assalamu alaikum warahmatullahi wabarakatuh": "salam",
}
_THANKS = [
    "thanks", "thank you", "thank u", "thanks a lot", "thanks so much", "thank you so much", "thank you very much", "thx", "tnx",
    "tanks", "thank", "i appreciate", "i appreciate it", "appreciate it", "appreciate", "much appreciated", "nice one", "well done",
    "weldone", "you try", "una try", "god bless you", "god bless", "bless you", "oshe", "e se", "ese", "daalu", "dalu", "nagode",
    "na gode", "jazakallah", "jazakallahu khairan", "i don hear",
]
_BYE = {
    "bye": "", "goodbye": "", "good bye": "", "bye bye": "", "see you": "", "see you later": "", "see you soon": "",
    "see you tomorrow": "", "see ya": "", "later": "", "catch you later": "", "talk later": "", "talk to you later": "", "ttyl": "",
    "take care": "", "have a good day": "", "have a nice day": "", "have a great day": "", "have a blessed day": "",
    "good night": "night", "goodnight": "night", "gn": "night", "nite": "night", "night": "night", "have a good night": "night",
    "have a nice evening": "", "i am leaving": "", "i am going": "", "i am off": "", "gotta go": "", "got to go": "",
    "i have to go": "", "i must go": "", "cheers": "", "peace out": "", "stay safe": "", "stay blessed": "", "safe journey": "",
    # Pidgin
    "i dey go": "pidgin", "i go go": "pidgin", "make i go": "pidgin", "i go reach you": "pidgin", "i go come back": "pidgin",
    "i go see you": "pidgin", "e don do": "pidgin", "i don go": "pidgin", "make we talk later": "pidgin", "we go talk": "pidgin",
    # Yoruba, Igbo, Hausa
    "o dabo": "", "odabo": "", "ka chi bo": "", "kachi bo": "", "sai an jima": "", "sai gobe": "", "sai anjima": "",
    "ka kwana lafiya": "night",
}
# words that may sit around a greeting, thanks or goodbye without turning it into a question
_FILLER = {"o", "oh", "ah", "there", "please", "pls", "plz", "abeg", "everyone", "everybody", "sir", "ma", "madam", "maam", "mam",
           "oga", "boss", "chioma", "team", "guys", "people", "dear", "na", "sha", "again", "friend", "bros", "bro", "sis", "aunty",
           "uncle", "chief", "fam", "oya"}
_ACK = {"ok", "okay", "alright", "cool", "great", "nice", "sure", "noted", "sharp", "wahala"}     # allowed only around thanks / goodbye

_TABLE: dict[tuple, tuple] = {}      # token tuple -> (category, tags)
for _p, _tag in _GREET.items():
    _TABLE[tuple(_norm(_p).split())] = ("greet", set(_tag.split()))
for _p in _THANKS:
    _TABLE.setdefault(tuple(_norm(_p).split()), ("thanks", set()))
for _p, _tag in _BYE.items():
    _TABLE[tuple(_norm(_p).split())] = ("bye", set(_tag.split()))
_MAX_LEN = max(len(k) for k in _TABLE)
_FILLER_N = {_norm(w) for w in _FILLER}
_ACK_N = {_norm(w) for w in _ACK}


def classify(text: str, business: str = "") -> Optional[dict]:
    """None when the message is anything but a greeting, thanks or goodbye. Otherwise
    {"kind": greeting|thanks|bye, "tod": morning|afternoon|evening|None, "style": plain|pidgin|yoruba|igbo|hausa|salam,
     "asks_how": bool, "night": bool}."""
    toks = _norm(text).split()
    if not toks or len(toks) > 14:
        return None
    biz = set(_norm(business).split())
    cats: set = set()
    tags: set = set()
    acks = 0
    i = 0
    while i < len(toks):
        for n in range(min(_MAX_LEN, len(toks) - i), 0, -1):
            hit = _TABLE.get(tuple(toks[i:i + n]))
            if hit:
                cats.add(hit[0])
                tags |= hit[1]
                i += n
                break
        else:
            t = toks[i]
            if t in _FILLER_N or t in biz:
                i += 1
            elif t in _ACK_N:
                acks += 1
                i += 1
            else:
                return None
    if not cats:
        return None
    if acks and not ({"thanks", "bye"} & cats):       # "ok thanks" is thanks; "ok hi" or "great hello" is not a greeting
        return None
    kind = "bye" if "bye" in cats else ("greeting" if "greet" in cats else "thanks")
    style = next((s for s in ("salam", "yoruba", "igbo", "hausa", "pidgin") if s in tags), "plain")
    tod = next((t for t in ("morning", "afternoon", "evening") if t in tags), None)
    return {"kind": kind, "tod": tod, "style": style, "asks_how": "how" in tags, "night": "night" in tags}


def _clock_part(now: Optional[datetime]) -> str:
    h = (now.astimezone(LAGOS) if now else datetime.now(LAGOS)).hour
    return "morning" if h < 12 else ("afternoon" if h < 17 else "evening")


def reply(info: dict, business: str = "", now: Optional[datetime] = None, turn: int = 0) -> str:
    """The words Chioma sends back. Always warm; a greeting ends by asking how she can help."""
    biz = (business or "").strip()
    style, kind = info["style"], info["kind"]
    if kind == "thanks":
        if style == "pidgin":
            return "You are welcome o! Is there anything else I fit help you with?"
        return "You are most welcome! Is there anything else I can help you with?"
    if kind == "bye":
        who = f"{biz}" if biz else "us"
        if info.get("night"):
            return f"Good night, and sleep well! Thank you for chatting with {who}. Come back anytime you need us."
        if style == "pidgin":
            return f"Thank you for reaching {who}. Safe journey o, and come back anytime you need us!"
        return f"Thank you for chatting with {who}. Take care, and come back anytime you need us. Goodbye!"
    # greeting
    tod = info.get("tod") or _clock_part(now)
    welcome = f"Welcome to {biz}." if biz else "Welcome."
    if style == "salam":
        opener = "Wa alaikum assalam! "
    elif style == "yoruba":
        opener = "E kaabo! "
    elif style == "igbo":
        opener = "Nno, you are most welcome! "
    elif style == "hausa":
        opener = "Sannu, you are most welcome! "
    elif style == "pidgin":
        opener = "How far! "
    elif info.get("tod"):
        opener = f"Good {info['tod']}! "
    else:
        opener = f"Hello, and good {tod}! " if turn % 2 == 0 else f"Hi there, good {tod}! "
    how = ""
    if style == "pidgin":                       # Pidgin greetings ("how far", "wetin dey") already ask how you are
        how = "I dey fine, thank you for asking. "
    elif info["asks_how"]:
        how = "I am doing very well, thank you for asking. "
    ask = "How I fit help you today?" if style == "pidgin" else "How can I help you today?"
    return f"{opener}{how}{welcome} {ask}"
