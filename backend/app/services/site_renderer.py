"""
app/services/site_renderer.py
------------------------------
SITE-1A — the site engine: content JSON x recipe -> one static, script-free HTML page.

Hardened from the SITE-0 prototype (website-business/engine-prototype/render.py):
  - `products` -> generic `items`, driven by the preset's `labels` (spec §5.1/§8.2) so
    the same three themes serve a boutique, a restaurant, a salon, or a "services" preset
    without any niche-specific copy baked into the renderer.
  - `image_label` placeholder strings -> real `image_asset_id` resolution against
    site_assets public URLs, falling back to the same placeholder box when a slot has no
    photo yet (so a preview looks reasonable before the builder uploads anything).
  - A colour system (§8.4): a custom hex colour is turned into a full, WCAG-checked
    palette; named palettes are unchanged.
  - Recipe validation (§8.3): every theme / palette / font pairing / section variant must
    exist in the registry and be allowed for the preset.
  - Every value still passes through html.escape() (spec §8.1). There is still no
    <script> anywhere in a themed page. Every href the engine emits is either a wa.me
    link it builds itself, or an internal #anchor — no user-supplied string is ever used
    as a raw href, so the §18 "links only on an allow-list" rule is satisfied by
    construction, not by a runtime check.

Public API:
  render_page(content, recipe, preset, assets_by_slot, preview_bar=True) -> str
  render_export(content, recipe, preset, assets_by_slot) -> str   # SITE-1A §8.6, no bar, local image paths
  validate_recipe(preset, recipe) -> None                          # raises ValueError
  resolve_recipe_colours(recipe) -> dict                           # palette dict, custom or named
  generate_slug(business_name) -> str
"""
from __future__ import annotations

import re
import secrets
from html import escape
from urllib.parse import quote

# ---------------------------------------------------------------- themes / palettes (code, §5.1)

THEMES = {
    "atelier": {  # elegant
        "fonts": ("Bodoni Moda", "Jost"),
        "font_url": "https://fonts.googleapis.com/css2?family=Bodoni+Moda:opsz,wght@6..96,500;6..96,700&family=Jost:wght@400;500;600&display=swap",
        "display_fallback": "Georgia, 'Times New Roman', serif",
        "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "radius": "2px", "btn_radius": "0", "upper_headings": False,
    },
    "market": {  # bold
        "fonts": ("Anton", "Manrope"),
        "font_url": "https://fonts.googleapis.com/css2?family=Anton&family=Manrope:wght@400;600;800&display=swap",
        "display_fallback": "Impact, 'Arial Narrow', sans-serif",
        "body_fallback": "'Segoe UI', Arial, sans-serif",
        "radius": "14px", "btn_radius": "999px", "upper_headings": True,
    },
    "studio": {  # minimal
        "fonts": ("Fraunces", "Karla"),
        "font_url": "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Karla:wght@400;500;700&display=swap",
        "display_fallback": "Georgia, serif",
        "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "radius": "8px", "btn_radius": "8px", "upper_headings": False,
    },
}

PALETTES = {
    "berry":  {"ground": "#F4F0EE", "ink": "#2B1D24", "muted": "#6E5A63", "accent": "#7A2E4A", "on_accent": "#FFFFFF", "soft": "#E9DDE0", "line": "#D9C8CD", "photo": ("#D8C3C8", "#B99AA3")},
    "cobalt": {"ground": "#FFFFFF", "ink": "#101935", "muted": "#4A5372", "accent": "#1F3FD1", "on_accent": "#FFFFFF", "soft": "#EEF1FB", "line": "#D5DBF2", "pop": "#FFB400", "photo": ("#C9D2F3", "#8C9BE0")},
    "sage":   {"ground": "#F2F4EF", "ink": "#1C2620", "muted": "#56645B", "accent": "#35664A", "on_accent": "#FFFFFF", "soft": "#E3E9E0", "line": "#CBD5C7", "photo": ("#D3DDCF", "#A9BCA6")},
}

SECTION_VARIANTS = {
    "hero": ("fullbleed", "collage", "centered"),
    "items": ("grid", "rows", "featured"),
    "about": ("left", "right", "quote"),
    "reviews": ("cards", "spotlight", "list"),
    "categories": ("tiles", "chips"),
    "order": ("steps",),
}

DEFAULT_LABELS = {"items": "Shop", "item": "Item", "price_style": "exact", "cta": "Order on WhatsApp"}
DEFAULT_WA_MESSAGES = {
    "browse":   "Hello! I saw your website and would like to know more.",
    "order":    "Hello! I'd like to order the {item}.",
    "category": "Hello! Please show me your {item}.",
    "start":    "Hello! I would like to start an order.",
}


# ---------------------------------------------------------------- colour system (§8.4)

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _relative_luminance(hex_colour: str) -> float:
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(hex_colour)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _mix(hex_colour: str, with_hex: str, amount: float) -> str:
    """amount=0 -> hex_colour, amount=1 -> with_hex."""
    r1, g1, b1 = _hex_to_rgb(hex_colour)
    r2, g2, b2 = _hex_to_rgb(with_hex)
    return _rgb_to_hex((
        r1 + (r2 - r1) * amount,
        g1 + (g2 - g1) * amount,
        b1 + (b2 - b1) * amount,
    ))


def palette_from_hex(hex_colour: str) -> dict:
    """
    Builds a full palette (same shape as PALETTES[...]) from one accent colour,
    per spec §8.4: dark/ink shades, soft/ground tints, greys tinted towards it,
    then a WCAG 4.5:1 contrast check on both button text and body text.
    """
    accent = hex_colour.upper()
    ink = _mix(accent, "#000000", 0.78)          # dark shade for headings/ink
    muted = _mix(accent, "#6B6B6B", 0.55)         # a tinted grey for secondary text
    ground = _mix(accent, "#FFFFFF", 0.96)        # near-white page background
    soft = _mix(accent, "#FFFFFF", 0.88)          # tinted card background
    line = _mix(accent, "#FFFFFF", 0.78)
    photo = (_mix(accent, "#FFFFFF", 0.55), _mix(accent, "#000000", 0.15))

    # Button text: try white, then ink, then darken the accent for buttons only.
    on_accent = "#FFFFFF"
    contrast_note = None
    if _contrast_ratio(accent, "#FFFFFF") < 4.5:
        if _contrast_ratio(accent, ink) >= 4.5:
            on_accent = ink
        else:
            # Darken the accent for buttons only — page accent stays as given.
            button_accent = accent
            for _ in range(8):
                button_accent = _mix(button_accent, "#000000", 0.12)
                if _contrast_ratio(button_accent, "#FFFFFF") >= 4.5:
                    break
            accent_for_buttons = button_accent
            on_accent = "#FFFFFF"
            contrast_note = (
                "Your colour was too light for white or dark button text to read clearly, "
                "so buttons use a slightly darker shade of it. The rest of the page keeps "
                "your original colour."
            )
        # if ink passed, on_accent already set above
    # Body text vs page background — ink is built dark enough (0.78 mix to black)
    # that this should always clear 4.5:1 against a near-white ground; if a future
    # accent breaks that assumption, darken ink further rather than fail silently.
    if _contrast_ratio(ink, ground) < 4.5:
        ink = _mix(ink, "#000000", 0.3)

    result = {
        "ground": ground, "ink": ink, "muted": muted, "accent": accent,
        "on_accent": on_accent, "soft": soft, "line": line, "photo": photo,
    }
    if contrast_note:
        result["_accent_for_buttons"] = accent_for_buttons
        result["_contrast_note"] = contrast_note
    return result


def resolve_recipe_colours(recipe: dict) -> dict:
    """Returns the palette dict a recipe should render with — named or custom."""
    if recipe.get("custom_colour"):
        return palette_from_hex(recipe["custom_colour"])
    return PALETTES[recipe["palette"]]


# ---------------------------------------------------------------- recipe validation (§8.3)

def validate_recipe(preset: dict, recipe: dict) -> None:
    """Raises ValueError if anything in the recipe isn't in the registry or isn't
    allowed for this preset. Called before every render — a bad recipe must never
    reach the HTML/CSS builders below."""
    theme = recipe.get("theme")
    if theme not in THEMES:
        raise ValueError(f"unknown theme: {theme!r}")
    allowed_themes = preset.get("allowed_themes") or list(THEMES)
    if theme not in allowed_themes:
        raise ValueError(f"theme {theme!r} is not allowed for preset {preset.get('key')!r}")

    if recipe.get("custom_colour"):
        if not re.match(r"^#[0-9A-Fa-f]{6}$", recipe["custom_colour"]):
            raise ValueError("custom_colour must be a 6-digit hex colour")
    elif recipe.get("palette"):
        if recipe["palette"] not in PALETTES:
            raise ValueError(f"unknown palette: {recipe['palette']!r}")
    else:
        raise ValueError("recipe needs either palette or custom_colour")

    order = recipe.get("order") or []
    if not order:
        raise ValueError("recipe.order must not be empty")
    allowed_sections = set(preset.get("sections") or SECTION_VARIANTS.keys())
    for sec in order:
        if sec not in SECTION_VARIANTS:
            raise ValueError(f"unknown section: {sec!r}")
        if sec not in allowed_sections:
            raise ValueError(f"section {sec!r} is not offered by preset {preset.get('key')!r}")
        variant = (recipe.get("variants") or {}).get(sec)
        if variant is not None and variant not in SECTION_VARIANTS[sec]:
            raise ValueError(f"unknown variant {variant!r} for section {sec!r}")


# ---------------------------------------------------------------- helpers

def esc(v) -> str:
    return escape(str(v), quote=True)


def naira(n) -> str:
    return "&#8358;" + f"{int(round(float(n))):,}"


def generate_slug(business_name: str) -> str:
    """`{business-name}-{6 random chars}` per spec §5.3."""
    base = re.sub(r"[^a-z0-9]+", "-", (business_name or "site").lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base) or "site"
    base = base[:40]
    suffix = secrets.token_hex(3)  # 6 hex chars
    return f"{base}-{suffix}"


class _Assets:
    """Resolves image_asset_id -> a URL (public preview) or a local export path,
    with the same placeholder box the prototype used when a slot has no photo yet."""

    def __init__(self, assets_by_id: dict, export_mode: bool = False):
        self._assets = assets_by_id or {}
        self._export = export_mode

    def img_or_placeholder(self, asset_id, label: str, css_class: str = "") -> str:
        asset = self._assets.get(asset_id) if asset_id else None
        if not asset:
            return (f'<div class="ph {css_class}" role="img" aria-label="{esc(label)}">'
                    f'<span class="ph-tag">Photo coming</span><span class="ph-label">{esc(label)}</span></div>')
        url = asset.get("export_path") if self._export else asset.get("public_url")
        url = esc(url or "")
        return f'<div class="photo {css_class}" role="img" aria-label="{esc(label)}"><img src="{url}" alt="{esc(label)}" loading="lazy"></div>'


def wa(business: dict, msg: str) -> str:
    return f"https://wa.me/{esc(str(business['whatsapp_e164']).lstrip('+'))}?text={quote(msg)}"


WA_ICON = ('<svg class="wa-i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
           '<path d="M4 20l1.3-3.9A8 8 0 1 1 8 19Z"/></svg>')


def btn_wa(business: dict, text: str, msg: str, cls: str = "btn btn-accent") -> str:
    return f'<a class="{cls}" href="{wa(business, msg)}" target="_blank" rel="noopener">{WA_ICON}<span>{esc(text)}</span></a>'


def price_html(item: dict, price_style: str) -> str:
    style = item.get("price_style") or price_style
    if style == "on_request":
        return '<span class="price">Price on request</span>'
    amount = naira(item.get("price_ngn", 0))
    if style == "from":
        return f'<span class="price">From {amount}</span>'
    return f'<span class="price">{amount}</span>'


def tag_html(item: dict) -> str:
    return f'<span class="tag">{esc(item["tag"])}</span>' if item.get("tag") else ""


# ---------------------------------------------------------------- section renderers

def _nav(c: dict, labels: dict, wa_msgs: dict) -> str:
    b = c["business"]
    msg = wa_msgs.get("browse", DEFAULT_WA_MESSAGES["browse"])
    return (f'<header class="nav wrap"><div class="brand">{esc(b["name"])}</div>'
            f'<nav class="nav-links"><a href="#shop">{esc(labels["items"])}</a><a href="#about">Our story</a><a href="#order">How to order</a></nav>'
            f'{btn_wa(b, labels["cta"], msg, "btn btn-small btn-accent")}</header>')


def _hero(c: dict, variant: str, assets: "_Assets") -> str:
    h = c["hero"]
    b = c["business"]
    img = assets.img_or_placeholder(h.get("image_asset_id"), h.get("headline", b["name"]), "ph-hero")
    if variant == "fullbleed":
        return (f'<section class="hero hero-fullbleed">{img}<div class="hero-scrim" aria-hidden="true"></div>'
                f'<div class="hero-over wrap"><p class="eyebrow">{esc(b.get("city",""))}{" &middot; " + esc(b["delivery_note"]) if b.get("delivery_note") else ""}</p>'
                f'<h1>{esc(h["headline"])}</h1><p class="lead">{esc(h.get("subhead",""))}</p>'
                f'<div class="row">{btn_wa(b, "Chat on WhatsApp", DEFAULT_WA_MESSAGES["browse"])}'
                f'<a class="btn btn-ghost-light" href="#shop">See more</a></div></div></section>')
    if variant == "collage":
        items = c.get("items", [])[:3]
        tiles = "".join(assets.img_or_placeholder(it.get("image_asset_id"), it["name"], f"ph-col ph-col-{i}") for i, it in enumerate(items))
        return (f'<section class="hero hero-collage wrap"><div class="collage-text">'
                f'<p class="chip">{esc(b.get("city",""))}</p><h1>{esc(h["headline"])}</h1>'
                f'<p class="lead">{esc(h.get("subhead",""))}</p><div class="row">'
                f'{btn_wa(b, "Chat on WhatsApp", DEFAULT_WA_MESSAGES["browse"])}'
                f'<a class="btn btn-outline" href="#shop">Browse all</a></div></div>'
                f'<div class="collage">{tiles}</div></section>')
    # centered
    strip = "".join(assets.img_or_placeholder(it.get("image_asset_id"), it["name"], "ph-strip") for it in c.get("items", [])[:4])
    return (f'<section class="hero hero-centered wrap"><p class="eyebrow">{esc(b.get("tagline",""))}</p>'
            f'<h1>{esc(h["headline"])}</h1><p class="lead">{esc(h.get("subhead",""))}</p>'
            f'<div class="row row-center">{btn_wa(b, "Chat on WhatsApp", DEFAULT_WA_MESSAGES["browse"])}</div>'
            f'<div class="strip">{strip}</div></section>')


def _categories(c: dict, variant: str, assets: "_Assets", wa_msgs: dict) -> str:
    cats = c.get("categories", [])
    if not cats:
        return ""
    b = c["business"]
    msg_tpl = wa_msgs.get("category", DEFAULT_WA_MESSAGES["category"])
    if variant == "chips":
        items = "".join(
            f'<a class="cat-chip" href="{wa(b, msg_tpl.format(item=x["name"]))}" target="_blank" rel="noopener">{esc(x["name"])}</a>'
            for x in cats)
        return f'<section class="chips-band"><div class="wrap chips">{items}</div></section>'
    items = "".join(
        f'<a class="cat" href="{wa(b, msg_tpl.format(item=x["name"]))}" target="_blank" rel="noopener">'
        f'{assets.img_or_placeholder(x.get("image_asset_id"), x["name"], "ph-cat")}'
        f'<div class="cat-label"><strong>{esc(x["name"])}</strong><span>{esc(x.get("teaser",""))}</span></div></a>'
        for x in cats)
    return f'<section class="sec wrap"><p class="eyebrow">Browse</p><h2>Find what you need</h2><div class="cats">{items}</div></section>'


def _items(c: dict, variant: str, assets: "_Assets", labels: dict, wa_msgs: dict) -> str:
    items = c.get("items", [])
    if not items:
        return ""
    b = c["business"]
    price_style = labels.get("price_style", "exact")
    order_tpl = wa_msgs.get("order", DEFAULT_WA_MESSAGES["order"])

    if variant == "rows":
        rows = "".join(
            f'<article class="prow {"prow-flip" if i % 2 else ""}">{assets.img_or_placeholder(p.get("image_asset_id"), p["name"], "ph-row")}'
            f'<div class="prow-body">{tag_html(p)}'
            f'<h3>{esc(p["name"])}</h3><p class="desc">{esc(p.get("desc",""))}</p><div class="price big">{price_html(p, price_style)}</div>'
            f'{btn_wa(b, labels["cta"], order_tpl.format(item=p["name"]))}</div></article>'
            for i, p in enumerate(items[:4]))
        more = "".join(f'<li><span>{esc(p["name"])}</span>{price_html(p, price_style)}</li>' for p in items[4:])
        more_html = f'<div class="more"><h3>Also available</h3><ul>{more}</ul></div>' if more else ""
        return f'<section class="sec wrap" id="shop"><p class="eyebrow">{esc(labels["items"])}</p><h2>Our {esc(labels["items"])}</h2><div class="prows">{rows}</div>{more_html}</section>'

    if variant == "featured" and items:
        f0, rest = items[0], items[1:]
        feat = (f'<article class="feat">{assets.img_or_placeholder(f0.get("image_asset_id"), f0["name"], "ph-feat")}<div class="feat-body">'
                f'<p class="eyebrow">Featured</p><h3>{esc(f0["name"])}</h3><p class="desc">{esc(f0.get("desc",""))}</p>'
                f'{price_html(f0, price_style)}{btn_wa(b, labels["cta"], order_tpl.format(item=f0["name"]))}</div></article>')
        small = "".join(
            f'<article class="mini">{assets.img_or_placeholder(p.get("image_asset_id"), p["name"], "ph-mini")}<div><h3>{esc(p["name"])}</h3>'
            f'{price_html(p, price_style)}<a class="text-link" href="{wa(b, order_tpl.format(item=p["name"]))}" target="_blank" rel="noopener">{esc(labels["cta"])} &rarr;</a></div></article>'
            for p in rest)
        return f'<section class="sec wrap" id="shop"><p class="eyebrow">{esc(labels["items"])}</p><h2>Our {esc(labels["items"])}</h2>{feat}<div class="minis">{small}</div></section>'

    # grid (default)
    cards = "".join(
        f'<article class="card">{assets.img_or_placeholder(p.get("image_asset_id"), p["name"], "ph-card")}'
        f'{tag_html(p)}'
        f'<div class="card-body"><h3>{esc(p["name"])}</h3><p class="desc">{esc(p.get("desc",""))}</p>'
        f'{price_html(p, price_style)}'
        f'{btn_wa(b, labels["cta"], order_tpl.format(item=p["name"]), "btn btn-line")}</div></article>'
        for p in items)
    return f'<section class="sec wrap" id="shop"><p class="eyebrow">{esc(labels["items"])}</p><h2>Our {esc(labels["items"])}</h2><div class="grid">{cards}</div></section>'


def _about(c: dict, variant: str, assets: "_Assets") -> str:
    a = c.get("about") or {}
    if not (a.get("title") or a.get("body") or a.get("pull_quote")):
        return ""
    if variant == "quote" and a.get("pull_quote"):
        return (f'<section class="about-band" id="about"><div class="wrap"><p class="band-quote">&ldquo;{esc(a["pull_quote"])}&rdquo;</p>'
                f'<p class="band-sign">{esc(a.get("owner",""))}</p><div class="band-body">'
                + "".join(f"<p>{esc(p)}</p>" for p in a.get("body", [])) + '</div></div></section>')
    side = "right" if variant == "right" else "left"
    return (f'<section class="sec wrap about about-{side}" id="about">{assets.img_or_placeholder(a.get("image_asset_id"), a.get("title","About"), "ph-about")}'
            f'<div class="about-body"><p class="eyebrow">Our story</p><h2>{esc(a.get("title",""))}</h2>'
            + "".join(f"<p>{esc(p)}</p>" for p in a.get("body", []))
            + (f'<p class="sign">&mdash; {esc(a["owner"])}</p>' if a.get("owner") else "")
            + '</div></section>')


def _reviews(c: dict, variant: str) -> str:
    reviews = c.get("reviews", [])
    if not reviews:
        return ""
    if variant == "spotlight":
        first, rest = reviews[0], reviews[1:]
        small = "".join(f'<figure><blockquote>{esc(x["text"])}</blockquote><figcaption>{esc(x.get("who",""))}</figcaption></figure>' for x in rest)
        return (f'<section class="sec wrap spot"><figure class="spot-main"><blockquote>&ldquo;{esc(first["text"])}&rdquo;</blockquote>'
                f'<figcaption>{esc(first.get("who",""))}</figcaption></figure><div class="spot-rest">{small}</div></section>')
    if variant == "list":
        items = "".join(f'<li><p>{esc(x["text"])}</p><span>{esc(x.get("who",""))}</span></li>' for x in reviews)
        return f'<section class="sec wrap"><h2>What people say</h2><ul class="rlist">{items}</ul></section>'
    cards = "".join(f'<figure class="rev"><blockquote>{esc(x["text"])}</blockquote><figcaption>{esc(x.get("who",""))}</figcaption></figure>' for x in reviews)
    return f'<section class="sec wrap"><p class="eyebrow">Reviews</p><h2>What people say</h2><div class="revs">{cards}</div></section>'


def _order(c: dict, b: dict, labels: dict, wa_msgs: dict) -> str:
    o = c.get("order_section") or {}
    steps = o.get("steps") or []
    if not steps:
        return ""
    steps_html = "".join(f'<li><span class="n">{i}</span><p>{esc(s)}</p></li>' for i, s in enumerate(steps, 1))
    msg = wa_msgs.get("start", DEFAULT_WA_MESSAGES["start"])
    return (f'<section class="sec wrap order" id="order"><h2>{esc(o.get("title") or "How to order")}</h2><ol class="steps">{steps_html}</ol>'
            f'<div class="row">{btn_wa(b, labels["cta"], msg)}</div></section>')


def _footer(c: dict) -> str:
    b = c["business"]
    hours = c.get("hours") or []
    location = c.get("location") or {}
    hours_html = ""
    if hours:
        rows = "".join(f'<p>{esc(h["days"])}: {esc(h["time"])}</p>' for h in hours)
        hours_html = f'<div>{rows}</div>'
    loc_html = ""
    if location.get("address") or location.get("landmark"):
        loc_html = f'<div><p>{esc(location.get("address",""))}</p><p>{esc(location.get("landmark",""))}</p></div>'
    return (f'<footer class="foot"><div class="wrap foot-in"><div><div class="brand">{esc(b["name"])}</div>'
            f'<p>{esc(b.get("city",""))}{" &middot; " + esc(b["delivery_note"]) if b.get("delivery_note") else ""}</p></div>'
            f'<div><p>WhatsApp: {esc(b.get("phone_display") or b["whatsapp_e164"])}</p>'
            + (f'<p>Instagram: @{esc(b["instagram"])}</p>' if b.get("instagram") else "") + '</div>'
            + hours_html + loc_html + '</div></footer>')


# ---------------------------------------------------------------- CSS (unchanged from prototype;
# palette values are substituted, not the rules themselves — see resolve_recipe_colours)

def _prune_css(css_text: str, body: str) -> str:
    used = set()
    for group in re.findall(r'class="([^"]+)"', body):
        used.update(group.split())

    def keep(sel: str) -> bool:
        classes = re.findall(r"\.([a-zA-Z0-9_-]+)", sel)
        return not classes or any(cl in used for cl in classes)

    def prune_rules(chunk: str) -> str:
        out = []
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", chunk):
            sels = [x for x in m.group(1).split(",") if keep(x)]
            if sels:
                out.append(",".join(s.strip() for s in sels) + "{" + m.group(2) + "}")
        return "".join(out)

    text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    text = re.sub(r"\s*\n\s*", "", text)
    out, i = [], 0
    while i < len(text):
        if text.startswith("@media", i):
            start = text.index("{", i)
            depth, j = 1, start + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            inner = prune_rules(text[start + 1:j - 1])
            if inner:
                out.append(text[i:start + 1] + inner + "}")
            i = j
        else:
            j = text.index("}", i) + 1
            out.append(prune_rules(text[i:j]))
            i = j
    return "".join(out)


def _css(theme_key: str, palette: dict) -> str:
    t = THEMES[theme_key]
    disp = f"'{t['fonts'][0]}', {t['display_fallback']}"
    body = f"'{t['fonts'][1]}', {t['body_fallback']}"
    up = "text-transform:uppercase;letter-spacing:.01em;" if t["upper_headings"] else ""
    pop = palette.get("pop", palette.get("_accent_for_buttons", palette["accent"]))
    btn_accent = palette.get("_accent_for_buttons", palette["accent"])
    return f"""
:root{{--ground:{palette['ground']};--ink:{palette['ink']};--muted:{palette['muted']};--accent:{palette['accent']};--btn-accent:{btn_accent};--on-accent:{palette['on_accent']};--soft:{palette['soft']};--line:{palette['line']};--pop:{pop};--ph1:{palette['photo'][0]};--ph2:{palette['photo'][1]};--r:{t['radius']};--br:{t['btn_radius']}}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:{body};color:var(--ink);background:var(--ground);line-height:1.6;-webkit-font-smoothing:antialiased}}
a{{color:inherit;text-decoration:none}}
img{{display:block;max-width:100%;height:auto}}
.wrap{{max-width:1160px;margin:0 auto;padding-left:24px;padding-right:24px}}
h1,h2,h3{{font-family:{disp};font-weight:{'400' if t['upper_headings'] else '600'};line-height:1.05;{up}}}
h1{{font-size:clamp(2.6rem,6vw,4.6rem)}} h2{{font-size:clamp(1.9rem,4vw,2.8rem);margin-bottom:28px}} h3{{font-size:1.35rem}}
.eyebrow{{font-size:.76rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}}
.lead{{font-size:1.1rem;color:var(--muted);max-width:34em;margin-top:16px}}
.row{{display:flex;flex-wrap:wrap;gap:12px;margin-top:28px}} .row-center{{justify-content:center}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:14px 22px;border-radius:var(--br);font-weight:600;font-size:.95rem;border:1.5px solid transparent;min-height:44px}}
.btn-accent{{background:var(--btn-accent);color:var(--on-accent)}}
.btn-line{{border-color:var(--ink);color:var(--ink);width:100%;justify-content:center}}
.btn-outline{{border-color:var(--ink)}}
.btn-ghost-light{{border-color:#fff;color:#fff}}
.btn-small{{padding:10px 16px;font-size:.85rem}}
.wa-i{{width:18px;height:18px;flex:none}}
.text-link{{color:var(--accent);font-weight:600;font-size:.9rem}}
.sec{{padding-top:80px;padding-bottom:80px}}
.nav{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-top:20px;padding-bottom:20px}}
.brand{{font-family:{disp};font-size:1.5rem;{up}}}
.nav-links{{display:flex;gap:28px;font-size:.92rem;color:var(--muted)}}
.ph,.photo{{position:relative;overflow:hidden;border-radius:var(--r);min-height:120px}}
.ph{{background:linear-gradient(150deg,var(--ph1),var(--ph2));display:flex;flex-direction:column;justify-content:flex-end;padding:14px}}
.ph-tag{{font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ink);opacity:.55}}
.ph-label{{font-size:.85rem;font-weight:600;color:var(--ink);opacity:.75}}
.photo img{{width:100%;height:100%;object-fit:cover;position:absolute;inset:0}}
.hero-fullbleed{{position:relative;min-height:560px;display:flex;align-items:flex-end}}
.hero-fullbleed .ph-hero,.hero-fullbleed .photo{{position:absolute;inset:0;border-radius:0}}
.hero-fullbleed .ph-hero{{background:linear-gradient(160deg,var(--ph1),var(--ph2) 55%,var(--ink));padding:24px;justify-content:flex-start;align-items:flex-end}}
.hero-fullbleed .photo img{{object-position:50% 20%}}
.hero-scrim{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 25%,rgba(0,0,0,.35) 60%,rgba(0,0,0,.72) 100%)}}
.hero-over{{position:relative;color:#fff;padding-top:120px;padding-bottom:64px;width:100%;text-shadow:0 1px 3px rgba(0,0,0,.35)}}
.hero-over .eyebrow{{color:#fff;opacity:.85}} .hero-over .lead{{color:#fff;opacity:.9}}
.hero-collage{{display:grid;grid-template-columns:1.1fr 1fr;gap:40px;align-items:center;padding-top:40px;padding-bottom:72px}}
.chip{{display:inline-block;background:var(--pop);color:var(--ink);font-weight:800;font-size:.78rem;padding:6px 12px;border-radius:999px;margin-bottom:18px;text-transform:uppercase;letter-spacing:.08em}}
.collage{{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:220px 220px;gap:14px}}
.ph-col-0{{grid-row:span 2}}
.hero-centered{{text-align:center;padding-top:72px;padding-bottom:40px}}
.hero-centered .lead{{margin-left:auto;margin-right:auto}}
.strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:56px}} .ph-strip{{aspect-ratio:3/4}}
.cats{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}
.cat{{display:flex;flex-direction:column;gap:10px}} .ph-cat{{aspect-ratio:4/5}}
.cat-label{{display:flex;flex-direction:column}} .cat-label span{{color:var(--muted);font-size:.9rem}}
.chips-band{{background:var(--ink);padding-top:18px;padding-bottom:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:10px}}
.cat-chip{{color:var(--ground);border:1.5px solid var(--ground);border-radius:999px;padding:8px 16px;font-weight:600;font-size:.9rem}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}}
.card{{position:relative;display:flex;flex-direction:column;background:var(--ground)}}
.ph-card{{aspect-ratio:4/5}}
.tag{{position:absolute;top:12px;left:12px;background:var(--accent);color:var(--on-accent);font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;padding:5px 10px}}
.card-body{{display:flex;flex-direction:column;gap:6px;padding-top:14px}} .desc{{color:var(--muted);font-size:.93rem}}
.price{{font-weight:700;font-size:1.05rem;margin:4px 0 10px;display:inline-block}} .price.big{{font-size:1.6rem}}
.prows{{display:flex;flex-direction:column;gap:32px}}
.prow{{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center;background:var(--soft);border-radius:var(--r);padding:24px}}
.prow-flip .ph-row,.prow-flip .photo{{order:2}} .ph-row{{aspect-ratio:1/1}}
.prow-body{{display:flex;flex-direction:column;gap:10px;align-items:flex-start}}
.prow-body h3{{font-size:clamp(1.8rem,3vw,2.6rem)}}
.more{{margin-top:40px;border-top:2px solid var(--ink);padding-top:20px}}
.more ul{{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:10px 40px;margin-top:14px}}
.more li{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:8px}}
.feat{{display:grid;grid-template-columns:1.3fr 1fr;gap:40px;align-items:center;margin-bottom:48px}} .ph-feat{{aspect-ratio:5/4}}
.feat-body{{display:flex;flex-direction:column;gap:10px;align-items:flex-start}}
.minis{{display:grid;grid-template-columns:repeat(5,1fr);gap:20px}}
.mini{{display:flex;flex-direction:column;gap:10px}} .ph-mini{{aspect-ratio:3/4}} .mini h3{{font-size:1.05rem}}
.about{{display:grid;grid-template-columns:1fr 1.1fr;gap:56px;align-items:center}}
.about-right .ph-about,.about-right .photo{{order:2}} .ph-about{{aspect-ratio:4/5}}
.about-body p{{margin-bottom:14px;color:var(--muted);max-width:34em}} .sign{{font-style:italic;color:var(--ink)!important}}
.about-band{{background:var(--accent);color:var(--on-accent);padding-top:88px;padding-bottom:88px}}
.band-quote{{font-family:{disp};font-size:clamp(2rem,4.4vw,3.4rem);line-height:1.08;max-width:18em;{up}}}
.band-sign{{margin-top:18px;font-weight:700}}
.band-body{{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:40px;opacity:.9}}
.revs{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
.rev{{background:var(--soft);border-radius:var(--r);padding:26px;display:flex;flex-direction:column;gap:14px}}
.rev figcaption,.spot figcaption{{font-size:.85rem;color:var(--muted);font-weight:600}}
.spot{{display:grid;grid-template-columns:1.4fr 1fr;gap:48px;align-items:center}}
.spot-main blockquote{{font-family:{disp};font-size:clamp(1.8rem,3.6vw,2.8rem);line-height:1.12;margin-bottom:16px;{up}}}
.spot-rest{{display:flex;flex-direction:column;gap:22px}} .spot-rest figure{{border-left:4px solid var(--pop);padding-left:16px}}
.rlist{{list-style:none;border-top:1px solid var(--line)}}
.rlist li{{display:grid;grid-template-columns:1fr 200px;gap:24px;padding:22px 0;border-bottom:1px solid var(--line)}}
.rlist p{{font-family:{disp};font-size:1.2rem}} .rlist span{{color:var(--muted);font-size:.9rem;text-align:right}}
.steps{{list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
.steps li{{display:flex;flex-direction:column;gap:10px;border-top:2px solid var(--ink);padding-top:16px}}
.n{{font-family:{disp};font-size:2rem;color:var(--accent)}}
.foot{{background:var(--ink);color:var(--ground);padding-top:48px;padding-bottom:48px}}
.foot-in{{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap}} .foot p{{opacity:.8;font-size:.92rem}}
@media (max-width:760px){{
 .nav-links{{display:none}} .sec{{padding-top:56px;padding-bottom:56px}}
 .hero-collage,.prow,.feat,.about,.spot,.band-body{{grid-template-columns:1fr}}
 .prow-flip .ph-row,.prow-flip .photo,.about-right .ph-about,.about-right .photo{{order:0}}
 .collage{{grid-template-rows:170px 170px}}
 .grid{{grid-template-columns:1fr 1fr;gap:14px}} .cats{{grid-template-columns:1fr 1fr}}
 .strip{{grid-template-columns:1fr 1fr}} .minis{{grid-template-columns:1fr 1fr}}
 .revs,.steps{{grid-template-columns:1fr}} .more ul{{grid-template-columns:1fr}}
 .rlist li{{grid-template-columns:1fr}} .rlist span{{text-align:left}}
 .hero-fullbleed{{min-height:520px}} .btn-line{{padding:12px 10px;font-size:.85rem}}
}}
"""


# ---------------------------------------------------------------- top-level render

def _render_body(content: dict, recipe: dict, preset: dict, assets: "_Assets") -> str:
    labels = {**DEFAULT_LABELS, **(preset.get("labels") or {})}
    wa_msgs = {**DEFAULT_WA_MESSAGES, **(preset.get("wa_messages") or {})}
    variants = recipe.get("variants") or {}
    hidden = set(recipe.get("hidden") or [])
    b = content["business"]

    # `variants.get(key, default)` only falls back when the key is ABSENT, not
    # when it's present with value None — and every recipe's `variants` here
    # comes from the Recipe Pydantic model (SectionVariants), whose fields
    # default to None but are still serialized as explicit `null` keys, never
    # omitted. So the `, default` form silently never applied: every section
    # was always rendering its "variant is None" fallback branch (for hero,
    # that branch shows no photo at all, even when one was uploaded) instead
    # of the intended default variant. `or default` treats None the same as
    # "key missing", which is what was actually meant here.
    renderers = {
        "hero": lambda: _hero(content, variants.get("hero") or "fullbleed", assets),
        "categories": lambda: _categories(content, variants.get("categories") or "tiles", assets, wa_msgs),
        "items": lambda: _items(content, variants.get("items") or "grid", assets, labels, wa_msgs),
        "about": lambda: _about(content, variants.get("about") or "left", assets),
        "reviews": lambda: _reviews(content, variants.get("reviews") or "cards"),
        "order": lambda: _order(content, b, labels, wa_msgs),
    }
    parts = [_nav(content, labels, wa_msgs)]
    for sec in recipe.get("order", []):
        if sec in hidden or sec not in renderers:
            continue
        parts.append(renderers[sec]())
    parts.append(_footer(content))
    return "\n".join(p for p in parts if p)


def _render_page(content: dict, recipe: dict, preset: dict, assets: "_Assets", preview_bar: bool) -> str:
    validate_recipe(preset, recipe)
    palette = resolve_recipe_colours(recipe)
    theme = THEMES[recipe["theme"]]
    body = _render_body(content, recipe, preset, assets)
    bar = ('<div style="background:#1b1b1b;color:#fff;text-align:center;font:600 12px/1 system-ui;padding:8px;letter-spacing:.06em">'
           'PREVIEW &mdash; NOT YET LIVE</div>') if preview_bar else ""
    seo = content.get("seo") or {}
    title = seo.get("title") or content["business"]["name"]
    description = seo.get("description") or ""
    meta_desc = f'<meta name="description" content="{esc(description)}">' if description else ""
    robots = '<meta name="robots" content="noindex, nofollow">' if preview_bar else ""
    css_text = _prune_css(_css(recipe["theme"], palette), body)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'{robots}{meta_desc}<title>{esc(title)}</title>'
            f'<link rel="stylesheet" href="{theme["font_url"]}">'
            f'<style>{css_text}</style></head>'
            f'<body>{bar}{body}</body></html>')


def render_page(content: dict, recipe: dict, preset: dict, assets_by_id: dict) -> str:
    """The public preview (§8.5) — includes the neutral preview bar and noindex."""
    return _render_page(content, recipe, preset, _Assets(assets_by_id, export_mode=False), preview_bar=True)


def render_export(content: dict, recipe: dict, preset: dict, assets_by_id: dict) -> str:
    """The export bundle's index.html (§8.6) — no preview bar, indexable, local image
    paths (each asset dict in assets_by_id must include 'export_path', e.g. 'images/hero.jpg')."""
    return _render_page(content, recipe, preset, _Assets(assets_by_id, export_mode=True), preview_bar=False)
