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
import secrets
import time
from datetime import datetime, timedelta, timezone
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


def screen_input(db, s: dict, text: str, business_name: str, ip: Optional[str] = None) -> Optional[dict]:
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
            if blocked and not state.get("ai_blocked") and ip:
                block_address(s.get("org_id"), ip)          # the same visitor address gets no AI from this business for a while, in any chat
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
_LEAK = re.compile(r"\b(?:system prompt|my instructions|my prompt|as an ai language model)\b|<\s*/?\s*(?:business_info|owner_notes|customer_message|products)\s*>|"
                   r"\b(?:i am|i'm|this is|you are talking to)\s+(?:claude|chat ?gpt|gpt|an? (?:large )?language model)\b|"
                   r"\b(?:made|built|created|trained|powered|developed) by (?:anthropic|openai)\b", re.I)
_VENDOR = re.compile(r"\b(?:anthropic|openai|chat ?gpt|claude)\b", re.I)        # a business may sell or use these (Claude Agents): fine when its own information says so

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


def _sentences(text: str) -> list:
    return [x for x in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if x]


def scrub(reply: str, facts: str, s: Optional[dict], reason: str) -> Optional[str]:
    """For a price, time, phone or link the business never gave: keep the sentences that are fine and drop the ones that are not.
    None when nothing useful is left (or for a promise or a real leak, which are never patched)."""
    if reason not in ("price", "time", "phone", "link"):
        return None
    keep = [x for x in _sentences(reply) if check_reply(x, facts, s) is None]
    out = " ".join(keep).strip()
    return out if len(out) >= 25 and check_reply(out, facts, s) is None else None


def check_reply(reply: str, facts: str, s: Optional[dict] = None) -> Optional[dict]:
    """None when the reply is fine, else {'reason', 'reply'}: the reply to show instead."""
    try:
        r, f = reply or "", facts or ""
        fl = f.lower()
        if _LEAK.search(r) or any(m.group(0).lower() not in fl for m in _VENDOR.finditer(r)):
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


# ── a block that spans chats ────────────────────────────────────────────────
# Scope: one business, one visitor address, AI only. The chat, the menu and the team stay open, so a shared mobile address
# can never lock a real customer out of reaching the business. First block 24 hours, a repeat within a week 7 days.

BLOCK_HOURS = 24
REPEAT_BLOCK_DAYS = 7
_local_flags: dict = {}


def _flag_set(name: str, ttl_s: int) -> None:
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            r.set(f"wc:flag:{name}", "1", ex=int(ttl_s))
            return
    except Exception as exc:
        logger.warning("webchat guard flag: redis unavailable (%s) - using in-process flag", exc)
    if len(_local_flags) > 20_000:
        _local_flags.clear()
    _local_flags[name] = time.monotonic() + ttl_s


def _flag_on(name: str) -> bool:
    try:
        from app.services.ai_service import _get_redis
        r = _get_redis()
        if r is not None:
            return bool(r.exists(f"wc:flag:{name}"))
    except Exception as exc:
        logger.warning("webchat guard flag: redis unavailable (%s) - using in-process flag", exc)
    return _local_flags.get(name, 0) > time.monotonic()


def block_address(org_id: str, ip: str) -> None:
    """Switch the AI off for this address at this business. Never raises."""
    try:
        repeat = wc.rate_limited(f"blocks:{org_id}:{ip}", 1, REPEAT_BLOCK_DAYS * 86400)      # True from the second block in a week
        _flag_set(f"ipblock:{org_id}:{ip}", (REPEAT_BLOCK_DAYS * 86400) if repeat else (BLOCK_HOURS * 3600))
    except Exception as exc:
        logger.warning("webchat guard block_address failed: %s", exc)


def address_blocked(org_id: str, ip: Optional[str]) -> bool:
    try:
        return bool(ip) and _flag_on(f"ipblock:{org_id}:{ip}")
    except Exception:
        return False


# ── a human check after a burst ─────────────────────────────────────────────
# No third-party service and no change to the page: Chioma asks a one-line sum in the chat. A script that fires messages without reading
# the replies fails it; a person answers in two seconds. Passing skips the check for 30 minutes.

BURST_MESSAGES, BURST_WINDOW_S = 10, 30
VERIFIED_MIN, CHECK_TRIES, COOLDOWN_MIN = 30, 2, 5
_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen".split())}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _later(minutes: int) -> str:
    return (_now() + timedelta(minutes=minutes)).isoformat()


def _future(iso) -> bool:
    try:
        return bool(iso) and datetime.fromisoformat(str(iso).replace("Z", "+00:00")) > _now()
    except Exception:
        return False


def _number_in(text: str) -> Optional[int]:
    m = re.search(r"\d+", text or "")
    if m:
        return int(m.group(0))
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if w in _WORDS:
            return _WORDS[w]
    return None


def _challenge(db, s: dict, tries: int = 0, lead: str = "Quick check before we continue:") -> str:
    a, b = 2 + secrets.randbelow(8), 2 + secrets.randbelow(8)
    wc.set_state(db, s, human_check={"answer": a + b, "tries": tries})
    return f"{lead} what is {a} + {b}?"


def human_check(db, s: dict, text: str) -> Optional[dict]:
    """None to carry on. {'reply': str or None} when this message is part of a check (None reply = stay quiet during the cool-off)."""
    try:
        state = s.get("state") or {}
        if _future(state.get("check_cooldown_until")):
            return {"reply": None}
        pending = state.get("human_check")
        if pending:
            if _number_in(text) == pending.get("answer"):
                wc.set_state(db, s, human_check=None, check_first=False, verified_until=_later(VERIFIED_MIN))
                return {"reply": "Thanks, that is all I needed. How can I help you?", "passed": True}
            tries = int(pending.get("tries") or 0) + 1
            if tries >= CHECK_TRIES:
                wc.set_state(db, s, human_check=None, check_cooldown_until=_later(COOLDOWN_MIN))
                return {"reply": "I will pause here for a few minutes. Please try again shortly.", "failed": True}
            return {"reply": _challenge(db, s, tries, "Not quite.")}
        if _future(state.get("verified_until")):
            return None
        if state.get("check_first") or wc.rate_limited(f"burst:{s.get('id')}", BURST_MESSAGES, BURST_WINDOW_S):
            return {"reply": _challenge(db, s), "asked": True}
    except Exception as exc:
        logger.warning("webchat guard human_check failed: %s", exc)
    return None
