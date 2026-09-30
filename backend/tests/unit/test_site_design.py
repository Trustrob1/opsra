"""
tests/unit/test_site_design.py
--------------------------------
SITE-1C-1 — design variety for Standard sites: the design registry (tokens, font pairings,
palettes), the renderer's token / font CSS, recipe validation, the seeded picker, and the
Pydantic models.

Pure unit tests: no network, no database. The renderer, registry and picker use only the
standard library; the models test needs pydantic.
"""
from __future__ import annotations

import hashlib
import re

import pytest

from app.services import site_design_registry as reg
from app.services import site_design_service as picker
from app.services import site_renderer as r

# ───────────────────────────── shared sample data ─────────────────────────────

CONTENT = {
    "business": {"name": "Adaeze Styles", "city": "Lekki, Lagos", "tagline": "Ankara and corporate wear", "whatsapp_e164": "+2348012345678",
                 "phone_display": "0801 234 5678", "instagram": "adaeze_styles", "delivery_note": "We deliver nationwide"},
    "hero": {"headline": "Welcome to Adaeze Styles", "subhead": "Ready-to-wear and made-to-order.", "image_asset_id": None},
    "about": {"title": "Our story", "body": ["We started in 2019.", "Every piece is cut to order."], "owner": "Adaeze",
              "pull_quote": "Clothes should feel like you.", "image_asset_id": None},
    "items": [
        {"name": "Ankara Wrap Dress", "desc": "Cotton wax print", "price_ngn": 35000, "price_style": "exact", "tag": "New", "image_asset_id": None},
        {"name": "Office Blazer", "desc": "Tailored fit", "price_ngn": 48000, "price_style": "from", "tag": None, "image_asset_id": None},
        {"name": "Occasion Gown", "desc": "Made to order", "price_ngn": 0, "price_style": "on_request", "tag": None, "image_asset_id": None},
        {"name": "Two-piece Set", "desc": "Matching set", "price_ngn": 42000, "price_style": "exact", "tag": None, "image_asset_id": None},
        {"name": "Kaftan", "desc": "Free size", "price_ngn": 25000, "price_style": "exact", "tag": None, "image_asset_id": None},
    ],
    "categories": [{"name": "Dresses", "teaser": "Day to night", "image_asset_id": None},
                   {"name": "Corporate", "teaser": "Boardroom ready", "image_asset_id": None}],
    "reviews": [{"text": "Perfect fit.", "who": "Ngozi"}, {"text": "Fast delivery.", "who": "Tolu"}, {"text": "Lovely fabric.", "who": "Amaka"}],
    "hours": [{"days": "Mon-Sat", "time": "9am-6pm"}],
    "location": {"address": "12 Admiralty Way", "landmark": "Near the roundabout"},
    "order_section": {"title": "How to order", "steps": ["Message us", "Confirm", "Receive"]},
    "seo": {"title": "Adaeze Styles", "description": "Fashion in Lekki"},
}
SECTIONS = ["hero", "categories", "items", "about", "reviews", "order"]
PRESET = {"key": "boutique", "sections": SECTIONS, "allowed_themes": ["atelier", "market", "studio"], "labels": {}, "wa_messages": {}}
VARIANTS = [
    {}, {"hero": "collage", "items": "rows", "about": "quote", "reviews": "spotlight", "categories": "chips"},
    {"hero": "centered", "items": "featured", "about": "right", "reviews": "list", "categories": "tiles"},
]


def _recipe(**over):
    base = {"theme": "atelier", "palette": "berry", "custom_colour": None, "order": SECTIONS, "hidden": [], "variants": {}}
    base.update(over)
    return base


def _render(recipe, preset=None):
    return r.render_page(CONTENT, recipe, preset or PRESET, {})


# ───────────────────────────── backward compatibility ─────────────────────────────
# SHA-256 of every page the ORIGINAL renderer (before SITE-1C-1) produced for the sample content:
# 3 themes x 3 palettes x 3 variant sets, plus custom-colour pages. A recipe without `fonts` /
# `tokens` (every existing site) must keep rendering byte for byte.

GOLDEN = {
    "atelier/berry/0": "cb0a7813c2d1244003b54ca9fe3c8ba17d80e33c251dceeb95fb25b075d112d1",
    "atelier/berry/1": "088e51af50a7b56af23d8bff834d107a8d06f5bca4954a6e17afabe21683af56",
    "atelier/berry/2": "7da1c03786b00d04ad47abc9cec58e7bd04cb26525df74ecbb7c84b40a735fe2",
    "atelier/cobalt/0": "3787aedb5f6444745098856b6c780d72cf2a6aaa5da830f76d1ce5204ef2c1ba",
    "atelier/cobalt/1": "0df1f74380cd254a3c2d153d43bd2c86bb8a67ec28c3184ba4063b944934666a",
    "atelier/cobalt/2": "080e57032d64ca54892d134e043ccbe99cccfc4d45e2f10bbf9ac92e6e9f27a1",
    "atelier/custom": "4635af1f34777febbd41dcbdfa270c32805d79654c60ac3b33fad39303f4c152",
    "atelier/sage/0": "c9742d2d8493b8ea2b7bdf096c979f63a858ddadb9d57f9e5edd0c1cc6281b48",
    "atelier/sage/1": "f9712ee9fbaa16383fb2efddbcb1820708684922aa440cfe41dd86642633eb39",
    "atelier/sage/2": "54b6d977799a8b0a934997bc4538750d4bcd9b22dc066e7544c291eded79bd41",
    "market/berry/0": "4c53cb69916094e7973f1a774fcc4dee8e757ed45281cd3797c84536e5985e8c",
    "market/berry/1": "1561cc2d1f4e41afb31ad927f17d76c59a23300fb44bfe921ac17f402c8c4748",
    "market/berry/2": "27d00ae928876665c035ab8d614643362365504583016ff6f1a8570235557af6",
    "market/cobalt/0": "05ee0f1508d3dcabf3d665f2e094ea8f2e0bbdc3522fb4a66cc44850951219e7",
    "market/cobalt/1": "09775401c2b7d48d71fa8a3a22559d327b7c972418702686fecd181ef6757f4f",
    "market/cobalt/2": "5fba8653ad1c60f6954aac527279949ba51b5ec7a48214f850bd1a2796a2b6f8",
    "market/custom": "621511dd513b14e2212a5d53b0d8d87c14c70edfbb72197c91ae824613aa4387",
    "market/sage/0": "9c9238218f8ccc3f92acc715aa5bf2832a88a98c904320605f1344e25cc34171",
    "market/sage/1": "a2f634a0c662cb8346aeca991afd4479846da84f3d9c5d4d62ea02f69794a149",
    "market/sage/2": "ffacdd788e353bc526f3f51cb0665a9b0c463d259592940758c73090b07c9a4a",
    "studio/berry/0": "e31300cc5437550f771b3696c613aae57df19f5b8c66023028724a193c6c1bc0",
    "studio/berry/1": "da5551ef35bd84e1d0a9bd4ea8bd9a59d0d60958e11dcc161949444515f8441c",
    "studio/berry/2": "03059492a2a233d3c39741e7d6a1fadbe65eecdc02d78bbedb6a14d3166268b5",
    "studio/cobalt/0": "b432b4f55bbee44126c44f06be13167203affda3c2561829ae7990386afb4641",
    "studio/cobalt/1": "fb0cbd345258e563fdc51811c000ff4c76d77f21cb4c5372bd754d61f169c249",
    "studio/cobalt/2": "5f3d82e3a10ad8d0940c1c237ba04fc18eb4c72ec8a5fd69025facbfa1b196f5",
    "studio/custom": "24fdf290a794b4124cadc11cf289e7d4c4d160d01e8c10201007579eb89b44cc",
    "studio/sage/0": "dd3bb510f3055092ea7212f5baedadfadba79ac82f6dfe06babda04dfdc30697",
    "studio/sage/1": "9f7916cddaf4c188f09c0b774bee49b72f5b42bee844f223d3994444d7e6d095",
    "studio/sage/2": "9ccbd8e0a1f09a4f28a63f7b5acd4074121b178182517267520522d0752208d6",
}


class TestBackwardCompatibility:
    def test_every_pre_1c1_recipe_renders_byte_identically(self):
        got = {}
        for theme in ("atelier", "market", "studio"):
            for palette in ("berry", "cobalt", "sage"):
                for vi, v in enumerate(VARIANTS):
                    html = _render(_recipe(theme=theme, palette=palette, variants=v))
                    got[f"{theme}/{palette}/{vi}"] = hashlib.sha256(html.encode()).hexdigest()
        for theme in ("atelier", "market", "studio"):
            html = _render(_recipe(theme=theme, palette=None, custom_colour="#7A2E4A", hidden=["reviews"]))
            got[f"{theme}/custom"] = hashlib.sha256(html.encode()).hexdigest()
        assert got == GOLDEN

    def test_none_tokens_and_fonts_render_the_same_as_absent(self):
        plain = _render(_recipe())
        assert _render(_recipe(fonts=None, tokens=None)) == plain
        assert _render(_recipe(tokens={t: None for t in reg.TOKENS})) == plain

    def test_original_three_palettes_are_unchanged(self):
        assert r.PALETTES["berry"]["accent"] == "#7A2E4A"
        assert r.PALETTES["cobalt"]["accent"] == "#1F3FD1" and r.PALETTES["cobalt"]["pop"] == "#FFB400"
        assert r.PALETTES["sage"]["accent"] == "#35664A"
        assert r.PALETTES is reg.PALETTES  # the old import path still resolves to the registry


# ───────────────────────────── registry ─────────────────────────────

class TestRegistry:
    def test_thirteen_font_pairings_in_known_groups(self):
        assert len(reg.FONT_PAIRINGS) == 13
        for key, p in reg.FONT_PAIRINGS.items():
            assert p["group"] in reg.FONT_GROUPS, key
            assert len(p["fonts"]) == 2, key
            assert p["heading_weight"] in ("400", "500", "600", "700", "800"), key

    def test_font_urls_load_at_most_two_families_with_display_swap(self):
        for key, p in reg.FONT_PAIRINGS.items():
            assert p["font_url"].startswith("https://fonts.googleapis.com/css2?family="), key
            assert p["font_url"].count("family=") == 2, key
            assert "display=swap" in p["font_url"], key

    def test_every_font_group_has_at_least_two_pairings(self):
        for g in reg.FONT_GROUPS:
            assert sum(1 for p in reg.FONT_PAIRINGS.values() if p["group"] == g) >= 2, g

    def test_registry_theme_pairings_match_the_themes(self):
        assert set(reg.THEME_META) == set(r.THEMES)
        for theme, meta in reg.THEME_META.items():
            pair, t = reg.FONT_PAIRINGS[meta["default_pairing"]], r.THEMES[theme]
            assert pair["fonts"] == t["fonts"] and pair["font_url"] == t["font_url"]
            assert pair["display_fallback"] == t["display_fallback"] and pair["body_fallback"] == t["body_fallback"]
            assert pair["heading_weight"] == ("400" if t["upper_headings"] else "600")
            assert pair["group"] in meta["font_groups"]

    def test_thirteen_tokens_with_at_least_two_options(self):
        assert set(reg.TOKENS) == {"radius", "density", "button", "heading_case", "image_style", "divider",
                                   "background", "bands", "cards", "finish", "hero_height", "mobile_cols", "image_fit"}
        assert all(len(v) >= 2 for v in reg.TOKENS.values())

    def test_palette_meta_covers_every_palette_and_only_those(self):
        assert set(reg.PALETTE_META) == set(reg.PALETTES)
        assert len(reg.PALETTES) >= 21

    @pytest.mark.parametrize("niche", reg.NICHES)
    def test_each_launch_niche_has_twelve_or_more_palettes(self, niche):
        assert len(reg.palettes_for_niche(niche)) >= 12

    def test_niche_lists_start_with_an_original_palette(self):
        # the SQL migration relies on this so the previous code stays safe if the DB is ahead of the deploy
        for niche in reg.NICHES:
            assert reg.palettes_for_niche(niche)[0] in ("berry", "cobalt", "sage")

    def test_unknown_niche_gets_every_palette(self):
        assert set(reg.palettes_for_niche("bakery")) == set(reg.PALETTES)


class TestPaletteContrast:
    """Every palette must be readable wherever the theme uses its colours."""

    @pytest.mark.parametrize("name", sorted(reg.PALETTES))
    def test_readable(self, name):
        p = reg.PALETTES[name]
        c = r._contrast_ratio
        assert c(p["ink"], p["ground"]) >= 7, "body text on the page"
        assert c(p["muted"], p["ground"]) >= 4.5, "secondary text on the page"
        assert c(p["accent"], p["ground"]) >= 4.5, "eyebrows and links in the accent colour"
        assert c(p["on_accent"], p["accent"]) >= 4.5, "buttons, tags and the quote band"
        assert c(p["muted"], p["soft"]) >= 4.5, "secondary text on tinted cards"
        assert c(p["ground"], p["ink"]) >= 7, "footer text"
        if "pop" in p:
            assert c(p["ink"], p["pop"]) >= 4.5, "chips draw dark ink on the pop colour"

    @pytest.mark.parametrize("name", sorted(reg.PALETTES))
    def test_shape(self, name):
        p = reg.PALETTES[name]
        for k in ("ground", "ink", "muted", "accent", "on_accent", "soft", "line"):
            assert re.match(r"^#[0-9A-F]{6}$", p[k]), (name, k)
        assert len(p["photo"]) == 2


# ───────────────────────────── renderer: fonts + tokens ─────────────────────────────

ALL_TOKEN_CASES = [(t, o) for t, opts in reg.TOKENS.items() for o in opts]


class TestFonts:
    def test_pairing_changes_font_link_and_families(self):
        html = _render(_recipe(fonts="playfair_lato"))
        assert reg.FONT_PAIRINGS["playfair_lato"]["font_url"] in html
        assert "'Playfair Display'" in html and "'Lato'" in html
        assert reg.FONT_PAIRINGS["bodoni_jost"]["font_url"] not in html

    def test_no_fonts_uses_the_theme_pair(self):
        html = _render(_recipe(theme="market"))
        assert r.THEMES["market"]["font_url"] in html and "'Anton'" in html

    @pytest.mark.parametrize("fonts", sorted(reg.FONT_PAIRINGS))
    def test_every_pairing_renders_on_every_theme(self, fonts):
        for theme in r.THEMES:
            html = _render(_recipe(theme=theme, fonts=fonts))
            assert reg.FONT_PAIRINGS[fonts]["fonts"][0] in html

    def test_heading_weight_comes_from_the_pairing(self):
        assert "font-weight:700;" in _render(_recipe(fonts="jakarta_inter"))


class TestTokens:
    @pytest.mark.parametrize("token,option", ALL_TOKEN_CASES)
    @pytest.mark.parametrize("theme", ["atelier", "market", "studio"])
    def test_each_option_renders_when_supported(self, theme, token, option):
        excluded = option in reg.THEME_META[theme]["token_exclusions"].get(token, ())
        recipe = _recipe(theme=theme, tokens={token: option})
        if excluded:
            with pytest.raises(ValueError):
                _render(recipe)
        else:
            html = _render(recipe)
            assert "<script" not in html.lower()
            assert html.startswith("<!doctype html>")

    def test_radius_overrides_the_root_variables(self):
        assert ":root{--r:0;--br:0}" in _render(_recipe(theme="market", tokens={"radius": "sharp"}))
        assert ":root{--r:14px;--br:999px}" in _render(_recipe(theme="studio", tokens={"radius": "pill"}))

    def test_density_uses_desktop_and_mobile_rules(self):
        html = _render(_recipe(tokens={"density": "airy"}))
        assert "@media (min-width:761px){.sec{padding-top:104px;padding-bottom:104px}.grid{gap:32px}}" in html
        assert "@media (max-width:760px){.sec{padding-top:72px;padding-bottom:72px}}" in html
        compact = _render(_recipe(tokens={"density": "compact"}))
        assert "@media (min-width:761px){.sec{padding-top:56px;padding-bottom:56px}.grid{gap:16px}}" in compact
        assert "@media (max-width:760px){.sec{padding-top:40px;padding-bottom:40px}}" in compact
        assert "padding-top:104px" not in _render(_recipe(tokens={"density": "regular"}))

    def test_outline_and_underline_buttons_keep_the_hero_button_solid(self):
        for style in ("outline", "underline"):
            html = _render(_recipe(tokens={"button": style}))
            assert ".btn-accent{background:transparent" in html
            assert ".hero-over .btn-accent,.hero-tint .btn-accent{background:var(--btn-accent);color:var(--on-accent)" in html
        assert ".btn-accent{background:transparent" not in _render(_recipe(tokens={"button": "solid"}))

    def test_heading_case_normal_removes_the_market_uppercase(self):
        assert "text-transform:uppercase" in _render(_recipe(theme="market"))
        html = _render(_recipe(theme="market", tokens={"heading_case": "normal"}))
        assert "h1,h2,h3{font-family:'Anton', Impact, 'Arial Narrow', sans-serif;font-weight:400;line-height:1.05;}" in html

    def test_heading_case_upper_on_a_lowercase_theme(self):
        html = _render(_recipe(theme="studio", tokens={"heading_case": "spaced_upper"}))
        assert "text-transform:uppercase;letter-spacing:.06em;" in html and "h1,h2{overflow-wrap:break-word}" in html

    def test_image_styles(self):
        # the CSS pruner drops `.photo` when the page has no uploaded photo, so match either form
        assert re.search(r"\.ph(,\.photo)?\{border-radius:0\}", _render(_recipe(tokens={"image_style": "square"})))
        assert re.search(r"\.ph(,\.photo)?\{border-radius:20px\}", _render(_recipe(tokens={"image_style": "rounded"})))
        assert "999px 999px var(--r) var(--r)" in _render(_recipe(tokens={"image_style": "arch"}))
        framed = _render(_recipe(tokens={"image_style": "framed"}))
        assert "box-shadow:0 0 0 5px var(--ground),0 0 0 6.5px var(--ink)" in framed
        assert re.search(r"\.hero-fullbleed \.ph(,\.hero-fullbleed \.photo)?\{box-shadow:none\}", framed)

    def test_image_styles_reach_real_photos_too(self):
        assets = {"a1": {"public_url": "https://x.supabase.co/a1.jpg"}}
        content = {**CONTENT, "about": {**CONTENT["about"], "image_asset_id": "a1"}}
        html = r.render_page(content, _recipe(tokens={"image_style": "rounded"}), PRESET, assets)
        assert '<div class="photo ph-about"' in html and ".ph,.photo{border-radius:20px}" in html

    def test_dividers(self):
        assert ".sec h2::after" not in _render(_recipe(tokens={"divider": "none"}))
        for d in ("line", "dot", "ornament"):
            assert ".sec h2::after" in _render(_recipe(tokens={"divider": d}))

    def test_token_css_is_pruned_to_used_classes(self):
        # no photo-grid sections -> nothing for .ph-card etc.; the CSS is still valid and smaller than unpruned
        html = _render(_recipe(order=["hero", "order"], tokens={"image_style": "arch"}))
        assert ".ph-card" not in html.split("<style>")[1].split("</style>")[0]


class TestValidation:
    def test_unknown_font_or_token_or_option_is_rejected(self):
        with pytest.raises(ValueError, match="font pairing"):
            _render(_recipe(fonts="comic_sans"))
        with pytest.raises(ValueError, match="design token"):
            _render(_recipe(tokens={"sparkle": "on"}))
        with pytest.raises(ValueError, match="option"):
            _render(_recipe(tokens={"radius": "wobbly"}))

    def test_theme_exclusions(self):
        with pytest.raises(ValueError, match="does not support"):
            _render(_recipe(theme="atelier", tokens={"radius": "pill"}))
        _render(_recipe(theme="market", tokens={"radius": "pill"}))

    def test_preset_can_narrow_fonts_and_tokens(self):
        preset = {**PRESET, "allowed_fonts": ["playfair_lato"], "token_options": {"button": ["solid"], "radius": []}}
        _render(_recipe(fonts="playfair_lato", tokens={"button": "solid", "radius": "soft"}), preset)
        with pytest.raises(ValueError, match="not allowed"):
            _render(_recipe(fonts="cormorant_jost"), preset)
        with pytest.raises(ValueError, match="not allowed"):
            _render(_recipe(tokens={"button": "outline"}), preset)

    def test_empty_preset_lists_allow_everything(self):
        preset = {**PRESET, "allowed_fonts": [], "token_options": {}}
        _render(_recipe(fonts="syne_dmsans", tokens={"button": "underline", "image_style": "arch"}), preset)

    def test_preset_design_field_validation(self):
        reg.validate_preset_design_fields(["playfair_lato"], {"button": ["solid", "outline"]}, ["berry", "gold"])
        reg.validate_preset_design_fields(None, None, None)
        with pytest.raises(ValueError, match="font pairing"):
            reg.validate_preset_design_fields(["nope"], {}, [])
        with pytest.raises(ValueError, match="token"):
            reg.validate_preset_design_fields([], {"sparkle": ["on"]}, [])
        with pytest.raises(ValueError, match="option"):
            reg.validate_preset_design_fields([], {"button": ["giant"]}, [])
        with pytest.raises(ValueError, match="palette"):
            reg.validate_preset_design_fields([], {}, ["berry", "neon"])
        with pytest.raises(ValueError, match="list"):
            reg.validate_preset_design_fields([], {"button": "solid"}, [])


class TestSafety:
    """Spec §8.1 still holds for every new option: no scripts, every value escaped."""

    def test_no_script_and_escaping_for_a_wide_sweep_of_looks(self):
        evil = {**CONTENT, "business": {**CONTENT["business"], "name": '<img src=x onerror=alert(1)>"&'}}
        for seed in range(40):
            recipe = picker.pick_recipe(PRESET, f"sweep-{seed}")
            html = r.render_page(evil, recipe, PRESET, {})
            assert "<script" not in html.lower()
            assert "<img src=x" not in html
            assert "&lt;img src=x onerror" in html


# ───────────────────────────── seeded picker ─────────────────────────────

def _fingerprint(recipe):
    return (recipe["theme"], recipe["palette"], recipe["custom_colour"], recipe["fonts"], tuple(sorted(recipe["tokens"].items())))


class TestPicker:
    def test_deterministic_for_a_seed(self):
        assert picker.pick_recipe(PRESET, "site-1") == picker.pick_recipe(PRESET, "site-1")

    def test_different_seeds_give_a_wide_spread(self):
        recipes = [picker.pick_recipe(PRESET, f"site-{i}") for i in range(80)]
        assert len({_fingerprint(x) for x in recipes}) >= 70
        assert len({x["theme"] for x in recipes}) == 3
        assert len({x["palette"] for x in recipes}) >= 10
        assert len({x["fonts"] for x in recipes}) >= 6
        for token, options in reg.TOKENS.items():
            if token in ("background", "finish", "hero_height", "mobile_cols", "image_fit"):  # SITE-1C-3c/3d/3e/3f/3g: opt-in, never random
                continue
            assert len({x["tokens"][token] for x in recipes}) >= 2, token

    def test_every_pick_is_valid_and_renders(self):
        for i in range(60):
            recipe = picker.pick_recipe(PRESET, f"valid-{i}")
            r.validate_recipe(PRESET, recipe)
            assert _render(recipe).startswith("<!doctype html>")

    def test_fonts_stay_within_the_themes_groups(self):
        for i in range(60):
            recipe = picker.pick_recipe(PRESET, f"fonts-{i}")
            assert reg.FONT_PAIRINGS[recipe["fonts"]]["group"] in reg.THEME_META[recipe["theme"]]["font_groups"]

    def test_theme_exclusions_are_respected(self):
        for i in range(120):
            recipe = picker.pick_recipe({**PRESET, "allowed_themes": ["atelier"]}, f"excl-{i}")
            assert recipe["tokens"]["radius"] != "pill"

    def test_respects_preset_narrowing(self):
        preset = {**PRESET, "allowed_themes": ["market"], "default_palettes": ["gold", "plum"], "allowed_fonts": ["poppins_nunito"],
                  "token_options": {"button": ["outline"], "divider": ["dot", "line"]}}
        for i in range(40):
            recipe = picker.pick_recipe(preset, f"narrow-{i}")
            assert recipe["theme"] == "market" and recipe["palette"] in ("gold", "plum")
            assert recipe["fonts"] == "poppins_nunito" and recipe["tokens"]["button"] == "outline"
            assert recipe["tokens"]["divider"] in ("dot", "line")

    def test_uses_niche_palettes_when_the_preset_lists_none(self):
        pals = {picker.pick_recipe({**PRESET, "default_palettes": []}, f"n-{i}")["palette"] for i in range(80)}
        assert pals <= set(reg.palettes_for_niche("boutique")) and len(pals) >= 8

    def test_brief_colour_answer_is_honoured(self):
        assert picker.pick_recipe(PRESET, "s", "#1a2b3c")["custom_colour"] == "#1A2B3C"
        assert picker.pick_recipe(PRESET, "s", "#1a2b3c")["palette"] is None
        named = picker.pick_recipe({**PRESET, "default_palettes": ["berry", "gold"]}, "s", "GOLD")
        assert named["palette"] == "gold" and named["custom_colour"] is None

    def test_a_broken_preset_falls_back_to_first_choice(self):
        bad = {**PRESET, "allowed_themes": ["not_a_theme"]}
        recipe = picker.pick_recipe(bad, "x")
        assert recipe == picker.first_choice_recipe(bad) and "tokens" not in recipe and "fonts" not in recipe

    def test_section_order_comes_from_the_preset(self):
        assert picker.pick_recipe({**PRESET, "sections": ["hero", "items", "order"]}, "o")["order"] == ["hero", "items", "order"]

    def test_first_choice_recipe_matches_the_pre_1c1_behaviour(self):
        rec = picker.first_choice_recipe({**PRESET, "default_palettes": ["sage", "berry"]})
        assert rec["theme"] == "atelier" and rec["palette"] == "sage" and rec["order"] == SECTIONS


class TestBuildRecipeHook:
    """site_copy_service._build_recipe: seeded picker with a seed, original behaviour without one."""

    @pytest.fixture()
    def build(self):
        try:
            from app.services.site_copy_service import _build_recipe
        except ImportError as exc:  # optional third-party deps (anthropic, ...) not installed
            pytest.skip(f"site_copy_service needs its full dependencies: {exc}")
        return _build_recipe

    def test_without_a_seed_it_is_the_old_first_choice_recipe(self, build):
        rec = build({**PRESET, "default_palettes": ["sage", "berry"]}, None)
        assert rec["theme"] == "atelier" and rec["palette"] == "sage" and "tokens" not in rec

    def test_with_a_seed_sites_differ(self, build):
        looks = {_fingerprint(build(PRESET, None, seed=f"site-{i}")) for i in range(30)}
        assert len(looks) >= 25

    def test_seeded_result_validates_as_a_recipe_model(self, build):
        from app.models.sites import Recipe
        for i in range(20):
            Recipe.model_validate(build(PRESET, None, seed=f"m-{i}"))


# ───────────────────────────── models ─────────────────────────────

class TestModels:
    def test_recipe_accepts_fonts_and_tokens_and_round_trips(self):
        from app.models.sites import Recipe
        rec = Recipe.model_validate({"theme": "atelier", "palette": "berry", "fonts": "playfair_lato", "order": ["hero"],
                                     "tokens": {"radius": "soft", "divider": "dot"}})
        dumped = rec.model_dump(mode="json")
        assert dumped["tokens"]["radius"] == "soft" and dumped["tokens"]["button"] is None
        r.validate_recipe(PRESET, dumped)  # the None-valued keys must be ignored

    def test_recipe_without_tokens_still_valid(self):
        from app.models.sites import Recipe
        assert Recipe.model_validate({"theme": "atelier", "palette": "berry", "order": ["hero"]}).tokens is None

    def test_unknown_token_key_is_rejected(self):
        from pydantic import ValidationError
        from app.models.sites import Recipe
        with pytest.raises(ValidationError):
            Recipe.model_validate({"theme": "atelier", "palette": "berry", "order": ["hero"], "tokens": {"sparkle": "on"}})

    def test_preset_models_accept_the_new_fields_and_thirty_palettes(self):
        from app.models.sites import SitePresetCreate, SitePresetUpdate
        pal = list(reg.PALETTES)
        c = SitePresetCreate(key="bakery", name="Bakery", sections=["hero"], allowed_themes=["atelier"],
                             default_palettes=pal, allowed_fonts=["playfair_lato"], token_options={"button": ["solid"]})
        assert len(c.default_palettes) == 21 and c.allowed_fonts == ["playfair_lato"]
        assert SitePresetCreate(key="b", name="B", sections=["hero"], allowed_themes=["atelier"]).token_options == {}
        u = SitePresetUpdate(allowed_fonts=[], token_options={})
        assert u.model_dump(exclude_unset=True) == {"allowed_fonts": [], "token_options": {}}


# ───────────────────────── hero photo + nav separation ─────────────────────────

def _with_hero_photo():
    import copy
    c = copy.deepcopy(CONTENT)
    c["hero"]["image_asset_id"] = "hero1"
    assets = {"hero1": {"public_url": "https://cdn.test/hero.jpg", "export_path": "images/hero.jpg"}}
    return c, assets


@pytest.mark.parametrize("variant", ["fullbleed", "collage", "centered"])
def test_hero_photo_shows_in_every_hero_layout(variant):
    c, assets = _with_hero_photo()
    html = r.render_page(c, _recipe(variants={"hero": variant}), PRESET, assets)
    assert "https://cdn.test/hero.jpg" in html


def test_centered_hero_without_any_photo_is_a_coloured_band():
    html = _render(_recipe(variants={"hero": "centered"}))
    assert '<div class="hero-tint-bar"><section class="hero hero-centered hero-tint' in html
    assert '<div class="strip">' not in html and '<div class="hero-banner">' not in html


def test_centered_hero_keeps_item_strip_when_items_have_photos():
    import copy
    c = copy.deepcopy(CONTENT)
    c["items"][0]["image_asset_id"] = "i1"
    assets = {"i1": {"public_url": "https://cdn.test/i1.jpg", "export_path": "images/i1.jpg"}}
    html = r.render_page(c, _recipe(variants={"hero": "centered"}), PRESET, assets)
    assert '<div class="strip">' in html and "https://cdn.test/i1.jpg" in html


def test_nav_is_a_separate_bar_above_the_hero():
    html = _render(_recipe())
    assert html.index('class="nav-bar"') < html.index('class="hero ')
    assert ".nav-bar{border-bottom:1px solid var(--line)" in html
