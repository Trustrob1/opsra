"""
app/services/site_premium_sections.py
--------------------------------------
SITE-PREMIUM P4-3a - section colours for a Premium site, from a FIXED set only (decided 3 Oct 2026).

A customer picks, per section, one of: the design's own colour (original), its page colour (base), its soft
surface colour (soft), its dark colour (dark) or the brand colour (brand). Nothing else, so every choice is a
colour the design was drawn with.

How it works (no AI, no stored CSS):
  * The choice is stored as art_direction["section_colours"] = {"about": "dark", ...}.
  * At render time this module turns it into one small override rule per section:
        :root [data-section="about"]{background-color:B;color:T;--bg:B;--ink:T;--surface:..;--muted:..;--accent:..}
    The section becomes a self-contained theme: background B, text T, and the variables the design reads inside it.
  * T (the text colour) is chosen by code from the design's own text/background colours and two tinted neutrals,
    whichever reads best on B (at least 4.5:1). If nothing reaches 4.5:1 the section is left alone.
  * Inside a section whose colour is the brand colour (or close to the accent) the accent and button text swap, so
    buttons never disappear into their own background.
  * Only hex values built here are written into the CSS, and section names must exist in the design: nothing a
    customer types ever reaches the stylesheet.
  * hero and nav are never offered (the hero scrim and the header were drawn against the page colour).

Pure functions, standard library only (section_names imports the renderer lazily). Never raises at render time.
"""
from __future__ import annotations

import re
from typing import Optional

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
EXCLUDED_SECTIONS = frozenset({"hero", "nav"})
NEUTRAL_INKS = ("#12141A", "#FAFAF7")          # tinted near-black and near-white, never pure
PALETTE_LABELS = {"base": "Page colour", "soft": "Soft", "dark": "Dark", "brand": "Brand colour"}
ORIGINAL = "original"
MAX_SECTIONS = 12
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")

_DECL_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*(?=;|$)")
_BLOCK_RE = re.compile(r"(?:^|\})\s*(?::root|html)\s*\{([^}]*)\}")


# ------------------------------------------------------------------ colour maths

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in (r, g, b)))


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blend(a: str, b: str, t: float) -> str:
    """a moved toward b by fraction t (0 = a, 1 = b)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


# ------------------------------------------------------------------ the design's colours

def root_hex_vars(css: str) -> dict:
    """Every custom property the CSS declares in :root / html as a #RRGGBB colour (later declarations win)."""
    found: dict = {}
    for block in _BLOCK_RE.finditer(css or ""):
        for name, value in _DECL_RE.findall(block.group(1)):
            found[name] = value.upper()
    return found


def design_colours(design: dict) -> dict:
    """The colour variables the page is drawn with: what the CSS declares, overlaid by the stored tokens."""
    colours = root_hex_vars(design.get("skeleton_css") or "")
    for k, v in (design.get("tokens") or {}).items():
        if isinstance(v, str) and HEX_RE.match(v) and str(k).startswith("--"):
            colours[k] = v.upper()
    return colours


def palette(design: dict) -> list[dict]:
    """The fixed set of section colours this design offers, in order, without duplicates:
    [{key, label, hex}] for base, soft, dark, brand (only those the design actually has)."""
    c = design_colours(design)
    wanted = (("base", c.get("--bg")), ("soft", c.get("--surface")), ("dark", c.get("--deep") or c.get("--ink")),
              ("brand", c.get("--accent")))
    out: list[dict] = []
    for key, value in wanted:
        # a colour that looks the same as one already offered (contrast under 1.06) is not a real choice
        if value and all(contrast(value, p["hex"]) >= 1.06 for p in out):
            out.append({"key": key, "label": PALETTE_LABELS[key], "hex": value.upper()})
    return out


def text_for(bg: str, colours: dict) -> Optional[str]:
    """The best text colour on bg (at least 4.5:1) from the design's own text and page colours plus tinted neutrals."""
    best, best_ratio = None, 0.0
    for cand in (colours.get("--ink"), colours.get("--bg")) + NEUTRAL_INKS:
        if not cand:
            continue
        r = contrast(cand, bg)
        if r > best_ratio:
            best, best_ratio = cand.upper(), r
    return best if best_ratio >= 4.5 else None


# ------------------------------------------------------------------ section names and the override CSS

def section_names(skeleton_html: str) -> list[str]:
    """The data-section names in the design, in page order, without hero and nav."""
    from app.services import site_premium_renderer as renderer   # lazy: keeps this module light
    names: list[str] = []

    def walk(nodes: list) -> None:
        for n in nodes:
            attrs = getattr(n, "attrs", None)
            if attrs is None:
                continue
            name = attrs.get("data-section")
            if name and _NAME_RE.match(name) and name not in EXCLUDED_SECTIONS and name not in names:
                names.append(name)
            walk(getattr(n, "children", []) or [])

    walk(renderer.parse_fragment(skeleton_html or ""))
    return names


_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_PAINT_RE = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*(?!none|transparent|inherit|initial|unset|(?:linear|radial|conic|repeating|url|image))[^;]+", re.I)
_CLASS_RE = re.compile(r"\.([a-zA-Z_][a-zA-Z0-9_-]*)")


def painted_classes(css: str) -> list[str]:
    """Classes the stylesheet gives a solid background (buttons, cards, chips, panels). Text inside a section
    is made to follow the section colour, but these keep their own text colour because they sit on their own
    background. Only plain class names that pass the name check are returned, so nothing odd reaches the CSS."""
    found: list[str] = []
    for sel, body in _RULE_RE.findall(re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)):
        if sel.lstrip().startswith("@") or not _PAINT_RE.search(body):
            continue
        for part in sel.split(","):
            classes = _CLASS_RE.findall(part.split()[-1] if part.split() else "")
            for c in classes:
                if _NAME_RE.match(c.lower()) and c not in found and c != "slot-ph":
                    found.append(c)
    return found[:40]


def override_rule(section: str, bg: str, colours: dict, painted: tuple = ()) -> Optional[str]:
    """The scoped rules that make `section` a self-contained theme on `bg`, or None when no text colour reads on it.
    The section gets the colour and text colour; the variables the design reads are re-pointed; and every text
    element in it that does not sit on its own painted background follows the section's text colour."""
    text = text_for(bg, colours)
    if not text:
        return None
    parts = [f"background-color:{bg}", f"color:{text}", f"--bg:{bg}", f"--ink:{text}"]
    surface = blend(bg, text, 0.08)
    muted = blend(text, bg, 0.30)
    if contrast(muted, bg) < 4.5:
        muted = text
    for name, value in colours.items():
        if name in ("--accent", "--accent-ink", "--bg", "--ink"):
            continue
        lowered = name.lower()
        if lowered in ("--surface", "--surf", "--sf", "--card", "--panel"):
            parts.append(f"{name}:{surface}")
        elif lowered in ("--muted", "--mute", "--mu", "--grey", "--gray"):
            parts.append(f"{name}:{muted}")
    accent, accent_ink = colours.get("--accent"), colours.get("--accent-ink")
    if accent and accent_ink and contrast(accent, bg) < 3.0:
        parts += [f"--accent:{text}", f"--accent-ink:{bg}"]      # buttons would vanish: invert them in this section
    head = f':root [data-section="{section}"]'
    rules = [f"{head}{{{';'.join(parts)}}}"]
    skip = "".join(f":not(.{c})" for c in painted if _NAME_RE.match(c.lower()))
    rules.append(f':root:root [data-section="{section}"] *{skip}{{color:inherit}}')
    return "".join(rules)


def override_css(design: dict) -> str:
    """The CSS for the design's chosen section colours. Never raises; anything invalid is skipped."""
    try:
        chosen = (design.get("art_direction") or {}).get("section_colours") or {}
        if not isinstance(chosen, dict) or not chosen:
            return ""
        pal = {p["key"]: p["hex"] for p in palette(design)}
        colours = design_colours(design)
        valid = set(section_names(design.get("skeleton_html") or ""))
        rules = []
        for section, key in chosen.items():
            if section in valid and key in pal:
                rule = override_rule(section, pal[key], colours, tuple(painted_classes(design.get("skeleton_css") or "")))
                if rule:
                    rules.append(rule)
        return "".join(rules)
    except Exception:  # S14 - a colour tweak must never take a page down
        return ""


# ---- P4-3b: show / hide a section and make its headline smaller or larger
SIZES = {"small": 0.85, "normal": 1.0, "large": 1.25}
NO_HIDE = frozenset({"footer"})      # the footer holds the contact details and must stay
NO_SIZE = frozenset({"footer"})


def _valid_names(design: dict) -> set:
    try:
        return set(section_names(design.get("skeleton_html") or ""))
    except Exception:  # S14
        return set()


def hidden_names(design: dict) -> list[str]:
    """Sections the customer hid, in page order, only those that exist and may be hidden. Never raises."""
    try:
        wanted = (design.get("art_direction") or {}).get("section_hidden") or []
        if not isinstance(wanted, list):
            return []
        valid = _valid_names(design)
        return [n for n in section_names(design.get("skeleton_html") or "") if n in wanted and n in valid and n not in NO_HIDE]
    except Exception:  # S14
        return []


def sizes(design: dict) -> dict:
    """{section: 'small'|'large'} for sections that exist and may be resized. Never raises."""
    try:
        wanted = (design.get("art_direction") or {}).get("section_size") or {}
        if not isinstance(wanted, dict):
            return {}
        valid = _valid_names(design)
        return {n: s for n, s in wanted.items() if n in valid and n not in NO_SIZE and s in ("small", "large")}
    except Exception:  # S14
        return {}


def size_css(design: dict) -> str:
    """One rule per resized section. zoom scales the heading with its own line height, so the layout stays tidy;
    break-word stops a long word from pushing the page sideways on a phone."""
    rules = []
    for name, size in sizes(design).items():
        rules.append(f':root:root [data-section="{name}"] :where(h1,h2){{zoom:{SIZES[size]};overflow-wrap:break-word}}')
    return "".join(rules)


def normalise_layout(design: dict, wanted: dict) -> tuple[list[str], dict]:
    """Merges {section: {show?: bool, size?: 'small'|'normal'|'large'}} into the design's current hidden list and
    sizes. Returns (hidden sections in page order, sizes). Raises ValueError with a plain reason."""
    if not isinstance(wanted, dict) or not wanted:
        raise ValueError("Pick a section.")
    if len(wanted) > MAX_SECTIONS:
        raise ValueError("Too many sections at once.")
    order = section_names(design.get("skeleton_html") or "")
    hidden, sz = set(hidden_names(design)), dict(sizes(design))
    for name, change in wanted.items():
        if name not in order:
            raise ValueError("That section is not part of your design.")
        if not isinstance(change, dict) or not change:
            raise ValueError("Pick show or hide, or a size.")
        show = change.get("show")
        if show is not None:
            if show is True:
                hidden.discard(name)
            elif show is False:
                if name in NO_HIDE:
                    raise ValueError("The footer stays, because it holds your contact details.")
                hidden.add(name)
            else:
                raise ValueError("Pick show or hide.")
        size = change.get("size")
        if size is not None:
            if size not in SIZES:
                raise ValueError("That size is not available.")
            if name in NO_SIZE:
                raise ValueError("The footer text cannot be resized.")
            if size == "normal":
                sz.pop(name, None)
            else:
                sz[name] = size
    return [n for n in order if n in hidden], sz


def label_for(section: str) -> str:
    """A plain label for a section name: 'our-menu' -> 'Our menu'."""
    text = re.sub(r"[-_]+", " ", section).strip()
    return text[:1].upper() + text[1:]


def section_options(design: dict) -> list[dict]:
    """What the editor shows: every colourable section with its current choice and the choices that read well."""
    chosen = (design.get("art_direction") or {}).get("section_colours") or {}
    colours = design_colours(design)
    pal = [p for p in palette(design) if text_for(p["hex"], colours)]
    hidden, sz = set(hidden_names(design)), sizes(design)
    out = []
    for name in section_names(design.get("skeleton_html") or ""):
        current = chosen.get(name)
        out.append({"name": name, "label": label_for(name),
                    "visible": name not in hidden, "can_hide": name not in NO_HIDE,
                    "size": sz.get(name, "normal"), "can_resize": name not in NO_SIZE,
                    "current": current if current in {p["key"] for p in pal} else ORIGINAL,
                    "options": [{"key": ORIGINAL, "label": "Original", "hex": None}] + pal})
    return out


def normalise_choice(design: dict, wanted: dict) -> dict:
    """Merges the requested {section: key} changes into the design's existing choices.
    key 'original' clears a section. Raises ValueError with a plain reason for an unknown section or colour."""
    if not isinstance(wanted, dict) or not wanted:
        raise ValueError("Pick a section and a colour.")
    if len(wanted) > MAX_SECTIONS:
        raise ValueError("Too many sections at once.")
    valid = set(section_names(design.get("skeleton_html") or ""))
    keys = {p["key"] for p in palette(design)}
    current = dict((design.get("art_direction") or {}).get("section_colours") or {})
    for section, key in wanted.items():
        if section not in valid:
            raise ValueError("That section is not part of your design.")
        if key == ORIGINAL:
            current.pop(section, None)
            continue
        if key not in keys:
            raise ValueError("That colour is not available for this design.")
        if text_for(next(p["hex"] for p in palette(design) if p["key"] == key), design_colours(design)) is None:
            raise ValueError("Text would be hard to read on that colour.")
        current[section] = key
    return current
