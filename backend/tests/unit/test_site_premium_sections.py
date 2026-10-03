"""SITE-PREMIUM P4-3a: per-section colours from a fixed set (no AI, no custom hex)."""
from __future__ import annotations

import re

import pytest

from app.services import site_premium_renderer as renderer
from app.services import site_premium_sections as sec
from app.services import site_premium_service as premium
from app.services import site_premium_tweaks as tw
from app.services.site_ops_service import ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.premium_gen_fixtures import CSS, SKELETON
from tests.unit.test_site_premium_render import ASSETS, CONTENT

ORG = "org-1"
RAW = f"<style>{CSS}</style>{SKELETON}"


def design_with(choice=None):
    d = {"skeleton_html": SKELETON, "skeleton_css": CSS,
         "tokens": {"--accent": "#2F4BFF", "--accent-ink": "#FFFFFF", "--bg": "#F5F6F4", "--ink": "#0E1B2C"},
         "art_direction": {"headline_font": "Outfit", "body_font": "Hanken Grotesk"}}
    if choice:
        d["art_direction"]["section_colours"] = choice
    return d


def make_db():
    site = {"id": "site-1", "org_id": ORG, "preset_id": "p1", "status": "preview_ready", "tier": "standard",
            "current_design_id": None, "content": CONTENT, "recipe": {}, "deleted_at": None}
    db = FakeDB(sites=[site], site_designs=[])
    premium.import_skeleton(db, ORG, db.rows("sites")[0], "user:u1", RAW, "Outfit", "Hanken Grotesk", ASSETS)
    return db


class TestModule:
    def test_sections_exclude_hero_and_nav(self):
        names = sec.section_names(SKELETON)
        assert "hero" not in names and "nav" not in names and "about" in names

    def test_palette_is_the_designs_own_colours_without_duplicates(self):
        pal = sec.palette(design_with())
        assert [p["key"] for p in pal] == ["base", "soft", "dark", "brand"]
        assert len({p["hex"] for p in pal}) == len(pal)

    def test_text_is_always_readable_on_every_palette_colour(self):
        d = design_with()
        colours = sec.design_colours(d)
        for p in sec.palette(d):
            text = sec.text_for(p["hex"], colours)
            assert text and sec.contrast(text, p["hex"]) >= 4.5

    def test_no_readable_text_means_no_rule(self):
        assert sec.override_rule("about", "#777777", {"--ink": "#777777", "--bg": "#888888"}) is None

    def test_rule_is_built_only_from_known_parts(self):
        d = design_with()
        rule = sec.override_rule("about", "#0E1B2C", sec.design_colours(d), tuple(sec.painted_classes(CSS)))
        assert rule.startswith(':root [data-section="about"]{background-color:#0E1B2C')
        assert re.fullmatch(r"[^<>\"']*", rule.replace('[data-section="about"]', ""))

    def test_brand_section_inverts_the_buttons(self):
        d = design_with()
        rule = sec.override_rule("about", "#2F4BFF", sec.design_colours(d), ())
        assert "--accent-ink:#2F4BFF" in rule                      # button text becomes the section colour

    def test_painted_classes_only_return_safe_names(self):
        css = ".b{background:#fff}.x{background:linear-gradient(red,blue)}.y{color:red}@media(x){.z{background-color:#000}}"
        assert sec.painted_classes(css) == ["b", "z"]

    def test_override_css_skips_unknown_sections_and_colours(self):
        css = sec.override_css(design_with({"about": "dark", "nope": "dark", "closing": "pink"}))
        assert 'data-section="about"' in css and 'data-section="nope"' not in css and 'data-section="closing"' not in css

    def test_override_css_never_raises(self):
        assert sec.override_css({"art_direction": {"section_colours": "x"}}) == ""
        assert sec.override_css({"art_direction": {"section_colours": {"about": "dark"}}, "skeleton_html": None}) == ""

    def test_choices_merge_and_original_clears(self):
        d = design_with({"about": "dark"})
        assert sec.normalise_choice(d, {"closing": "soft"}) == {"about": "dark", "closing": "soft"}
        assert sec.normalise_choice(d, {"about": "original"}) == {}

    @pytest.mark.parametrize("wanted", [{}, {"hero": "dark"}, {"about": "pink"}, {"missing": "dark"}])
    def test_bad_choices_are_refused(self, wanted):
        with pytest.raises(ValueError):
            sec.normalise_choice(design_with(), wanted)

    def test_options_list_each_section_with_original_first(self):
        opts = sec.section_options(design_with({"about": "dark"}))
        about = next(o for o in opts if o["name"] == "about")
        assert about["current"] == "dark" and about["options"][0]["key"] == "original"
        assert next(o for o in opts if o["name"] == "closing")["current"] == "original"


class TestRenderer:
    def render(self, design):
        return renderer.render_premium_page(content=CONTENT, design=design, assets_by_id=ASSETS, export=False)

    def test_marker_and_rule_only_for_chosen_sections(self):
        html = self.render(design_with({"about": "dark"}))
        assert 'data-section="about"' in html
        assert len(re.findall(r"<[a-z]+ [^>]*data-section=", html)) == 1     # no other marker leaks into the page
        assert ':root [data-section="about"]{background-color:#0E1B2C' in html

    def test_without_a_choice_the_page_is_unchanged(self):
        html = self.render(design_with())
        assert "data-section" not in html

    def test_a_stale_choice_draws_nothing_and_does_not_crash(self):
        html = self.render(design_with({"gone": "dark"}))
        assert "data-section" not in html


class TestPlan:
    def test_plan_stores_the_choice_and_reports_the_change(self):
        db = make_db()
        site = db.rows("sites")[0]
        design = tw.current_design(db, ORG, site)
        plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", section_colours={"about": "dark"})
        assert plan["art_direction"]["section_colours"] == {"about": "dark"}
        assert plan["changes"]["sections"] == {"about": "dark"}
        assert 'data-section="about"' in plan["html"]

    def test_going_back_to_original_removes_the_key(self):
        db = make_db()
        site = db.rows("sites")[0]
        design = tw.current_design(db, ORG, site)
        plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", section_colours={"about": "dark"})
        tw.apply_tweak(db, ORG, site, "builder:b1", design, plan)
        design2 = tw.current_design(db, ORG, site)
        plan2 = tw.plan_tweak(design2, site["content"], ASSETS, "boutique", section_colours={"about": "original"})
        assert "section_colours" not in plan2["art_direction"]
        assert plan2["changes"]["sections"] == {"about": "original"}

    def test_same_choice_is_not_a_change(self):
        db = make_db()
        site = db.rows("sites")[0]
        design = tw.current_design(db, ORG, site)
        plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", section_colours={"about": "dark"})
        tw.apply_tweak(db, ORG, site, "builder:b1", design, plan)
        with pytest.raises(ValidationFailed):
            tw.plan_tweak(tw.current_design(db, ORG, site), site["content"], ASSETS, "boutique", section_colours={"about": "dark"})

    def test_unknown_section_is_refused_in_plain_words(self):
        db = make_db()
        site = db.rows("sites")[0]
        with pytest.raises(ValidationFailed, match="not part of your design"):
            tw.plan_tweak(tw.current_design(db, ORG, site), site["content"], ASSETS, "boutique", section_colours={"zzz": "dark"})

    def test_brand_follows_a_new_accent_in_the_same_change(self):
        db = make_db()
        site = db.rows("sites")[0]
        plan = tw.plan_tweak(tw.current_design(db, ORG, site), site["content"], ASSETS, "boutique",
                             accent="#C0243B", section_colours={"about": "brand"})
        assert "background-color:#C0243B" in plan["html"]

    def test_look_options_include_sections(self):
        db = make_db()
        site = db.rows("sites")[0]
        opts = tw.look_options(tw.current_design(db, ORG, site), "boutique")
        assert any(s["name"] == "about" for s in opts["sections"])


# ---------------------------------------------------------------- P4-3b: show / hide / headline size

def layout_design(hidden=None, size=None):
    d = design_with()
    if hidden:
        d["art_direction"]["section_hidden"] = hidden
    if size:
        d["art_direction"]["section_size"] = size
    return d


class TestLayoutModule:
    def test_hide_and_size_merge_into_the_current_state(self):
        d = layout_design(hidden=["about"], size={"items": "large"})
        hidden, sized = sec.normalise_layout(d, {"closing": {"show": False}, "about": {"show": True}, "items": {"size": "small"}})
        assert hidden == ["closing"] and sized == {"items": "small"}

    def test_normal_size_clears_the_size(self):
        d = layout_design(size={"items": "large"})
        assert sec.normalise_layout(d, {"items": {"size": "normal"}}) == ([], {})

    @pytest.mark.parametrize("wanted", [{}, {"hero": {"show": False}}, {"nope": {"show": False}}, {"footer": {"show": False}},
                                        {"footer": {"size": "large"}}, {"items": {"size": "huge"}}, {"items": {}}, {"items": "hide"},
                                        {"items": {"show": "no"}}])
    def test_bad_layout_changes_are_refused(self, wanted):
        with pytest.raises(ValueError):
            sec.normalise_layout(design_with(), wanted)

    def test_stale_names_are_ignored_not_fatal(self):
        d = layout_design(hidden=["gone", "footer"], size={"gone": "large", "items": "tiny"})
        assert sec.hidden_names(d) == [] and sec.sizes(d) == {}

    def test_size_css_uses_known_numbers_only(self):
        css = sec.size_css(layout_design(size={"items": "large", "about": "small"}))
        assert 'data-section="items"] :where(h1,h2){zoom:1.25' in css and "zoom:0.85" in css

    def test_options_report_visibility_size_and_limits(self):
        opts = {o["name"]: o for o in sec.section_options(layout_design(hidden=["about"], size={"items": "large"}))}
        assert opts["about"]["visible"] is False and opts["items"]["size"] == "large" and opts["closing"]["size"] == "normal"
        assert opts["footer"]["can_hide"] is False and opts["footer"]["can_resize"] is False

    def test_a_colour_that_looks_the_same_as_another_is_not_offered_twice(self):
        d = design_with()
        d["skeleton_css"] = ":root{--accent:#2F4BFF;--accent-ink:#FFFFFF;--bg:#1C1827;--ink:#F5F6F4;--deep:#1B1726}"
        d["tokens"] = {"--accent": "#2F4BFF", "--accent-ink": "#FFFFFF", "--bg": "#1C1827", "--ink": "#F5F6F4"}
        keys = [p["key"] for p in sec.palette(d)]
        assert "base" in keys and "dark" not in keys


NAV_SKELETON = SKELETON.replace('<a class="btn" data-slot-href="whatsapp">Order on WhatsApp</a></header>',
                                '<ul><li><a href="#shop">Shop</a></li><li><a href="#top">Top</a></li></ul>'
                                '<a class="btn" data-slot-href="whatsapp">Order on WhatsApp</a></header>', 1)


class TestLayoutRenderer:
    def render(self, design):
        return renderer.render_premium_page(content=CONTENT, design=design, assets_by_id=ASSETS, export=False)

    def test_a_hidden_section_is_left_out_with_its_links(self):
        d = {**layout_design(hidden=["items"]), "skeleton_html": NAV_SKELETON}
        html = self.render(d)
        assert "The collection" not in html and 'id="shop"' not in html and 'href="#shop"' not in html
        assert 'href="#top"' in html                                   # other links stay
        assert "Ready when you are" in html

    def test_nothing_is_hidden_without_a_choice(self):
        html = self.render({**design_with(), "skeleton_html": NAV_SKELETON})
        assert "The collection" in html and 'href="#shop"' in html

    def test_a_resized_section_keeps_its_marker_and_gets_a_rule(self):
        html = self.render(layout_design(size={"closing": "large"}))
        assert 'data-section="closing"' in html and "zoom:1.25" in html
        assert len(re.findall(r"<[a-z]+ [^>]*data-section=", html)) == 1

    def test_a_stale_hidden_name_does_not_crash(self):
        assert "The collection" in self.render(layout_design(hidden=["gone"]))


class TestLayoutPlan:
    def plan(self, **kw):
        db = make_db()
        site = db.rows("sites")[0]
        design = tw.current_design(db, ORG, site)
        return db, site, design, tw.plan_tweak(design, site["content"], ASSETS, "boutique", **kw)

    def test_hiding_and_sizing_are_stored_and_reported(self):
        _db, _s, _d, plan = self.plan(section_layout={"closing": {"show": False}, "items": {"size": "large"}})
        art = plan["art_direction"]
        assert art["section_hidden"] == ["closing"] and art["section_size"] == {"items": "large"}
        assert plan["changes"]["layout"] == {"closing": {"show": False}, "items": {"size": "large"}}
        assert "Ready when you are" not in plan["html"]

    def test_showing_again_removes_the_key(self):
        db, site, design, plan = self.plan(section_layout={"closing": {"show": False}})
        tw.apply_tweak(db, ORG, site, "builder:b1", design, plan)
        plan2 = tw.plan_tweak(tw.current_design(db, ORG, site), site["content"], ASSETS, "boutique",
                              section_layout={"closing": {"show": True}})
        assert "section_hidden" not in plan2["art_direction"] and "Ready when you are" in plan2["html"]

    def test_no_change_is_refused(self):
        with pytest.raises(ValidationFailed):
            self.plan(section_layout={"closing": {"show": True}})

    def test_the_footer_cannot_be_hidden(self):
        with pytest.raises(ValidationFailed, match="footer"):
            self.plan(section_layout={"footer": {"show": False}})
