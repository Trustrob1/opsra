"""
app/services/webchat_smart_service.py
-------------------------------------
SMART-1: what makes Chioma useful with the AI off (and cheaper with it on). No AI is called here.
  - word matching that forgives plurals, small typos and filler words (rank, weak_ties)
  - related buttons shown under an answer (related)
  - built-in answers for opening hours, phone number and address from the business's own details (info_answer)
  - a short guided form of tap-to-answer questions (guide_*)
  - starter menus by kind of business (STARTERS), a setup checklist (checklist)
  - the owner's "teach Chioma" step for a question she could not answer (suggest_keyword, teach)
Everything here is pure or defensive: a failure falls back to the old behaviour, it never breaks a chat.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

STOP = {
    "the", "a", "an", "i", "me", "my", "you", "your", "yours", "we", "our", "is", "are", "am", "do", "does", "did", "can", "could", "would", "will", "to", "of",
    "for", "in", "on", "at", "and", "or", "about", "please", "pls", "plz", "want", "wanted", "like", "need", "tell", "know", "more", "what", "how", "with",
    "have", "has", "it", "its", "this", "that", "there", "any", "some", "be", "if", "so", "just", "hi", "hello", "hey",
    "abeg", "wetin", "dey", "una", "biko", "oga", "madam", "sir", "na", "dem", "wey", "sef",
}


def norm_words(text: str) -> list:
    """Lower-case content words of a message: punctuation and filler words (English and Pidgin) removed."""
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split() if w not in STOP]


def stem(w: str) -> str:
    """A rough root so price / prices / pricing meet: strips -s, -ing, -ed and a final -e."""
    w = (w or "").lower()
    if len(w) > 3 and w.endswith("ss"):
        pass
    elif len(w) > 3 and w.endswith("s"):
        w = w[:-1]
    for suf in ("ing", "ed"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def _close(a: str, b: str) -> bool:
    """True when two words are the same root or one small typo apart (letters swapped, one wrong, one missing)."""
    sa, sb = stem(a), stem(b)
    if sa == sb:
        return True
    if len(sa) >= 4 and len(sb) >= 4 and sa[0] == sb[0]:
        if sorted(sa) == sorted(sb):
            return True
        if len(sa) >= 5 and difflib.SequenceMatcher(None, sa, sb).ratio() >= 0.8:
            return True
    return False


def _kw_hits(kw: str, t: str, words: list) -> int:
    """1 when the keyword is in the message exactly (as before) or, for a single word, close to one of its words."""
    if not kw:
        return 0
    if f" {kw} " in t or (len(kw) >= 4 and kw in t):
        return 1
    if " " not in kw and len(kw) >= 3 and any(_close(kw, w) for w in words if len(w) >= 3):
        return 1
    return 0


def rank(cfg: dict, text: str) -> list:
    """[(hits, item)] best first (ties keep menu order). Exact keyword +1, button label as a phrase +2, close-spelling keyword +1,
    a long word of the label (>= 5 letters) +1."""
    t = f" {re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower())} "
    words = norm_words(text)
    out = []
    for it in cfg.get("menu") or []:
        if it.get("action") == "human":
            out.append((0, it))
            continue
        seen = {stem(kw) if " " not in kw else kw for kw in (it.get("keywords") or []) if _kw_hits(kw, t, words)}      # price / prices count once
        hits = len(seen)
        label = re.sub(r"[^a-z0-9 ]", " ", (it.get("label") or "").lower()).strip()
        if label and label in t:
            hits += 2
        elif hits == 0:                  # a long word of the label counts only when nothing else matched (no double count)
            lw = [w for w in norm_words(label) if len(w) >= 5]
            if lw and any(_close(w, x) for w in lw for x in words if len(x) >= 5):
                hits += 1
        out.append((hits, it))
    out.sort(key=lambda p: -p[0])
    return out


def weak_ties(cfg: dict, text: str) -> list:
    """Two or more buttons that match a typed message equally well on a single weak hit: the visitor is asked which one they mean."""
    r = rank(cfg, text)
    if not r or r[0][0] != 1:
        return []
    return [it for h, it in r if h == 1 and it.get("action") != "human"][:3]


# ── related buttons ─────────────────────────────────────────────────────────

def _item_choice(it: dict) -> dict:
    return {"id": "item", "menu_id": it["id"], "label": str(it["label"])[:40]}


def related(cfg: dict, item: dict, n: int = 3) -> list:
    """Buttons to show under an answer: the next few topics (booking first), then the team. Never the one just answered."""
    others = [m for m in (cfg.get("menu") or []) if m.get("id") and m.get("label") and m["id"] != item.get("id") and m.get("action") != "human"]
    others.sort(key=lambda m: (0 if m.get("featured") else 1, 0 if m.get("action") in ("booking", "guide") else 1))
    out = [_item_choice(m) for m in others[:n]]
    if any(m.get("action") == "human" for m in (cfg.get("menu") or [])):
        out.append({"id": "human", "label": "Talk to the team"})
    return out


# ── built-in answers from the business's own details ─────────────────────────

_HOURS = re.compile(r"\b(?:opening hours|open(?:ing)? (?:time|hours)|working hours|business hours|are you (?:open|closed)|when (?:do|are) you (?:open|close)|what time (?:do|are) you (?:open|close)|closing time|hours)\b", re.I)
_PHONE = re.compile(r"\b(?:phone number|contact number|your number|call you|number to call|telephone|how (?:can|do) i (?:call|contact|reach) you)\b", re.I)
_ADDRESS = re.compile(r"\b(?:where are you|your (?:address|location)|address|location|directions|find you|where is your|where do you (?:operate|work))\b", re.I)


def _short(text: str) -> bool:
    return len((text or "").split()) <= 9


def info_answer(cfg: dict, text: str) -> Optional[str]:
    """Opening hours, phone number or address, only from details the business has actually set. None when it has not set that detail
    (the normal path then carries on) or the message is a long enquiry that merely mentions one of these words."""
    try:
        if not _short(text):
            return None
        from app.services import webchat_call_service as call
        from app.services import webchat_handover_service as ho
        org = cfg.get("_call_org") or {}
        if _HOURS.search(text):
            hours = call.hours_text(org.get("business_hours"))
            if hours:
                state, reopens = ho.team_state(cfg)
                tail = " The team is online now." if state == ho.TEAM_OPEN else (f" The team is away and back {reopens}." if reopens else "")
                return f"We are open {hours}.{tail}"
        if _PHONE.search(text):
            number = call.number_for(cfg)
            if number:
                return f"You can call us on {call.display_number(number)}."
        if _ADDRESS.search(text):
            addr = (cfg.get("address") or "").strip()
            if addr:
                return f"You can find us at {addr}."
    except Exception as exc:
        logger.warning("webchat info_answer failed: %s", exc)
    return None


# ── guided form ──────────────────────────────────────────────────────────────

def clean_guide(raw) -> Optional[dict]:
    """{'steps': [{'q', 'options'}], 'done'}: up to 4 questions, up to 5 tap options each. None when nothing usable."""
    if not isinstance(raw, dict):
        return None
    steps = []
    for st in (raw.get("steps") if isinstance(raw.get("steps"), list) else [])[:4]:
        if not isinstance(st, dict):
            continue
        q = wc._clean_text(st.get("q"), 120)
        if not q:
            continue
        opts = [wc._clean_text(o, 40) for o in (st.get("options") if isinstance(st.get("options"), list) else [])[:5]]
        steps.append({"q": q, "options": [o for o in opts if o]})
    if not steps:
        return None
    return {"steps": steps, "done": wc._clean_text(raw.get("done"), 300)}


def guide_prompt(guide: dict, i: int) -> dict:
    """{'text', 'choices'} for question i: the options are tap buttons that send the option as the visitor's answer."""
    st = guide["steps"][i]
    return {"text": st["q"], "choices": [{"id": "say", "label": o} for o in st["options"]]}


def guide_summary(item: dict, answers: list) -> str:
    guide = item.get("guide") or {"steps": []}
    parts = [f"{guide['steps'][k]['q'].rstrip('?:. ')}: {a}" for k, a in enumerate(answers) if k < len(guide["steps"])]
    return f"{item.get('label') or 'Request'} - " + "; ".join(parts)


def parse_guide_text(text: str) -> dict:
    """The owner's box: one question per line, options after a colon separated by | (e.g. 'What do you need?: Website | Training')."""
    steps = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        q, _, rest = line.partition(":")
        if rest:
            q = q.strip() + "?" if not q.strip().endswith("?") else q.strip()
            opts = [o.strip() for o in rest.split("|") if o.strip()]
        else:
            q, opts = line, []
        steps.append({"q": q, "options": opts})
    return {"steps": steps}


# ── starter menus ────────────────────────────────────────────────────────────

_ASK = "[Add your answer here]"


def _quote_guide(options: list) -> dict:
    return {"steps": [{"q": "What do you need?", "options": options},
                      {"q": "Roughly when do you need it?", "options": ["This week", "This month", "Not sure yet"]}],
            "done": "Thank you. I have passed this to the team and they will reply here."}


STARTERS = {
    "salon": {"label": "Salon or beauty", "menu": [
        {"id": "services", "label": "Services and prices", "keywords": ["price", "cost", "how much", "service", "braid", "wig", "hair"], "answer": "[Add your services and prices here]"},
        {"id": "products", "label": "Hair products", "keywords": ["product", "shampoo", "oil", "extension"], "answer": "[Add what you sell and how to order]"},
        {"id": "hours", "label": "Opening hours", "keywords": ["open", "close", "hours", "time"], "answer": "[Add your opening hours]"},
        {"id": "location", "label": "Where to find us", "keywords": ["where", "location", "address", "direction"], "answer": "[Add your address]"},
        {"id": "book", "label": "Book an appointment", "action": "booking", "keywords": ["book", "appointment", "reserve"]},
        {"id": "talk", "label": "Talk to us", "action": "human", "keywords": ["human", "person", "call", "agent"]},
    ]},
    "services": {"label": "Services, agency or consulting", "menu": [
        {"id": "services", "label": "What we do", "keywords": ["service", "services", "offer", "help", "work"], "answer": "[Describe your main services in two sentences]"},
        {"id": "pricing", "label": "Prices", "keywords": ["price", "prices", "pricing", "cost", "how much", "quote", "package"], "answer": "[Add your prices, or how a quote works]"},
        {"id": "quote", "label": "Get a quote", "action": "guide", "keywords": ["quote", "estimate", "proposal"], "guide": _quote_guide(["[Service 1]", "[Service 2]", "Something else"])},
        {"id": "book", "label": "Book a call", "action": "booking", "keywords": ["book", "appointment", "schedule", "call me", "call back"]},
        {"id": "talk", "label": "Talk to the team", "action": "human", "keywords": []},
    ]},
    "restaurant": {"label": "Restaurant or food", "menu": [
        {"id": "menu", "label": "Our menu", "keywords": ["menu", "food", "eat", "dish", "meal", "drink"], "answer": "[Add your menu or a link to it]"},
        {"id": "hours", "label": "Opening hours", "keywords": ["open", "close", "hours", "time"], "answer": "[Add your opening hours]"},
        {"id": "delivery", "label": "Delivery", "keywords": ["deliver", "delivery", "dispatch", "rider"], "answer": "[Add where you deliver, the fee and how long it takes]"},
        {"id": "reserve", "label": "Reserve a table", "action": "booking", "keywords": ["reserve", "reservation", "table", "book"]},
        {"id": "location", "label": "Where to find us", "keywords": ["where", "location", "address", "direction"], "answer": "[Add your address]"},
        {"id": "talk", "label": "Talk to the team", "action": "human", "keywords": []},
    ]},
    "shop": {"label": "Shop or retail", "menu": [
        {"id": "products", "label": "What we sell", "keywords": ["product", "products", "sell", "item", "stock", "available"], "answer": "[Add what you sell and how to order]"},
        {"id": "pricing", "label": "Prices", "keywords": ["price", "prices", "cost", "how much"], "answer": "[Add your prices, or tell visitors to ask for an item]"},
        {"id": "delivery", "label": "Delivery and payment", "keywords": ["deliver", "delivery", "pay", "payment", "transfer", "shipping"], "answer": "[Add how you deliver and how customers pay]"},
        {"id": "order", "label": "Place an order", "action": "guide", "keywords": ["order", "buy", "purchase"], "guide": _quote_guide(["[Item 1]", "[Item 2]", "Something else"])},
        {"id": "talk", "label": "Talk to the team", "action": "human", "keywords": []},
    ]},
    "clinic": {"label": "Clinic or health", "menu": [
        {"id": "services", "label": "Our services", "keywords": ["service", "services", "treatment", "doctor", "test", "checkup"], "answer": "[Add the services you offer]"},
        {"id": "fees", "label": "Fees", "keywords": ["price", "prices", "fee", "fees", "cost", "how much"], "answer": "[Add your consultation fees, or how to get them]"},
        {"id": "hours", "label": "Opening hours", "keywords": ["open", "close", "hours", "time"], "answer": "[Add your opening hours]"},
        {"id": "book", "label": "Book an appointment", "action": "booking", "keywords": ["book", "appointment", "reserve", "see a doctor"]},
        {"id": "location", "label": "Where to find us", "keywords": ["where", "location", "address", "direction"], "answer": "[Add your address]"},
        {"id": "talk", "label": "Talk to the team", "action": "human", "keywords": []},
    ]},
}


def starter_list() -> list:
    return [{"id": k, "label": v["label"]} for k, v in STARTERS.items()]


# ── setup checklist ──────────────────────────────────────────────────────────

def checklist(cfg: dict, open_unanswered: int = 0) -> dict:
    """What the owner still needs to do for Chioma to be useful. Each item: {id, label, done, hint}."""
    from app.services import webchat_call_service as call
    menu = [m for m in (cfg.get("menu") or []) if not m.get("builtin")]
    answers = [m for m in menu if m.get("action") not in ("booking", "human", "guide")]
    org = cfg.get("_call_org") or {}
    items = [
        {"id": "menu", "label": "Add at least 3 buttons with real answers", "done": len([m for m in answers if (m.get("answer") or "").strip()]) >= 3,
         "hint": "Pick a starter menu for your kind of business, then edit it."},
        {"id": "placeholders", "label": "Replace every [bracketed] answer", "done": bool(menu) and not any(re.search(r"\[.*\]", m.get("answer") or "") or any(re.search(r"\[.*\]", str(o)) for st in ((m.get("guide") or {}).get("steps") or []) for o in st.get("options", [])) for m in menu),
         "hint": "Visitors would see the brackets."},
        {"id": "keywords", "label": "Give each answer 3 or more words that trigger it", "done": bool(answers) and all(len(m.get("keywords") or []) >= 3 for m in answers),
         "hint": "These are what a typed message is matched against."},
        {"id": "hours", "label": "Set your business hours", "done": bool(call.hours_text(org.get("business_hours"))), "hint": "Chioma then answers 'are you open' and tells visitors when you are back."},
        {"id": "phone", "label": "Turn on the call button with your number", "done": bool(cfg.get("call_enabled") and call.number_for(cfg)), "hint": "She can then give your phone number."},
        {"id": "address", "label": "Add your address", "done": bool((cfg.get("address") or "").strip()), "hint": "She can then answer 'where are you'."},
        {"id": "booking", "label": "Add a booking button", "done": any(m.get("action") == "booking" for m in menu), "hint": "Offered first when your team is away."},
        {"id": "team", "label": "Keep a Talk to the team button", "done": any(m.get("action") == "human" for m in menu), "hint": "Visitors always need a way to reach a person."},
        {"id": "unanswered", "label": "Teach Chioma the questions she missed", "done": open_unanswered == 0, "hint": f"{open_unanswered} waiting below." if open_unanswered else "Nothing waiting."},
    ]
    return {"items": items, "done": sum(1 for i in items if i["done"]), "total": len(items)}


# ── teach Chioma from a question she could not answer ───────────────────────

def suggest_keyword(question: str) -> str:
    """The most useful single word of a question to add as a keyword: the longest content word."""
    words = [w for w in norm_words(question) if len(w) >= 3 and not w.isdigit()]
    return max(words, key=len) if words else ""


def teach(db, org_id: str, gap_id: str, menu_id: str, keyword: str) -> dict:
    """Adds the keyword to a button and closes the question. Raises ValueError with a plain message on bad input."""
    kw = wc._clean_text(keyword, 30).lower().strip()
    if len(kw) < 2:
        raise ValueError("Type the word first.")
    cfg = wc.get_config(db, org_id)
    menu = [dict(m) for m in cfg.get("menu") or []]
    item = next((m for m in menu if m.get("id") == menu_id and m.get("action") != "human"), None)
    if not item:
        raise ValueError("Pick one of your buttons.")
    kws = list(item.get("keywords") or [])
    if kw not in kws:
        if len(kws) >= 15:
            raise ValueError("That button already has 15 words. Remove one first.")
        kws.append(kw)
    item["keywords"] = kws
    wc.save_config(db, org_id, {"menu": menu})
    rows = db.table("knowledge_gaps").select("id").eq("id", gap_id).eq("org_id", org_id).limit(1).execute().data or []
    if not rows:
        raise ValueError("That question was not found.")
    from datetime import datetime, timezone
    db.table("knowledge_gaps").update({"status": "answered", "resolved_at": datetime.now(timezone.utc).isoformat()}).eq("id", gap_id).eq("org_id", org_id).execute()
    return {"taught": True, "keyword": kw, "menu_id": menu_id}
