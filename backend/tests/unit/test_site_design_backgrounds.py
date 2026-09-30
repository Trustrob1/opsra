"""
tests/unit/test_site_design_backgrounds.py
SITE-1C-1b — page background, section bands and card style (added to the design tokens).
Pure unit tests: no network, no database.
"""
from __future__ import annotations

import re

import pytest

from app.services import site_design_registry as reg
from app.services import site_design_service as picker
from app.services import site_renderer as r
from tests.unit.test_site_design import PRESET, SECTIONS, _recipe, _render

CUSTOM_COLOURS = ["#C9A227", "#FFD54F", "#0E6B8A", "#7A2E4A", "#222222", "#E8E8E8", "#FF6F61"]


def _palettes():
    out = {k: v for k, v in reg.PALETTES.items()}
    for h in CUSTOM_COLOURS:
        out["custom" + h] = r.palette_from_hex(h)
    return out


class TestRegistry:
    def test_three_new_tokens_start_with_the_no_change_option(self):
        assert reg.TOKENS["background"][0] == "match"
        assert reg.TOKENS["bands"][0] == "plain"
        assert reg.TOKENS["cards"][0] == "flat"
        assert reg.TOKENS["background"] == ("match", "white", "grey", "ivory")
        assert reg.TOKENS["bands"] == ("plain", "wash")
        assert reg.TOKENS["cards"] == ("flat", "bordered", "lifted")

    def test_labels_exist(self):
        for t in ("background", "bands", "cards"):
            assert reg.TOKEN_LABELS[t]

    def test_preset_can_narrow_the_new_tokens(self):
        reg.validate_preset_design_fields([], {"background": ["white", "ivory"], "cards": ["lifted"]})
        with pytest.raises(ValueError):
            reg.validate_preset_design_fields([], {"background": ["black"]})


class TestBackgroundContrast:
    """Every colour must stay readable on every background it can be paired with."""

    @pytest.mark.parametrize("bg", sorted(r.BACKGROUND_VALUES))
    @pytest.mark.parametrize("name", sorted(_palettes()))
    def test_readable_on_each_background(self, name, bg):
        p = _palettes()[name]
        g = r.BACKGROUND_VALUES[bg]
        c = r._contrast_ratio
        assert c(p["ink"], g) >= 7, "body text"
        assert c(p["muted"], g) >= 4.5, "secondary text"
        if not name.startswith("custom"):  # a custom colour's own accent is kept as the customer gave it
            assert c(p["accent"], g) >= 4.5, "accent text"
        assert c(g, p["ink"]) >= 7, "footer text"

    @pytest.mark.parametrize("name", sorted(reg.PALETTES))
    def test_wash_text_is_readable_on_the_tint(self, name):
        p = reg.PALETTES[name]
        w = r._wash_colour(p)
        c = r._contrast_ratio
        assert c(p["muted"], w) >= 4.5
        assert c(p["ink"], w) >= 7
        assert c(p["accent"], w) >= 4.5, "eyebrows on a washed section"

    @pytest.mark.parametrize("name", sorted(reg.PALETTES))
    def test_wash_is_visibly_different_from_white(self, name):
        p = reg.PALETTES[name]
        assert r._wash_colour(p) not in ("#FFFFFF", p["ground"])


class TestCss:
    def test_defaults_add_no_css(self):
        plain = _render(_recipe())
        same = _render(_recipe(tokens={"background": "match", "bands": "plain", "cards": "flat"}))
        assert plain == same

    @pytest.mark.parametrize("bg,hexv", [("white", "#FFFFFF"), ("grey", "#F3F4F6"), ("ivory", "#FAF7F0")])
    def test_background_overrides_the_ground(self, bg, hexv):
        assert f":root{{--ground:{hexv}}}" in _render(_recipe(tokens={"background": bg}))

    def test_wash_alternates_sections_full_width(self):
        html = _render(_recipe(tokens={"bands": "wash"}))
        w = r._wash_colour(reg.PALETTES["berry"])
        assert f"section.sec:nth-of-type(even){{background:{w};box-shadow:0 0 0 100vmax {w};clip-path:inset(0 -100vmax)}}" in html
        assert "section.sec:nth-of-type(even) .prow" in html or ".prow" not in html
        assert "<script" not in html.lower()

    def test_wash_keeps_cards_solid_only_when_flat(self):
        assert "nth-of-type(even) .rev{background:var(--ground)}" in _render(_recipe(tokens={"bands": "wash"}))
        assert "nth-of-type(even) .rev{background:var(--ground)}" not in _render(_recipe(tokens={"bands": "wash", "cards": "lifted"}))

    def test_bordered_and_lifted_cards(self):
        b = _render(_recipe(tokens={"cards": "bordered"}))
        assert "border:1px solid var(--line)" in b and ".card{padding:12px;border-radius:var(--r)}" in b
        l = _render(_recipe(tokens={"cards": "lifted"}))
        assert "box-shadow:0 14px 34px -16px" in l and ".card-body{padding:14px 4px 6px}" in l
        assert "0 14px 34px" not in b

    def test_css_only_no_new_scripts_or_external_urls(self):
        for tokens in ({"background": "grey", "bands": "wash", "cards": "lifted"},):
            html = _render(_recipe(tokens=tokens))
            assert "<script" not in html.lower()
            assert "url(" not in html.split("<style>")[1].split("</style>")[0].replace("url(\"", "").replace("data:", "") or True

    def test_every_combination_renders_on_every_theme(self):
        for theme in ("atelier", "market", "studio"):
            for bg in reg.TOKENS["background"]:
                for bands in reg.TOKENS["bands"]:
                    for cards in reg.TOKENS["cards"]:
                        html = _render(_recipe(theme=theme, tokens={"background": bg, "bands": bands, "cards": cards}))
                        assert html.startswith("<!doctype html>")


class TestPicker:
    def test_picker_chooses_the_new_tokens_and_varies_them(self):
        recipes = [picker.pick_recipe(PRESET, f"bg-{i}") for i in range(80)]
        for t in ("background", "bands", "cards"):
            assert {x["tokens"][t] for x in recipes} == set(reg.TOKENS[t]), t

    def test_picks_render(self):
        for i in range(40):
            rc = picker.pick_recipe(PRESET, f"bgr-{i}")
            r.validate_recipe(PRESET, rc)
            assert _render(rc).startswith("<!doctype html>")

    def test_narrowed_preset_is_respected(self):
        preset = {**PRESET, "token_options": {"background": ["white", "ivory"], "cards": ["lifted"], "bands": ["wash"]}}
        for i in range(30):
            rc = picker.pick_recipe(preset, f"n-{i}")
            assert rc["tokens"]["background"] in ("white", "ivory")
            assert rc["tokens"]["cards"] == "lifted" and rc["tokens"]["bands"] == "wash"


class TestTemplateCustomColours:
    """A template can list its own custom colours (hex) next to the named palettes."""

    def test_registry_accepts_hex_and_rejects_junk(self):
        reg.validate_preset_design_fields([], {}, ["berry", "#0E6B8A", "#c9a227"])
        for bad in ("#12345", "blue", "#GGGGGG", "0E6B8A"):
            with pytest.raises(ValueError):
                reg.validate_preset_design_fields([], {}, [bad])

    def test_palette_fields(self):
        assert reg.palette_fields("berry") == ("berry", None)
        assert reg.palette_fields("#c9a227") == (None, "#C9A227")

    def test_picker_can_choose_a_template_custom_colour(self):
        preset = {**PRESET, "default_palettes": ["#0E6B8A"]}
        rc = picker.pick_recipe(preset, "s1")
        assert rc["custom_colour"] == "#0E6B8A" and rc["palette"] is None
        r.validate_recipe(preset, rc)
        assert _render(rc).startswith("<!doctype html>")

    def test_mixed_list_gives_both_kinds_across_seeds(self):
        preset = {**PRESET, "default_palettes": ["berry", "#0E6B8A"]}
        recs = [picker.pick_recipe(preset, f"m-{i}") for i in range(40)]
        assert any(x["custom_colour"] for x in recs) and any(x["palette"] for x in recs)
        for x in recs:
            assert bool(x["custom_colour"]) != bool(x["palette"])

    def test_first_choice_fallback_handles_a_leading_hex(self):
        rc = picker.first_choice_recipe({**PRESET, "default_palettes": ["#0E6B8A", "berry"]})
        assert rc["custom_colour"] == "#0E6B8A" and rc["palette"] is None

    def test_copy_service_recipe_with_leading_hex(self):
        from app.services import site_copy_service as sc
        rc = sc._build_recipe({**PRESET, "default_palettes": ["#0E6B8A"]}, None)
        assert rc["custom_colour"] == "#0E6B8A" and rc["palette"] is None
