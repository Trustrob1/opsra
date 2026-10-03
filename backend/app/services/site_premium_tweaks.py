"""
app/services/site_premium_tweaks.py
------------------------------------
SITE-PREMIUM P4-2 - customer look tweaks for a Premium site: the brand (accent) colour and the font style.
No AI, no new HTML. A tweak saves a NEW design version (kind 'patch', parent = the version it started from)
that has the same skeleton and CSS but different `tokens` and `art_direction` fonts. The renderer already
writes those values after the skeleton CSS, so nothing in the design itself is rewritten.

Rules (decisions of 3 Oct 2026):
  * Colour = the accent colour only. Page background and text colour stay as designed, because the hero
    scrim and surfaces were drawn against them.
  * Button text colour (--accent-ink) is chosen here, never by the customer: whichever of the design's own
    background, its text colour, or a tinted near-white / near-black reads best (at least 4.5:1).
  * The accent must keep at least 3:1 against the page background, must not be in the banned brown-gold range,
    and the same static checks used at generation (hue, contrast, font pairs) are re-run.
  * Fonts: only other headline fonts of the SAME style group as the current one (and that the niche list
    allows), so line lengths stay close to what the design was drawn for; no screenshot check exists yet
    (P3 on hold). Anton, Big Shoulders Display, Italiana and Cormorant are never offered as a swap target
    (spec 6A: short or large headlines only). Body fonts: the allowed pairs for that group.
  * Everything is scoped by org_id (S14). A failed tweak saves nothing.
"""
from __future__ import annotations

import colorsys
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_premium_checks as checks
from app.services import site_premium_fonts as fonts
from app.services import site_premium_renderer as renderer
from app.services import site_premium_sections as sections
from app.services import site_premium_service as premium
from app.services.site_ops_service import NotFound, SiteOpsError, ValidationFailed

logger = logging.getLogger(__name__)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NEUTRAL_INKS = ("#12141A", "#FAFAF7")          # tinted near-black and near-white, never pure
SWAP_EXCLUDED = frozenset({"Anton", "Big Shoulders Display", "Italiana", "Cormorant"})
_ROOT_VARS = ("--accent", "--accent-ink", "--bg", "--ink")

# key, name, hex, accent family (the art-direction families)
ACCENT_SWATCHES = (
    ("cobalt", "Cobalt blue", "#1F4FD8", "blue"),
    ("sky", "Sky blue", "#2A8FD6", "blue"),
    ("teal", "Teal", "#0E8F86", "green_teal"),
    ("emerald", "Emerald", "#12804F", "green_teal"),
    ("crimson", "Crimson", "#C0243B", "red_wine"),
    ("coral", "Coral", "#E8553F", "red_wine"),
    ("wine", "Wine", "#8A1F4A", "red_wine"),
    ("rose", "Rose", "#E0457B", "violet_pink"),
    ("magenta", "Magenta", "#C2268F", "violet_pink"),
    ("violet", "Violet", "#6D3FD0", "violet_pink"),
    ("slate", "Slate", "#3D4A5C", "metal"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def family_for(hex_value: str) -> str:
    """Best-effort accent family for a custom colour (art-direction vocabulary)."""
    r, g, b = (c / 255 for c in checks.hex_to_rgb(hex_value))
    hue, _light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360.0
    if sat < 0.15:
        return "metal"
    if 50 <= hue < 90:
        return "yellow_green"
    if 90 <= hue < 190:
        return "green_teal"
    if 190 <= hue < 250:
        return "blue"
    if 250 <= hue < 335:
        return "violet_pink"
    return "red_wine"


def current_tokens(design: dict) -> dict:
    """The colour variables the page is rendered with: the stored tokens over what the CSS declares."""
    merged = dict(renderer.extract_root_tokens(design.get("skeleton_css") or ""))
    for k, v in (design.get("tokens") or {}).items():
        if isinstance(v, str) and HEX_RE.match(v):
            merged[k] = v
    return merged


def pick_accent_ink(accent: str, bg: str, ink: str) -> Optional[str]:
    """The best button-text colour for this accent (at least 4.5:1), or None when nothing reads on it."""
    best, best_ratio = None, 0.0
    for cand in (bg, ink) + NEUTRAL_INKS:
        r = checks.contrast_ratio(cand, accent)
        if r > best_ratio:
            best, best_ratio = cand, r
    return best if best_ratio >= 4.5 else None


def accent_problem(accent: str, bg: str, ink: str) -> Optional[str]:
    """A plain-English reason this accent cannot be used on this design, or None when it can."""
    if not isinstance(accent, str) or not HEX_RE.match(accent):
        return "Choose a colour in the form #RRGGBB, for example #1F4FD8."
    if checks.is_brown_gold(accent):
        return "Tan, bronze, brass and khaki colours are not used on Premium sites. Please pick another colour."
    if checks.contrast_ratio(accent, bg) < 3.0:
        return "This colour is too close to your page background, so links and highlights would be hard to see."
    if pick_accent_ink(accent, bg, ink) is None:
        return "Button text would be hard to read on this colour. Try a slightly lighter or darker shade."
    return None


def font_options(design: dict, niche: Optional[str]) -> dict:
    """Headline and body fonts the customer may switch to for this design (same style group only)."""
    art = design.get("art_direction") or {}
    head, body = art.get("headline_font") or "", art.get("body_font") or ""
    group = (fonts.HEADLINE_FONTS.get(head) or {}).get("group")
    if not group:
        return {"group": None, "headlines": [], "bodies": [], "current": {"headline": head, "body": body}}
    niche_list = fonts.NICHE_HEADLINES.get((niche or "").lower())
    heads = []
    for name, meta in fonts.HEADLINE_FONTS.items():
        if meta["group"] != group:
            continue
        if name == head or (name not in SWAP_EXCLUDED and (not niche_list or name in niche_list)):
            heads.append(name)
    bodies = list(fonts.PROPOSED_PAIRS.get(group, ()))
    if body and body not in bodies:
        bodies.insert(0, body)
    return {"group": group, "headlines": heads, "bodies": bodies, "current": {"headline": head, "body": body}}


def look_options(design: dict, niche: Optional[str]) -> dict:
    """Everything the editor card needs: the current look, which swatches work on this design, the fonts."""
    tokens = current_tokens(design)
    bg, ink, accent = tokens.get("--bg"), tokens.get("--ink"), tokens.get("--accent")
    swatches = []
    for key, name, hex_value, _fam in ACCENT_SWATCHES:
        reason = accent_problem(hex_value, bg, ink) if (bg and ink) else "This design cannot be recoloured."
        swatches.append({"key": key, "name": name, "hex": hex_value, "ok": reason is None, "reason": reason})
    fo = font_options(design, niche)
    names = list(dict.fromkeys(fo["headlines"] + fo["bodies"]))
    params = []
    for n in names:
        meta = fonts.HEADLINE_FONTS.get(n) or fonts.BODY_FONTS.get(n)
        if meta:
            params.append(fonts._family_param(n, meta["wght"]))
    sample = ("https://fonts.googleapis.com/css2?" + "&".join(params) + "&display=swap") if params else None
    return {"current": {"accent": accent, "headline_font": fo["current"]["headline"], "body_font": fo["current"]["body"]},
            "swatches": swatches, "fonts": fo, "sample_css_url": sample,
            "sections": sections.section_options(design)}


def plan_tweak(design: dict, content: dict, assets_by_id: dict, niche: Optional[str], accent: Optional[str] = None,
               headline_font: Optional[str] = None, body_font: Optional[str] = None,
               section_colours: Optional[dict] = None, section_layout: Optional[dict] = None) -> dict:
    """Validates a requested look and returns the new parts (tokens, art_direction, notes, page html) without
    saving anything. Raises ValidationFailed with a plain reason."""
    tokens = current_tokens(design)
    missing = [k for k in _ROOT_VARS if k not in tokens]
    if missing:
        raise ValidationFailed("This design cannot be recoloured, because it does not declare " + ", ".join(missing) + ".")
    art = dict(design.get("art_direction") or {})
    cur_head, cur_body = art.get("headline_font") or "", art.get("body_font") or ""
    new_tokens = dict(tokens)
    new_art = dict(art)
    changes: dict = {}

    if accent is not None:
        accent = accent.strip().upper()
        reason = accent_problem(accent, tokens["--bg"], tokens["--ink"])
        if reason:
            raise ValidationFailed(reason)
        if accent != tokens["--accent"].upper():
            new_tokens["--accent"] = accent
            new_tokens["--accent-ink"] = pick_accent_ink(accent, tokens["--bg"], tokens["--ink"])
            new_art["accent_hex"] = accent
            new_art["accent_family"] = family_for(accent)
            changes["accent"] = accent

    opts = font_options(design, niche)
    if headline_font is not None and headline_font != cur_head:
        if headline_font not in opts["headlines"]:
            raise ValidationFailed(f"{headline_font} is not available for this design.")
        new_art["headline_font"] = headline_font
        changes["headline_font"] = headline_font
    if body_font is not None and body_font != cur_body:
        if body_font not in opts["bodies"]:
            raise ValidationFailed(f"{body_font} is not available with this heading font.")
        new_art["body_font"] = body_font
        changes["body_font"] = body_font

    if section_colours:
        # P4-3a: per-section colours from the design's own fixed set. {section: key}; 'original' clears one.
        # Worked out against the design AS IT WILL BE (new accent included), so 'brand' means the new brand colour.
        try:
            merged = sections.normalise_choice({**design, "tokens": new_tokens, "art_direction": new_art}, section_colours)
        except ValueError as exc:
            raise ValidationFailed(str(exc))
        before = dict(art.get("section_colours") or {})
        if merged != before:
            if merged:
                new_art["section_colours"] = merged
            else:
                new_art.pop("section_colours", None)
            changes["sections"] = {s: merged.get(s, sections.ORIGINAL) for s in set(merged) | set(before)
                                   if merged.get(s) != before.get(s)}

    if section_layout:
        # P4-3b: show / hide a section and make its headline smaller or larger (deterministic, no AI)
        trial = {**design, "tokens": new_tokens, "art_direction": new_art}
        try:
            hidden, sized = sections.normalise_layout(trial, section_layout)
        except ValueError as exc:
            raise ValidationFailed(str(exc))
        before_hidden, before_sizes = sections.hidden_names(design), sections.sizes(design)
        layout_changes: dict = {}
        for name in set(hidden) | set(before_hidden) | set(sized) | set(before_sizes):
            c: dict = {}
            if (name in hidden) != (name in before_hidden):
                c["show"] = name not in hidden
            if sized.get(name, "normal") != before_sizes.get(name, "normal"):
                c["size"] = sized.get(name, "normal")
            if c:
                layout_changes[name] = c
        if layout_changes:
            for key, value in (("section_hidden", hidden), ("section_size", sized)):
                if value:
                    new_art[key] = value
                else:
                    new_art.pop(key, None)
            changes["layout"] = layout_changes

    if not changes:
        raise ValidationFailed("That is already your current look. Pick something different.")

    try:
        fonts.validate_fonts(new_art.get("headline_font", ""), new_art.get("body_font", ""))
    except fonts.FontError as exc:
        raise ValidationFailed(str(exc))
    override = ":root{" + ";".join(f"{k}:{v}" for k, v in new_tokens.items() if k in _ROOT_VARS) + "}"
    static = checks.run_static_checks(design.get("skeleton_html") or "", (design.get("skeleton_css") or "") + override,
                                      new_art.get("headline_font"), new_art.get("body_font"), strict=False)
    if static["errors"]:
        raise ValidationFailed(" ".join(static["errors"]))

    new_design = {**design, "tokens": new_tokens, "art_direction": new_art}
    try:   # prove the page still renders with the real content
        html = renderer.render_premium_page(content=content or {}, design=new_design, assets_by_id=assets_by_id or {}, export=False)
    except Exception as exc:  # S14
        raise ValidationFailed(f"The page could not be drawn with this look ({exc}).")
    return {"tokens": new_tokens, "art_direction": new_art, "changes": changes, "html": html,
            "warnings": static["warnings"]}


def current_design(db: Any, org_id: str, site: dict) -> dict:
    row = None
    if (site.get("tier") or "standard") == "premium" and site.get("current_design_id"):
        row = _one((db.table("site_designs").select("*").eq("id", site["current_design_id"]).eq("org_id", org_id)
                    .eq("site_id", site["id"]).eq("status", "ready").limit(1).execute()).data)
    if not row:
        raise NotFound("This site does not have a Premium design to change.")
    return row


def apply_tweak(db: Any, org_id: str, site: dict, actor: str, design: dict, plan: dict) -> dict:
    """Saves an already validated plan (from plan_tweak) as a new design version and makes it current."""
    existing = (db.table("site_designs").select("id, version").eq("site_id", site["id"]).eq("org_id", org_id)
                .execute()).data or []
    version = max((int(r["version"]) for r in existing), default=0) + 1
    checks_blob = dict(design.get("checks") or {})
    checks_blob["tweak"] = {"changes": plan["changes"], "warnings": plan["warnings"]}
    row = {
        "org_id": org_id, "site_id": site["id"], "version": version, "kind": "patch", "parent_id": design["id"],
        "skeleton_html": design["skeleton_html"], "skeleton_css": design.get("skeleton_css") or "",
        "slot_manifest": design.get("slot_manifest") or {}, "art_direction": plan["art_direction"],
        "tokens": plan["tokens"], "status": "ready", "staged": False, "checks": checks_blob,
        "created_by": actor, "created_at": _now_iso(),
    }
    inserted = _one((db.table("site_designs").insert(row).execute()).data) or {}
    new_id = inserted.get("id")
    if not new_id:
        raise SiteOpsError("Your new look could not be saved. Nothing was changed.")
    db.table("sites").update({"current_design_id": new_id, "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    premium._prune(db, org_id, site["id"], keep_id=new_id)
    return {"id": new_id, "version": version, "changes": plan["changes"]}


def restore_previous(db: Any, org_id: str, site: dict) -> dict:
    """Go back one step: only for a tweak (kind 'patch') whose earlier version is still saved."""
    design = current_design(db, org_id, site)
    parent_id = design.get("parent_id")
    if design.get("kind") != "patch" or not parent_id:
        raise NotFound("There is no earlier look to go back to.")
    return premium.use_design(db, org_id, site, parent_id)
