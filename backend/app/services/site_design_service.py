"""
app/services/site_design_service.py
------------------------------------
SITE-1C-1 — the seeded recipe picker (spec SITE-1C §8, first slice).

Before this, `site_copy_service._build_recipe` always used the FIRST allowed theme and the
FIRST default palette, so almost every generated site started identical. `pick_recipe`
chooses a theme, palette, font pairing and design tokens from what the preset allows,
deterministically from a seed (the site id): the same site always gets the same look, and
different sites get different ones.

Not in this slice (SITE-1C-2): the brand-personality answer, org-wide "avoid recent looks"
fingerprints, and section variants (variants need photo-count awareness first).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from app.services import site_design_registry as reg
from app.services import site_renderer

logger = logging.getLogger(__name__)


def _h(seed: str, axis: str) -> int:
    return int(hashlib.sha256(f"{seed}|{axis}".encode()).hexdigest()[:12], 16)


def _choose(seed: str, axis: str, options: list):
    return options[_h(seed, axis) % len(options)]


def _palette_pool(preset: dict) -> list[str]:
    chosen = [p for p in (preset.get("default_palettes") or []) if p in reg.PALETTES or reg.is_hex(p)]
    return chosen or reg.palettes_for_niche(preset.get("key")) or ["berry"]


def pick_recipe(preset: dict, seed: str, colour_answer=None) -> dict:
    """Returns a recipe dict that already passes site_renderer.validate_recipe for this preset.
    Never raises: on any problem it falls back to the pre-1C-1 behaviour (first theme, first palette)."""
    try:
        recipe = _pick(preset, str(seed), colour_answer)
        site_renderer.validate_recipe(preset, recipe)
        return recipe
    except Exception as exc:  # a picker bug must never stop a site being built
        logger.warning("[SITE-1C] pick_recipe failed, using first-choice recipe: %s", exc)
        return first_choice_recipe(preset, colour_answer)


def _pick(preset: dict, seed: str, colour_answer) -> dict:
    themes = [t for t in (preset.get("allowed_themes") or []) if t in site_renderer.THEMES] or ["atelier"]
    theme = _choose(seed, "theme", themes)

    palettes = _palette_pool(preset)
    palette, custom = None, None
    if isinstance(colour_answer, str):
        v = colour_answer.strip()
        if reg.is_hex(v):
            custom = v.upper()
        else:
            named = next((p for p in palettes if p.lower() == v.lower()), None)
            palette = named
    if not custom and not palette:
        palette, custom = reg.palette_fields(_choose(seed, "palette", palettes))

    fonts = _choose(seed, "fonts", reg.allowed_pairings(preset, theme))
    tokens = {t: _choose(seed, f"token:{t}", reg.allowed_token_options(preset, theme, t)) for t in reg.TOKENS}

    return {
        "theme": theme, "palette": palette, "custom_colour": custom,
        "fonts": fonts, "tokens": tokens,
        "order": preset.get("sections") or ["hero", "about", "items", "order"], "hidden": [],
    }


def first_choice_recipe(preset: dict, colour_answer=None) -> dict:
    """The pre-SITE-1C-1 behaviour, kept as the safe fallback."""
    themes = preset.get("allowed_themes") or ["atelier"]
    palettes = preset.get("default_palettes") or ["berry"]
    palette, custom = reg.palette_fields(palettes[0])
    if isinstance(colour_answer, str):
        v = colour_answer.strip()
        if reg.is_hex(v):
            palette, custom = None, v.upper()
        elif v.lower() in [p.lower() for p in palettes]:
            palette = next(p for p in palettes if p.lower() == v.lower())
    return {"theme": themes[0], "palette": palette, "custom_colour": custom,
            "order": preset.get("sections") or ["hero", "about", "items", "order"], "hidden": []}
