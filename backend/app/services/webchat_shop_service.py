"""
app/services/webchat_shop_service.py
------------------------------------
WEBCHAT-3b — products, cart and checkout inside the web chat.

Separate from the WhatsApp agent (ai_agent_service is untouched). The cart lives on the chat session
(webchat_sessions.state.cart), so a visitor needs no phone number to browse; checkout needs contact details.

Rules
  * Only when the business switched it on (config.shop_enabled).
  * Prices are NEVER taken from the browser or the model. Every add and the checkout re-read the product
    from the business's own catalog.
  * Adding to the cart and checking out are explicit taps by the visitor. The AI may only suggest product ids,
    and those are checked against the catalog before a card is shown.
  * Checkout = a Paystack payment link made with the business's OWN paystack_storefront keys (same route the
    WhatsApp agent uses). No Paystack, or any failure -> the chat is handed to a person and the team is told.
  * Free to run: no AI call, no credit use.
S14: public helpers never raise past the router; they return {"error": "..."} for visitor mistakes.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

LIST_LIMIT = 12
MAX_LINES = 15
MAX_QTY = 10
CARD_DESC_CHARS = 160


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _money(v: float) -> str:
    return f"₦{v:,.0f}"


def _variants(p: dict) -> list[dict]:
    out = []
    for v in p.get("variants") or []:
        vid = v.get("id") or v.get("variant_id")
        if vid is None or str(vid).strip() == "":
            continue
        out.append({"id": str(vid), "label": str(v.get("title") or v.get("size") or v.get("name") or "Standard")[:40],
                    "price": _num(v.get("price")) or _num(p.get("price"))})
    return out


def _variant_in_stock(v: dict) -> bool:
    """Same rule the public catalog page uses: an explicit available flag wins, else Shopify inventory fields."""
    if isinstance(v.get("available"), bool):
        return v["available"]
    if v.get("inventory_management") in (None, "") or v.get("inventory_policy") == "continue":
        return True
    try:
        return int(v.get("inventory_quantity") or 0) > 0
    except (TypeError, ValueError):
        return False


def _stock_state(p: dict, variant_id) -> Optional[str]:
    """STORE-1: None when the item (and chosen option) can be sold; else a short reason for the visitor.
    A product marked unavailable, or an option with no stock, cannot be added or paid for."""
    if p.get("available") is False:
        return "That item is out of stock."
    if variant_id is not None:
        raw = next((v for v in (p.get("variants") or [])
                    if str(v.get("id") or v.get("variant_id") or "") == str(variant_id)), None)
        if raw is not None and not _variant_in_stock(raw):
            return "That option is out of stock."
    return None


def _card(p: dict) -> dict:
    imgs = p.get("catalog_images") or []
    desc = (p.get("catalog_description") or p.get("description") or "").strip()
    return {
        "id": str(p.get("id")), "title": str(p.get("title") or "Product")[:80], "price": _num(p.get("price")),
        "image_url": wc._clean_url(imgs[0]) if imgs else None,
        "description": desc[:CARD_DESC_CHARS] or None, "variants": _variants(p),
    }


def _fetch_all(db, org_id: str) -> list[dict]:
    rows = (db.table("products")
            .select("id, title, price, variants, catalog_images, description, catalog_description, available")
            .eq("org_id", org_id).execute().data) or []
    return [r for r in rows if r.get("id") and (r.get("title") or "").strip()]


def _fetch_one(db, org_id: str, product_id: str) -> Optional[dict]:
    rows = (db.table("products")
            .select("id, title, price, variants, catalog_images, description, catalog_description, available")
            .eq("org_id", org_id).eq("id", product_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def _rank(rows: list[dict], q: Optional[str]) -> list[dict]:
    """A query ranks by word hits in title/description; no query (or no hit) keeps catalogue order."""
    words = {w for w in re.findall(r"[a-z0-9]+", (q or "").lower()) if len(w) > 2}
    if not words:
        return rows

    def score(p):
        blob = f"{p.get('title') or ''} {p.get('catalog_description') or p.get('description') or ''}".lower()
        return sum(1 for w in words if w in blob)
    ranked = sorted(rows, key=score, reverse=True)
    hits = [p for p in ranked if score(p) > 0]
    return hits or ranked


_GENERIC_TITLE_WORDS = {"with", "from", "that", "this", "your", "daily", "pack", "set", "new", "best", "free"}


def text_matches(db, org_id: str, text: str, limit: int = 3) -> list[dict]:
    """BOT-PRODUCTS-1: products whose TITLE the visitor's typed words name ('do you have a water flosser', 'toothpaste price'), for when no AI
    reads the message. Needs a real title word (4+ letters, plural-tolerant); no hit, or too many hits to be a clear match, gives []. Never raises."""
    try:
        words = {re.sub(r"s$", "", w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 4}
        if not words:
            return []
        hits = []
        for p in _fetch_all(db, org_id):
            title_words = {re.sub(r"s$", "", w) for w in re.findall(r"[a-z0-9]+", str(p.get("title") or "").lower())
                           if len(w) >= 4 and w not in _GENERIC_TITLE_WORDS}
            n = len(words & title_words)
            if n:
                hits.append((n, p))
        if not hits or len(hits) > limit + 1:
            return []
        hits.sort(key=lambda h: h[0], reverse=True)
        top = hits[0][0]
        best = [p for n, p in hits if n == top]
        return best[:limit] if len(best) <= limit else []
    except Exception as exc:
        logger.warning("webchat text_matches failed org=%s: %s", org_id, exc)
        return []


def match_reply(rows: list[dict]) -> str:
    """The sentence that goes with the product cards for a typed product question."""
    if len(rows) == 1:
        p = rows[0]
        price = _num(p.get("price"))
        stock = "" if _stock_state(p, None) is None else " It is out of stock right now."
        return f"Yes, we have the {str(p.get('title') or 'product')[:80]}" + (f" at {_money(price)}." if price > 0 else ".") + stock + " Tap Add to cart below, or tap Shop to see everything."
    return "Here is what we have that matches. Tap Add to cart on the one you want, or tap Shop to see everything."


def search(db, org_id: str, q: Optional[str] = None, limit: int = LIST_LIMIT) -> list[dict]:
    """Cards for the Shop view. A query ranks by word hits in title/description; no query = catalogue order."""
    try:
        rows = _rank(_fetch_all(db, org_id), q)
        return [_card(p) for p in rows[:limit]]
    except Exception as exc:
        logger.warning("webchat shop search failed org=%s: %s", org_id, exc)
        return []


def cards_for(db, org_id: str, ids) -> list[dict]:
    """Cards for AI-suggested product ids; ids that are not in this business's catalogue are dropped."""
    try:
        wanted = [str(i) for i in (ids or []) if i][:3]
        if not wanted:
            return []
        by_id = {str(p["id"]): p for p in _fetch_all(db, org_id)}
        return [_card(by_id[i]) for i in wanted if i in by_id]
    except Exception as exc:
        logger.warning("webchat shop cards failed org=%s: %s", org_id, exc)
        return []


FACT_DESC_CHARS = 300


def facts_for_prompt(db, org_id: str, text: str, viewing_id: Optional[str] = None, limit: int = 6) -> list[dict]:
    """WEBCHAT-CATALOG-1 (CATCHAT-3): what the AI may say about products: id, title, price, in stock or not and a short
    description (about 300 characters). The product the visitor is looking at always comes first."""
    try:
        rows = _fetch_all(db, org_id)
        ranked = _rank(rows, text)[:limit]
        if viewing_id:
            seen = next((p for p in rows if str(p.get("id")) == str(viewing_id)), None)
            if seen:
                ranked = [seen] + [p for p in ranked if str(p.get("id")) != str(viewing_id)][:max(limit - 1, 0)]
        out = []
        for p in ranked:
            desc = " ".join(str(p.get("catalog_description") or p.get("description") or "").split())[:FACT_DESC_CHARS]
            out.append({"id": str(p["id"]), "title": str(p.get("title") or "Product")[:80], "price": _num(p.get("price")),
                        "in_stock": _stock_state(p, None) is None, "blurb": desc})
        return out
    except Exception as exc:
        logger.warning("webchat shop facts failed org=%s: %s", org_id, exc)
        return []


def viewing(db, s: dict, cfg: dict, product_id) -> dict:
    """WEBCHAT-CATALOG-1 (CATCHAT-2): the visitor opened the chat from a product page. Remember the product on the chat
    session and say hello about it, once per product. The id is checked against THIS business's catalogue like an
    AI-suggested id: unknown, other-business or hidden ids are ignored. With the shop off: title and price text only.
    Returns {'messages': [...], 'cards': [...]} (both empty when there is nothing to say). Never raises."""
    empty = {"messages": [], "cards": []}
    try:
        pid = str(product_id or "").strip()[:60]
        if not pid or (s.get("state") or {}).get("viewing") == pid:
            return empty
        p = _fetch_one(db, s["org_id"], pid)
        if not p or not (p.get("title") or "").strip():
            return empty
        card = _card(p)
        shop_on = bool(cfg.get("shop_enabled"))
        out_of_stock = p.get("available") is False
        wc.set_state(db, s, viewing=pid, viewing_title=card["title"])
        text = f"Asking about {card['title']}?"
        if out_of_stock:
            text += " It is out of stock right now. Ask me and I can suggest something similar."
        elif shop_on:
            text += " Here it is. Ask me anything about it, add it to your cart, or tap Shop to see everything else."
        elif card["price"] > 0:
            text += f" It is {_money(card['price'])}. Ask me anything about it."
        else:
            text += " Ask me anything about it."
        msg = wc.append_message(db, s, "bot", text)
        return {"messages": [msg], "cards": [card] if (shop_on and not out_of_stock) else []}
    except Exception as exc:
        logger.warning("webchat viewing failed org=%s: %s", s.get("org_id"), exc)
        return empty


ANSWER_DESC_CHARS = 420


def _cut_at_sentence(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    head = text[:n]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if end >= n // 2:
        return head[:end + 1]
    return head.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."


def product_answer(db, s: dict, cfg: dict, question: str) -> Optional[str]:
    """WEBCHAT-CATALOG-1b: no AI answer was possible (AI off, no credit, ...) but the visitor is looking at a product
    (state.viewing, set from the Storefront). Reply from THIS business's own catalogue text instead of 'I did not catch that':
    the description (about 420 characters, cut at a sentence), the price and whether it is in stock, then the Menu / team line.
    Honest wording: if none of the question's words appear in the description it says it has no more detail. No AI, no cost.
    Returns the text, or None (caller uses the normal fallback). Never raises."""
    try:
        pid = (s.get("state") or {}).get("viewing")
        if not pid:
            return None
        p = _fetch_one(db, s["org_id"], str(pid))
        if not p or not (p.get("title") or "").strip():
            return None
        title = str(p.get("title") or "")[:80]
        desc = " ".join(str(p.get("catalog_description") or p.get("description") or "").split())
        price = _num(p.get("price"))
        in_stock = _stock_state(p, None) is None
        if not desc and price <= 0:
            return None
        words = {w for w in re.findall(r"[a-z0-9]+", (question or "").lower()) if len(w) > 3}
        blob = f"{title} {desc}".lower()
        hit = bool(words) and any(w in blob for w in words)
        lead = f"Here is what we have on {title}:" if hit or not desc else f"I do not have that exact detail. Here is what we have on {title}:"
        parts = [lead]
        if desc:
            parts.append(_cut_at_sentence(desc, ANSWER_DESC_CHARS))
        facts = []
        if price > 0:
            facts.append(f"From {_money(price)}" if len(p.get("variants") or []) > 1 else _money(price))
        facts.append("In stock" if in_stock else "Out of stock right now")
        parts.append(". ".join(facts) + ".")
        parts.append(wc.SCRIPTED_TAIL)
        return " ".join(parts)
    except Exception as exc:
        logger.warning("webchat product_answer failed org=%s: %s", s.get("org_id"), exc)
        return None


def catalogue_for_prompt(db, org_id: str, text: str, limit: int = 6) -> list[dict]:
    """Small id/title/price list handed to the AI so it can suggest real products."""
    return [{"id": c["id"], "title": c["title"], "price": c["price"]} for c in search(db, org_id, text, limit)]


# ── Cart ────────────────────────────────────────────────────────────────────

def _cart(s: dict) -> list[dict]:
    c = (s.get("state") or {}).get("cart")
    return [dict(i) for i in c] if isinstance(c, list) else []


def _totals(cart: list[dict]) -> float:
    return round(sum(_num(i.get("price")) * int(i.get("qty") or 0) for i in cart), 2)


def view(s: dict) -> dict:
    cart = _cart(s)
    return {"items": cart, "total": _totals(cart), "count": sum(int(i.get("qty") or 0) for i in cart)}


def _save(db, s: dict, cart: list[dict]) -> dict:
    wc.set_state(db, s, cart=cart)
    return view(s)


def add(db, s: dict, product_id: str, variant_id: Optional[str], qty: int = 1) -> dict:
    qty = max(1, min(int(qty or 1), MAX_QTY))
    p = _fetch_one(db, s["org_id"], str(product_id or ""))
    if not p:
        return {"error": "That item is no longer available."}
    variants = _variants(p)
    chosen = None
    if variants:
        chosen = next((v for v in variants if v["id"] == str(variant_id or "")), None)
        if not chosen:
            return {"error": "Please choose an option first."}
        price, label = chosen["price"], chosen["label"]
    else:
        price, label = _num(p.get("price")), None
    if price <= 0:
        return {"error": "This item cannot be ordered online. Please ask our team."}
    reason = _stock_state(p, chosen["id"] if chosen else None)          # STORE-1
    if reason:
        return {"error": reason}
    name = str(p.get("title"))[:80] + (f" - {label}" if label and label.lower() not in ("default", "default title", "standard") else "")
    cart = _cart(s)
    key = (str(p["id"]), chosen["id"] if chosen else None)
    for line in cart:
        if (line.get("pid"), line.get("vid")) == key:
            line["qty"] = min(int(line.get("qty") or 0) + qty, MAX_QTY)
            line["price"], line["name"] = price, name
            break
    else:
        if len(cart) >= MAX_LINES:
            return {"error": "Your cart is full. Please check out first."}
        cart.append({"pid": key[0], "vid": key[1], "name": name, "price": price, "qty": qty})
    return _save(db, s, cart)


def remove(db, s: dict, product_id: str, variant_id: Optional[str]) -> dict:
    key = (str(product_id or ""), str(variant_id) if variant_id else None)
    return _save(db, s, [i for i in _cart(s) if (i.get("pid"), i.get("vid")) != key])


def clear(db, s: dict) -> dict:
    return _save(db, s, [])


def _reprice(db, s: dict) -> tuple[list[dict], list[str]]:
    """Fresh prices for every line; lines that are gone or unorderable are dropped and named."""
    kept, dropped = [], []
    for line in _cart(s):
        p = _fetch_one(db, s["org_id"], str(line.get("pid") or ""))
        price = 0.0
        if p and _stock_state(p, line.get("vid")):                       # STORE-1: sold out since it was added
            p = None
        if p:
            vs = _variants(p)
            if vs:
                v = next((x for x in vs if x["id"] == line.get("vid")), None)
                price = v["price"] if v else 0.0
            else:
                price = _num(p.get("price"))
        if price > 0:
            line["price"] = price
            kept.append(line)
        else:
            dropped.append(str(line.get("name") or "an item"))
    return kept, dropped


def _summary(cart: list[dict]) -> str:
    lines = [f"{i['name']} x{i['qty']} = {_money(_num(i['price']) * int(i['qty']))}" for i in cart]
    return "\n".join(lines) + f"\nTotal: {_money(_totals(cart))}"


def checkout(db, s: dict, cfg: dict) -> dict:
    """
    Make a Paystack link for the cart. Returns {messages, cart, checkout_url?, human?} or {"error"}.
    Visitor must have given contact details (the payment is tied to their lead).
    """
    if not s.get("lead_id"):
        return {"error": "Please share your contact details first.", "ask_contact": True}
    cart, dropped = _reprice(db, s)
    if not cart:
        _save(db, s, [])
        return {"error": "Your cart is empty." if not dropped else "Those items are no longer available."}
    total = _totals(cart)
    if total <= 0:
        return {"error": "Your cart is empty."}
    _save(db, s, cart)

    out = [wc.append_message(db, s, "visitor", "Checkout:\n" + _summary(cart))]
    note = (f" (No longer available and removed: {', '.join(dropped)}.)" if dropped else "")
    url = None
    ref = None
    try:
        from app.services.paystack_storefront_service import generate_payment_link
        res = generate_payment_link(db=db, org_id=s["org_id"], lead_id=s["lead_id"], amount=total,
                                    payment_type="full", currency="NGN")
        url = res.get("checkout_url")
        ref = res.get("reference")
    except Exception as exc:
        logger.warning("webchat checkout link failed org=%s: %s", s.get("org_id"), exc)

    wc.log_event(db, s["org_id"], s["id"], "order", s.get("source"), ref=ref)      # WEBCHAT-5b

    if not url:
        wc.set_human(db, s)
        out.append(wc.append_message(db, s, "bot", "Thank you. We could not make a payment link just now, so a team member will "
                                                   "complete your order with you here." + note))
        wc.notify_managers(db, s["org_id"], f"Order request: {s.get('contact_name') or 'web chat visitor'}",
                           _summary(cart)[:500], s["lead_id"], "webchat_order")
        return {"messages": out, "cart": view(s), "human": True}

    out.append(wc.append_message(db, s, "bot", f"Your order:\n{_summary(cart)}\n\nPay securely here: {url}{note}"))
    try:
        from app.services import webchat_followup_service as fu
        fu.send_order_link(db, s, cfg, _summary(cart), url)      # WEBCHAT-4/4b
    except Exception as exc:
        logger.warning("webchat order email hook failed: %s", exc)
    wc.set_state(db, s, cart=[], last_checkout={"total": total, "at": wc._iso(wc._now()), "reference": ref})
    try:
        from app.services import lead_service
        lead_service.write_timeline_event(db, s["org_id"], s["lead_id"], event_type="webchat_order", actor_id=None,
                                          description="Web chat checkout started: " + _summary(cart)[:500],
                                          metadata={"total": total, "lines": len(cart)})
    except Exception as exc:
        logger.warning("webchat order timeline failed: %s", exc)
    wc.notify_managers(db, s["org_id"], f"Checkout started: {s.get('contact_name') or 'web chat visitor'}",
                       f"{_money(total)} - payment link sent in web chat", s["lead_id"], "webchat_order")
    return {"messages": out, "cart": view(s), "checkout_url": url}
