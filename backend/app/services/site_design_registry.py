"""
app/services/site_design_registry.py
-------------------------------------
SITE-1C-1 — the design registry for Standard sites: design tokens, font pairings,
palettes (with niche / personality tags) and the per-theme rules for which
combinations are allowed.

Pure data + validation. No I/O, no imports from site_renderer (site_renderer imports
THIS module, never the other way round). Themes themselves still live in
site_renderer.THEMES because they are code (SITE-0 §8: theme HTML/CSS is never uploaded).

Backward compatibility (spec SITE-1C §3): a recipe with no `fonts` and no `tokens`
(every site created before SITE-1C-1) renders byte-identically to before — the
renderer only adds token CSS for tokens that are actually set.

The frontend mirrors these registries in frontend/src/modules/sites/sitesKit.js
(FONT_PAIRINGS, TOKENS, PALETTES). tests/unit/test_site_design.py checks that the two
stay in step.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------- design tokens (spec SITE-1C §3)

TOKENS: dict[str, tuple[str, ...]] = {
    "radius": ("sharp", "soft", "pill"),
    "density": ("airy", "regular", "compact"),
    "button": ("solid", "outline", "underline"),
    "heading_case": ("normal", "upper", "spaced_upper"),
    "image_style": ("square", "rounded", "arch", "framed"),
    "divider": ("none", "line", "dot", "ornament"),
    # SITE-1C-1b: page background, alternating section bands, card style.
    # The first option of each is "no change" (renders exactly as before).
    "background": ("match", "white", "grey", "ivory"),
    "bands": ("plain", "wash"),
    # SITE-1C-3e: "tile" = soft filled card with padded text (text no longer touches the photo's edge).
    "cards": ("flat", "bordered", "lifted", "tile"),
    # SITE-1C-3e: how tall a Full photo hero is. Never picked at random (a template opts in, like "finish").
    "hero_height": ("standard", "tall"),
    # SITE-1C-3f: cards per row on phones for grid-style sections (Items grid, Featured, Categories tiles).
    "mobile_cols": ("two", "one"),
    # SITE-1C-3d: "Refined look" — display-scale type, roomier spacing, a floating header, photo hover,
    # a dark story band and a floating WhatsApp button, all CSS-only. "standard" renders as before.
    # The picker never chooses it at random: a template opts in by narrowing this token to ["refined"].
    "finish": ("standard", "refined"),
}

TOKEN_LABELS: dict[str, str] = {
    "radius": "Corners",
    "density": "Spacing",
    "button": "Buttons",
    "heading_case": "Headings",
    "image_style": "Photos",
    "divider": "Section divider",
    "background": "Page background",
    "bands": "Section bands",
    "cards": "Cards",
    "finish": "Refined look",
    "hero_height": "Hero height",
    "mobile_cols": "Cards on phones",
}

# ---------------------------------------------------------------- section layouts (SITE-1C-2)
# Canonical list; site_renderer.SECTION_VARIANTS is this same object. The FIRST layout of each
# section is its default (what a recipe with no `variants` renders).
SECTION_VARIANTS: dict[str, tuple[str, ...]] = {
    "hero": ("fullbleed", "collage", "centered"),
    "items": ("grid", "rows", "featured", "scroll"),   # SITE-1C-3f: "scroll" = a swipe row (opt-in, never random)
    "about": ("left", "right", "quote"),
    "reviews": ("cards", "spotlight", "list"),
    "categories": ("tiles", "chips"),
    "order": ("steps",),
    # SITE-1C-3: extra sections (a template opts in by listing them in its `sections`).
    "announcement": ("bar",),
    "faq": ("list", "columns"),
    "menu": ("list", "columns"),
    "visit": ("split", "card"),
    "process": ("numbered", "timeline"),
    "team": ("cards", "list"),
    "gallery": ("grid", "masonry", "tiles"),            # SITE-1C-3f: "tiles" = big photo tiles with captions on them (opt-in)
    # SITE-1C-3f: a closing full-width photo banner with a headline and a WhatsApp button.
    "banner": ("photo",),
}

# ---------------------------------------------------------------- font pairings (spec SITE-1C §4)
# `heading_weight` keeps each pairing's display face at a weight it actually ships.
# The first three are the original theme pairings, unchanged (see THEMES in site_renderer).

FONT_GROUPS = ("elegant", "editorial", "bold", "friendly", "minimal")

_GF = "https://fonts.googleapis.com/css2?family="

FONT_PAIRINGS: dict[str, dict] = {
    "bodoni_jost": {
        "label": "Bodoni + Jost", "group": "elegant", "fonts": ("Bodoni Moda", "Jost"),
        "font_url": _GF + "Bodoni+Moda:opsz,wght@6..96,500;6..96,700&family=Jost:wght@400;500;600&display=swap",
        "display_fallback": "Georgia, 'Times New Roman', serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "600",
    },
    "anton_manrope": {
        "label": "Anton + Manrope", "group": "bold", "fonts": ("Anton", "Manrope"),
        "font_url": _GF + "Anton&family=Manrope:wght@400;600;800&display=swap",
        "display_fallback": "Impact, 'Arial Narrow', sans-serif", "body_fallback": "'Segoe UI', Arial, sans-serif",
        "heading_weight": "400",
    },
    "fraunces_karla": {
        "label": "Fraunces + Karla", "group": "editorial", "fonts": ("Fraunces", "Karla"),
        "font_url": _GF + "Fraunces:opsz,wght@9..144,400;9..144,600&family=Karla:wght@400;500;700&display=swap",
        "display_fallback": "Georgia, serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "600",
    },
    "playfair_lato": {
        "label": "Playfair + Lato", "group": "elegant", "fonts": ("Playfair Display", "Lato"),
        "font_url": _GF + "Playfair+Display:wght@500;600;700&family=Lato:wght@400;700&display=swap",
        "display_fallback": "Georgia, 'Times New Roman', serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "600",
    },
    "cormorant_jost": {
        "label": "Cormorant + Jost", "group": "elegant", "fonts": ("Cormorant Garamond", "Jost"),
        "font_url": _GF + "Cormorant+Garamond:wght@500;600;700&family=Jost:wght@400;500;600&display=swap",
        "display_fallback": "Georgia, 'Times New Roman', serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "600",
    },
    "cormorant_dmsans": {
        "label": "Cormorant + DM Sans", "group": "elegant", "fonts": ("Cormorant Garamond", "DM Sans"),
        "font_url": _GF + "Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@400;500;700&display=swap",
        "display_fallback": "Georgia, 'Times New Roman', serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "500",
    },
    "dmserif_dmsans": {
        "label": "DM Serif + DM Sans", "group": "editorial", "fonts": ("DM Serif Display", "DM Sans"),
        "font_url": _GF + "DM+Serif+Display&family=DM+Sans:wght@400;500;700&display=swap",
        "display_fallback": "Georgia, serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "400",
    },
    "archivo_worksans": {
        "label": "Archivo Black + Work Sans", "group": "bold", "fonts": ("Archivo Black", "Work Sans"),
        "font_url": _GF + "Archivo+Black&family=Work+Sans:wght@400;500;600&display=swap",
        "display_fallback": "Impact, 'Arial Narrow', sans-serif", "body_fallback": "'Segoe UI', Arial, sans-serif",
        "heading_weight": "400",
    },
    "syne_dmsans": {
        "label": "Syne + DM Sans", "group": "bold", "fonts": ("Syne", "DM Sans"),
        "font_url": _GF + "Syne:wght@600;700;800&family=DM+Sans:wght@400;500;700&display=swap",
        "display_fallback": "'Arial Black', Arial, sans-serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "700",
    },
    "poppins_nunito": {
        "label": "Poppins + Nunito", "group": "friendly", "fonts": ("Poppins", "Nunito"),
        "font_url": _GF + "Poppins:wght@500;600;700&family=Nunito:wght@400;600;700&display=swap",
        "display_fallback": "'Segoe UI', Arial, sans-serif", "body_fallback": "'Segoe UI', Arial, sans-serif",
        "heading_weight": "600",
    },
    "lora_nunito": {
        "label": "Lora + Nunito", "group": "friendly", "fonts": ("Lora", "Nunito"),
        "font_url": _GF + "Lora:wght@500;600;700&family=Nunito:wght@400;600;700&display=swap",
        "display_fallback": "Georgia, serif", "body_fallback": "'Segoe UI', Arial, sans-serif",
        "heading_weight": "600",
    },
    "jakarta_inter": {
        "label": "Plus Jakarta + Inter", "group": "minimal", "fonts": ("Plus Jakarta Sans", "Inter"),
        "font_url": _GF + "Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap",
        "display_fallback": "'Segoe UI', Arial, sans-serif", "body_fallback": "'Segoe UI', Arial, sans-serif",
        "heading_weight": "700",
    },
    "sora_karla": {
        "label": "Sora + Karla", "group": "minimal", "fonts": ("Sora", "Karla"),
        "font_url": _GF + "Sora:wght@500;600;700&family=Karla:wght@400;500;700&display=swap",
        "display_fallback": "'Segoe UI', Arial, sans-serif", "body_fallback": "'Helvetica Neue', Arial, sans-serif",
        "heading_weight": "600",
    },
}

# ---------------------------------------------------------------- theme rules (spec SITE-1C §3, §8)
# font_groups: which pairing groups suit the theme (the picker only mixes within these).
# default_pairing: the pairing a theme renders with when the recipe sets no `fonts`.
# token_exclusions: options a theme does not support (kept small and deliberate).

THEME_META: dict[str, dict] = {
    "atelier": {
        "font_groups": ("elegant", "editorial"), "default_pairing": "bodoni_jost",
        "token_exclusions": {"radius": ("pill",)},
    },
    "market": {
        "font_groups": ("bold", "friendly"), "default_pairing": "anton_manrope",
        "token_exclusions": {},
    },
    "studio": {
        "font_groups": ("minimal", "friendly", "editorial"), "default_pairing": "fraunces_karla",
        "token_exclusions": {},
    },
}

# ---------------------------------------------------------------- palettes (spec SITE-1C §5)
# Same shape as the original three. New palettes add `pop` (the chip / highlight colour, drawn
# behind dark ink text) so they never depend on the accent-as-highlight fallback.
# Contrast is checked for every palette in tests/unit/test_site_design.py.

PALETTES: dict[str, dict] = {
    "berry":  {"ground": "#F4F0EE", "ink": "#2B1D24", "muted": "#6E5A63", "accent": "#7A2E4A", "on_accent": "#FFFFFF", "soft": "#E9DDE0", "line": "#D9C8CD", "photo": ("#D8C3C8", "#B99AA3")},
    "cobalt": {"ground": "#FFFFFF", "ink": "#101935", "muted": "#4A5372", "accent": "#1F3FD1", "on_accent": "#FFFFFF", "soft": "#EEF1FB", "line": "#D5DBF2", "pop": "#FFB400", "photo": ("#C9D2F3", "#8C9BE0")},
    "sage":   {"ground": "#F2F4EF", "ink": "#1C2620", "muted": "#56645B", "accent": "#35664A", "on_accent": "#FFFFFF", "soft": "#E3E9E0", "line": "#CBD5C7", "photo": ("#D3DDCF", "#A9BCA6")},
    "terracotta": {"ground": "#FAF3EC", "ink": "#2E1F17", "muted": "#6B5346", "accent": "#B4441F", "on_accent": "#FFFFFF", "soft": "#F1E2D3", "line": "#E3CDB9", "pop": "#F2B45A", "photo": ("#E8CDB5", "#C99A78")},
    "midnight": {"ground": "#F7F5F0", "ink": "#0F172A", "muted": "#4B5563", "accent": "#1E3A5F", "on_accent": "#FFFFFF", "soft": "#E8ECF2", "line": "#D2D9E3", "pop": "#D9A441", "photo": ("#C5D0DF", "#8A9BB5")},
    "emerald": {"ground": "#F1F7F4", "ink": "#0E2A21", "muted": "#4C6358", "accent": "#0F6B4F", "on_accent": "#FFFFFF", "soft": "#DDEDE5", "line": "#C4DDD1", "pop": "#F2C14E", "photo": ("#BFE0D0", "#7FB79C")},
    "gold": {"ground": "#FBF8F1", "ink": "#17130B", "muted": "#5F5644", "accent": "#8A6414", "on_accent": "#FFFFFF", "soft": "#F0E8D2", "line": "#E0D3AE", "pop": "#E8C468", "photo": ("#E4D5A8", "#B99B4E")},
    "blush": {"ground": "#FDF3F3", "ink": "#3A1F26", "muted": "#7A5A63", "accent": "#B03A5B", "on_accent": "#FFFFFF", "soft": "#F8E1E5", "line": "#EFC9D1", "pop": "#F6B7C3", "photo": ("#F3CDD5", "#E39BAD")},
    "plum": {"ground": "#F6F1F7", "ink": "#24122E", "muted": "#5F4A6B", "accent": "#5B2A86", "on_accent": "#FFFFFF", "soft": "#E8DCEF", "line": "#D6C3E1", "pop": "#F0C36A", "photo": ("#D6C2E3", "#A784C4")},
    "coral": {"ground": "#FFF7F3", "ink": "#2B1510", "muted": "#6D4B41", "accent": "#C03434", "on_accent": "#FFFFFF", "soft": "#FDE6DC", "line": "#F4CDBD", "pop": "#FFB199", "photo": ("#F8D3C6", "#E79A84")},
    "teal": {"ground": "#F0F7F7", "ink": "#0B2A2E", "muted": "#46636A", "accent": "#0E6B78", "on_accent": "#FFFFFF", "soft": "#DCEDEF", "line": "#C2DDE0", "pop": "#FFC857", "photo": ("#BDE0E4", "#78B5BE")},
    "mustard": {"ground": "#FFFBF0", "ink": "#231A05", "muted": "#6A5A2E", "accent": "#8A5A00", "on_accent": "#FFFFFF", "soft": "#FBEFCF", "line": "#F0DFA6", "pop": "#F5B700", "photo": ("#F3DFA0", "#D8AE3A")},
    "charcoal": {"ground": "#F5F5F3", "ink": "#151515", "muted": "#555555", "accent": "#222222", "on_accent": "#FFFFFF", "soft": "#E9E9E6", "line": "#D4D4D0", "pop": "#DAD7CE", "photo": ("#D9D9D6", "#A6A6A2")},
    "royal": {"ground": "#FFFFFF", "ink": "#0B1B3A", "muted": "#4A5878", "accent": "#B3122A", "on_accent": "#FFFFFF", "soft": "#F1F3F8", "line": "#DCE1EC", "pop": "#FFD166", "photo": ("#D6DCEC", "#98A6CC")},
    "forest": {"ground": "#F3F5EE", "ink": "#14210F", "muted": "#4F5E45", "accent": "#2F5D1F", "on_accent": "#FFFFFF", "soft": "#E2E9D6", "line": "#CDD8BB", "pop": "#E0C341", "photo": ("#CBDBB4", "#93B06E")},
    "sky": {"ground": "#F4F9FD", "ink": "#0F2438", "muted": "#4D6478", "accent": "#1D6FB8", "on_accent": "#FFFFFF", "soft": "#E1EEF9", "line": "#C9DEF0", "pop": "#FFD37A", "photo": ("#C6DDF1", "#8FB8DE")},
    "rose_gold": {"ground": "#FBF4F1", "ink": "#33211F", "muted": "#765A56", "accent": "#A2544B", "on_accent": "#FFFFFF", "soft": "#F3E3DD", "line": "#E6CFC7", "pop": "#EBC1A8", "photo": ("#EBCFC5", "#CE9A8E")},
    "sunset": {"ground": "#FFF9F2", "ink": "#2A1206", "muted": "#6A4E3A", "accent": "#C2410C", "on_accent": "#FFFFFF", "soft": "#FFE9D2", "line": "#F4D2AE", "pop": "#FDBA74", "photo": ("#FBD9B4", "#EE9A5C")},
    "olive": {"ground": "#F6F5EC", "ink": "#1F2110", "muted": "#5A5C3E", "accent": "#5F6B1B", "on_accent": "#FFFFFF", "soft": "#E8E9D2", "line": "#D5D8B5", "pop": "#D9C04A", "photo": ("#D6D9B0", "#A3AB62")},
    "mist": {"ground": "#F5F5F9", "ink": "#1E1E2E", "muted": "#55556B", "accent": "#4B4BA8", "on_accent": "#FFFFFF", "soft": "#E6E6F2", "line": "#D2D2E6", "pop": "#F2C94C", "photo": ("#D0D0EA", "#9B9BD0")},
    "cocoa": {"ground": "#F8F2EC", "ink": "#2A1A12", "muted": "#6E5647", "accent": "#6B3E26", "on_accent": "#FFFFFF", "soft": "#EBDDD0", "line": "#DCC8B6", "pop": "#E0B084", "photo": ("#DCC3AD", "#B08863")},
}

NICHES = ("boutique", "restaurant", "salon", "services")
PERSONALITIES = ("elegant", "bold", "playful", "minimal", "warm")   # used from SITE-1C-2

PALETTE_META: dict[str, dict] = {
    "berry":      {"niches": ("boutique", "salon"), "personality": ("elegant", "warm")},
    "cobalt":     {"niches": ("services", "restaurant", "boutique"), "personality": ("bold", "minimal")},
    "sage":       {"niches": ("salon", "services", "boutique"), "personality": ("minimal", "warm")},
    "terracotta": {"niches": ("restaurant", "boutique", "salon"), "personality": ("warm", "playful")},
    "midnight":   {"niches": ("services", "boutique", "salon"), "personality": ("elegant", "minimal")},
    "emerald":    {"niches": ("restaurant", "services", "salon"), "personality": ("warm", "elegant")},
    "gold":       {"niches": ("boutique", "salon", "restaurant"), "personality": ("elegant",)},
    "blush":      {"niches": ("salon", "boutique", "restaurant"), "personality": ("playful", "elegant", "warm")},
    "plum":       {"niches": ("boutique", "salon", "services"), "personality": ("elegant", "bold")},
    "coral":      {"niches": ("restaurant", "boutique", "salon"), "personality": ("playful", "bold")},
    "teal":       {"niches": ("services", "salon", "restaurant"), "personality": ("minimal", "playful")},
    "mustard":    {"niches": ("restaurant", "boutique", "services"), "personality": ("warm", "bold")},
    "charcoal":   {"niches": ("boutique", "services", "salon"), "personality": ("minimal", "elegant")},
    "royal":      {"niches": ("services", "restaurant", "boutique"), "personality": ("bold", "elegant")},
    "forest":     {"niches": ("restaurant", "services", "salon"), "personality": ("warm", "minimal")},
    "sky":        {"niches": ("services", "salon", "boutique"), "personality": ("minimal", "playful")},
    "rose_gold":  {"niches": ("salon", "boutique", "restaurant"), "personality": ("elegant", "warm")},
    "sunset":     {"niches": ("restaurant", "boutique", "salon"), "personality": ("bold", "playful")},
    "olive":      {"niches": ("restaurant", "services", "salon"), "personality": ("warm", "minimal")},
    "mist":       {"niches": ("services", "salon", "boutique"), "personality": ("minimal", "elegant")},
    "cocoa":      {"niches": ("restaurant", "boutique", "salon"), "personality": ("warm", "elegant")},
}


def palettes_for_niche(niche: Optional[str]) -> list[str]:
    """Palette keys tagged for a niche (a preset key like 'boutique'); every palette if the
    niche is unknown (custom presets a staff member created, e.g. 'bakery')."""
    matched = [k for k, m in PALETTE_META.items() if niche in m["niches"]]
    return matched or list(PALETTES)


# ---------------------------------------------------------------- what a theme / preset allows

def theme_default_pairing(theme: str) -> str:
    return THEME_META[theme]["default_pairing"]


def allowed_pairings(preset: dict, theme: str) -> list[str]:
    """Pairing ids the picker may use for this theme + preset. A preset with an empty
    `allowed_fonts` allows every pairing that suits the theme's font groups."""
    groups = THEME_META[theme]["font_groups"]
    suited = [k for k, p in FONT_PAIRINGS.items() if p["group"] in groups]
    chosen = [k for k in (preset.get("allowed_fonts") or []) if k in FONT_PAIRINGS]
    pool = [k for k in suited if k in chosen] if chosen else suited
    return pool or [theme_default_pairing(theme)]


def palette_fields(entry: str) -> tuple[Optional[str], Optional[str]]:
    """A template's palette list holds palette keys and/or custom hex colours.
    Returns (palette, custom_colour) ready for a recipe: exactly one of them is set."""
    if is_hex(entry):
        return None, entry.upper()
    return entry, None


def allowed_token_options(preset: dict, theme: str, token: str) -> list[str]:
    """Options the picker may use for one token: theme exclusions applied, then the preset's
    `token_options[token]` if staff narrowed it (empty / missing means every option)."""
    options = [o for o in TOKENS[token] if o not in THEME_META[theme]["token_exclusions"].get(token, ())]
    narrowed = ((preset.get("token_options") or {}).get(token)) or []
    narrowed = [o for o in narrowed if o in options]
    return narrowed or options


def allowed_variants(preset: dict, section: str) -> list[str]:
    """Layouts the picker may use for a section. A preset with no `allowed_variants[section]`
    (every preset before SITE-1C-2) allows all of them."""
    every = list(SECTION_VARIANTS[section])
    narrowed = [v for v in ((preset.get("allowed_variants") or {}).get(section) or []) if v in every]
    return narrowed or every


# ---------------------------------------------------------------- brand personality (spec SITE-1C §6)
# The client's answer to "How should your website feel?". Labels are what they see (web form and
# WhatsApp list); D1C-2 (final wording) is open, so they live here in ONE place.
# Each personality steers the picker: which font groups, token options, layouts and theme it
# leans towards. Preferences only weight the choice — nothing outside a preset's allowed pool is
# ever picked, and a skipped answer leaves every axis unweighted.

PERSONALITY_KEY = "personality"
PERSONALITY_PROMPT = "How should your website feel?"

PERSONALITIES: dict[str, dict] = {
    "elegant": {
        "label": "Elegant and refined",
        "font_groups": ("elegant", "editorial"), "themes": ("atelier",),
        "tokens": {"radius": ("sharp", "soft"), "heading_case": ("spaced_upper", "normal"), "image_style": ("arch", "framed"),
                   "divider": ("ornament", "line"), "density": ("airy",), "button": ("outline", "underline"), "cards": ("bordered", "flat"), "background": ("ivory", "match")},
        "variants": {"hero": ("fullbleed", "centered"), "about": ("quote", "left"), "reviews": ("spotlight",), "items": ("grid", "featured")},
    },
    "bold": {
        "label": "Bold and confident",
        "font_groups": ("bold",), "themes": ("market",),
        "tokens": {"radius": ("sharp", "pill"), "heading_case": ("upper",), "image_style": ("square",), "divider": ("none", "line"),
                   "density": ("compact", "regular"), "button": ("solid",), "cards": ("lifted", "bordered"), "bands": ("wash",)},
        "variants": {"hero": ("fullbleed", "collage"), "items": ("featured", "grid"), "reviews": ("cards",), "about": ("left", "right")},
    },
    "playful": {
        "label": "Playful and fun",
        "font_groups": ("friendly", "bold"), "themes": ("market", "studio"),
        "tokens": {"radius": ("pill", "soft"), "image_style": ("rounded", "arch"), "divider": ("dot", "none"), "button": ("solid",),
                   "cards": ("lifted",), "bands": ("wash",), "density": ("regular",)},
        "variants": {"hero": ("collage", "centered"), "items": ("grid", "rows"), "reviews": ("cards", "list"), "about": ("right", "left")},
    },
    "minimal": {
        "label": "Clean and minimal",
        "font_groups": ("minimal",), "themes": ("studio",),
        "tokens": {"radius": ("sharp", "soft"), "heading_case": ("normal",), "image_style": ("square",), "divider": ("none", "line"),
                   "density": ("airy",), "button": ("underline", "outline"), "cards": ("flat",), "background": ("white", "grey"), "bands": ("plain",)},
        "variants": {"hero": ("centered", "fullbleed"), "items": ("rows", "grid"), "reviews": ("list",), "about": ("quote", "left")},
    },
    "warm": {
        "label": "Warm and friendly",
        "font_groups": ("friendly", "editorial"), "themes": ("studio", "atelier"),
        "tokens": {"radius": ("soft",), "image_style": ("rounded",), "divider": ("dot", "line"), "density": ("regular", "airy"),
                   "button": ("solid",), "cards": ("bordered", "lifted"), "background": ("ivory",)},
        "variants": {"hero": ("collage", "fullbleed"), "about": ("left", "right"), "reviews": ("cards", "spotlight"), "items": ("grid", "rows")},
    },
}


def personality_from_answer(answer) -> Optional[str]:
    """Maps a brief answer (the label the client picked, or the key) to a personality key; None if skipped/unknown."""
    if not isinstance(answer, str):
        return None
    v = answer.strip().lower()
    if not v:
        return None
    for key, meta in PERSONALITIES.items():
        if v == key or v == meta["label"].lower():
            return key
    return None


def personality_question() -> dict:
    """The brief question every preset gets (unless it already defines its own `personality` question)."""
    return {
        "key": PERSONALITY_KEY, "prompt": PERSONALITY_PROMPT, "type": "choice",
        "choices": [m["label"] for m in PERSONALITIES.values()],
        "required": False, "skip_ok": True,
    }


def with_personality_question(questions) -> list[dict]:
    """Adds the personality question to a preset's brief questions without changing the stored preset.
    It goes before the first photos/items step (so photo uploads stay last), otherwise at the end."""
    qs = list(questions or [])
    if any(isinstance(q, dict) and q.get("key") == PERSONALITY_KEY for q in qs):
        return qs
    at = next((i for i, q in enumerate(qs) if isinstance(q, dict) and q.get("type") in ("photos", "items")), len(qs))
    return qs[:at] + [personality_question()] + qs[at:]


# ---------------------------------------------------------------- validation

def validate_preset_design_fields(allowed_fonts, token_options, default_palettes=None, allowed_variants=None) -> None:
    """Called by the preset create/update routes. Raises ValueError with a plain message."""
    for f in allowed_fonts or []:
        if f not in FONT_PAIRINGS:
            raise ValueError(f"Unknown font pairing: {f}")
    for token, options in (token_options or {}).items():
        if token not in TOKENS:
            raise ValueError(f"Unknown design token: {token}")
        if not isinstance(options, (list, tuple)):
            raise ValueError(f"Options for {token} must be a list")
        for o in options:
            if o not in TOKENS[token]:
                raise ValueError(f"Unknown option {o!r} for {token}")
    if allowed_variants is not None and not isinstance(allowed_variants, dict):
        raise ValueError("allowed_variants must be an object")
    for section, layouts in (allowed_variants or {}).items():
        if section not in SECTION_VARIANTS:
            raise ValueError(f"Unknown section: {section}")
        if not isinstance(layouts, (list, tuple)):
            raise ValueError(f"Layouts for {section} must be a list")
        for v in layouts:
            if v not in SECTION_VARIANTS[section]:
                raise ValueError(f"Unknown layout {v!r} for {section}")
    for p in default_palettes or []:
        # A template may list named palettes and/or its own custom colours (6-digit hex).
        if p not in PALETTES and not is_hex(p):
            raise ValueError(f"Unknown palette: {p}")


def validate_fonts_and_tokens(preset: dict, recipe: dict) -> None:
    """Recipe-level checks for `fonts` and `tokens` (called from site_renderer.validate_recipe).
    A recipe without either is always valid — that is every pre-SITE-1C-1 site."""
    theme = recipe.get("theme")
    fonts = recipe.get("fonts")
    if fonts:
        if fonts not in FONT_PAIRINGS:
            raise ValueError(f"unknown font pairing: {fonts!r}")
        allowed = preset.get("allowed_fonts") or []
        if allowed and fonts not in allowed:
            raise ValueError(f"font pairing {fonts!r} is not allowed for preset {preset.get('key')!r}")
    tokens = recipe.get("tokens") or {}
    for token, value in tokens.items():
        if value is None:
            continue
        if token not in TOKENS:
            raise ValueError(f"unknown design token: {token!r}")
        if value not in TOKENS[token]:
            raise ValueError(f"unknown option {value!r} for {token!r}")
        if theme in THEME_META and value in THEME_META[theme]["token_exclusions"].get(token, ()):
            raise ValueError(f"theme {theme!r} does not support {token}={value!r}")
        narrowed = ((preset.get("token_options") or {}).get(token)) or []
        if narrowed and value not in narrowed:
            raise ValueError(f"{token}={value!r} is not allowed for preset {preset.get('key')!r}")


_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX.match(v))
