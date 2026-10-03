"""
app/services/site_premium_checks.py
------------------------------------
SITE-PREMIUM P1b - the code-enforced design checks of spec section 13A that can be run on a skeleton
without a browser. Pure functions, no I/O (the browser checks live in site_premium_visual.py).

run_static_checks() returns {"errors": [...], "warnings": [...]}:
  * errors   - hard failures: an accent in the banned brown-gold range, unreadable contrast, a CSS
               file that names its own fonts, a font pair that breaks the confirmed pairing rules.
  * warnings - taste rules that staff may knowingly break on a hand-written import (pure #000/#fff,
               cream or brass hex, em-dashes or filler in static text, too many eyebrows, a crowded
               hero, too few layout families, missing reduced-motion, marquee count, cursor override).
Call with strict=True (P2 generation) and every warning is promoted to an error so it can be fed
back to the model for its one retry.

Every finding is a short plain-English sentence; the dashboard and the import script print them as is.
"""
from __future__ import annotations

import colorsys
import math
import re
from typing import Optional

from app.services import site_premium_fonts as fonts
from app.services import site_premium_renderer as renderer

_HEX6 = re.compile(r"#([0-9a-fA-F]{6})\b")
_HEX3 = re.compile(r"#([0-9a-fA-F]{3})\b(?![0-9a-fA-F])")

FILLER_WORDS = (
    "elevate", "seamless", "seamlessly", "unlock", "unleash", "game-changer", "game changer",
    "cutting-edge", "cutting edge", "world-class", "leverage", "synergy", "next-level", "next level",
    "revolutionize", "revolutionise", "state-of-the-art", "welcome to our", "one-stop shop", "tailored solutions",
)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-↪]")
_TEXT_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "li", "blockquote", "cite", "figcaption", "small", "strong", "em"}
_GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                     "ui-monospace", "ui-rounded", "inherit", "initial", "unset", "revert", "emoji", "math"}
# groups whose headline fonts are "image-text split" style layouts when named so
_SPLIT_WORDS = ("split",)


# ------------------------------------------------------------------ colour maths

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hex_to_hls(h: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return hh * 360.0, ll, ss          # hue degrees, lightness 0-1, saturation 0-1


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_brown_gold(h: str) -> bool:
    """Spec 13A: hue 25-50 degrees and muted (tan, bronze, brass, caramel, champagne, khaki)."""
    hue, light, sat = hex_to_hls(h)
    return 25.0 <= hue <= 50.0 and sat <= 0.65 and 0.12 <= light <= 0.9


def _is_cream(h: str) -> bool:
    hue, light, sat = hex_to_hls(h)
    return 30.0 <= hue <= 55.0 and 0.1 <= sat <= 0.6 and light >= 0.88


def _is_brass(h: str) -> bool:
    hue, light, sat = hex_to_hls(h)
    return 35.0 <= hue <= 52.0 and 0.3 <= sat <= 0.85 and 0.3 <= light <= 0.68


# ------------------------------------------------------------------ css helpers

def root_hex_vars(css: str) -> dict:
    """Every custom property declared in :root / html whose value is a #RRGGBB colour."""
    import tinycss2
    found: dict = {}
    for rule in tinycss2.parse_stylesheet(css or "", skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        if tinycss2.serialize(rule.prelude).strip() not in (":root", "html"):
            continue
        for d in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True):
            if d.type == "declaration" and d.name.startswith("--"):
                value = tinycss2.serialize(d.value).strip()
                if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    found[d.name] = value
    return found


def _all_hexes(css: str) -> list[str]:
    out = [("#" + m.group(1)).upper() for m in _HEX6.finditer(css)]
    for m in _HEX3.finditer(css):
        out.append("#" + "".join(c * 2 for c in m.group(1)).upper())
    return out


def _font_family_values(css: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"font-family\s*:\s*([^;}]+)", css, re.I)]


# ------------------------------------------------------------------ html helpers

def _walk(nodes: list):
    for n in nodes:
        if isinstance(n, str):
            continue
        yield n
        yield from _walk(n.children)


def _text_of(node, include_slots: bool = False) -> str:
    """Static text only: text inside an element that is filled from a slot is client content."""
    if isinstance(node, str):
        return node
    if not include_slots and any(k in node.attrs for k in ("data-slot", "data-repeat")):
        return ""
    return "".join(_text_of(c, include_slots) for c in node.children)


def _sections(nodes: list) -> list:
    return [n for n in _walk(nodes) if "data-section" in n.attrs]


# ------------------------------------------------------------------ the checks

def _check_colours(css: str, errors: list, warnings: list) -> None:
    tokens = root_hex_vars(css)
    accent, accent_ink = tokens.get("--accent"), tokens.get("--accent-ink")
    bg, ink = tokens.get("--bg"), tokens.get("--ink")
    if accent and is_brown_gold(accent):
        errors.append(f"The accent colour {accent} is in the banned brown-gold range (tan, bronze, brass, caramel, "
                      "champagne or khaki). Choose an accent from another colour family.")
    if ink and bg:
        r = contrast_ratio(ink, bg)
        if r < 4.5:
            errors.append(f"Text colour {ink} on the background {bg} has contrast {r:.1f}:1; it must be at least 4.5:1.")
    if accent and accent_ink:
        r = contrast_ratio(accent_ink, accent)
        if r < 4.5:
            errors.append(f"Button text {accent_ink} on the accent {accent} has contrast {r:.1f}:1; it must be at least 4.5:1.")
    if accent and bg:
        r = contrast_ratio(accent, bg)
        if r < 3.0:
            warnings.append(f"The accent {accent} on the background {bg} has contrast {r:.1f}:1; accent text and links "
                            "need at least 3:1.")
    for name, value in tokens.items():
        if name in ("--muted", "--text-muted", "--ink-muted") and bg:
            r = contrast_ratio(value, bg)
            if r < 4.5:
                warnings.append(f"Secondary text {name} {value} on the background has contrast {r:.1f}:1; aim for 4.5:1.")
    hexes = _all_hexes(css)
    if any(h in ("#000000", "#FFFFFF") for h in hexes):
        warnings.append("The CSS uses pure #000000 or #FFFFFF. Use a tinted near-black and near-white instead.")
    cream = sorted({h for h in hexes if _is_cream(h)})
    brass = sorted({h for h in hexes if _is_brass(h)})
    if cream:
        warnings.append("Warm cream colours are banned as a default look (" + ", ".join(cream[:3]) + "). Try a cool, grey or dark ground.")
    if brass:
        warnings.append("Brass, tan or bronze colours are banned unless the product is that material (" + ", ".join(brass[:3]) + ").")


def _check_fonts(css: str, headline_font: Optional[str], body_font: Optional[str], errors: list) -> None:
    for value in _font_family_values(css):
        for part in value.split(","):
            name = part.strip().strip("'\"").lower()
            if not name or name.startswith("var(") or name in _GENERIC_FAMILIES:
                continue
            errors.append(f"The CSS names the font \"{part.strip().strip(chr(39) + chr(34))}\" directly. Fonts must come from "
                          "var(--font-head) and var(--font-body) so the registry rules apply.")
            return
    if headline_font and body_font:
        head = fonts.HEADLINE_FONTS.get(headline_font)
        if head:
            allowed = fonts.PROPOSED_PAIRS.get(head["group"], ())
            if allowed and body_font not in allowed:
                errors.append(f"{headline_font} ({head['group']}) cannot be paired with {body_font}. "
                              f"Allowed body fonts: {', '.join(allowed)}.")


def _check_text_rules(nodes: list, warnings: list) -> None:
    static = " ".join(_text_of(n) for n in nodes)
    if "—" in static:
        warnings.append("The page's own wording contains an em-dash. Use a comma, a full stop or a colon.")
    if _EMOJI.search(static):
        warnings.append("The page's own wording contains an emoji. Use drawn SVG icons or none.")
    low = static.lower()
    hits = [w for w in FILLER_WORDS if w in low]
    if hits:
        warnings.append("The page's own wording uses filler phrases (" + ", ".join(hits[:4]) + "). Say something specific.")


def _check_structure(nodes: list, warnings: list) -> None:
    sections = _sections(nodes)
    body_sections = [s for s in sections if s.attrs.get("data-section") not in ("nav", "footer", "announcement")]
    n_sections = len(sections)
    eyebrows = sum(1 for n in _walk(nodes) if n.attrs.get("data-role") == "eyebrow")
    limit = max(1, math.ceil(n_sections / 3)) if n_sections else 1
    if eyebrows > limit:
        warnings.append(f"The design has {eyebrows} eyebrow labels for {n_sections} sections; the limit is {limit}.")
    for s in sections:
        if s.attrs.get("data-section") == "hero":
            texts = [n for n in _walk([s]) if n.tag in _TEXT_TAGS and _text_of(n, True).strip()
                     and not any(a.tag in _TEXT_TAGS for a in _walk(n.children) if a is not n)]
            if len(texts) > 4:
                warnings.append(f"The hero has {len(texts)} text elements; keep it to 4 or fewer.")
            for n in _walk([s]):
                if n.tag == "p" and "data-slot" not in n.attrs:
                    words = len(_text_of(n).split())
                    if words > 20:
                        warnings.append(f"The hero's own sub-text is {words} words; keep it to 20 or fewer.")
    layouts = [s.attrs.get("data-layout", "") for s in body_sections]
    if len(body_sections) >= 8 and len({x for x in layouts if x}) < 4:
        warnings.append("With 8 or more sections the design should use at least 4 different layouts (data-layout).")
    run = best = 0
    for x in layouts:
        run = run + 1 if any(w in x for w in _SPLIT_WORDS) else 0
        best = max(best, run)
    if best > 2:
        warnings.append("More than two image-and-text split sections in a row. Vary the layout.")


_LEN_RE = re.compile(r"^(-?\d*\.?\d+)(px|rem|em|%|vw|vh)?$")


def _radius_size(token: str) -> str:
    """'big' (arch-sized), 'flat' (square-ish) or 'mid' for one border-radius length."""
    m = _LEN_RE.match((token or "").strip().lower())
    if not m:
        return "mid"
    n, unit = float(m.group(1)), m.group(2) or "px"
    if unit == "%":
        return "big" if n >= 35 else ("flat" if n <= 8 else "mid")
    if unit in ("rem", "em"):
        return "big" if n >= 5 else ("flat" if n <= 1.5 else "mid")
    if unit in ("vw", "vh"):
        return "big" if n >= 8 else ("flat" if n <= 1.5 else "mid")
    return "big" if n >= 80 else ("flat" if n <= 24 else "mid")


def _has_arch_frame(css: str) -> bool:
    """True when any rule gives two big top corners and flat bottom corners (an arch-top frame)."""
    for block in re.findall(r"\{([^{}]*)\}", css or ""):
        m = re.search(r"(?<![\w-])border-radius\s*:\s*([^;}/]+)", block, re.I)
        if m:
            v = m.group(1).split()
            if len(v) == 4 and _radius_size(v[0]) == "big" and _radius_size(v[1]) == "big" \
                    and _radius_size(v[2]) == "flat" and _radius_size(v[3]) == "flat":
                return True
        tl = re.search(r"border-top-left-radius\s*:\s*([^;}/\s]+)", block, re.I)
        tr = re.search(r"border-top-right-radius\s*:\s*([^;}/\s]+)", block, re.I)
        if tl and tr and _radius_size(tl.group(1)) == "big" and _radius_size(tr.group(1)) == "big":
            br = re.search(r"border-bottom-(?:left|right)-radius\s*:\s*([^;}/\s]+)", block, re.I)
            if not br or _radius_size(br.group(1)) == "flat":
                return True
    return False


def _check_css_rules(css: str, warnings: list) -> None:
    if "prefers-reduced-motion" not in css:
        warnings.append("The CSS has no prefers-reduced-motion rule. Motion must switch off for people who ask for it.")
    if re.search(r"(?<!min-)(?<!max-)height\s*:\s*100d?vh", css, re.I):
        warnings.append("A section is given a fixed height of 100vh/100dvh. Use min-height so content is never cut off on phones.")
    marquees = {m.group(1) for m in re.finditer(r"@(?:-webkit-)?keyframes\s+([\w-]*(?:marquee|ticker)[\w-]*)", css, re.I)}
    if len(marquees) > 1:
        warnings.append("More than one marquee. Use at most one, CSS only.")
    if _has_arch_frame(css):
        warnings.append("An arch-top frame (large rounded top corners, flat bottom) is used. Arch frames are not permitted: use a plain rectangle (radius 12px at most) or full-bleed.")
    if re.search(r"cursor\s*:\s*(?:none|url)", css, re.I):
        warnings.append("The CSS overrides the cursor. Custom cursors are not allowed.")


def run_static_checks(html: str, css: str, headline_font: Optional[str] = None, body_font: Optional[str] = None,
                      strict: bool = False) -> dict:
    """html is the sanitised body markup, css the validated CSS. Returns {"errors": [...], "warnings": [...]}."""
    errors: list[str] = []
    warnings: list[str] = []
    nodes = renderer.parse_fragment(html or "")
    _check_colours(css or "", errors, warnings)
    _check_fonts(css or "", headline_font, body_font, errors)
    _check_text_rules(nodes, warnings)
    _check_structure(nodes, warnings)
    _check_css_rules(css or "", warnings)
    if strict:
        errors, warnings = errors + warnings, []
    return {"errors": errors, "warnings": warnings}
