"""tests/unit/test_site_refined.py — SITE-1C-3d: the CSS-only 'Refined look' (tokens.finish == 'refined')."""
from __future__ import annotations

import re

import pytest

from app.services import site_design_registry as reg
from app.services import site_design_service as picker
from app.services import site_renderer as r
from tests.unit.test_site_design import PRESET, _recipe, _render


def _refined(**tok):
    return _recipe(tokens={"finish": "refined", **tok})


def _style(html):
    return re.search(r"<style>(.*?)</style>", html, re.S).group(1)


class TestStandardIsUntouched:
    @pytest.mark.parametrize("tokens", [None, {}, {"finish": "standard"}, {"finish": None}])
    def test_no_refined_output(self, tokens):
        html = _render(_recipe(tokens=tokens) if tokens is not None else _recipe())
        assert "wa-fab" not in html and "@keyframes" not in html and "@supports" not in html
        assert "position:sticky" not in html and "backdrop-filter" not in html

    def test_standard_token_alone_changes_nothing_but_the_token_block(self):
        assert _render(_recipe(tokens={"finish": "standard"})) == _render(_recipe())


class TestRefinedOutput:
    def test_has_every_refined_piece(self):
        from copy import deepcopy
        from tests.unit.test_site_design import CONTENT
        content = deepcopy(CONTENT)
        content["hero"]["image_asset_id"] = "a1"     # a real photo, so the photo rules are kept by the pruner
        assets = {"a1": {"public_url": "https://abc.supabase.co/storage/v1/object/public/site-assets/a.jpg"}}
        html = r.render_page(content, {**_refined(), "variants": {"about": "quote"}}, PRESET, assets)  # quote layout = dark band
        css = _style(html)
        for piece in (".nav-bar{position:sticky", "backdrop-filter:blur(14px)", ".about-band{background:var(--ink)",
                      ".photo:hover img{transform:scale(1.04)}", ".btn:hover{transform:translateY(-2px)}",
                      "@keyframes rise{", "@supports (animation-timeline:view())", "animation-timeline:view()",
                      "@media (prefers-reduced-motion:reduce)", "@media print"):
            assert piece in css, piece
        assert "clamp(3rem,8vw,6.5rem)" in css

    def test_floating_whatsapp_button(self):
        html = _render(_refined())
        m = re.search(r'<a class="wa-fab" href="(https://wa\.me/2348012345678\?text=[^"]+)" target="_blank" rel="noopener" aria-label="([^"]+)">', html)
        assert m and m.group(2) == "Order on WhatsApp"
        assert html.count('class="wa-fab"') == 1

    def test_no_script_anywhere(self):
        for theme in ("atelier", "market", "studio"):
            assert "<script" not in _render(_refined(), None) and "<script" not in _render({**_refined(), "theme": theme})

    def test_css_braces_are_balanced_after_pruning(self):
        for theme in ("atelier", "market", "studio"):
            css = _style(_render({**_refined(), "theme": theme}))
            assert css.count("{") == css.count("}")

    def test_the_reveal_never_hides_content_without_support(self):
        # the animation only exists inside @supports, and is switched off for reduced motion and print
        css = _style(_render(_refined()))
        outside = re.sub(r"@supports \(animation-timeline:view\(\)\)\{.*?\}\}", "", css)
        assert "animation:rise" not in outside

    def test_light_pairing_gets_light_tight_headings(self):
        css = _style(_render(_refined(), None))  # atelier default pairing (Bodoni) is elegant
        assert "font-weight:400;letter-spacing:-.03em" in css

    def test_bold_pairing_keeps_its_weight_and_spacing(self):
        css = _style(_render({**_refined(), "theme": "market"}))
        assert "clamp(2.8rem,7vw,5.2rem)" in css and "letter-spacing:-.03em" not in css

    def test_uppercase_headings_skip_negative_spacing(self):
        css = _style(_render(_refined(heading_case="upper")))
        assert "letter-spacing:-.03em" not in css and "clamp(3rem,8vw,6.5rem)" in css

    def test_compact_spacing_is_respected_others_get_roomier(self):
        assert "padding-top:112px" not in _style(_render(_refined(density="compact")))
        assert "padding-top:112px" in _style(_render(_refined(density="regular")))

    def test_the_new_font_pairing_renders(self):
        html = _render({**_refined(), "fonts": "cormorant_dmsans"})
        assert "family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans" in html
        assert "'Cormorant Garamond'" in html

    def test_refined_still_valid_with_every_look_option(self):
        for bg in ("match", "white", "grey", "ivory"):
            for cards in ("flat", "bordered", "lifted"):
                for bands in ("plain", "wash"):
                    assert _render(_refined(background=bg, cards=cards, bands=bands)).startswith("<!doctype html>")


class TestPrunerAtRules:
    def test_keyframes_and_supports_pass_through(self):
        css = "@keyframes x{from{opacity:0}to{opacity:1}}@supports (a:b){.used{color:red}.gone{color:blue}}.used{margin:0}"
        out = r._prune_css(css, '<p class="used">')
        assert "@keyframes x{from{opacity:0}to{opacity:1}}" in out
        assert "@supports (a:b){.used{color:red}}" in out and ".gone" not in out


class TestPickerAndValidation:
    def test_default_is_standard(self):
        for i in range(30):
            assert picker.pick_recipe(PRESET, f"f-{i}")["tokens"]["finish"] == "standard"

    def test_template_can_make_every_new_site_refined(self):
        preset = {**PRESET, "token_options": {"finish": ["refined"]}}
        for i in range(30):
            rec = picker.pick_recipe(preset, f"f-{i}")
            assert rec["tokens"]["finish"] == "refined"
            assert _render(rec, preset).count('class="wa-fab"') == 1

    def test_allowing_both_options_still_starts_standard(self):
        preset = {**PRESET, "token_options": {"finish": ["standard", "refined"]}}
        assert picker.pick_recipe(preset, "f-1")["tokens"]["finish"] == "standard"

    def test_a_site_may_turn_it_on_unless_the_template_forbids_it(self):
        r.validate_recipe(PRESET, _refined())
        with pytest.raises(ValueError):
            r.validate_recipe({**PRESET, "token_options": {"finish": ["standard"]}}, _refined())
        with pytest.raises(ValueError):
            r.validate_recipe(PRESET, _recipe(tokens={"finish": "glossy"}))

    def test_recipe_model_accepts_the_token(self):
        from app.models.sites import Recipe
        rec = Recipe(theme="atelier", palette="berry", order=["hero"], tokens={"finish": "refined"})
        assert rec.tokens.finish == "refined"

    def test_registry_labels(self):
        assert reg.TOKENS["finish"] == ("standard", "refined") and reg.TOKEN_LABELS["finish"] == "Refined look"
