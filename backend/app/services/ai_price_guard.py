"""
app/services/ai_price_guard.py
------------------------------
WA-PRICE-GUARD-1 — the WhatsApp AI must not answer a price complaint by offering something cheaper (a smaller size, a lower variant, a
cheaper product). Chioma's prompt already forbids discounts, but nothing stopped the model from "helping" with a smaller mattress.

The prompt now says so (build_agent_system_prompt). This module is the backstop in code: when the customer is complaining about price and the
reply would offer an item priced below what they were looking at, the reply is replaced by a hand-over to the team.

Pure functions, no database. "What they were looking at" (the anchor) is, in order: the dearest catalogue item the customer named in this
message, the anchor saved earlier in the session, then the dearest catalogue item named in the recent conversation. No anchor means no block
(the prompt rule still applies).
"""
from __future__ import annotations

import re
from typing import Any, Optional

PRICE_COMPLAINT = re.compile(
    r"\b(too\s+(?:expensive|much|costly|high|pricey)|expensive|pricey|costly|cheaper|cheapest|cheap|afford|discount|reduce\s+(?:the\s+)?price|"
    r"lower\s+(?:the\s+)?price|last\s+price|best\s+price|bargain|negotiat\w*|high\s+for\s+me|(?:is|that'?s|it'?s)\s+(?:a\s+lot|high)|"
    r"out\s+of\s+(?:my\s+)?budget|over\s+(?:my\s+)?budget|my\s+budget)\b", re.I)

# words that say nothing about WHICH product it is (every mattress is a "premium mattress", and the shop's own name is on many titles)
GENERIC = {"mattress", "mattresses", "premium", "luxury", "organic", "the", "and", "for", "with", "bed", "royal", "rest", "by", "new", "best"}
HANDOVER_MESSAGE = "I understand the price matters. Let me get our team to help you with that."
HISTORY_LOOKBACK = 8


def _num(v: Any) -> Optional[float]:
    try:
        n = float(str(v).replace(",", "").replace("₦", "").strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _words(s: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower())]


def is_price_complaint(text: str, data: Optional[dict] = None) -> bool:
    return bool(PRICE_COMPLAINT.search(text or "")) or (data or {}).get("objection_type") == "price"


def _title_hit(title: str, text_words: set) -> bool:
    key = [w for w in _words(title) if w not in GENERIC and len(w) >= 2]
    return bool(key) and all(w in text_words for w in key)


def _label_hit(label: str, text: str) -> bool:
    lab = (label or "").strip().lower()
    if len(lab) < 3 or lab == "standard":
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(lab) + r"(?![a-z0-9])", text.lower()) is not None


def mentioned_prices(text: str, catalog: list) -> list:
    """Prices of the catalogue products and variants this text names (a product by its distinctive words, a variant by its label)."""
    tw = set(_words(text))
    out = []
    for p in catalog or []:
        hit = _title_hit(p.get("title") or "", tw)
        if hit and _num(p.get("price")) is not None:
            out.append(_num(p.get("price")))
        for v in p.get("variants") or []:
            if _label_hit(v.get("label") or "", text) and _num(v.get("price")) is not None:
                out.append(_num(v.get("price")))
    return out


def price_of(catalog: list, product_id: Any, variant_id: Any = None) -> Optional[float]:
    for p in catalog or []:
        if str(p.get("id")) != str(product_id):
            continue
        if variant_id:
            for v in p.get("variants") or []:
                if str(v.get("id")).strip() == str(variant_id).strip() and _num(v.get("price")) is not None:
                    return _num(v.get("price"))
        return _num(p.get("price"))
    return None


def anchor_price(inbound: str, saved: Any, history: list, catalog: list) -> Optional[float]:
    here = mentioned_prices(inbound, catalog)
    if here:
        return max(here)
    if _num(saved) is not None:
        return _num(saved)
    older = []
    for m in (history or [])[-HISTORY_LOOKBACK:]:
        older += mentioned_prices(str((m or {}).get("content") or ""), catalog)
    return max(older) if older else None


def offered_prices(action: dict, catalog: list) -> list:
    """Prices of everything the reply puts in front of the customer: items named in the text, and the product or variant it recommends."""
    data = action.get("data") or {}
    out = mentioned_prices(str(action.get("message") or ""), catalog)
    if action.get("action") in ("recommend_product", "request_variant", "confirm_add_to_cart") and data.get("product_id"):
        p = price_of(catalog, data.get("product_id"), data.get("variant_id"))
        if p is not None:
            out.append(p)
    return out


def check(inbound: str, action: dict, saved_anchor: Any, history: list, catalog: list) -> Optional[dict]:
    """Return a hand-over action when a price complaint is being answered with something cheaper, else None."""
    if not is_price_complaint(inbound, action.get("data")) or action.get("action") == "escalate":
        return None
    anchor = anchor_price(inbound, saved_anchor, history, catalog)
    if anchor is None:
        return None
    if any(p < anchor for p in offered_prices(action, catalog)):
        return {"action": "escalate", "message": HANDOVER_MESSAGE, "data": {"reason": "price_objection"}}
    return None


def next_anchor(inbound: str, action: dict, saved_anchor: Any, catalog: list) -> Any:
    """What to remember for the next turn. A price complaint never lowers it (otherwise the reply to the complaint would become the new normal)."""
    here = mentioned_prices(inbound, catalog)
    if here:
        return max(here)
    if not is_price_complaint(inbound, action.get("data")):
        data = action.get("data") or {}
        if action.get("action") in ("recommend_product", "request_variant", "confirm_add_to_cart") and data.get("product_id"):
            p = price_of(catalog, data.get("product_id"), data.get("variant_id"))
            if p is not None:
                return p
    return saved_anchor


# ── web chat (Chioma): products have one price each, and the product the visitor is viewing is the anchor ──
CHAT_HANDOVER_REPLY = "I understand the price matters. I can pass you to our team to help with that."


def check_chat(inbound: str, reply: str, product_ids: Optional[list], viewing_id: Any, history_text: str, catalog: list) -> bool:
    """True when a visitor's price complaint is being answered with something cheaper (named in the reply or shown as a card).
    Anchor: the dearest catalogue item the visitor named now, else the product they are viewing, else the dearest one named earlier."""
    if not is_price_complaint(inbound):
        return False
    here = mentioned_prices(inbound, catalog)
    anchor = max(here) if here else (price_of(catalog, viewing_id) if viewing_id else None)
    if anchor is None:
        older = mentioned_prices(history_text or "", catalog)
        anchor = max(older) if older else None
    if anchor is None:
        return False
    offered = mentioned_prices(reply or "", catalog) + [p for p in (price_of(catalog, i) for i in (product_ids or [])) if p is not None]
    return any(p < anchor for p in offered)
