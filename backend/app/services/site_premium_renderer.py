"""
app/services/site_premium_renderer.py
--------------------------------------
SITE-PREMIUM P1 - fills a sanitised Premium skeleton (site_premium_sanitiser) with a site's content
JSON and wraps it in the page head (spec sections 2 and 6). Output is ONE static HTML page, so
hosting, domains, renewals and backups need no change.

The model/staff skeleton marks editable values with slot attributes; this module owns everything
else: escaping, image URLs, link URLs, fonts, JSON-LD, Open Graph, robots, canonical.

Slot markers (all stripped from the output):
  data-slot="path"          replace the element's content with that value (escaped). Empty -> element dropped.
  data-format="naira|price" optional, for numbers: "naira" -> 15,000 with the naira sign; "price" also
                            honours the item's price_style (exact / from / on_request).
  data-slot-img="path"      an <img>: src/alt/width/height from the site's own asset. No asset -> a tinted placeholder.
                            "hero.image" and "hero.image_asset_id" both work. data-priority="high" = hero image.
  data-slot-href="kind"     whatsapp | whatsapp:<message key> | phone | instagram | maps (links built here).
  data-repeat="path"        the ELEMENT is repeated once per list entry (max 60). Paths inside are relative to the
                            entry; "." means the entry itself (a plain string). <template> is NOT used: the
                            sanitiser drops template contents (spec section 6 amended).
  data-if="path" / "!path"  keep the element only when the value is present (or absent).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import quote

from app.services import site_premium_fonts as fonts
from app.services.site_premium_sanitiser import SLOT_ATTRS

MAX_REPEAT = 60
VOID_TAGS = {"br", "hr", "img"}
CONTRACT_VARS = ("--accent", "--accent-ink", "--bg", "--ink", "--font-head", "--font-body")
COLOUR_VARS = ("--accent", "--accent-ink", "--bg", "--ink")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_IG_RE = re.compile(r"^[A-Za-z0-9._]{1,40}$")
NAIRA = "₦"

_BASE_CSS = (
    "*,*::before,*::after{box-sizing:border-box}"
    "html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}"
    "body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-body)}"
    "img,svg{max-width:100%}img{height:auto}[hidden]{display:none!important}"
    ".slot-ph{display:block;width:100%;height:100%;min-height:120px;background:color-mix(in srgb,var(--ink) 9%,var(--bg))}"
)
_REDUCED_MOTION_CSS = (
    "@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;"
    "animation-iteration-count:1!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}"
)


# ------------------------------------------------------------------ a tiny DOM

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)   # Node | str

    def clone(self) -> "Node":
        return Node(self.tag, dict(self.attrs), [c.clone() if isinstance(c, Node) else c for c in self.children])


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_fragment(html: str) -> list:
    b = _TreeBuilder()
    b.feed(html or "")
    b.close()
    return b.root.children


def _serialise(nodes: list) -> str:
    out: list[str] = []
    for n in nodes:
        if isinstance(n, str):
            out.append(escape(n, quote=False))
            continue
        attrs = "".join(f' {k}="{escape(str(v), quote=True)}"' for k, v in n.attrs.items())
        if n.tag in VOID_TAGS:
            out.append(f"<{n.tag}{attrs}>")
        else:
            out.append(f"<{n.tag}{attrs}>{_serialise(n.children)}</{n.tag}>")
    return "".join(out)


# ------------------------------------------------------------------ values

def _get(obj: Any, path: str) -> Any:
    cur = obj
    for seg in path.split("."):
        if seg == "":
            return None
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list) and seg.isdigit():
            i = int(seg)
            cur = cur[i] if i < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def _present(v: Any) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


@dataclass
class Ctx:
    content: dict
    assets: dict
    export: bool
    price_style: str = "exact"
    scopes: list = field(default_factory=list)       # innermost last: the current repeat entries

    def child(self, item: Any) -> "Ctx":
        return Ctx(self.content, self.assets, self.export, self.price_style, self.scopes + [item])

    def lookup(self, path: str) -> Any:
        if path == ".":
            return self.scopes[-1] if self.scopes else None
        for scope in reversed(self.scopes):
            if isinstance(scope, dict):
                v = _get(scope, path)
                if v is not None:
                    return v
        if path.startswith("custom."):
            return _get(self.content.get("custom") or {}, path[len("custom."):])
        return _get(self.content, path)

    def current_item(self) -> Optional[dict]:
        for scope in reversed(self.scopes):
            if isinstance(scope, dict):
                return scope
        return None


def naira(n: Any) -> str:
    return NAIRA + f"{int(round(float(n))):,}"


def _format(value: Any, fmt: str, ctx: Ctx) -> str:
    if fmt in ("naira", "price"):
        item = ctx.current_item() or {}
        style = item.get("price_style") or ctx.price_style
        if fmt == "price" and style == "on_request":
            return "Price on request"
        try:
            amount = naira(value)
        except (TypeError, ValueError):
            return ""
        return f"From {amount}" if fmt == "price" and style == "from" else amount
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


# ------------------------------------------------------------------ links and images

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def build_link(kind: str, ctx: Ctx) -> Optional[tuple[str, bool]]:
    """(href, external) or None when the content can't support that link."""
    biz = ctx.content.get("business") or {}
    base, _, key = kind.partition(":")
    if base == "whatsapp":
        number = _digits(biz.get("whatsapp_e164", ""))
        if not number:
            return None
        from app.services.site_renderer import DEFAULT_WA_MESSAGES
        item = ctx.current_item()
        if key:
            msg = DEFAULT_WA_MESSAGES.get(key, DEFAULT_WA_MESSAGES["browse"])
        elif item and item.get("name"):
            msg = DEFAULT_WA_MESSAGES["order"]
        else:
            msg = DEFAULT_WA_MESSAGES["browse"]
        name = (item or {}).get("name", "")
        msg = msg.replace("{item}", str(name) if name else "item")
        return f"https://wa.me/{number}?text={quote(msg)}", True
    if base == "phone":
        number = _digits(biz.get("phone_display", "")) or _digits(biz.get("whatsapp_e164", ""))
        return (f"tel:+{number}", False) if number else None
    if base == "instagram":
        handle = (biz.get("instagram") or "").strip().lstrip("@")
        return (f"https://instagram.com/{handle}", True) if _IG_RE.match(handle) else None
    if base == "maps":
        addr = ((ctx.content.get("location") or {}).get("address") or "").strip()
        return (f"https://www.google.com/maps/search/?api=1&query={quote(addr)}", True) if addr else None
    return None


def _image_value(path: str, ctx: Ctx) -> Any:
    v = ctx.lookup(path)
    if v is None and not path.endswith("_asset_id"):
        v = ctx.lookup(path + "_asset_id")
    return v


def _image_node(node: Node, ctx: Ctx) -> Node:
    path = node.attrs.get("data-slot-img", "")
    asset_id = _image_value(path, ctx)
    asset = ctx.assets.get(asset_id) if asset_id else None
    alt = node.attrs.get("alt", "")
    url = None
    if asset:
        url = asset.get("export_path") if ctx.export else asset.get("public_url")
    if not url:
        classes = (node.attrs.get("class", "") + " slot-ph").strip()
        return Node("div", {"class": classes, "role": "img", "aria-label": alt or "Photo coming soon"})
    attrs = {"src": url, "alt": alt}
    for k in ("class", "id", "width", "height"):
        if k in node.attrs:
            attrs[k] = node.attrs[k]
    if asset.get("width") and "width" not in attrs:
        attrs["width"] = str(asset["width"])
    if asset.get("height") and "height" not in attrs:
        attrs["height"] = str(asset["height"])
    if node.attrs.get("data-priority") == "high":
        attrs["fetchpriority"] = "high"
    else:
        attrs["loading"] = "lazy"
        attrs["decoding"] = "async"
    return Node("img", attrs)


# ------------------------------------------------------------------ the slot pass

def _strip_markers(attrs: dict) -> dict:
    return {k: v for k, v in attrs.items() if k not in SLOT_ATTRS}


def _truthy_if(expr: str, ctx: Ctx) -> bool:
    negate = expr.startswith("!")
    present = _present(ctx.lookup(expr.lstrip("!")))
    return (not present) if negate else present


def _transform(nodes: list, ctx: Ctx) -> list:
    out: list = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
            continue
        a = n.attrs
        if "data-if" in a and not _truthy_if(a["data-if"], ctx):
            continue
        if "data-repeat" in a:
            items = ctx.lookup(a["data-repeat"])
            if not isinstance(items, list) or not items:
                continue
            for item in items[:MAX_REPEAT]:
                inner = n.clone()
                del inner.attrs["data-repeat"]
                out.extend(_transform([inner], ctx.child(item)))
            continue
        if "data-slot-img" in a:
            out.append(_image_node(n, ctx))
            continue
        if "data-slot" in a:
            value = ctx.lookup(a["data-slot"])
            fmt = a.get("data-format", "")
            if not _present(value) and not (fmt in ("naira", "price") and value is not None):
                continue
            if isinstance(value, (list, dict)):
                continue
            out.append(Node(n.tag, _strip_markers(a), [_format(value, fmt, ctx)]))
            continue
        attrs = dict(a)
        if "data-slot-href" in a:
            link = build_link(a["data-slot-href"], ctx)
            if link is None:
                continue
            href, external = link
            attrs["href"] = href
            if external:
                attrs["target"] = "_blank"
                attrs["rel"] = "noopener"
        out.append(Node(n.tag, _strip_markers(attrs), _transform(n.children, ctx)))
    return out


def fill_slots(skeleton_html: str, content: dict, assets_by_id: dict, export: bool = False) -> str:
    ctx = Ctx(content=content or {}, assets=assets_by_id or {}, export=export)
    return _serialise(_transform(parse_fragment(skeleton_html), ctx))


# ------------------------------------------------------------------ the page

def extract_root_tokens(css: str) -> dict:
    """The contract colours declared as hex in :root, read from validated CSS."""
    import tinycss2
    found: dict = {}
    for rule in tinycss2.parse_stylesheet(css or "", skip_comments=True, skip_whitespace=True):
        if rule.type != "qualified-rule":
            continue
        sel = tinycss2.serialize(rule.prelude).strip()
        if sel not in (":root", "html"):
            continue
        for d in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True):
            if d.type == "declaration" and d.name in COLOUR_VARS:
                value = tinycss2.serialize(d.value).strip()
                if _HEX_RE.match(value):
                    found[d.name] = value
    return found


def css_contract_errors(css: str) -> list[str]:
    """Spec section 6: the skeleton must declare the four colours in :root and USE all six variables."""
    errors: list[str] = []
    declared = extract_root_tokens(css)
    for name in COLOUR_VARS:
        if name not in declared:
            errors.append(f"CSS must declare {name} as a #RRGGBB colour in :root")
    for name in CONTRACT_VARS:
        if f"var({name}" not in css:
            errors.append(f"CSS must use var({name})")
    return errors


def _json_ld(content: dict, canonical: Optional[str]) -> str:
    biz = content.get("business") or {}
    seo = content.get("seo") or {}
    data: dict = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": biz.get("name", "")}
    if seo.get("description"):
        data["description"] = seo["description"]
    if canonical:
        data["url"] = canonical
    number = _digits(biz.get("phone_display", "")) or _digits(biz.get("whatsapp_e164", ""))
    if number:
        data["telephone"] = "+" + number
    addr = ((content.get("location") or {}).get("address") or "").strip()
    if addr:
        data["address"] = {"@type": "PostalAddress", "streetAddress": addr, "addressLocality": biz.get("city", "")}
    ig = (biz.get("instagram") or "").strip().lstrip("@")
    if _IG_RE.match(ig):
        data["sameAs"] = [f"https://instagram.com/{ig}"]
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def render_premium_page(*, content: dict, design: dict, assets_by_id: dict, export: bool,
                        canonical_domain: Optional[str] = None) -> str:
    """The full page. `design` is a site_designs row (skeleton_html, skeleton_css, tokens, art_direction)."""
    art = design.get("art_direction") or {}
    headline_font = art.get("headline_font") or ""
    body_font = art.get("body_font") or ""
    font_link = fonts.font_url(headline_font, body_font)          # raises FontError if not in the registry
    head_stack, body_stack = fonts.font_stacks(headline_font, body_font)

    tokens = design.get("tokens") or {}
    var_css = ["--font-head:" + head_stack, "--font-body:" + body_stack]
    for name in COLOUR_VARS:
        value = tokens.get(name)
        if value and _HEX_RE.match(value):
            var_css.append(f"{name}:{value}")
    tokens_css = ":root{" + ";".join(var_css) + "}"

    body = fill_slots(design.get("skeleton_html") or "", content, assets_by_id, export=export)

    biz = content.get("business") or {}
    seo = content.get("seo") or {}
    title = seo.get("title") or biz.get("name", "")
    description = seo.get("description") or ""
    canonical = f"https://{canonical_domain}/" if (export and canonical_domain) else None
    preview_bar = "" if export else (
        '<div style="background:#1b1b1b;color:#fff;text-align:center;font:600 12px/1 system-ui;padding:8px;'
        'letter-spacing:.06em">PREVIEW &mdash; NOT YET LIVE</div>')
    robots = ('<meta name="robots" content="index, follow, max-image-preview:large">' if export
              else '<meta name="robots" content="noindex, nofollow">')
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        robots,
        f"<title>{escape(title)}</title>",
    ]
    if description:
        head.append(f'<meta name="description" content="{escape(description, quote=True)}">')
    if tokens.get("--bg") and _HEX_RE.match(tokens["--bg"]):
        head.append(f'<meta name="theme-color" content="{tokens["--bg"]}">')
    if canonical:
        head.append(f'<link rel="canonical" href="{escape(canonical, quote=True)}">')
        head.append(f'<meta property="og:url" content="{escape(canonical, quote=True)}">')
    head += [
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{escape(biz.get("name", ""), quote=True)}">',
        f'<meta property="og:title" content="{escape(title, quote=True)}">',
    ]
    if description:
        head.append(f'<meta property="og:description" content="{escape(description, quote=True)}">')
    head += [
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{escape(font_link, quote=True)}">',
        f'<script type="application/ld+json">{_json_ld(content, canonical)}</script>',
        f"<style>{_BASE_CSS}{design.get('skeleton_css') or ''}{tokens_css}{_REDUCED_MOTION_CSS}</style>",
    ]
    return ('<!doctype html><html lang="en"><head>' + "".join(head) + "</head><body>"
            + preview_bar + body + "</body></html>")
