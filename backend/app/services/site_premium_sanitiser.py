"""
app/services/site_premium_sanitiser.py
---------------------------------------
SITE-PREMIUM P1 - the security core (spec section 5). A Premium skeleton is HTML + CSS written by
a model (or pasted by staff) and is treated as UNTRUSTED. This module reduces it to a safe subset.

Approach:
  * HTML: nh3 (a real parser, allow-list). Never regex. Scripts, iframes, forms, inputs, event
    handlers, inline styles, src/srcset and every href that is not an in-page "#anchor" are removed.
    Images and links come from slots, filled by the renderer from the site's own data.
  * CSS: pulled out of <style> blocks BEFORE nh3 runs, tokenised with tinycss2 and validated:
    no @import, @font-face or @charset, no url()/image-set()/expression(), no behavior or
    -moz-binding, no "<" anywhere (so it can never close the <style> tag it is written into).
    Fonts are the renderer's job (Premium font registry), so the skeleton never needs a url().
  * Size cap on HTML + CSS together.

Two things nh3 cannot do that matter here, found by testing on 2 Oct 2026:
  * <template> contents are dropped, so repeats mark the element to repeat (data-repeat) instead of
    wrapping it in <template> (spec section 6 amended).
  * <style> is never allowed through nh3; CSS travels as its own validated string.

Pure functions, no I/O. The result is a SanitisedSkeleton; fatal problems raise SanitiseError with
a list of plain-English reasons (these are fed back to the model for its one retry).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import nh3
import tinycss2

from app.services.site_premium_behaviours import clean_behaviour_value

MAX_TOTAL_BYTES = 250_000          # HTML + CSS together (spec section 5, to be tuned)
MAX_CSS_CHARS = 120_000

_SVG_PAINT = {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-rule",
              "clip-rule", "opacity", "transform", "clip-path", "mask", "fill-opacity", "stroke-opacity"}

_HTML_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "blockquote", "br", "caption", "cite", "code",
    "dd", "del", "details", "div", "dl", "dt", "em", "figcaption", "figure", "footer", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "li", "main", "mark", "nav", "ol", "p",
    "picture", "q", "s", "section", "small", "span", "strong", "sub", "summary", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "time", "tr", "u", "ul",
}
_SVG_ATTRS: dict[str, set[str]] = {
    "svg": {"viewBox", "width", "height", "preserveAspectRatio", "xmlns", "focusable"} | _SVG_PAINT,
    "g": set(_SVG_PAINT),
    "path": {"d"} | _SVG_PAINT,
    "circle": {"cx", "cy", "r"} | _SVG_PAINT,
    "ellipse": {"cx", "cy", "rx", "ry"} | _SVG_PAINT,
    "rect": {"x", "y", "width", "height", "rx", "ry"} | _SVG_PAINT,
    "line": {"x1", "y1", "x2", "y2"} | _SVG_PAINT,
    "polyline": {"points"} | _SVG_PAINT,
    "polygon": {"points"} | _SVG_PAINT,
    "defs": set(),
    "linearGradient": {"x1", "y1", "x2", "y2", "gradientUnits", "gradientTransform"},
    "radialGradient": {"cx", "cy", "r", "fx", "fy", "gradientUnits", "gradientTransform"},
    "stop": {"offset", "stop-color", "stop-opacity"},
    "clipPath": {"clipPathUnits"},
    "mask": {"maskUnits"},
    "text": {"x", "y", "text-anchor"} | _SVG_PAINT,
    "tspan": {"x", "y"},
}
ALLOWED_TAGS = _HTML_TAGS | set(_SVG_ATTRS)

# Slot markers are the contract with the renderer (spec section 6).
SLOT_ATTRS = {"data-slot", "data-slot-img", "data-slot-href", "data-repeat", "data-if", "data-format",
              "data-section", "data-layout", "data-role", "data-priority"}
_GENERIC_ATTRS = {"class", "id", "lang", "dir", "title", "role", "data-behaviour"} | SLOT_ATTRS

_ATTRS: dict[str, set[str]] = {
    "*": set(_GENERIC_ATTRS),
    "a": {"href"},
    "img": {"alt", "width", "height", "loading", "decoding", "fetchpriority"},
    "details": {"open"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "time": {"datetime"},
    "ol": {"start", "reversed"},
    **{k: set(v) for k, v in _SVG_ATTRS.items()},
}
# No <title>/<desc> are allowed: a pasted document's <title> would otherwise survive as page text.
_CLEAN_CONTENT_TAGS = {"script", "style", "head", "title", "noscript", "iframe", "object", "embed", "textarea",
                       "select", "button", "form", "frameset", "applet"}

_ANCHOR_RE = re.compile(r"^#[A-Za-z0-9_\-:.]{1,80}$")
_LOCAL_URL_RE = re.compile(r"^url\(#[A-Za-z0-9_\-:.]{1,80}\)$")
_SLOT_PATH_RE = re.compile(r"^[A-Za-z0-9_.\-:!]{0,80}$")
_XMLNS = "http://www.w3.org/2000/svg"

_BANNED_CSS_FUNCS = {"url", "image-set", "-webkit-image-set", "expression", "element", "image",
                     "cross-fade", "paint", "src", "-moz-element"}
_BANNED_CSS_PROPS = {"behavior", "-moz-binding"}
_ALLOWED_AT_RULES = {"media", "supports", "keyframes", "-webkit-keyframes", "layer", "container", "property"}
_NESTED_RULE_LISTS = {"media", "supports", "layer", "container", "keyframes", "-webkit-keyframes"}


class SanitiseError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class SanitisedSkeleton:
    html: str
    css: str
    removed: list[str] = field(default_factory=list)   # things stripped (warnings, not failures)


# ------------------------------------------------------------------ HTML

def _attribute_filter(tag: str, attr: str, value: str):
    low = (value or "").strip().lower()
    if "javascript:" in low or "vbscript:" in low or low.startswith("data:"):
        return None
    if attr == "href":
        return value if _ANCHOR_RE.match(value or "") else None
    if attr == "xmlns":
        return value if value == _XMLNS else None
    if "url(" in low:
        return value if _LOCAL_URL_RE.match((value or "").strip()) else None
    if attr == "data-behaviour":
        return clean_behaviour_value(value)     # only names from the Opsra behaviour library survive
    if attr in SLOT_ATTRS and attr not in ("data-section", "data-layout", "data-role", "data-priority", "data-format"):
        return value if _SLOT_PATH_RE.match(value or "") else None
    if attr in ("data-section", "data-layout", "data-role", "data-format"):
        return value if re.match(r"^[a-z0-9_\-]{1,40}$", value or "") else None
    if attr == "loading":
        return value if value in ("lazy", "eager") else None
    if attr == "fetchpriority":
        return value if value in ("high", "low", "auto") else None
    if len(value or "") > 2000:
        return None
    return value


class _Scan(HTMLParser):
    """Walks the RAW input once to (a) pull out <style> text and (b) say what will be stripped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css: list[str] = []
        self.removed: list[str] = []
        self._in_style = False
        self._allowed = {t.lower() for t in ALLOWED_TAGS}
        self._attrs = {k.lower(): {a.lower() for a in v} for k, v in _ATTRS.items()}

    def _note(self, msg: str) -> None:
        if msg not in self.removed and len(self.removed) < 25:
            self.removed.append(msg)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "style":
            self._in_style = True
            return
        if tag not in self._allowed and tag not in ("html", "body", "head", "title"):
            self._note(f"removed <{tag}>")
        for name, val in attrs:
            name = (name or "").lower()
            val = val or ""
            if name.startswith("on"):
                self._note(f"removed event attribute {name}")
            elif name == "style":
                self._note("removed an inline style attribute (use classes in the CSS)")
            elif name in ("src", "srcset", "poster"):
                self._note(f"removed {name} (images come from slots)")
            elif name == "href" and not _ANCHOR_RE.match(val):
                self._note("removed a link that is not an in-page #anchor (links come from slots)")
            elif name not in self._attrs.get("*", set()) and name not in self._attrs.get(tag, set()) \
                    and not name.startswith("aria-") and name != "href":
                self._note(f"removed attribute {name} on <{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)


def sanitise_html(raw: str) -> str:
    """HTML only (no CSS). Returns the safe markup string."""
    return nh3.clean(
        raw or "",
        tags=set(ALLOWED_TAGS),
        attributes={k: set(v) for k, v in _ATTRS.items()},
        attribute_filter=_attribute_filter,
        strip_comments=True,
        link_rel=None,
        url_schemes=set(),
        clean_content_tags=set(_CLEAN_CONTENT_TAGS),
        generic_attribute_prefixes={"aria-"},
    )


# ------------------------------------------------------------------ CSS

def _walk_tokens(tokens, errors: list[str]) -> None:
    for t in tokens or []:
        kind = getattr(t, "type", "")
        if kind == "function":
            if t.lower_name in _BANNED_CSS_FUNCS:
                errors.append(f"CSS function {t.lower_name}() is not allowed")
            _walk_tokens(t.arguments, errors)
        elif kind in ("url", "bad-url"):
            errors.append("CSS url() is not allowed (fonts and images are added by the renderer)")
        elif kind in ("() block", "[] block", "{} block"):
            _walk_tokens(t.content, errors)
        elif kind == "error":
            errors.append(f"CSS parse problem: {t.message}")


def _check_rules(nodes, errors: list[str], depth: int = 0) -> None:
    if depth > 6:
        errors.append("CSS is nested too deeply")
        return
    for n in nodes:
        kind = n.type
        if kind in ("whitespace", "comment"):
            continue
        if kind == "error":
            errors.append(f"CSS parse problem: {n.message}")
        elif kind == "at-rule":
            name = n.lower_at_keyword
            if name not in _ALLOWED_AT_RULES:
                errors.append(f"CSS @{name} is not allowed")
                continue
            _walk_tokens(n.prelude, errors)
            if n.content is not None:
                if name in _NESTED_RULE_LISTS:
                    _check_rules(tinycss2.parse_rule_list(n.content, skip_comments=True, skip_whitespace=True), errors, depth + 1)
                else:
                    _check_rules(tinycss2.parse_blocks_contents(n.content, skip_comments=True, skip_whitespace=True), errors, depth + 1)
        elif kind == "qualified-rule":
            _walk_tokens(n.prelude, errors)
            _check_rules(tinycss2.parse_blocks_contents(n.content, skip_comments=True, skip_whitespace=True), errors, depth + 1)
        elif kind == "declaration":
            if n.lower_name in _BANNED_CSS_PROPS:
                errors.append(f"CSS property {n.lower_name} is not allowed")
            _walk_tokens(n.value, errors)


def sanitise_css(css: str) -> str:
    """Validate and return the CSS (comments dropped). Raises SanitiseError with every reason found."""
    css = css or ""
    errors: list[str] = []
    if len(css) > MAX_CSS_CHARS:
        raise SanitiseError([f"CSS is too large ({len(css):,} characters, limit {MAX_CSS_CHARS:,})"])
    nodes = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    _check_rules(nodes, errors)
    out = tinycss2.serialize(nodes)
    if "<" in out or "<" in css:
        errors.append("CSS must not contain the '<' character")
    if errors:
        seen: list[str] = []
        for e in errors:
            if e not in seen:
                seen.append(e)
        raise SanitiseError(seen[:12])
    return out.strip()


# ------------------------------------------------------------------ public entry

def sanitise_skeleton(raw: str) -> SanitisedSkeleton:
    """Raw model/staff output (HTML with optional <style> blocks) -> safe markup + validated CSS."""
    raw = raw or ""
    if not raw.strip():
        raise SanitiseError(["The skeleton is empty"])
    if len(raw.encode("utf-8")) > MAX_TOTAL_BYTES * 2:
        raise SanitiseError(["The skeleton is far too large to process"])
    scan = _Scan()
    scan.feed(raw)
    scan.close()
    css = sanitise_css("\n".join(scan.css))
    html = sanitise_html(raw).strip()
    if not html:
        raise SanitiseError(["Nothing is left after removing unsafe content"])
    total = len(html.encode("utf-8")) + len(css.encode("utf-8"))
    if total > MAX_TOTAL_BYTES:
        raise SanitiseError([f"The skeleton is too large ({total:,} bytes, limit {MAX_TOTAL_BYTES:,})"])
    return SanitisedSkeleton(html=html, css=css, removed=scan.removed)
