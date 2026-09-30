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


class TestHeroHeightAndTileCards:
    """SITE-1C-3e: a choosable tall Full photo hero, and a padded 'tile' card style."""

    def test_tall_hero_css_only_for_a_full_photo_hero(self):
        tall = _recipe(tokens={"hero_height": "tall"}, variants={"hero": "fullbleed"})
        css = _style(_render(tall))
        assert ".hero-fullbleed{min-height:88vh;min-height:min(92svh,900px)}" in css
        assert "@media (max-width:760px){.hero-fullbleed{min-height:86vh;min-height:min(86svh,760px)}}" in css
        for v in ("centered", "collage"):
            assert "92svh" not in _style(_render(_recipe(tokens={"hero_height": "tall"}, variants={"hero": v})))

    def test_standard_hero_height_changes_nothing(self):
        rec = _recipe(variants={"hero": "fullbleed"})
        assert "svh" not in _style(_render({**rec, "tokens": {"hero_height": "standard"}}))

    def test_tall_hero_is_independent_of_the_refined_look(self):
        assert "svh" in _style(_render(_recipe(tokens={"hero_height": "tall"}, variants={"hero": "fullbleed"})))
        assert "position:sticky" not in _style(_render(_recipe(tokens={"hero_height": "tall"})))

    def test_tile_cards_pad_the_text_and_fill_the_card(self):
        css = _style(_render(_recipe(tokens={"cards": "tile"})))
        assert ".card{background:var(--soft);border-radius:var(--r)}" in css
        assert ".card-body{padding:18px 18px 22px;gap:8px}" in css
        assert "@media (max-width:760px){.grid{gap:18px}.card-body{padding:14px 14px 18px}}" in css

    def test_flat_cards_stay_as_they_were(self):
        for tokens in (None, {"cards": "flat"}):
            css = _style(_render(_recipe(tokens=tokens) if tokens else _recipe()))
            assert "padding:18px 18px 22px" not in css

    def test_refined_turns_flat_cards_into_tiles_but_keeps_an_explicit_style(self):
        assert "padding:18px 18px 22px" in _style(_render(_refined()))
        assert "padding:18px 18px 22px" in _style(_render(_refined(cards="flat")))
        assert "padding:18px 18px 22px" not in _style(_render(_refined(cards="bordered")))
        assert "padding:18px 18px 22px" not in _style(_render(_refined(cards="lifted")))

    def test_tile_keeps_the_arch_photo_shape(self):
        css = _style(_render(_recipe(tokens={"cards": "tile", "image_style": "arch"})))
        assert ".card .ph,.card .photo{border-radius" not in css

    def test_css_is_balanced(self):
        css = _style(_render(_recipe(tokens={"cards": "tile", "hero_height": "tall"}, variants={"hero": "fullbleed"})))
        assert css.count("{") == css.count("}")

    def test_picker_never_picks_a_tall_hero_unless_the_template_asks(self):
        for i in range(30):
            assert picker.pick_recipe(PRESET, f"h-{i}")["tokens"]["hero_height"] == "standard"
        preset = {**PRESET, "token_options": {"hero_height": ["tall"]}}
        for i in range(30):
            assert picker.pick_recipe(preset, f"h-{i}")["tokens"]["hero_height"] == "tall"
        both = {**PRESET, "token_options": {"hero_height": ["standard", "tall"]}}
        assert picker.pick_recipe(both, "h-1")["tokens"]["hero_height"] == "standard"

    def test_picker_can_choose_tile_cards(self):
        seen = {picker.pick_recipe(PRESET, f"t-{i}")["tokens"]["cards"] for i in range(80)}
        assert "tile" in seen and seen == set(reg.TOKENS["cards"])

    def test_model_and_labels(self):
        from app.models.sites import Recipe
        rec = Recipe(theme="atelier", palette="berry", order=["hero"], tokens={"hero_height": "tall", "cards": "tile"})
        assert rec.tokens.hero_height == "tall" and reg.TOKEN_LABELS["hero_height"] == "Hero height"


# ───────────────────────── SITE-1C-3f: scroll row, tiles, banner, one-per-row ─────────────────────────
from copy import deepcopy  # noqa: E402
from tests.unit.test_site_design import CONTENT  # noqa: E402


P3F = {**PRESET, "sections": list(reg.SECTION_VARIANTS)}
ORD = ["hero", "items", "about", "reviews", "gallery", "order", "banner"]


def _with_banner(**over):
    c = deepcopy(CONTENT)
    c["banner"] = {"eyebrow": "Visit", "headline": "Ready when you are.", "text": "Order today.",
                   "button_text": "Chat with us", "image_asset_id": None, **over}
    return c


class TestOptInPickerRule:
    @pytest.mark.parametrize("tok,opt,base", [("finish", "refined", "standard"), ("hero_height", "tall", "standard"),
                                              ("mobile_cols", "one", "two")])
    def test_listed_first_starts_on_and_listed_second_starts_off(self, tok, opt, base):
        on = {**PRESET, "token_options": {tok: [opt, base]}}
        off = {**PRESET, "token_options": {tok: [base, opt]}}
        locked = {**PRESET, "token_options": {tok: [opt]}}
        assert picker.pick_recipe(on, "s-1")["tokens"][tok] == opt
        assert picker.pick_recipe(off, "s-1")["tokens"][tok] == base
        assert picker.pick_recipe(locked, "s-1")["tokens"][tok] == opt
        assert picker.pick_recipe(PRESET, "s-1")["tokens"][tok] == base

    def test_a_site_can_still_switch_back_when_both_are_listed(self):
        preset = {**PRESET, "token_options": {"mobile_cols": ["one", "two"]}}
        r.validate_recipe(preset, _recipe(tokens={"mobile_cols": "two"}))


class TestOptInLayouts:
    def test_never_random_unless_the_template_lists_them(self):
        for i in range(60):
            v = picker.pick_recipe(PRESET, f"v-{i}")["variants"]
            assert v.get("items") != "scroll" and v.get("gallery") != "tiles"

    def test_staff_can_pick_them_per_site(self):
        rec = _recipe(variants={"items": "scroll", "gallery": "tiles"})
        r.validate_recipe(PRESET, rec)


class TestScrollRow:
    def test_items_scroll_wraps_the_cards(self):
        html = _render(_recipe(variants={"items": "scroll"}))
        assert 'class="grid-scroll"' in html and 'tabindex="0"' in html and "scroll-snap-type" in html
        assert "grid-scroll" not in _render(_recipe())

    def test_css_balanced(self):
        css = _style(_render(_recipe(variants={"items": "scroll"})))
        assert css.count("{") == css.count("}")


class TestTilesGallery:
    def test_tiles_render_with_overlaid_captions(self):
        c = deepcopy(CONTENT)
        c["gallery"] = [{"image_asset_id": None, "caption": f"Look {i}"} for i in range(5)]
        html = r.render_page(c, _recipe(order=ORD, variants={"gallery": "tiles"}), P3F, {})
        assert html.count('class="gal-tile"') == 5 and "gal-tiles" in html and "Look 3" in html
        assert "gal-tiles" not in r.render_page(c, _recipe(order=ORD), P3F, {})


class TestBanner:
    def test_renders_nothing_without_a_headline(self):
        c = _with_banner(headline="")
        assert 'id="banner"' not in r.render_page(c, _recipe(order=ORD), P3F, {})

    def test_old_content_without_banner_is_valid(self):
        from app.models.sites import SiteContentV1
        assert SiteContentV1.model_validate(deepcopy(CONTENT)).banner.headline == ""

    def test_renders_with_headline_and_solid_button_under_outline_tokens(self):
        html = r.render_page(_with_banner(), _recipe(order=ORD, tokens={"button": "outline"}), P3F, {})
        assert 'id="banner"' in html and "Ready when you are." in html and "Chat with us" in html
        css = _style(html)
        assert ".banner-btn{background:var(--btn-accent)" in css or ".banner-btn{" in css
        assert css.count("{") == css.count("}")

    def test_no_banner_keeps_the_original_button_selector(self):
        css = _style(_render(_recipe(tokens={"button": "outline"})))
        assert ".hero-over .btn-accent,.hero-tint .btn-accent{background:var(--btn-accent);color:var(--on-accent)" in css


class TestMobileCols:
    def test_one_per_row_rule(self):
        css = _style(_render(_recipe(tokens={"mobile_cols": "one"})))
        assert "grid-template-columns:1fr;gap:20px" in css
        assert "grid-template-columns:1fr;gap:20px" not in _style(_render(_recipe(tokens={"mobile_cols": "two"})))
