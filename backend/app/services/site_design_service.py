"""
app/services/site_design_service.py
------------------------------------
SITE-1C — the recipe picker.

SITE-1C-1: chooses theme, palette, fonts and tokens from what a preset allows, deterministically
from a seed (the site id), so different sites look different and the same site is stable.

SITE-1C-2 adds:
  * the client's brand PERSONALITY (registry.PERSONALITIES) weights every axis;
  * section LAYOUTS (recipe.variants), limited by the preset's `allowed_variants` and by what the
    site actually has (a collage needs photos and items);
  * ANTI-SAMENESS: candidates are scored against looks used recently (the same builder's last 3
    sites, and the same niche across the org in the last 30 days) and an exact repeat is avoided;
  * a SHORTLIST of ~6 valid candidates; the AI copy call may choose one (by number), and the
    deterministic top pick is always the fallback;
  * a fingerprint, logged as a `design_pick` site_event.

Never raises out of pick_recipe: any problem falls back to the pre-1C behaviour.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services import site_design_registry as reg
from app.services import site_renderer

logger = logging.getLogger(__name__)

CANDIDATES = 48          # generated per site
SHORTLIST_SIZE = 6       # offered to the AI / returned
PREFERRED_WEIGHT = 4     # a personality-preferred option is this many times likelier than another
BUILDER_RECENT = 3       # same builder: avoid their last N looks
NICHE_DAYS = 30          # same niche in the org: avoid looks used in the last N days
NICHE_RECENT_MAX = 40

# The section layouts the picker sets. The SITE-1C-3 sections come last on purpose: every choice is
# hashed per axis, so adding names here never changes what a template without them picks.
VARIANT_SECTIONS = ("hero", "items", "about", "reviews", "categories",
                    "faq", "menu", "visit", "process", "team", "gallery")


def _h(seed: str, axis: str) -> int:
    return int(hashlib.sha256(f"{seed}|{axis}".encode()).hexdigest()[:12], 16)


def _choose(seed: str, axis: str, options: list):
    return options[_h(seed, axis) % len(options)]


def _wchoose(seed: str, axis: str, options: list, preferred=()):
    """Deterministic weighted choice: preferred options count PREFERRED_WEIGHT times."""
    if not options:
        raise ValueError(f"no options for {axis}")
    pool: list = []
    for o in options:
        pool.extend([o] * (PREFERRED_WEIGHT if o in preferred else 1))
    return pool[_h(seed, axis) % len(pool)]


def _palette_pool(preset: dict) -> list[str]:
    chosen = [p for p in (preset.get("default_palettes") or []) if p in reg.PALETTES or reg.is_hex(p)]
    return chosen or reg.palettes_for_niche(preset.get("key")) or ["berry"]


# ---------------------------------------------------------------- fingerprints

def fingerprint(recipe: dict) -> str:
    """A short hash of what a visitor would see as 'the look': theme, colour, fonts, tokens, layouts, order."""
    tokens = recipe.get("tokens") or {}
    variants = recipe.get("variants") or {}
    parts = [recipe.get("theme") or "", recipe.get("custom_colour") or recipe.get("palette") or "", recipe.get("fonts") or ""]
    parts += [f"{k}={tokens[k]}" for k in sorted(tokens) if tokens[k]]
    parts += [f"{k}={variants[k]}" for k in sorted(variants) if variants[k]]
    parts.append(",".join(recipe.get("order") or []))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _axes(recipe: dict) -> dict:
    """Flat axis -> value map used to measure how different two looks are."""
    ax = {"theme": recipe.get("theme"), "colour": recipe.get("custom_colour") or recipe.get("palette"), "fonts": recipe.get("fonts")}
    for k, v in (recipe.get("tokens") or {}).items():
        ax[f"t:{k}"] = v
    for k, v in (recipe.get("variants") or {}).items():
        ax[f"v:{k}"] = v
    return ax


def distance(a: dict, b: dict) -> int:
    """How many axes differ between two recipes (theme, colour and fonts count double: they change the feel most)."""
    x, y = _axes(a), _axes(b)
    d = 0
    for k in set(x) | set(y):
        if x.get(k) != y.get(k):
            d += 2 if k in ("theme", "colour", "fonts") else 1
    return d


# ---------------------------------------------------------------- site context (what a layout needs)

def _layout_ok(section: str, variant: str, ctx: Optional[dict]) -> bool:
    """Photo/content awareness: a layout is skipped when the site can't fill it. ctx=None (template
    previews, Shuffle) means anything goes."""
    if not ctx:
        return True
    photos, items, reviews = int(ctx.get("photos") or 0), int(ctx.get("items") or 0), int(ctx.get("reviews") or 0)
    if section == "hero" and variant == "collage":
        return items >= 3 and photos >= 3
    if section == "items" and variant == "featured":
        return items >= 3 and photos >= 1
    if section == "about" and variant in ("left", "right"):
        return photos >= 1
    if section == "reviews" and variant == "spotlight":
        return reviews >= 1
    return True


def _variant_pool(preset: dict, section: str, ctx: Optional[dict]) -> list[str]:
    listed = (preset.get("allowed_variants") or {}).get(section) or []
    pool = [v for v in reg.allowed_variants(preset, section)
            if _layout_ok(section, v, ctx) and ((section, v) not in OPT_IN_VARIANTS or v in listed)]
    return pool or [reg.allowed_variants(preset, section)[0]]


# ---------------------------------------------------------------- candidate generation

OPT_IN_TOKENS = {"finish": "refined", "hero_height": "tall", "mobile_cols": "one", "image_fit": "top"}
# Layouts the picker never chooses at random. Staff/builders can still pick them for any site, and a
# template makes one its default by listing it under "Allowed layouts" (SITE-1C-3f).
OPT_IN_VARIANTS = {("items", "scroll"), ("gallery", "tiles")}


def _candidate(preset: dict, seed: str, colour_answer, personality: Optional[str], ctx: Optional[dict]) -> dict:
    p = reg.PERSONALITIES.get(personality) if personality else None
    themes = [t for t in (preset.get("allowed_themes") or []) if t in site_renderer.THEMES] or ["atelier"]
    theme = _wchoose(seed, "theme", themes, p["themes"] if p else ())

    palettes = _palette_pool(preset)
    palette, custom = None, None
    if isinstance(colour_answer, str):
        v = colour_answer.strip()
        if reg.is_hex(v):
            custom = v.upper()
        else:
            palette = next((x for x in palettes if x.lower() == v.lower()), None)
    if not custom and not palette:
        tagged = tuple(k for k in palettes if p and personality in reg.PALETTE_META.get(k, {}).get("personality", ()))
        palette, custom = reg.palette_fields(_wchoose(seed, "palette", palettes, tagged))

    pairings = reg.allowed_pairings(preset, theme)
    grouped = tuple(k for k in pairings if p and reg.FONT_PAIRINGS[k]["group"] in p["font_groups"])
    fonts = _wchoose(seed, "fonts", pairings, grouped)

    tokens = {t: _wchoose(seed, f"token:{t}", reg.allowed_token_options(preset, theme, t), (p["tokens"].get(t, ()) if p else ()))
              for t in reg.TOKENS}
    # SITE-1C-3c: every new site starts on a white page, whatever its palette. Staff or the builder can
    # still change it per site in the Design card; personalities no longer steer this one token.
    if "white" in reg.allowed_token_options(preset, theme, "background"):
        tokens["background"] = "white"
    # SITE-1C-3d/3e: opt-in tokens are never picked at random. A template turns one on for all its new
    # sites by narrowing it to that one option in the Look studio; otherwise sites start standard.
    # "Starts on" = the opt-in option is listed FIRST (the template editor writes [opt_in, standard], which
    # keeps the standard option available per site; ["refined"] alone also works and locks it on).
    for tok, opt_in in OPT_IN_TOKENS.items():
        listed = (preset.get("token_options") or {}).get(tok) or []
        tokens[tok] = opt_in if listed[:1] == [opt_in] else reg.TOKENS[tok][0]

    order = list(preset.get("sections") or ["hero", "about", "items", "order"])
    variants = {sec: _wchoose(seed, f"variant:{sec}", _variant_pool(preset, sec, ctx), (p["variants"].get(sec, ()) if p else ()))
                for sec in VARIANT_SECTIONS if sec in order}

    return {"theme": theme, "palette": palette, "custom_colour": custom, "fonts": fonts, "tokens": tokens,
            "variants": variants, "order": order, "hidden": []}


def _fit(recipe: dict, personality: Optional[str]) -> float:
    """0..1: how many personality preferences the recipe honours."""
    p = reg.PERSONALITIES.get(personality) if personality else None
    if not p:
        return 0.0
    hits = total = 0
    total += 1; hits += recipe["theme"] in p["themes"]
    total += 1; hits += reg.FONT_PAIRINGS.get(recipe.get("fonts") or "", {}).get("group") in p["font_groups"]
    total += 1; hits += personality in reg.PALETTE_META.get(recipe.get("palette") or "", {}).get("personality", ())
    for k, prefs in p["tokens"].items():
        total += 1; hits += (recipe.get("tokens") or {}).get(k) in prefs
    for k, prefs in p["variants"].items():
        if k in (recipe.get("variants") or {}):
            total += 1; hits += recipe["variants"][k] in prefs
    return hits / total if total else 0.0


def _score(recipe: dict, recents: list[dict], personality: Optional[str]) -> tuple:
    """Higher is better. (not an exact repeat, distance to the nearest recent look, personality fit)."""
    fp = fingerprint(recipe)
    if recents:
        repeat = any(fingerprint(r) == fp for r in recents)
        nearest = min(distance(recipe, r) for r in recents)
    else:
        repeat, nearest = False, 99
    return (0 if repeat else 1, min(nearest, 12), round(_fit(recipe, personality), 3))


def design_shortlist(preset: dict, seed: str, colour_answer=None, personality: Optional[str] = None,
                     recents: Optional[list] = None, ctx: Optional[dict] = None, size: int = SHORTLIST_SIZE) -> list[dict]:
    """Up to `size` distinct, valid recipes, best first. The first one is the deterministic pick."""
    seed = str(seed)
    recents = [r for r in (recents or []) if isinstance(r, dict)]
    seen, scored = set(), []
    for i in range(CANDIDATES):
        try:
            cand = _candidate(preset, f"{seed}#{i}", colour_answer, personality, ctx)
            site_renderer.validate_recipe(preset, cand)
        except Exception as exc:  # a bad combination is skipped, never fatal
            logger.debug("[SITE-1C] candidate %s rejected: %s", i, exc)
            continue
        fp = fingerprint(cand)
        if fp in seen:
            continue
        seen.add(fp)
        scored.append((_score(cand, recents, personality), -_h(seed, f"tie:{fp}"), cand))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [c for _, _, c in scored[:size]]


def pick_recipe(preset: dict, seed: str, colour_answer=None, personality: Optional[str] = None,
                recents: Optional[list] = None, ctx: Optional[dict] = None, choice: Optional[int] = None) -> dict:
    """Returns a recipe dict that already passes site_renderer.validate_recipe for this preset.
    `choice` (0-based index into the shortlist, e.g. the AI's pick) is honoured when valid.
    Never raises: on any problem it falls back to the pre-1C-1 behaviour (first theme, first palette)."""
    try:
        short = design_shortlist(preset, str(seed), colour_answer, personality, recents, ctx)
        if not short:
            raise ValueError("empty shortlist")
        recipe = short[choice] if isinstance(choice, int) and 0 <= choice < len(short) else short[0]
        site_renderer.validate_recipe(preset, recipe)
        return recipe
    except Exception as exc:
        logger.warning("[SITE-1C] pick_recipe failed, using first-choice recipe: %s", exc)
        return first_choice_recipe(preset, colour_answer)


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


# ---------------------------------------------------------------- describing looks (for the AI shortlist)

def describe(recipe: dict) -> str:
    """One plain-English line for a candidate, used in the AI prompt and the staff view."""
    t = recipe.get("tokens") or {}
    v = recipe.get("variants") or {}
    bits = [f"{recipe.get('theme')} theme", f"{recipe.get('custom_colour') or recipe.get('palette')} colour",
            f"{reg.FONT_PAIRINGS.get(recipe.get('fonts') or '', {}).get('label', 'theme')} fonts"]
    for k in ("radius", "image_style", "cards", "background"):
        if t.get(k):
            bits.append(f"{k.replace('_', ' ')} {t[k]}")
    for k in ("hero", "items", "about"):
        if v.get(k):
            bits.append(f"{k} {v[k]}")
    return ", ".join(bits)


# ---------------------------------------------------------------- recents + logging (I/O)

def recent_looks(db, org_id: str, builder_id: Optional[str], preset_id: Optional[str], exclude_site_id: Optional[str] = None) -> list[dict]:
    """Recipes of recent sites to steer away from: this builder's last few, plus the same template's
    sites in the org over the last 30 days. Best effort: any failure returns []."""
    try:
        out: list[dict] = []
        if builder_id:
            rows = (db.table("sites").select("id, recipe").eq("org_id", org_id).eq("builder_id", builder_id)
                    .order("created_at", desc=True).limit(BUILDER_RECENT + 1).execute()).data or []
            out += [r["recipe"] for r in rows if r.get("id") != exclude_site_id and isinstance(r.get("recipe"), dict)][:BUILDER_RECENT]
        if preset_id:
            since = (datetime.now(timezone.utc) - timedelta(days=NICHE_DAYS)).isoformat()
            rows = (db.table("sites").select("id, recipe").eq("org_id", org_id).eq("preset_id", preset_id)
                    .gte("created_at", since).order("created_at", desc=True).limit(NICHE_RECENT_MAX + 1).execute()).data or []
            out += [r["recipe"] for r in rows if r.get("id") != exclude_site_id and isinstance(r.get("recipe"), dict)][:NICHE_RECENT_MAX]
        return [r for r in out if r.get("theme")]
    except Exception as exc:
        logger.warning("[SITE-1C] recent_looks failed: %s", exc)
        return []


def log_design_pick(db, org_id: str, site_id: Optional[str], recipe: dict, personality: Optional[str],
                    chosen_by: str, shortlist_size: int) -> None:
    """site_events `design_pick` (spec §8). Best effort (S14)."""
    try:
        db.table("site_events").insert({
            "org_id": org_id, "site_id": site_id, "order_id": None, "actor": "system", "event": "design_pick",
            "detail": {"fingerprint": fingerprint(recipe), "personality": personality, "chosen_by": chosen_by,
                       "shortlist_size": shortlist_size, "theme": recipe.get("theme"),
                       "colour": recipe.get("custom_colour") or recipe.get("palette"), "fonts": recipe.get("fonts")},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("[SITE-1C] design_pick event failed: %s", exc)


def look_stats(db, org_id: str, days: int = NICHE_DAYS) -> dict:
    """Per template: how many sites were made in the last `days` days and how many distinct looks
    (fingerprints) they used, so staff can spot a thin pool. {preset_id: {sites, distinct, repeats}}."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (db.table("sites").select("preset_id, recipe").eq("org_id", org_id).gte("created_at", since).limit(2000).execute()).data or []
    by: dict[str, list[str]] = {}
    for r in rows:
        if r.get("preset_id") and isinstance(r.get("recipe"), dict) and r["recipe"].get("theme"):
            by.setdefault(r["preset_id"], []).append(fingerprint(r["recipe"]))
    return {pid: {"sites": len(fps), "distinct": len(set(fps)), "repeats": len(fps) - len(set(fps))} for pid, fps in by.items()}


# ---------------------------------------------------------------- "suggest another design" (SITE-1C-2b)
DESIGN_SUGGESTION_CAP = 5    # free suggestion rounds per site before it goes live (builders); staff are uncapped
SUGGESTIONS_PER_ROUND = 4


def suggestions_used(db, org_id: str, site_id: str) -> int:
    """How many suggestion rounds this site has had (counted from `design_suggested` site_events, so no schema change)."""
    try:
        rows = (db.table("site_events").select("id").eq("org_id", org_id).eq("site_id", site_id)
                .eq("event", "design_suggested").limit(500).execute()).data or []
        return len(rows)
    except Exception as exc:
        logger.warning("[SITE-1C] suggestions_used failed site=%s: %s", site_id, exc)
        return 0


def suggest_for_site(db, org_id: str, site: dict, preset: dict, round_no: int, count: int = SUGGESTIONS_PER_ROUND) -> list[dict]:
    """A fresh set of valid looks for an existing site: never the current look, never a recent one, same
    personality and the same brand colour if it set its own. Keeps the site's section order and hidden
    sections. Each round uses a new seed, so pressing the button again gives different looks."""
    current = site.get("recipe") if isinstance(site.get("recipe"), dict) else {}
    content = site.get("content") if isinstance(site.get("content"), dict) else {}
    try:
        photos = len((db.table("site_assets").select("id").eq("site_id", site["id"]).execute()).data or [])
    except Exception:
        photos = 0
    ctx = {"photos": photos, "items": len(content.get("items") or []), "reviews": len(content.get("reviews") or [])}
    personality = reg.personality_from_answer((site.get("brief") or {}).get(reg.PERSONALITY_KEY))
    recents = recent_looks(db, org_id, site.get("builder_id"), site.get("preset_id"), site.get("id"))
    if current.get("theme"):
        recents = [current] + recents
    colour = current.get("custom_colour") or None
    pool = design_shortlist(preset, f"{site['id']}#suggest{round_no}", colour, personality, recents, ctx, size=count + 2)
    cur_fp = fingerprint(current) if current.get("theme") else None
    out = []
    for r in pool:
        if fingerprint(r) == cur_fp:
            continue
        r = {**r, "order": list(current.get("order") or r["order"]), "hidden": list(current.get("hidden") or [])}
        try:
            site_renderer.validate_recipe(preset, r)
        except Exception:
            continue
        out.append({"recipe": r, "summary": describe(r), "fingerprint": fingerprint(r)})
        if len(out) >= count:
            break
    return out
