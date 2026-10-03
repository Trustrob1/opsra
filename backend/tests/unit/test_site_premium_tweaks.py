"""SITE-PREMIUM P4-2: customer colour and font tweaks (no AI)."""
from __future__ import annotations

import pytest

from app.services import site_premium_checks as checks
from app.services import site_premium_service as premium
from app.services import site_premium_tweaks as tw
from app.services.site_ops_service import NotFound, ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.premium_gen_fixtures import CSS, SKELETON
from tests.unit.test_site_premium_render import ASSETS, CONTENT

ORG = "org-1"
RAW = f"<style>{CSS}</style>{SKELETON}"          # accent #2F4BFF, bg #F5F6F4, ink #0E1B2C, Outfit + Hanken Grotesk


def make_db():
    site = {"id": "site-1", "org_id": ORG, "preset_id": "p1", "status": "preview_ready", "tier": "standard",
            "current_design_id": None, "content": CONTENT, "recipe": {}, "deleted_at": None}
    db = FakeDB(sites=[site], site_designs=[])
    premium.import_skeleton(db, ORG, db.rows("sites")[0], "user:u1", RAW, "Outfit", "Hanken Grotesk", ASSETS)
    return db


def current(db):
    site = db.rows("sites")[0]
    return site, tw.current_design(db, ORG, site)


def tweak(db, **kw):
    site, design = current(db)
    plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", **kw)
    return tw.apply_tweak(db, ORG, site, "builder:b1", design, plan)


class TestColourRules:
    def test_family_for(self):
        assert tw.family_for("#1F4FD8") == "blue"
        assert tw.family_for("#0E8F86") == "green_teal"
        assert tw.family_for("#C0243B") == "red_wine"
        assert tw.family_for("#6D3FD0") == "violet_pink"
        assert tw.family_for("#808080") == "metal"

    def test_accent_problem_reasons(self):
        bg, ink = "#F5F6F4", "#0E1B2C"
        assert tw.accent_problem("#1F4FD8", bg, ink) is None
        assert "#RRGGBB" in tw.accent_problem("blue", bg, ink)
        assert "Tan" in tw.accent_problem("#A67C52", bg, ink)               # brown-gold range
        assert "too close" in tw.accent_problem("#EEF0EC", bg, ink)         # no contrast with the page

    def test_button_text_is_readable_and_never_pure(self):
        for _k, _n, hex_value, _f in tw.ACCENT_SWATCHES:
            ink = tw.pick_accent_ink(hex_value, "#F5F6F4", "#0E1B2C")
            if ink:
                assert checks.contrast_ratio(ink, hex_value) >= 4.5
                assert ink.upper() not in ("#000000", "#FFFFFF")

    def test_swatches_are_never_brown_gold_cream_or_brass(self):
        for _k, _n, hex_value, _f in tw.ACCENT_SWATCHES:
            assert not checks.is_brown_gold(hex_value)
            assert not checks._is_cream(hex_value) and not checks._is_brass(hex_value)


class TestOptions:
    def test_swatch_flags_depend_on_the_designs_background(self):
        _site, design = current(make_db())
        light = {s["key"]: s["ok"] for s in tw.look_options(design, "boutique")["swatches"]}
        assert light["cobalt"] is True
        dark = {**design, "tokens": {**design["tokens"], "--bg": "#101820", "--ink": "#F2F4F6"}}
        dark_flags = tw.look_options(dark, "boutique")["swatches"]
        assert {s["key"]: s for s in dark_flags}["slate"]["ok"] is False
        assert {s["key"]: s for s in dark_flags}["slate"]["reason"]

    def test_fonts_same_group_only_and_never_the_cautioned_ones(self):
        _site, design = current(make_db())
        fo = tw.font_options(design, "boutique")
        assert fo["group"] == "sans" and "Outfit" in fo["headlines"] and "Bricolage Grotesque" in fo["headlines"]
        assert "Bodoni Moda" not in fo["headlines"]                         # a serif: another group
        assert not set(fo["headlines"]) & tw.SWAP_EXCLUDED
        assert set(fo["bodies"]) == {"Hanken Grotesk", "Manrope", "Karla"}

    def test_sample_url_lists_the_offered_fonts(self):
        _site, design = current(make_db())
        url = tw.look_options(design, "boutique")["sample_css_url"]
        assert url.startswith("https://fonts.googleapis.com/css2?") and "Bricolage+Grotesque" in url and url.endswith("display=swap")


class TestPlan:
    def test_accent_change_sets_tokens_and_readable_button_text(self):
        site, design = current(make_db())
        plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", accent="#c0243b")
        assert plan["tokens"]["--accent"] == "#C0243B" and plan["tokens"]["--bg"] == "#F5F6F4"
        assert checks.contrast_ratio(plan["tokens"]["--accent-ink"], "#C0243B") >= 4.5
        assert plan["art_direction"]["accent_hex"] == "#C0243B" and plan["art_direction"]["accent_family"] == "red_wine"
        assert "--accent:#C0243B" in plan["html"]

    def test_font_change_updates_the_page_font_link(self):
        site, design = current(make_db())
        plan = tw.plan_tweak(design, site["content"], ASSETS, "boutique", headline_font="Bricolage Grotesque", body_font="Manrope")
        assert plan["art_direction"]["headline_font"] == "Bricolage Grotesque"
        assert "Bricolage+Grotesque" in plan["html"] and "Manrope" in plan["html"]

    @pytest.mark.parametrize("kw", [
        {"accent": "#A67C52"}, {"accent": "red"}, {"accent": "#F0F2EE"},
        {"headline_font": "Bodoni Moda"},          # another style group
        {"headline_font": "Anton"},                # never a swap target
        {"headline_font": "Not A Font"},
        {"body_font": "DM Sans"},                  # not a pair for a sans headline
        {},                                        # nothing asked for
        {"accent": "#2F4BFF"},                     # already the current colour
    ])
    def test_refused(self, kw):
        site, design = current(make_db())
        with pytest.raises(ValidationFailed):
            tw.plan_tweak(design, site["content"], ASSETS, "boutique", **kw)

    def test_design_without_colour_variables_is_refused(self):
        site, design = current(make_db())
        bare = {**design, "skeleton_css": "body{margin:0}", "tokens": {}}
        with pytest.raises(ValidationFailed):
            tw.plan_tweak(bare, site["content"], ASSETS, "boutique", accent="#1F4FD8")


class TestSaveAndGoBack:
    def test_tweak_saves_a_new_version_and_keeps_the_original(self):
        db = make_db()
        original_id = db.rows("sites")[0]["current_design_id"]
        res = tweak(db, accent="#C0243B")
        rows = {r["id"]: r for r in db.rows("site_designs")}
        new = rows[res["id"]]
        assert new["kind"] == "patch" and new["parent_id"] == original_id and new["version"] == 2
        assert new["skeleton_html"] == rows[original_id]["skeleton_html"] and new["skeleton_css"] == rows[original_id]["skeleton_css"]
        assert new["tokens"]["--accent"] == "#C0243B" and rows[original_id]["tokens"]["--accent"] == "#2F4BFF"
        assert new["created_by"] == "builder:b1" and new["org_id"] == ORG
        assert db.rows("sites")[0]["current_design_id"] == res["id"]

    def test_go_back_restores_the_parent_then_has_nowhere_to_go(self):
        db = make_db()
        original_id = db.rows("sites")[0]["current_design_id"]
        tweak(db, accent="#C0243B")
        site = db.rows("sites")[0]
        tw.restore_previous(db, ORG, site)
        assert db.rows("sites")[0]["current_design_id"] == original_id
        with pytest.raises(NotFound):
            tw.restore_previous(db, ORG, db.rows("sites")[0])

    def test_standard_site_has_nothing_to_tweak(self):
        site = {"id": "s", "org_id": ORG, "tier": "standard", "current_design_id": None}
        with pytest.raises(NotFound):
            tw.current_design(FakeDB(sites=[site], site_designs=[]), ORG, site)

    def test_other_orgs_design_is_not_visible(self):
        db = make_db()
        site = dict(db.rows("sites")[0])
        with pytest.raises(NotFound):
            tw.current_design(db, "org-2", site)

    def test_many_tweaks_never_prune_the_original_full_design(self):
        db = make_db()
        original_id = db.rows("sites")[0]["current_design_id"]
        colours = ["#C0243B", "#1F4FD8", "#0E8F86", "#6D3FD0", "#12804F", "#C2268F"]
        for i in range(14):
            tweak(db, accent=colours[i % len(colours)] if colours[i % len(colours)].upper() != db.rows("site_designs")[-1]["tokens"]["--accent"].upper() else colours[(i + 1) % len(colours)])
        ids = {r["id"] for r in db.rows("site_designs")}
        assert original_id in ids and len(ids) <= premium.KEEP_VERSIONS + premium.KEEP_FULL_DESIGNS
