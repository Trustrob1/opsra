"""
backend/app/services/site_import_slotting.py
SITE-IMPORT 2 - makes an uploaded page editable WITHOUT letting a model touch it.

Claude is shown an outline of the page (element ids, tags, classes, text) and returns a PLAN: which element is the business name,
which elements are the repeated cards of `items`, which link is the WhatsApp button. This module then
  * checks the plan against the page (outline() / apply_plan()),
  * writes the slot markers into the page's own source - only whole attributes are added, nothing else changes,
  * reads the content (text, prices, WhatsApp number) straight out of the page, so no word is ever written by a model,
  * proves the result (compare()): filling the marked page with that content must give back the original page.
  fill() is the renderer for a marked page: slots replaced by the site's content, everything else untouched, scripts and
  styles byte for byte.

Marker vocabulary is the Premium one (SITE-PREMIUM spec section 6): data-slot, data-format, data-slot-img, data-slot-href,
data-repeat. data-if / data-section are not produced at Level 2. Pure functions, no I/O, no network.
"""
from __future__ import annotations

import re
from html import escape, unescape
from typing import Any, Optional

from app.services import site_import_dom as dom
from app.services.site_import_dom import Elem, Raw, Text

MARKERS = ("data-slot", "data-slot-img", "data-slot-href", "data-slot-alt", "data-repeat", "data-format", "data-if", "data-section")
MAX_REPEAT = 60
MAX_OUTLINE_CHARS = 60_000
MAX_PLAN_ITEMS = 400
LINK_KINDS = ("whatsapp", "phone", "instagram")      # 'maps' is not offered at Level 2: its address cannot be read back from a link
_PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.([a-z_][a-z0-9_]*|[0-9]{1,2}))*$")
_CUSTOM_RE = re.compile(r"^custom\.[a-z][a-z0-9_]{0,40}$")
_SKIP_OUTLINE = frozenset({"script", "style", "noscript", "template", "head", "svg", "iframe"})


class PlanError(Exception):
    def __init__(self, errors: list):
        super().__init__("; ".join(errors[:3]))
        self.errors = errors


# ------------------------------------------------------------------ outline (what Claude sees)

def _sig(el: Elem, depth: int = 2) -> str:
    kids = "" if depth == 0 else ",".join(_sig(c, depth - 1) for c in el.children if isinstance(c, Elem) and c.tag not in dom.RAW_TEXT)
    return f"{el.tag}.{'.'.join(sorted((el.attrs.get('class') or '').split()))}[{kids}]"


def _line(el: Elem, depth: int) -> str:
    bits = [el.tag]
    if el.attrs.get("id"):
        bits[0] += "#" + el.attrs["id"][:30]
    cls = (el.attrs.get("class") or "").split()[:3]
    if cls:
        bits[0] += "." + ".".join(cls)
    for a in ("href", "src", "alt", "type"):
        if el.attrs.get(a):
            bits.append(f'{a}="{el.attrs[a][:90]}"')
    line = "  " * depth + f"{el.id} <{' '.join(bits)}>"
    if dom.is_leaf_text(el):
        t = dom.text_of(el)
        if t:
            line += f' "{t[:140]}{"…" if len(t) > 140 else ""}"'
    else:
        direct = " ".join(" ".join(unescape(c.raw) for c in el.children if isinstance(c, Text)).split())
        if direct:
            line += f' ~"{direct[:80]}{"…" if len(direct) > 80 else ""}" (mixed: text and elements)'
    return line


def outline(root: Elem) -> str:
    """One line per element of <body>. A run of 4+ identical siblings (cards) shows its first two and lists the ids of the rest."""
    body = dom.find(root, "body") or root
    lines: list = []

    def walk(el: Elem, depth: int):
        kids = [c for c in el.children if isinstance(c, Elem)]
        i = 0
        while i < len(kids):
            k = kids[i]
            if k.tag in _SKIP_OUTLINE:
                lines.append("  " * depth + f"{k.id} <{k.tag}> (not shown)")
                i += 1
                continue
            sig = _sig(k)
            j = i
            while j < len(kids) and kids[j].tag not in _SKIP_OUTLINE and _sig(kids[j]) == sig:
                j += 1
            run = kids[i:j]
            if len(run) >= 4:
                for r in run[:2]:
                    lines.append(_line(r, depth))
                    walk(r, depth + 1)
                lines.append("  " * depth + f"… {len(run) - 2} more like {run[0].id}: " + ", ".join(r.id for r in run[2:]))
                i = j
            else:
                lines.append(_line(k, depth))
                walk(k, depth + 1)
                i += 1
    walk(body, 0)
    text = "\n".join(lines)
    return text if len(text) <= MAX_OUTLINE_CHARS else text[:MAX_OUTLINE_CHARS] + "\n… (outline cut: the page is very large)"


# ------------------------------------------------------------------ small helpers

def _set_path(content: dict, path: str, value: Any) -> None:
    cur: Any = content
    segs = path.split(".")
    for n, seg in enumerate(segs):
        last = n == len(segs) - 1
        nxt = segs[n + 1] if not last else None
        if seg.isdigit():
            i = int(seg)
            while len(cur) <= i:
                cur.append("")
            if last:
                cur[i] = value
            else:
                if not cur[i]:
                    cur[i] = [] if nxt.isdigit() else {}
                cur = cur[i]
        else:
            if last:
                cur[seg] = value
            else:
                if seg not in cur or not cur[seg]:
                    cur[seg] = [] if nxt.isdigit() else {}
                cur = cur[seg]


_PRICE_RX = re.compile(r"(\d[\d,]*(?:\.\d{1,2})?)")


def parse_price(text: str, fmt: str) -> tuple:
    """(number, price_style) from page text such as '₦2,500', 'From ₦2,500' or 'Price on request'."""
    t = text.strip()
    if fmt == "price" and t.lower() == "price on request":
        return 0.0, "on_request"
    style = "exact"
    if fmt == "price" and t.lower().startswith("from"):
        style, t = "from", t[4:].strip()
    if not t.startswith("₦"):
        raise ValueError(f"'{text}' is not written like ₦2,500, so it cannot be an editable price")
    m = _PRICE_RX.fullmatch(t[1:].strip())
    if not m:
        raise ValueError(f"'{text}' is not a plain price")
    return float(m.group(1).replace(",", "")), style


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def whatsapp_number(href: str) -> Optional[str]:
    m = re.match(r"^https?://(?:wa\.me/|api\.whatsapp\.com/send\?(?:[^#]*&)?phone=)(\+?\d{8,18})", (href or "").strip(), re.I)
    return m.group(1).lstrip("+") if m else None


def _kind_info(kind: str, el: Elem) -> tuple:
    """(content path, value) read from a link, or raises ValueError (plain words)."""
    href = (el.attrs.get("href") or "").strip()
    if kind == "whatsapp":
        n = whatsapp_number(href)
        if not n:
            raise ValueError("is not a wa.me or api.whatsapp.com/send WhatsApp link")
        return "business.whatsapp_e164", "+" + n
    if kind == "phone":
        if not re.fullmatch(r"tel:\+\d{8,18}", href):
            raise ValueError("is not a tel:+countrycode link (leave other phone links as they are)")
        return "business.phone_display", href[4:]
    if kind == "instagram":
        m = re.match(r"^https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,40})/?(?:\?.*)?$", href)
        if not m:
            raise ValueError("is not an instagram.com/handle link")
        return "business.instagram", m.group(1)
    raise ValueError(f"link kind '{kind}' is not one of: {', '.join(LINK_KINDS)}")


# ------------------------------------------------------------------ applying a plan

def _check_plan_shape(plan: Any) -> list:
    errs: list = []
    if not isinstance(plan, dict):
        return ["The plan must be a JSON object."]
    for key in ("slots", "images", "links", "repeats"):
        if not isinstance(plan.get(key, []), list):
            errs.append(f"plan.{key} must be a list")
    n = sum(len(plan.get(k) or []) for k in ("slots", "images", "links", "repeats"))
    if n > MAX_PLAN_ITEMS:
        errs.append("The plan is too large.")
    return errs


def _slot_items(items: Any, label: str, errs: list) -> list:
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not isinstance(it.get("el"), str):
            errs.append(f"{label}: every entry needs an 'el' id")
            continue
        out.append(it)
    return out


def apply_plan(html: str, plan: Any, asset_for=None) -> dict:
    """Returns {"skeleton", "content", "errors", "warnings", "images"}. When errors is non-empty the skeleton/content are not usable.
    The page is parsed from `html` (the already cleaned page); `plan` is Claude's answer.
    Pictures: every slotted <img> is reported in "images" as {"src", "where"}; when `asset_for(src)` is given (the job registers the
    page's own files as site photos) the returned id is written into the content (hero.image_asset_id, items.N.image_asset_id ...),
    so the editor can swap each photo and the filled page shows the right one per card."""
    errors = _check_plan_shape(plan)
    if errors:
        return {"skeleton": "", "content": {}, "errors": errors, "warnings": [], "images": []}
    root = dom.parse(html)
    index = dom.assign_ids(root)
    body = dom.find(root, "body")
    errors, warnings = [], []
    if body is None:
        return {"skeleton": "", "content": {}, "errors": ["The page has no <body>."], "warnings": [], "images": []}
    for el in index.values():
        if any(m in el.attrs for m in MARKERS):
            return {"skeleton": "", "content": {}, "errors": [f"{el.id}: the page already contains Opsra slot markers."], "warnings": [], "images": []}

    marks: dict = {}                       # Elem -> {attr: value}
    content: dict = {}
    claimed: set = set()                   # element ids already used by one slot
    wa_numbers: set = set()

    def el_of(eid: str, label: str, allowed_inside: Optional[Elem] = None) -> Optional[Elem]:
        el = index.get(eid)
        if el is None:
            errors.append(f"{label}: element {eid} does not exist")
            return None
        if not dom.is_inside(el, frozenset({"#root"})) and el.parent is None:
            return None
        if el.tag in dom.RAW_TEXT or dom.is_inside(el, dom.RAW_TEXT | {"head", "svg", "template", "noscript", "textarea"}):
            errors.append(f"{label}: {eid} <{el.tag}> is not page content")
            return None
        if body not in list(dom.ancestors(el)) and el is not body:
            errors.append(f"{label}: {eid} is outside the page body")
            return None
        if eid in claimed:
            errors.append(f"{label}: element {eid} is used by more than one slot")
            return None
        return el

    def text_value(el: Elem, label: str) -> Optional[str]:
        if not dom.is_leaf_text(el):
            errors.append(f"{label}: {el.id} <{el.tag}> holds other elements, so a text slot would lose them. "
                          f"Slot the inner element that holds only text")
            return None
        t = dom.text_of(el)
        if not t:
            errors.append(f"{label}: {el.id} has no text")
            return None
        return t

    def valid_path(path: Any, label: str) -> bool:
        if not isinstance(path, str) or not (path == "." or _PATH_RE.match(path) or _CUSTOM_RE.match(path)):
            errors.append(f"{label}: '{path}' is not a valid content path")
            return False
        return True

    def do_slots(items, scope_label: str, in_repeat: bool, put):
        for it in _slot_items(items, scope_label, errors):
            el = el_of(it["el"], scope_label)
            path, fmt = it.get("path"), it.get("format")
            if el is None or not valid_path(path, scope_label):
                continue
            if fmt not in (None, "", "naira", "price"):
                errors.append(f"{scope_label}: format '{fmt}' is not naira or price")
                continue
            if in_repeat and _CUSTOM_RE.match(path):
                errors.append(f"{scope_label}: custom fields are not allowed inside a repeated block ({path})")
                continue
            txt = text_value(el, scope_label)
            if txt is None:
                continue
            claimed.add(el.id)
            m = marks.setdefault(el, {})
            m["data-slot"] = path
            if fmt:
                m["data-format"] = fmt
            put(path, el, txt, fmt)

    def do_images(items, label: str, in_repeat: bool):
        for it in _slot_items(items, label, errors):
            el = el_of(it["el"], label)
            path = it.get("path")
            if el is None or not valid_path(path, label):
                continue
            if el.tag != "img" or not el.attrs.get("src"):
                errors.append(f"{label}: {el.id} <{el.tag}> is not an <img> with a src")
                continue
            claimed.add(el.id)
            marks.setdefault(el, {})["data-slot-img"] = path
            image_refs.append({"src": el.attrs["src"], "where": (None, None, _asset_key(path))})

    def do_links(items, label: str):
        for it in _slot_items(items, label, errors):
            el = el_of(it["el"], label)
            kind = it.get("kind")
            if el is None:
                continue
            if el.tag != "a":
                errors.append(f"{label}: {el.id} <{el.tag}> is not a link")
                continue
            try:
                path, value = _kind_info(str(kind), el)
            except ValueError as exc:
                errors.append(f"{label}: link {el.id} {exc}")
                continue
            claimed.add(el.id)
            marks.setdefault(el, {})["data-slot-href"] = kind
            if kind == "whatsapp":
                wa_numbers.add(value)
            else:
                prev = _get(content, path)
                if prev not in (None, "", value):
                    errors.append(f"{label}: links of kind {kind} point to different values ({prev} and {value})")
                _set_path(content, path, value)

    def top_put(path, el, txt, fmt):
        if fmt:
            try:
                num, style = parse_price(txt, fmt)
            except ValueError as exc:
                errors.append(str(exc))
                return
            _set_path(content, path, num)
            return
        _set_path(content, path, txt)

    # ---- repeats first, so top-level checks can exclude their elements
    repeat_inner: set = set()
    repeats = []
    for n, rp in enumerate(plan.get("repeats") or [], 1):
        label = f"repeat {n}"
        if not isinstance(rp, dict) or not valid_path(rp.get("path"), label) or _CUSTOM_RE.match(str(rp.get("path"))) or rp.get("path") == ".":
            errors.append(f"{label}: needs a list path such as 'items'")
            continue
        ids = rp.get("instances")
        if not isinstance(ids, list) or len(ids) < 1 or not all(isinstance(i, str) for i in ids):
            errors.append(f"{label}: 'instances' must list the element ids of each repeated block")
            continue
        if len(ids) > MAX_REPEAT:
            errors.append(f"{label}: more than {MAX_REPEAT} blocks")
            continue
        missing = [i for i in ids if i not in index]
        for i in missing:
            errors.append(f"{label}: element {i} does not exist")
        if missing:
            continue
        inst = [index[i] for i in ids]
        if len({id(e.parent) for e in inst}) != 1 or len({e.tag for e in inst}) != 1:
            errors.append(f"{label}: the blocks must be siblings of the same kind of element")
            continue
        repeats.append((rp, inst, label))
        for e in inst:
            repeat_inner.add(e.id)
            repeat_inner.update(x.id for x in dom.iter_elems(e))

    image_refs: list = []

    for rp, inst, label in repeats:
        path = rp["path"]
        template = inst[0]
        marks.setdefault(template, {})["data-repeat"] = path
        claimed.add(template.id)
        within = {template.id} | {x.id for x in dom.iter_elems(template)}

        slotted: list = []                      # (kind_key, template element, spec)
        used_ids: set = set()
        for kind_key in ("slots", "images", "links"):
            for it in _slot_items(rp.get(kind_key), f"{label} {kind_key}", errors):
                el = index.get(it["el"])
                if el is None or el.id not in within:
                    errors.append(f"{label}: {it['el']} is not inside the first block ({template.id})")
                    continue
                if el.id in used_ids:
                    errors.append(f"{label}: element {el.id} is used twice")
                    continue
                if kind_key != "links" and not valid_path(it.get("path"), f"{label} {el.id}"):
                    continue
                used_ids.add(el.id)
                slotted.append((kind_key, el, it))
        slot_ids = {el.id for _k, el, _i in slotted}

        # line every other block up with the first one; a difference that no slot explains is an error
        maps: list = [{e: e for e in [template] + list(dom.iter_elems(template))}]
        for inst_el in inst[1:]:
            mapping: dict = {}
            _align(template, inst_el, slot_ids, mapping, errors, label)
            maps.append(mapping)

        entries: list = [dict() for _ in inst]
        for kind_key, el, it in slotted:
            lab = f"{label} {el.id}"
            spath = it.get("path")
            if kind_key == "slots":
                fmt = it.get("format")
                if fmt not in (None, "", "naira", "price"):
                    errors.append(f"{lab}: format '{fmt}' is not naira or price")
                    continue
                if _CUSTOM_RE.match(spath):
                    errors.append(f"{lab}: custom fields are not allowed inside a repeated block")
                    continue
                if not dom.is_leaf_text(el):
                    errors.append(f"{lab}: {el.id} holds other elements, so a text slot would lose them")
                    continue
                m = marks.setdefault(el, {})
                m["data-slot"] = spath
                if fmt:
                    m["data-format"] = fmt
                claimed.add(el.id)
                for k in range(len(inst)):
                    target = maps[k].get(el)
                    if target is None:
                        continue                                  # an optional element this block does not have
                    if not dom.is_leaf_text(target):
                        errors.append(f"{lab}: block {inst[k].id} has other elements inside {target.id}, so its text cannot be a slot")
                        continue
                    txt = dom.text_of(target)
                    if not txt:
                        continue
                    try:
                        if fmt:
                            num, style = parse_price(txt, fmt)
                            _set_path(entries[k], spath, num)
                            if fmt == "price" and style != "exact":
                                entries[k]["price_style"] = style
                        elif spath == ".":
                            entries[k] = txt
                        else:
                            _set_path(entries[k], spath, txt)
                    except ValueError as exc:
                        errors.append(f"{lab}: {exc}")
            elif kind_key == "images":
                if el.tag != "img" or not el.attrs.get("src"):
                    errors.append(f"{lab}: not an <img> with a src")
                    continue
                marks.setdefault(el, {})["data-slot-img"] = spath
                claimed.add(el.id)
                key = _asset_key(spath)
                for k in range(len(inst)):
                    target = maps[k].get(el)
                    if target is not None and target.attrs.get("src"):
                        image_refs.append({"src": target.attrs["src"], "where": (path, k, key)})
            else:
                if el.tag != "a":
                    errors.append(f"{lab}: not a link")
                    continue
                kind = it.get("kind")
                for k in range(len(inst)):
                    target = maps[k].get(el)
                    if target is None:
                        continue
                    try:
                        p, v = _kind_info(str(kind), target)
                    except ValueError as exc:
                        errors.append(f"{lab}: link {target.id} {exc}")
                        continue
                    if kind == "whatsapp":
                        wa_numbers.add(v)
                marks.setdefault(el, {})["data-slot-href"] = kind
                claimed.add(el.id)

        # a picture's alt text that differs from card to card must come from the card's own text (its name)
        for kind_key, el, it in slotted:
            if kind_key != "images" or el not in marks:
                continue
            alts = [(maps[k].get(el).attrs.get("alt", "") if maps[k].get(el) is not None else "") for k in range(len(inst))]
            if len(set(alts)) <= 1:
                continue
            def text_slot(match_alts: bool):
                for kk, e2, sp in slotted:
                    if kk != "slots" or sp.get("format") or sp.get("path") in (".", None):
                        continue
                    if match_alts and not all(isinstance(entries[k], dict) and entries[k].get(sp["path"]) == alts[k] for k in range(len(inst))):
                        continue
                    if not match_alts and sp["path"] != "name":
                        continue
                    return sp["path"]
                return None
            source = text_slot(True)
            if source:
                marks[el]["data-slot-alt"] = source
                continue
            source = text_slot(False)
            if source:
                marks[el]["data-slot-alt"] = source
                warnings.append(f"{label}: the pictures' alt texts differ from the block names; they will use the block name instead")
            else:
                errors.append(f"{label}: the pictures in the blocks have different alt texts ({alts[0][:30]!r}, {alts[1][:30]!r}) and the blocks "
                              f"have no name slot to take them from (give the pictures the same alt text, or slot the block's name)")

        _set_path(content, path, entries)

    # ---- everything outside repeats
    def outside_check(items):
        return [it for it in _slot_items(items, "slot", errors) if it.get("el") not in repeat_inner]

    for kind_key in ("slots", "images", "links"):
        for it in _slot_items(plan.get(kind_key), kind_key, errors):
            if it.get("el") in repeat_inner:
                errors.append(f"{kind_key}: {it['el']} is inside a repeated block; list it under that repeat instead")
    do_slots(outside_check(plan.get("slots")), "slot", False, top_put)
    do_images(outside_check(plan.get("images")), "image", False)
    do_links(outside_check(plan.get("links")), "link")

    if len(wa_numbers) > 1:
        errors.append("The WhatsApp links point to different numbers: " + ", ".join(sorted(wa_numbers)))
    if wa_numbers:
        _set_path(content, "business.whatsapp_e164", sorted(wa_numbers)[0])
    else:
        errors.append("The page has no WhatsApp link (a wa.me/number link). Level 2 needs one, because the editor and WhatsApp EDIT need the business number.")

    if errors:
        return {"skeleton": "", "content": {}, "errors": _dedupe(errors), "warnings": warnings, "images": []}

    # ---- pictures: the page's own files become site photos (when the caller can do that)
    for ref in image_refs:
        where_path, k, key = ref["where"]
        asset_id = asset_for(ref["src"]) if asset_for else None
        ref["asset_id"] = asset_id
        if asset_id:
            if where_path is None:
                _set_path(content, key, asset_id)
            else:
                content[where_path][k][key] = asset_id
        elif where_path is not None and len({r["src"] for r in image_refs if r["where"][0] == where_path and r["where"][2] == key}) > 1:
            errors.append(f"The pictures of the '{where_path}' blocks differ but could not be registered as photos ({ref['src']}). "
                          f"Use jpg, png or webp pictures that are part of the upload.")
    if errors:
        return {"skeleton": "", "content": {}, "errors": _dedupe(errors), "warnings": warnings, "images": []}

    # ---- remove the other blocks of each repeat, then write the markers
    for rp, inst, _label in repeats:
        for extra in inst[1:]:
            _drop(extra)
    _apply_marks(marks)
    skeleton = dom.serialise(root)
    return {"skeleton": skeleton, "content": content, "errors": [], "warnings": warnings,
            "images": [{"src": r["src"], "asset_id": r.get("asset_id")} for r in image_refs]}


def _dedupe(items: list) -> list:
    out: list = []
    for i in items:
        if i not in out:
            out.append(i)
    return out[:25]


def _get(d: Any, path: str) -> Any:
    cur = d
    for s in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(s)
        elif isinstance(cur, list) and s.isdigit() and int(s) < len(cur):
            cur = cur[int(s)]
        else:
            return None
    return cur


def _drop(el: Elem) -> None:
    """Removes an element and the whitespace text just before it from its parent."""
    p = el.parent
    if p is None:
        return
    i = p.children.index(el)
    del p.children[i]
    if i > 0 and isinstance(p.children[i - 1], Text) and not p.children[i - 1].raw.strip():
        del p.children[i - 1]


def _apply_marks(marks: dict) -> None:
    for el, attrs in marks.items():
        el.raw_start = dom.set_attrs(el.raw_start, attrs)
        el.attrs.update(attrs)


def _asset_key(path: str) -> str:
    return path if path.endswith("_asset_id") else path + "_asset_id"


def _own_text(el: Elem) -> str:
    return " ".join(" ".join(unescape(c.raw) for c in el.children if isinstance(c, Text)).split())


def _align(a: Elem, b: Elem, slot_ids: set, mapping: dict, errors: list, label: str) -> None:
    """Lines block b up with the first block a, element by element. Differences are allowed only where a slot carries them
    (the slotted element's text, an image's src, a link's href) or where a slotted element is simply absent from b."""
    if a.tag != b.tag:
        errors.append(f"{label}: block {b.id} has <{b.tag}> where the first block has <{a.tag}> ({a.id})")
        return
    mapping[a] = b
    if a.id in slot_ids:
        for e1, e2 in zip(dom.iter_elems(a), dom.iter_elems(b)):
            mapping[e1] = e2
        return
    for k in sorted(set(a.attrs) | set(b.attrs)):
        if a.attrs.get(k) != b.attrs.get(k):
            errors.append(f"{label}: {b.id} differs from {a.id} in its '{k}' attribute and has no slot for it "
                          f"(make the blocks match, or leave this repeat out)")
            return
    ak = [c for c in a.children if isinstance(c, Elem)]
    bk = [c for c in b.children if isinstance(c, Elem)]
    j = 0
    for ae in ak:
        if j < len(bk) and bk[j].tag == ae.tag:
            _align(ae, bk[j], slot_ids, mapping, errors, label)
            j += 1
        elif ae.id not in slot_ids:
            errors.append(f"{label}: {b.id} has no <{ae.tag}> where {a.id} has one ({ae.id}), and that element is not a slot")
            return
    if j < len(bk):
        errors.append(f"{label}: {b.id} has an extra <{bk[j].tag}> that {a.id} does not have")
        return
    if _own_text(a) != _own_text(b):
        errors.append(f"{label}: the text of {b.id} differs from {a.id} (\"{_own_text(a)[:40]}\" / \"{_own_text(b)[:40]}\") but has no slot")


# ------------------------------------------------------------------ filling (the renderer for a marked page)

def _renderer():
    from app.services import site_premium_renderer as r
    return r


def _format_value(value: Any, fmt: str, ctx) -> str:
    return _renderer()._format(value, fmt, ctx)


def fill(skeleton: str, content: dict, assets_by_id: Optional[dict] = None, export: bool = False) -> str:
    """The page: slots replaced by the site's content, every other byte of the skeleton as it was."""
    r = _renderer()
    root = dom.parse(skeleton)
    ctx = r.Ctx(content=content or {}, assets=assets_by_id or {}, export=export)
    out: list = []
    _fill_nodes(root.children, ctx, out, r)
    return "".join(out)


def _fill_nodes(nodes: list, ctx, out: list, r) -> None:
    for pos, n in enumerate(nodes):
        if isinstance(n, (Text, Raw)):
            out.append(n.raw)
            continue
        _fill_elem(n, ctx, out, r, nodes, pos)


def _clean_start(el: Elem, extra: Optional[dict] = None, drop: tuple = MARKERS) -> str:
    raw = dom.strip_attrs(el.raw_start, drop)
    return dom.set_attrs(raw, extra) if extra else raw


def _fill_elem(el: Elem, ctx, out: list, r, siblings: list, pos: int) -> None:
    a = el.attrs
    if "data-repeat" in a:
        items = ctx.lookup(a["data-repeat"])
        if not isinstance(items, list) or not items:
            return
        lead = siblings[pos - 1].raw if pos > 0 and isinstance(siblings[pos - 1], Text) and not siblings[pos - 1].raw.strip() else ""
        for k, item in enumerate(items[:MAX_REPEAT]):
            if k:
                out.append(lead)
            inner = Elem(el.tag, {x: y for x, y in a.items() if x != "data-repeat"}, dom.strip_attrs(el.raw_start, ("data-repeat",)), el.void)
            inner.children, inner.raw_end = el.children, el.raw_end
            _fill_elem(inner, ctx.child(item), out, r, [inner], 0)
        return
    if "data-if" in a:
        present = r._present(ctx.lookup(a["data-if"].lstrip("!")))
        if present == a["data-if"].startswith("!"):
            return
    if "data-slot-img" in a:
        asset_id = r._image_value(a["data-slot-img"], ctx)
        asset = ctx.assets.get(asset_id) if asset_id else None
        url = (asset.get("export_path") if ctx.export else asset.get("public_url")) if asset else None
        extra: dict = {}
        if a.get("data-slot-alt"):
            alt = ctx.lookup(a["data-slot-alt"])
            if r._present(alt) and not isinstance(alt, (list, dict)):
                extra["alt"] = str(alt)
        if url:
            out.append(_clean_start(el, {**extra, "src": url, "srcset": None, "sizes": None}))
        else:
            out.append(_clean_start(el, extra))                # no photo chosen yet: the page's own picture stays
        return
    if "data-slot" in a:
        value = ctx.lookup(a["data-slot"])
        fmt = a.get("data-format", "")
        if not r._present(value) and not (fmt in ("naira", "price") and value is not None):
            return
        if isinstance(value, (list, dict)):
            return
        out.append(_clean_start(el))
        out.append(escape(_format_value(value, fmt, ctx), quote=False))
        out.append(el.raw_end or f"</{el.tag}>")
        return
    if "data-slot-href" in a:
        link = r.build_link(a["data-slot-href"], ctx)
        if link is None:
            return
        href, external = link
        extra = {"href": href}
        if external:
            extra.update({"target": "_blank", "rel": "noopener"})
        out.append(_clean_start(el, extra))
    else:
        out.append(_clean_start(el))
    _fill_nodes(el.children, ctx, out, r)
    if el.raw_end:
        out.append(el.raw_end)


# ------------------------------------------------------------------ proof

_CONTACT_RX = re.compile(r"^(https?://(wa\.me|api\.whatsapp\.com|(www\.)?instagram\.com)/|tel:)", re.I)


def _norm(html: str) -> list:
    """The page as a comparable list: tags with their attributes (contact links and slot-managed attributes reduced), text
    with whitespace collapsed. Comments and whitespace-only text are ignored."""
    root = dom.parse(html)
    out: list = []

    def walk(el: Elem):
        for c in el.children:
            if isinstance(c, Text):
                t = " ".join(unescape(c.raw).split())
                if t:
                    out.append(("t", t))
            elif isinstance(c, Elem):
                attrs = {k: v for k, v in c.attrs.items() if k not in MARKERS}
                if c.tag == "img":
                    attrs.pop("src", None)
                    attrs.pop("alt", None)                      # alt text is not visible, and follows the card's name (data-slot-alt)
                    attrs.pop("srcset", None)
                    attrs.pop("sizes", None)
                if c.tag == "a" and _CONTACT_RX.match(attrs.get("href", "")):
                    attrs["href"] = "#contact"
                    attrs.pop("target", None)
                    attrs.pop("rel", None)
                out.append(("e", c.tag, tuple(sorted(attrs.items()))))
                if c.tag in dom.RAW_TEXT:
                    out.append(("raw", "".join(x.raw for x in c.children if isinstance(x, Text))))
                else:
                    walk(c)
                out.append(("/", c.tag))
    walk(root)
    return out


def compare(original: str, filled: str) -> list:
    """Empty when the filled page equals the original (after the exemptions in _norm). Otherwise plain-words differences."""
    a, b = _norm(original), _norm(filled)
    if a == b:
        return []
    diffs: list = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            diffs.append(f"The rebuilt page differs from the original at item {i}: original {_short(x)}, rebuilt {_short(y)}")
            break
    if len(a) != len(b) and not diffs:
        diffs.append(f"The rebuilt page has {len(b)} parts, the original has {len(a)}")
    return diffs


def _short(x: tuple) -> str:
    return str(x)[:140]


def used_top_level(manifest_slots: list) -> list:
    from app.services import site_premium_service as p
    return p.used_top_level({"slots": manifest_slots})
