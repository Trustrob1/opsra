"""
app/services/site_premium_fonts.py
-----------------------------------
SITE-PREMIUM P1 - the Premium font registry (spec section 6A). Separate from the Standard
registry (site_design_registry.FONT_PAIRINGS). Pure data + validation, no I/O.

Confirmed by Trust (2 Oct 2026): 20 headline fonts, 6 body fonts, the ban list, at most 2 families
per site. PROPOSED and NOT enforced yet (DP-9): the niche table, the pairing rules and the
rotation cautions - they are stored here as data for P2 but nothing in P1 rejects on them.

IMPORTANT (spec 6A): the build sandbox could not reach Google Fonts, so every `wght` list below is
from memory of each family's published range. Before launch, open each font_url once in a browser;
a family that returns an error is removed from the registry.
"""
from __future__ import annotations

from typing import Optional

BANNED_FONTS = frozenset({
    "playfair display", "fraunces", "instrument serif", "inter", "roboto", "arial",
    "open sans", "poppins", "space grotesk",
})

_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "'Helvetica Neue', Arial, sans-serif"
_DISPLAY_SANS = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
_CONDENSED = "Impact, 'Arial Narrow', sans-serif"
_SLAB = "Rockwell, Georgia, serif"

# name -> (group, google "wght" list, fallback stack)
HEADLINE_FONTS: dict[str, dict] = {
    "Bricolage Grotesque": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Familjen Grotesk": {"group": "sans", "wght": "400;600;700", "fallback": _DISPLAY_SANS},
    "Outfit": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Sora": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Geologica": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Gabarito": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Red Hat Display": {"group": "sans", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Big Shoulders Display": {"group": "condensed", "wght": "500;700;900", "fallback": _CONDENSED},
    "Anton": {"group": "condensed", "wght": "400", "fallback": _CONDENSED},
    "Fredoka": {"group": "soft", "wght": "400;500;700", "fallback": _DISPLAY_SANS},
    "Lexend": {"group": "soft", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Baloo 2": {"group": "soft", "wght": "400;600;800", "fallback": _DISPLAY_SANS},
    "Bodoni Moda": {"group": "serif", "wght": "400;600;800", "fallback": _SERIF},
    "Young Serif": {"group": "serif", "wght": "400", "fallback": _SERIF},
    "Literata": {"group": "serif", "wght": "400;600;800", "fallback": _SERIF},
    "Petrona": {"group": "serif", "wght": "400;600;800", "fallback": _SERIF},
    "Cormorant": {"group": "serif", "wght": "400;600;700", "fallback": _SERIF},
    "Newsreader": {"group": "serif", "wght": "400;600;800", "fallback": _SERIF},
    "Bitter": {"group": "slab", "wght": "400;600;800", "fallback": _SLAB},
    "Italiana": {"group": "classical", "wght": "400", "fallback": _SERIF},
}

BODY_FONTS: dict[str, dict] = {
    "Hanken Grotesk": {"wght": "400;500;700", "fallback": _SANS},
    "Figtree": {"wght": "400;500;700", "fallback": _SANS},
    "Nunito Sans": {"wght": "400;600;700", "fallback": _SANS},
    "Karla": {"wght": "400;500;700", "fallback": _SANS},
    "DM Sans": {"wght": "400;500;700", "fallback": _SANS},
    "Manrope": {"wght": "400;500;700", "fallback": _SANS},
}

# ---- PROPOSED (DP-9) - data only in P1, not enforced -------------------------------------------

NICHE_HEADLINES: dict[str, tuple[str, ...]] = {
    "boutique": ("Bodoni Moda", "Young Serif", "Cormorant", "Bricolage Grotesque", "Familjen Grotesk", "Red Hat Display", "Outfit"),
    "restaurant": ("Young Serif", "Petrona", "Bitter", "Bricolage Grotesque", "Gabarito", "Baloo 2", "Fredoka"),
    "salon": ("Bodoni Moda", "Cormorant", "Italiana", "Newsreader", "Outfit", "Sora"),
    "church": ("Literata", "Newsreader", "Petrona", "Bitter", "Lexend", "Geologica"),
    "school": ("Lexend", "Baloo 2", "Fredoka", "Literata", "Bitter", "Gabarito"),
    "real_estate": ("Newsreader", "Cormorant", "Literata", "Bitter", "Geologica", "Sora", "Red Hat Display"),
    "logistics": ("Big Shoulders Display", "Anton", "Bitter", "Sora", "Geologica", "Familjen Grotesk"),
    "events": ("Anton", "Big Shoulders Display", "Bodoni Moda", "Cormorant", "Bricolage Grotesque", "Gabarito"),
    "photographer": ("Cormorant", "Newsreader", "Italiana", "Familjen Grotesk", "Sora", "Outfit"),
    "consultant": ("Newsreader", "Literata", "Geologica", "Sora", "Familjen Grotesk", "Red Hat Display"),
}

# headline group -> body fonts that pair well (geometric sans also avoids DM Sans)
PROPOSED_PAIRS: dict[str, tuple[str, ...]] = {
    "condensed": ("Hanken Grotesk", "Figtree"),
    "soft": ("Nunito Sans", "Figtree"),
    "sans": ("Hanken Grotesk", "Manrope", "Karla"),
    "serif": ("Hanken Grotesk", "DM Sans", "Karla"),
    "slab": ("Hanken Grotesk", "DM Sans", "Karla"),
    "classical": ("Hanken Grotesk", "DM Sans", "Karla"),
}


class FontError(ValueError):
    pass


def is_banned(name: str) -> bool:
    return (name or "").strip().lower() in BANNED_FONTS


def validate_fonts(headline: str, body: str) -> None:
    """Registry membership only (P1). Raises FontError with a plain reason."""
    for label, name in (("headline", headline), ("body", body)):
        if is_banned(name):
            raise FontError(f"The {label} font '{name}' is not allowed on Premium sites.")
    if headline not in HEADLINE_FONTS:
        raise FontError(f"'{headline}' is not in the Premium headline font list.")
    if body not in BODY_FONTS:
        raise FontError(f"'{body}' is not in the Premium body font list.")


def _family_param(name: str, wght: str) -> str:
    return "family=" + name.replace(" ", "+") + ":wght@" + wght


def font_url(headline: str, body: str) -> str:
    """The one Google Fonts stylesheet URL the renderer writes. Raises FontError if not in the registry."""
    validate_fonts(headline, body)
    h, b = HEADLINE_FONTS[headline], BODY_FONTS[body]
    return ("https://fonts.googleapis.com/css2?" + _family_param(headline, h["wght"]) + "&"
            + _family_param(body, b["wght"]) + "&display=swap")


def font_stacks(headline: str, body: str) -> tuple[str, str]:
    """CSS font-family values for --font-head and --font-body (name first, then the fallback stack)."""
    validate_fonts(headline, body)
    return (f"'{headline}', {HEADLINE_FONTS[headline]['fallback']}", f"'{body}', {BODY_FONTS[body]['fallback']}")


def default_pair(niche: Optional[str] = None) -> tuple[str, str]:
    """A safe pair for staff imports that don't name one: the niche's first headline, else Outfit."""
    head = (NICHE_HEADLINES.get((niche or "").lower()) or ("Outfit",))[0]
    group = HEADLINE_FONTS[head]["group"]
    return head, PROPOSED_PAIRS[group][0]
