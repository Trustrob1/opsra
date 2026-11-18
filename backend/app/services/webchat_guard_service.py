"""
app/services/webchat_guard_service.py
-------------------------------------
WEB-ONLY-1c-SAFE: guards around Chioma's AI that do not depend on the AI obeying its instructions.

  * screen_input: before any AI call, a visitor message that tries to override Chioma, asks how she works, or asks for something outside
    the business (poems, code, homework, politics, medical or legal advice) gets a fixed reply. No AI call, no credit. Attempts to override her
    are counted per chat: warning, last warning, then the AI is switched off for that chat and the team is told.
  * check_reply: after the AI answers, every amount, time, phone number, link and email in the reply must appear in the business facts she was
    given, she may not make commitments she cannot keep (refund approved, booked, guaranteed), and she may not reveal her instructions or model.
    A reply that fails is replaced by "a team member will confirm", and the chat is handed over.
Pure functions plus two small state writes. Nothing here raises.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

STRIKES_TO_BLOCK = 3

_ATTACK = [re.compile(p, re.I) for p in (
    r"\b(?:ignore|disregard|forget|override|bypass)\b[^.?!]{0,40}\b(?:instructions?|rules?|prompt|guidelines?|restrictions?|previous|above)\b",
    r"\b(?:you are now|from now on,? you are|pretend (?:to be|you are|that you)|act as (?:if|though)|role-?play as)\b",
    r"\bnew instructions\b",
    r"\b(?:jailbreak|dan mode|developer mode|do anything now|sudo mode)\b",
    r"</?\s*(?:system|customer_message|business_info|owner_notes|products|conversation)\s*>",
    r"[A-Za-z0-9+/]{60,}={0,2}",
)]
_REVEAL = re.compile(
    r"\b(?:system prompt|your (?:hidden |initial |original )?(?:prompt|instructions)|what (?:model|llm)\b|which (?:model|llm|ai)\b|"
    r"are you (?:chat ?gpt|gpt|claude|gemini|llama|openai|anthropic)|powered by|who (?:made|built|created|trained) you|what are your rules)", re.I)
_OFFTOPIC = [re.compile(p, re.I) for p in (
    r"\b(?:write|compose|draft|generate|create)\b[^.?!]{0,25}\b(?:poem|essay|story|song|lyrics|joke|rap|homework|assignment|python|javascript|code|program)\b",
    r"\b(?:solve|calculate)\b[^.?!]{0,30}\b(?:equation|integral|derivative|homework|math problem)\b",
    r"\b(?:who (?:is|was) the (?:president|prime minister)|which party|vote for)\b",
    r"\b(?:diagnose|diagnosis|dosage|prescri(?:be|ption)|symptoms? of)\b",
    r"\b(?:legal advice|sue (?:him|her|them|someone|my))\b",
)]


def _name(name: str) -> str:
    return (name or "").strip() or "this business"


def attack_reply(name: str, strikes: int) -> str:
    n = _name(name)
    if strikes <= 1:
        return f"I can only help with questions about {n}. What would you like to know about our products or services?"
    if strikes == 2:
        return "I cannot help with that. If it happens again I will stop answering here and pass this chat to the team."
    return "I am going to stop answering here. A team member will look at this chat if you need help."


def reveal_reply(name: str) -> str:
    n = _name(name)
    return f"I am {n}'s virtual assistant. I cannot share how I work, but I am happy to answer questions about {n}."


def offtopic_reply(name: str) -> str:
    return f"I can only help with questions about {_name(name)}. Is there something about our products, prices or services I can help with?"


def _is_attack(text: str) -> bool:
    return any(p.search(text) for p in _ATTACK)


def screen_input(db, s: dict, text: str, business_name: str) -> Optional[dict]:
    """{'reply', 'kind', 'blocked'?} when the message must not reach the AI, else None."""
    try:
        t = text or ""
        state = s.get("state") or {}
        if _is_attack(t):
            strikes = int(state.get("strikes") or 0) + 1
            blocked = strikes >= STRIKES_TO_BLOCK
            kv = {"strikes": strikes}
            if blocked:
                kv["ai_blocked"] = True
            wc.set_state(db, s, **kv)
            return {"reply": attack_reply(business_name, strikes), "kind": "attack", "blocked": blocked and not state.get("ai_blocked"), "strikes": strikes}
        if _REVEAL.search(t):
            return {"reply": reveal_reply(business_name), "kind": "reveal"}
        if any(p.search(t) for p in _OFFTOPIC):
            return {"reply": offtopic_reply(business_name), "kind": "offtopic"}
    except Exception as exc:
        logger.warning("webchat guard screen_input failed: %s", exc)
    return None


# ── the reply checker ───────────────────────────────────────────────────────

_MONEY = re.compile(r"(?:₦|#|\bNGN\s?|\bN(?=\d))\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m)?\b|(\d[\d,]*(?:\.\d+)?)\s?(k|m)?\s?naira\b", re.I)
_ANY_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b", re.I)
_PHONE = re.compile(r"(?<![\d])(?:\+?234|0)[\d\s-]{9,13}(?![\d])")
_URL = re.compile(r"https?://[^\s,;)\]]+|www\.[^\s,;)\]]+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_COMMIT = re.compile(
    r"\bi(?:'ve| have| will|'ll)\s+(?:book(?:ed)?|confirm(?:ed)?|reserve[d]?|approve[d]?|hold|refund(?:ed)?|cancel(?:led|ed)?|process(?:ed)?|ordered)\b|"
    r"\b(?:refund|discount|booking|order|payment|reservation)\b[^.!?]{0,20}\b(?:is |has been |have been |was )?(?:approved|confirmed|processed|successful|guaranteed)\b|"
    r"\bguarantee[sd]?\b|\bi promise\b|\bwe promise\b|\bi can give you (?:a )?discount\b", re.I)
_LEAK = re.compile(r"\b(?:system prompt|my instructions|my prompt|as an ai language model|anthropic|openai|chat ?gpt|claude)\b|<\s*/?\s*(?:business_info|owner_notes|customer_message|products)\s*>", re.I)

HANDOFF_REPLIES = {
    "price": "I do not want to give you a wrong figure, so a team member will confirm that for you.",
    "time": "I do not want to give you the wrong time, so a team member will confirm that for you.",
    "phone": "I do not want to give you a wrong contact detail, so a team member will share it with you.",
    "link": "I do not want to point you to the wrong place, so a team member will share the right link with you.",
    "commitment": "I cannot promise that myself, so a team member will confirm it for you.",
    "leak": "I can only help with questions about this business. A team member can take it from here.",
}


def _money_values(text: str) -> set:
    out = set()
    for m in _MONEY.finditer(text or ""):
        num, suf = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        out.add(v * (1000 if (suf or "").lower() == "k" else 1_000_000 if (suf or "").lower() == "m" else 1))
    return out


def _all_numbers(text: str) -> set:
    out = set()
    for m in _ANY_NUM.finditer(text or ""):
        try:
            out.add(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s?k\b", text or "", re.I):
        try:
            out.add(float(m.group(1).replace(",", "")) * 1000)
        except ValueError:
            pass
    return out


def _times(text: str) -> set:
    return {(int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()) for m in _TIME.finditer(text or "")}


def _phone_key(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    return "0" + d[3:] if d.startswith("234") else d


def _phones(text: str) -> set:
    return {k for k in (_phone_key(m.group(0)) for m in _PHONE.finditer(text or "")) if len(k) >= 10}


def _host(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).split("/")[0].rstrip(".,")


def check_reply(reply: str, facts: str, s: Optional[dict] = None) -> Optional[dict]:
    """None when the reply is fine, else {'reason', 'reply'}: the reply to show instead."""
    try:
        r, f = reply or "", facts or ""
        fl = f.lower()
        if _LEAK.search(r):
            return {"reason": "leak", "reply": HANDOFF_REPLIES["leak"]}
        for m in _COMMIT.finditer(r):
            if m.group(0).lower() not in fl:
                return {"reason": "commitment", "reply": HANDOFF_REPLIES["commitment"]}
        known_nums = _all_numbers(f)
        if any(v not in known_nums for v in _money_values(r)):
            return {"reason": "price", "reply": HANDOFF_REPLIES["price"]}
        if not _times(r) <= _times(f):
            return {"reason": "time", "reply": HANDOFF_REPLIES["time"]}
        known_phones = _phones(f) | ({_phone_key((s or {}).get("contact_phone"))} if (s or {}).get("contact_phone") else set())
        if not _phones(r) <= known_phones:
            return {"reason": "phone", "reply": HANDOFF_REPLIES["phone"]}
        for u in _URL.findall(r):
            if _host(u) not in fl.replace("www.", "") and _host(u) != "opsra.com.ng":
                return {"reason": "link", "reply": HANDOFF_REPLIES["link"]}
        for e in _EMAIL.findall(r):
            if e.lower() not in fl:
                return {"reason": "link", "reply": HANDOFF_REPLIES["link"]}
    except Exception as exc:
        logger.warning("webchat guard check_reply failed: %s", exc)
    return None
