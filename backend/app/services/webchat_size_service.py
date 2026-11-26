"""
app/services/webchat_size_service.py
------------------------------------
SIZE-CONFIRM-1: visitors write sizes their own way ("6*6", "6 by 6", "6x6 14inchi", "72x72", "183 x 203 cm"). Chioma reads the
size, matches it to the closest size in the business's own product options ("Standard king: 6/6 ft."), and ASKS the visitor
to confirm what she understood before she gives any price. Only after a yes does she list the products in that size, each
with that size's own price. No AI, so it is free and works even when the AI is unavailable.

Works for any business whose product options carry two dimensions (mattresses, beds, rugs, bedsheets, tiles, frames). A
business with no such options never sees any of this. Never raises: a problem here means "carry on as normal".
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

FT_MIN, FT_MAX = 2.0, 9.0          # sizes written in feet
IN_MIN, IN_MAX = 30.0, 110.0       # sizes written in inches (72x72)
CM_MIN, CM_MAX = 70.0, 260.0       # sizes written in centimetres (183 x 203)
TOLERANCE_FT = 0.75                # how far the visitor's size may be from an option and still be that option
LIST_MAX = 6                       # products listed after a yes
CHOICES_MAX = 8                    # sizes offered as buttons

_NUM = r"(\d{1,3}(?:\.\d{1,2})?)"
_SEP = r"\s*(?:ft\.?|feet|foot|'|in\.?|inch(?:es)?|cm)?\s*(?:x|×|\*|by|on|/|-)\s*"
_PAIR = re.compile(_NUM + _SEP + _NUM + r"\s*(ft\.?|feet|foot|'|in\.?|inch(?:es|i)?|\"|cm)?", re.I)
_THICK = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:inch(?:es|i)?|in\b|\")(?:\s*thick)?", re.I)
_YES_EXTRA = re.compile(r"^(?:correct|exactly|that'?s (?:it|right|correct)|right|yes o|yes ma|yes sir|confirm(?:ed)?)\b", re.I)
_LIST_Q = re.compile(r"\b(?:all|what|which|available|other|show me|list|your)\b[^?.!]{0,30}\bsizes?\b|\bsizes?\b[^?.!]{0,30}\b(?:available|do you have|you have|are there)\b", re.I)
_BIGGER = re.compile(r"\b(?:bigger|biggest|larger|largest|wider|big size|next size up)\b", re.I)
_SMALLER = re.compile(r"\b(?:smaller|smallest|small size|next size down)\b", re.I)
_UNIT_IN = re.compile(r"^(in\.?|inch(?:es|i)?|\")$", re.I)


def _to_ft(a: float, b: float, unit: str) -> Optional[tuple]:
    """Both numbers in feet, or None when they are not a plausible size (a price, a phone number, a date)."""
    u = (unit or "").lower()
    both_in = IN_MIN <= a <= IN_MAX and IN_MIN <= b <= IN_MAX
    if _UNIT_IN.match(u) or (not u and both_in):           # no unit and both up to 110: inches (72x72), the usual way
        if not both_in:
            return None
        a, b = a / 12.0, b / 12.0
    elif u == "cm" or (not u and CM_MIN <= a <= CM_MAX and CM_MIN <= b <= CM_MAX):
        a, b = a / 30.48, b / 30.48
    if not (FT_MIN <= a <= FT_MAX and FT_MIN <= b <= FT_MAX):
        return None
    return tuple(sorted((round(a, 2), round(b, 2))))


def parse_size(text: str) -> Optional[dict]:
    """{'dims': (w, l) in feet, smaller first, 'thickness': inches or None, 'said': what they typed} or None."""
    t = str(text or "")
    if len(t) > 160:
        return None
    for m in _PAIR.finditer(t):
        a, b, unit = float(m.group(1)), float(m.group(2)), m.group(3) or ""
        dims = _to_ft(a, b, unit)
        if dims:
            rest = t[:m.start()] + " " + t[m.end():]
            th = _THICK.search(rest)
            thick = float(th.group(1)) if th and 4 <= float(th.group(1)) <= 24 else None
            return {"dims": dims, "thickness": thick, "said": m.group(0).strip()}
    return None


def option_size(label: str) -> Optional[tuple]:
    """The size an option label describes, in feet: 'Standard king: 6/6 ft.', 'Grand king 80×80 (6/6.7×6/6.7)',
    'Queen 152 × 203 × 35 cm'. Inches and centimetres are read before feet so '80×80 (6/6.7…)' is 80 by 80 inches."""
    s = str(label or "")
    m = re.search(r"(\d{2,3}(?:\.\d)?)\s*[x×*]\s*(\d{2,3}(?:\.\d)?)(?:\s*[x×*]\s*\d{1,2})?\s*(cm)?", s, re.I)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit = "cm" if (m.group(3) or a > IN_MAX or b > IN_MAX) else "in"
        got = _to_ft(a, b, unit)
        if got:
            return got
    m = re.search(r"(\d(?:\.\d{1,2})?)\s*(?:ft\.?|')?\s*[/x×*]\s*(\d(?:\.\d{1,2})?)\s*(?:ft|feet|')", s, re.I)
    if m:
        return _to_ft(float(m.group(1)), float(m.group(2)), "ft")
    return None


def size_name(label: str) -> str:
    """'Standard king: 6/6 ft.' -> 'Standard king'; 'Queen 152 × 203 × 35 cm' -> 'Queen'; a bare size keeps itself."""
    s = str(label or "").strip()
    name = re.split(r"[:(]|\s\d", s, maxsplit=1)[0].strip(" -–:,.")
    return name or s.rstrip(".")


def nice_ft(dims: tuple) -> str:
    def one(x: float) -> str:
        return str(int(round(x))) if abs(x - round(x)) < 0.05 else f"{x:.1f}".rstrip("0").rstrip(".")
    return f"{one(dims[0])} by {one(dims[1])} ft"


def catalogue_sizes(rows: list) -> list:
    """Every sized option in the catalogue: [{'label', 'name', 'dims', 'product', 'price', 'in_stock'}]."""
    from app.services import webchat_shop_service as shop
    out = []
    for p in rows or []:
        if p.get("available") is False:
            continue
        for v in p.get("variants") or []:
            label = str(v.get("title") or v.get("option1") or "").strip()
            dims = option_size(label)
            if not dims:
                continue
            out.append({"label": label, "name": size_name(label), "dims": dims, "product": p,
                        "price": shop._num(v.get("price")) or shop._num(p.get("price")), "in_stock": shop._variant_in_stock(v)})
    return out


def _dist(a: tuple, b: tuple) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def best_size(sizes: list, dims: tuple) -> Optional[dict]:
    """The catalogue size closest to what the visitor typed (exact first), or None when nothing is close enough."""
    near = [z for z in sizes if _dist(z["dims"], dims) <= TOLERANCE_FT]
    if not near:
        return None
    return min(near, key=lambda z: (round(_dist(z["dims"], dims), 2), -sum(1 for y in sizes if y["name"] == z["name"])))


def size_menu(sizes: list) -> list:
    """One button per size name, smallest first (labels as the business wrote them, so a tap reads back exactly)."""
    seen, out = set(), []
    for z in sorted(sizes, key=lambda z: (z["dims"][0] * z["dims"][1], z["name"])):
        key = z["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(z)
    return out[:CHOICES_MAX]


def _confirm_text(z: dict, thickness: Optional[float]) -> str:
    th = f", {thickness:g} inches thick" if thickness else ""
    return f"Just to be sure, you mean the {z['name']} size, {nice_ft(z['dims'])}{th}? 😊"


def _confirmed(db, s: dict, sizes: list, z: dict, thickness: Optional[float]) -> dict:
    from app.services import webchat_service as wc
    wc.set_state(db, s, size_last=z["name"])            # remembered, so "bigger size" later means the next one up
    t, ids = _products_text(sizes, z, thickness)
    return _reply(t, cards=ids)


def _products_text(sizes: list, z: dict, thickness: Optional[float]) -> tuple:
    """The reply after a yes, and the product ids for cards."""
    same = [y for y in sizes if y["name"].lower() == z["name"].lower() and y["in_stock"]]
    seen, rows = set(), []
    for y in sorted(same, key=lambda y: y["price"] or 0):
        title = str(y["product"].get("title") or "").strip()
        key = re.sub(r"[^a-z0-9]", "", title.lower())
        if key in seen:
            continue                                  # the same product listed twice (e.g. "X Black" and "X - Black")
        seen.add(key)
        rows.append(y)
    if not rows:
        return (f"I'm sorry, the {z['name']} size ({nice_ft(z['dims'])}) is out of stock right now. I can pass you to the team to check when it is back.", [])
    from app.services import webchat_shop_service as shop
    lines = "; ".join(f"{y['product']['title']} {shop._money(y['price'])}" for y in rows[:LIST_MAX] if y["price"])
    more = f" and {len(rows) - LIST_MAX} more" if len(rows) > LIST_MAX else ""
    text = f"Great! In {z['name']} ({nice_ft(z['dims'])}) we have: {lines}{more}."
    if thickness:
        text += f" For the {thickness:g}-inch thickness, the team can confirm which one fits."
    return text, [str(y["product"]["id"]) for y in rows[:3]]


def _reply(text: str, choices=None, cards=None) -> dict:
    out = {"text": text, "choices": choices or [], "cards_ids": cards or []}
    return out


def handle(db, s: dict, cfg: dict, text: str) -> Optional[dict]:
    """Called for every typed message when the business shows products in the chat. Returns a reply
    {'text', 'choices', 'cards_ids'} or None to carry on as normal. Keeps its own step in the chat's state ('size_ask')."""
    from app.services import webchat_service as wc
    from app.services import webchat_shop_service as shop
    from app.services import webchat_contact_service as contact
    try:
        if not (cfg.get("shop_enabled") or cfg.get("products_read")):
            return None
        pend = (s.get("state") or {}).get("size_ask")
        last = (s.get("state") or {}).get("size_last")                # the size they confirmed earlier in this chat
        said = parse_size(text)
        wants_list = not said and bool(_LIST_Q.search(text or ""))
        rel = None if said else ("up" if _BIGGER.search(text or "") else "down" if _SMALLER.search(text or "") else None)
        if not pend and not said and not wants_list and not rel:
            return None                                # most messages: nothing to do, no database trip
        sizes = catalogue_sizes(shop._fetch_all(db, s["org_id"]))
        if not sizes:
            return None
        yes_no = [{"id": "say", "label": "Yes"}, {"id": "say", "label": "No"}]
        menu = size_menu(sizes)
        if (wants_list or rel) and not pend:
            if rel and last:                             # "bigger size" after a confirmed size: the next one up (or down), confirmed first
                i = next((k for k, y in enumerate(menu) if y["name"].lower() == last.lower()), None)
                j = None if i is None else (i + 1 if rel == "up" else i - 1)
                if j is not None and 0 <= j < len(menu):
                    z = menu[j]
                    wc.set_state(db, s, size_ask={"name": z["name"], "thickness": None})
                    return _reply(_confirm_text(z, None), choices=yes_no)
                if j is not None:
                    edge = "biggest" if rel == "up" else "smallest"
                    wc.set_state(db, s, size_ask={"name": None, "thickness": None})
                    return _reply(f"The {last} is our {edge} size. Here are all our sizes, which one would you like?",
                                  choices=[{"id": "say", "label": y["label"][:40]} for y in menu])
            wc.set_state(db, s, size_ask={"name": None, "thickness": None})
            lead = ("Sure! Which size do you have in mind? Here they are, from smallest to biggest."
                    if rel else "Here are our sizes, from smallest to biggest. Which one would you like?")
            return _reply(lead, choices=[{"id": "say", "label": y["label"][:40]} for y in menu])
        if pend:
            wc.set_state(db, s, size_ask=None)          # asked once: whatever they say next settles it
            low = str(text or "").strip().lower().rstrip(". ")
            picked = next((z for z in sizes if z["label"].lower().rstrip(". ") == low), None)
            if not picked and not pend.get("name") and not said:      # after the size list they typed a size name ("standard king")
                named = [z for z in sizes if re.search(r"\b" + re.escape(z["name"].lower()) + r"\b", low)]
                picked = max(named, key=lambda z: len(z["name"])) if named else None
            if picked:                                  # chose a size from our own list: that is their confirmation
                return _confirmed(db, s, sizes, picked, pend.get("thickness"))
            if pend.get("name") and (contact.is_yes(text) or _YES_EXTRA.match(low)):
                z = next((y for y in sizes if y["name"].lower() == pend["name"].lower()), None)
                if z:
                    return _confirmed(db, s, sizes, z, pend.get("thickness"))
            if pend.get("name") and contact.is_no(text) and not said:      # "no, 6 by 7" is a new size: read back below
                wc.set_state(db, s, size_ask={"name": None, "thickness": pend.get("thickness")})
                return _reply("No problem. Which of our sizes do you need?",
                              choices=[{"id": "say", "label": z["label"][:40]} for z in size_menu(sizes)])
            if not said and (wants_list or rel):
                wc.set_state(db, s, size_ask={"name": None, "thickness": pend.get("thickness")})
                return _reply("Here are our sizes, from smallest to biggest. Which one would you like?",
                              choices=[{"id": "say", "label": y["label"][:40]} for y in menu])
            if not said:
                return None                             # they moved on to something else: answer that as normal
        z = best_size(sizes, said["dims"])
        if not z:
            wc.set_state(db, s, size_ask={"name": None, "thickness": said.get("thickness")})
            return _reply(f"I don't think we have {nice_ft(said['dims'])}. These are the sizes we have, which one would you like?",
                          choices=[{"id": "say", "label": y["label"][:40]} for y in size_menu(sizes)])
        wc.set_state(db, s, size_ask={"name": z["name"], "thickness": said.get("thickness")})
        return _reply(_confirm_text(z, said.get("thickness")), choices=yes_no)
    except Exception as exc:
        logger.warning("webchat size step failed org=%s: %s", s.get("org_id"), exc)
        return None


def sizes_for_prompt(p: dict, limit: int = 8) -> str:
    """'Standard king 6 by 6 ft N625,000; Queen 5 by 6 ft N...' for the AI's product list ('' when the product has no sized options)."""
    from app.services import webchat_shop_service as shop
    parts = []
    for v in (p.get("variants") or [])[:limit]:
        label = str(v.get("title") or "").strip()
        dims = option_size(label)
        if not dims:
            continue
        price = shop._num(v.get("price")) or shop._num(p.get("price"))
        parts.append(f"{size_name(label)} {nice_ft(dims)}" + (f" N{price:,.0f}" if price else ""))
    return "; ".join(parts)
