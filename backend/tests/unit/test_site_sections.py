"""
tests/unit/test_site_sections.py
---------------------------------
SITE-1C-3 — the optional sections: announcement bar, FAQ, price list, hours & location,
how we work, team and gallery. Renderer, recipe validation, content models, picker.

Pure unit tests: no network, no database.
"""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.models.sites import Recipe, SiteContentV1, SitePresetCreate
from app.routers.sites import _SAMPLE_CONTENT
from app.services import site_design_registry as reg
from app.services import site_design_service as picker
from app.services import site_renderer as r

NEW_SECTIONS = ["announcement", "faq", "menu", "visit", "process", "team", "gallery"]

BASE = {
    "business": {"name": "Bola Bakes", "city": "Ikeja", "tagline": "Cakes", "whatsapp_e164": "+2348012345678",
                 "phone_display": "", "instagram": "", "delivery_note": ""},
    "hero": {"headline": "Fresh cakes daily", "subhead": "Baked in Ikeja.", "image_asset_id": None},
    "about": {"title": "Our story", "body": ["We bake."], "owner": "Bola", "pull_quote": "", "image_asset_id": None},
    "items": [{"name": "Chocolate cake", "desc": "Rich", "price_ngn": 15000, "price_style": "exact", "tag": None, "image_asset_id": None}],
    "categories": [], "reviews": [],
    "hours": [{"days": "Mon-Sat", "time": "8am-6pm"}],
    "location": {"address": "5 Allen Avenue", "landmark": "Beside the bank"},
    "order_section": {"title": "How to order", "steps": ["Message us", "Pay", "Collect"]},
    "seo": {"title": "Bola Bakes", "description": "Cakes"},
}
FULL = {
    **BASE,
    "announcement": {"text": "Closed on Sunday"},
    "faqs": [{"q": "Do you deliver?", "a": "Yes, across Lagos."}, {"q": "Deposit?", "a": "50% upfront."}],
    "menu": [{"name": "Cakes", "lines": [{"name": "Small", "desc": "6 inch", "price_ngn": 8000, "price_style": "exact"},
                                         {"name": "Large", "desc": "", "price_ngn": 20000, "price_style": "from"},
                                         {"name": "Wedding", "desc": "", "price_ngn": 0, "price_style": "on_request"}]},
             {"name": "Extras", "lines": [{"name": "Candles", "desc": "", "price_ngn": 500, "price_style": "exact"}]}],
    "process": {"title": "How we work", "steps": [{"title": "Tell us", "text": "Colours and size."}, {"title": "We bake", "text": ""}]},
    "team": [{"name": "Bola", "role": "Baker", "bio": "Owner.", "image_asset_id": None}, {"name": "Chidi", "role": "", "bio": "", "image_asset_id": None}],
    "gallery": [{"caption": "Birthday", "image_asset_id": None}, {"caption": "", "image_asset_id": None}, {"caption": "Wedding", "image_asset_id": None}],
}
OLD_ORDER = ["hero", "items", "about", "order"]
ALL_ORDER = ["announcement", "hero", "about", "process", "items", "menu", "gallery", "team", "faq", "order", "visit"]
PRESET_OLD = {"key": "bakery", "sections": OLD_ORDER, "allowed_themes": ["atelier", "market", "studio"], "labels": {}, "wa_messages": {}}
PRESET_ALL = {**PRESET_OLD, "sections": ALL_ORDER}
SECTION_MARK = {"faq": 'id="faq"', "menu": 'id="menu"', "visit": 'id="visit"', "process": 'id="process"', "team": 'id="team"',
                "gallery": 'id="gallery"', "announcement": 'class="announce"'}


def _recipe(order=ALL_ORDER, variants=None, **over):
    base = {"theme": "atelier", "palette": "berry", "custom_colour": None, "order": order, "hidden": [], "variants": variants or {}}
    base.update(over)
    return base


def _render(content=FULL, recipe=None, preset=PRESET_ALL):
    return r.render_page(content, recipe or _recipe(), preset, {})


class TestRegistry:
    def test_new_sections_have_layouts_and_the_first_is_the_default(self):
        for sec in NEW_SECTIONS:
            assert sec in reg.SECTION_VARIANTS and len(reg.SECTION_VARIANTS[sec]) >= 1
        assert r.SECTION_VARIANTS is reg.SECTION_VARIANTS

    def test_every_new_section_but_the_bar_has_two_layouts(self):
        for sec in NEW_SECTIONS:
            assert len(reg.SECTION_VARIANTS[sec]) == {"announcement": 1, "gallery": 3}.get(sec, 2)

    def test_the_original_six_are_untouched(self):
        for sec, layouts in {"hero": ("fullbleed", "collage", "centered"), "items": ("grid", "rows", "featured", "scroll"),
                             "about": ("left", "right", "quote"), "reviews": ("cards", "spotlight", "list"),
                             "categories": ("tiles", "chips"), "order": ("steps",)}.items():
            assert reg.SECTION_VARIANTS[sec] == layouts


class TestRendering:
    def test_every_new_section_renders_in_every_layout(self):
        for sec in NEW_SECTIONS:
            for layout in reg.SECTION_VARIANTS[sec]:
                html = _render(recipe=_recipe(variants={sec: layout}))
                assert SECTION_MARK[sec] in html, (sec, layout)

    def test_default_layout_is_used_when_variants_are_null(self):
        # Recipe models serialise unset variants as explicit nulls; the renderer must treat that as "default".
        nulls = {sec: None for sec in NEW_SECTIONS}
        assert _render(recipe=_recipe(variants=nulls)) == _render(recipe=_recipe(variants={}))

    def test_layouts_differ(self):
        for sec in NEW_SECTIONS:
            layouts = reg.SECTION_VARIANTS[sec]
            if len(layouts) > 1:
                assert _render(recipe=_recipe(variants={sec: layouts[0]})) != _render(recipe=_recipe(variants={sec: layouts[1]})), sec

    def test_faq_uses_details_without_script(self):
        html = _render(recipe=_recipe(variants={"faq": "list"}))
        assert "<details" in html and "<summary>Do you deliver?</summary>" in html
        assert "<script" not in html.lower()
        assert "<details" not in _render(recipe=_recipe(variants={"faq": "columns"}))

    def test_menu_prices_follow_price_style(self):
        html = _render()
        assert "N8,000" in html.replace("₦", "N") or "8,000" in html
        assert "From " in html and "Price on request" in html

    def test_visit_shows_hours_address_and_a_directions_link(self):
        html = _render(recipe=_recipe(variants={"visit": "split"}))
        assert "Mon-Sat" in html and "5 Allen Avenue" in html and "Beside the bank" in html
        assert "Ask for directions" in html and "wa.me/2348012345678" in html

    def test_visit_without_an_address_has_no_directions_button(self):
        content = {**FULL, "location": {"address": "", "landmark": ""}}
        html = _render(content)
        assert "Opening hours" in html and "Ask for directions" not in html

    def test_process_numbers_its_steps(self):
        html = _render(recipe=_recipe(variants={"process": "numbered"}))
        assert '<span class="n">1</span><h3>Tell us</h3>' in html and '<span class="n">2</span>' in html

    def test_gallery_masonry_marks_shapes_and_grid_does_not(self):
        assert "ph-gal-t" in _render(recipe=_recipe(variants={"gallery": "masonry"}))
        assert "ph-gal-t" not in _render(recipe=_recipe(variants={"gallery": "grid"}))

    def test_team_and_gallery_use_real_photos_when_uploaded(self):
        content = {**FULL, "team": [{"name": "Bola", "role": "", "bio": "", "image_asset_id": "t1"}],
                   "gallery": [{"caption": "Cake", "image_asset_id": "g1"}]}
        assets = {"t1": {"public_url": "https://cdn.example/t1.jpg"}, "g1": {"public_url": "https://cdn.example/g1.jpg"}}
        html = r.render_page(content, _recipe(), PRESET_ALL, assets)
        assert "https://cdn.example/t1.jpg" in html and "https://cdn.example/g1.jpg" in html

    def test_announcement_always_sits_above_the_menu(self):
        html = _render(recipe=_recipe(order=["hero", "items", "announcement"]))
        assert html.index('class="announce"') < html.index('class="nav-bar"')

    def test_hidden_sections_are_not_rendered(self):
        html = _render(recipe=_recipe(hidden=NEW_SECTIONS))
        for sec in NEW_SECTIONS:
            assert SECTION_MARK[sec] not in html

    @pytest.mark.parametrize("sec, empty", [
        ("announcement", {"announcement": {"text": ""}}), ("faq", {"faqs": []}), ("menu", {"menu": []}),
        ("visit", {"hours": [], "location": {"address": "", "landmark": ""}}), ("process", {"process": {"title": "", "steps": []}}),
        ("team", {"team": []}), ("gallery", {"gallery": []}),
    ])
    def test_a_section_with_no_content_renders_nothing(self, sec, empty):
        assert SECTION_MARK[sec] not in _render({**FULL, **empty})

    def test_rows_missing_their_key_text_are_skipped(self):
        content = {**FULL, "faqs": [{"q": "Only a question", "a": "x"}, {"q": "", "a": "no question"}],
                   "menu": [{"name": "Empty group", "lines": []}]}
        html = _render(content)
        assert "Only a question" in html and "no question" not in html and "Empty group" not in html


class TestFooterAndCompatibility:
    def test_footer_keeps_hours_when_there_is_no_visit_section(self):
        html = _render(recipe=_recipe(order=OLD_ORDER), preset=PRESET_OLD)
        assert 'class="foot"' in html and "Mon-Sat: 8am-6pm" in html and "5 Allen Avenue" in html

    def test_footer_drops_hours_when_the_visit_section_shows_them(self):
        html = _render(recipe=_recipe(order=["hero", "items", "visit"]))
        assert "Mon-Sat: 8am-6pm" not in html and html.count("5 Allen Avenue") == 1

    def test_footer_keeps_hours_when_visit_is_listed_but_hidden_or_empty(self):
        assert "Mon-Sat: 8am-6pm" in _render(recipe=_recipe(order=["hero", "visit"], hidden=["visit"]))

    def test_old_content_without_the_new_keys_still_validates_and_renders(self):
        content = SiteContentV1.model_validate(BASE).model_dump()
        assert content["faqs"] == [] and content["menu"] == [] and content["announcement"]["text"] == ""
        assert r.render_page(content, _recipe(order=OLD_ORDER), PRESET_OLD, {}).startswith("<!doctype html>")

    def test_a_template_offering_new_sections_does_not_change_a_site_that_has_no_content_for_them(self):
        # Old site: its recipe never lists the new sections -> identical to a recipe that lists them all with nothing to show.
        with_all = r.render_page(BASE, _recipe(order=OLD_ORDER + ["faq", "menu", "process", "team", "gallery", "announcement"]), PRESET_ALL, {})
        plain = r.render_page(BASE, _recipe(order=OLD_ORDER), PRESET_ALL, {})
        assert with_all == plain

    def test_pages_without_new_sections_carry_none_of_their_css(self):
        html = r.render_page(BASE, _recipe(order=OLD_ORDER), PRESET_OLD, {})
        for cls in ("announce", "faq-item", "menu-group", "visit-card", "proc-line", "member", "gal-masonry", "hours-list"):
            assert cls not in html, cls

    def test_menu_css_does_not_leak_into_the_older_sections(self):
        # The pruner keeps a rule if ANY class in it is used, so new rules must not reuse old class names.
        css = re.search(r"<style>(.*?)</style>", r.render_page(BASE, _recipe(order=OLD_ORDER), PRESET_OLD, {}), re.S).group(1)
        assert "menu-" not in css and "faq-" not in css


class TestSafety:
    EVIL = '<img src=x onerror=alert(1)>"&'

    def _evil(self):
        return {
            **FULL,
            "announcement": {"text": self.EVIL},
            "faqs": [{"q": self.EVIL, "a": self.EVIL}],
            "menu": [{"name": self.EVIL, "lines": [{"name": self.EVIL, "desc": self.EVIL, "price_ngn": 1, "price_style": "exact"}]}],
            "hours": [{"days": self.EVIL, "time": self.EVIL}],
            "location": {"address": self.EVIL, "landmark": self.EVIL},
            "process": {"title": self.EVIL, "steps": [{"title": self.EVIL, "text": self.EVIL}]},
            "team": [{"name": self.EVIL, "role": self.EVIL, "bio": self.EVIL, "image_asset_id": None}],
            "gallery": [{"caption": self.EVIL, "image_asset_id": None}],
        }

    @pytest.mark.parametrize("layouts", [0, 1])
    def test_every_new_field_is_escaped_and_there_is_no_script(self, layouts):
        variants = {sec: reg.SECTION_VARIANTS[sec][min(layouts, len(reg.SECTION_VARIANTS[sec]) - 1)] for sec in NEW_SECTIONS}
        html = _render(self._evil(), _recipe(variants=variants))
        assert "<img src=x" not in html and "<script" not in html.lower()
        assert html.count("&lt;img src=x onerror") >= 12

    def test_every_look_renders_with_every_section(self):
        for seed in range(40):
            recipe = picker.pick_recipe(PRESET_ALL, f"sec-{seed}")
            r.validate_recipe(PRESET_ALL, recipe)
            html = r.render_page(FULL, recipe, PRESET_ALL, {})
            assert "<script" not in html.lower() and html.startswith("<!doctype html>")

    @pytest.mark.parametrize("token, option", [(t, o) for t, opts in reg.TOKENS.items() for o in opts])
    def test_every_token_option_renders_with_every_section(self, token, option):
        html = _render(recipe=_recipe(theme="market", tokens={token: option}))
        assert "<script" not in html.lower() and 'id="gallery"' in html


class TestRecipeValidation:
    def test_a_section_the_template_does_not_offer_is_rejected(self):
        with pytest.raises(ValueError, match="not offered"):
            r.validate_recipe(PRESET_OLD, _recipe(order=OLD_ORDER + ["faq"]))

    def test_an_offered_section_is_accepted(self):
        r.validate_recipe(PRESET_ALL, _recipe())

    def test_unknown_layout_is_rejected(self):
        with pytest.raises(ValueError, match="unknown variant"):
            r.validate_recipe(PRESET_ALL, _recipe(variants={"faq": "carousel"}))

    def test_layouts_can_be_narrowed_per_template(self):
        preset = {**PRESET_ALL, "allowed_variants": {"gallery": ["grid"]}}
        r.validate_recipe(preset, _recipe(variants={"gallery": "grid"}))
        with pytest.raises(ValueError, match="not allowed"):
            r.validate_recipe(preset, _recipe(variants={"gallery": "masonry"}))

    def test_template_design_fields_accept_the_new_sections_and_layouts(self):
        SitePresetCreate(key="bakery", name="Bakery", sections=ALL_ORDER + ["categories", "reviews"], allowed_themes=["atelier"],
                         allowed_variants={"faq": ["columns"], "team": ["list"]})


class TestModels:
    def _content(self, **over):
        return {**BASE, **over}

    def test_defaults_are_empty(self):
        c = SiteContentV1.model_validate(BASE)
        assert (c.announcement.text, c.faqs, c.menu, c.process.steps, c.team, c.gallery) == ("", [], [], [], [], [])

    @pytest.mark.parametrize("field, value", [
        ("announcement", {"text": "x" * 141}),
        ("faqs", [{"q": "q", "a": "a"}] * 13),
        ("faqs", [{"q": "", "a": "a"}]),
        ("faqs", [{"q": "q", "a": "a" * 601}]),
        ("menu", [{"name": "g", "lines": []}] * 9),
        ("menu", [{"name": "g", "lines": [{"name": "l", "price_ngn": 1}] * 16}]),
        ("menu", [{"name": "g", "lines": [{"name": "l", "price_ngn": 1.234}]}]),
        ("menu", [{"name": "g", "lines": [{"name": "l", "price_ngn": -1}]}]),
        ("process", {"title": "t", "steps": [{"title": "s"}] * 7}),
        ("process", {"title": "t", "steps": [{"title": ""}]}),
        ("team", [{"name": "n"}] * 7),
        ("team", [{"name": "n", "bio": "b" * 301}]),
        ("gallery", [{"caption": "c"}] * 10),
        ("gallery", [{"caption": "c" * 101}]),
    ])
    def test_limits_are_enforced(self, field, value):
        with pytest.raises(ValidationError):
            SiteContentV1.model_validate(self._content(**{field: value}))

    def test_the_maximums_are_accepted(self):
        SiteContentV1.model_validate(self._content(
            faqs=[{"q": "q", "a": "a"}] * 12, menu=[{"name": "g", "lines": [{"name": "l", "price_ngn": 1}] * 15}] * 8,
            process={"title": "t", "steps": [{"title": "s"}] * 6}, team=[{"name": "n"}] * 6, gallery=[{"caption": "c"}] * 9))

    def test_recipe_and_preset_allow_up_to_sixteen_sections(self):
        order = list(reg.SECTION_VARIANTS) + ["hero"] * 3
        Recipe.model_validate({"theme": "atelier", "palette": "berry", "order": order[:16]})
        with pytest.raises(ValidationError):
            Recipe.model_validate({"theme": "atelier", "palette": "berry", "order": order[:16] + ["hero"]})

    def test_recipe_variants_accept_the_new_keys(self):
        rec = Recipe.model_validate({"theme": "atelier", "palette": "berry", "order": ["faq"], "variants": {"faq": "columns", "gallery": "masonry"}})
        assert rec.variants.faq == "columns" and rec.variants.gallery == "masonry"

    def test_sample_content_for_template_previews_is_valid_and_fills_every_new_section(self):
        c = SiteContentV1.model_validate(_SAMPLE_CONTENT)
        assert c.announcement.text and c.faqs and c.menu and c.process.steps and c.team and c.gallery and c.hours
        html = r.render_page(_SAMPLE_CONTENT, _recipe(), PRESET_ALL, {})
        for sec in NEW_SECTIONS:
            assert SECTION_MARK[sec] in html


class TestPicker:
    def test_a_template_with_the_new_sections_gets_a_layout_for_each(self):
        recipe = picker.pick_recipe(PRESET_ALL, "abc")
        for sec in ("faq", "menu", "visit", "process", "team", "gallery"):
            assert recipe["variants"][sec] in reg.SECTION_VARIANTS[sec]
        assert "announcement" not in recipe["variants"]

    def test_a_template_without_them_picks_exactly_what_it_picked_before(self, monkeypatch):
        # Adding names to VARIANT_SECTIONS must not move any existing pick (every choice is hashed per axis).
        new = [picker.pick_recipe(PRESET_OLD, f"site-{i}") for i in range(40)]
        monkeypatch.setattr(picker, "VARIANT_SECTIONS", ("hero", "items", "about", "reviews", "categories"))
        old = [picker.pick_recipe(PRESET_OLD, f"site-{i}") for i in range(40)]
        assert new == old

    def test_the_picker_respects_narrowed_layouts_for_new_sections(self):
        preset = {**PRESET_ALL, "allowed_variants": {"gallery": ["masonry"], "faq": ["columns"]}}
        for i in range(30):
            recipe = picker.pick_recipe(preset, f"n-{i}")
            assert recipe["variants"]["gallery"] == "masonry" and recipe["variants"]["faq"] == "columns"

    def test_describe_handles_the_new_layouts(self):
        assert isinstance(picker.describe(picker.pick_recipe(PRESET_ALL, "d")), str)
