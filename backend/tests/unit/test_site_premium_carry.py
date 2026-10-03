"""SITE-PREMIUM P5-a: a redesign keeps the customer's brand colour and section choices where they fit."""
from __future__ import annotations

from unittest.mock import patch

from app.services import site_premium_carry as carry
from app.services import site_premium_generation_service as gen
from app.services import site_premium_history as hist
from app.services import site_premium_tweaks as tw
from tests.unit.premium_gen_fixtures import ScriptedClaude, good_art_reply, good_build_reply
from tests.unit.test_site_premium_generation import ORG, _row
from tests.unit.test_site_premium_history import premium_db, site
from tests.unit.test_site_premium_render import ASSETS, CONTENT
from tests.unit.test_site_premium_sections import design_with


def full(art=None):
    d = design_with()
    d["art_direction"].update(art or {})
    return d


class TestCarryOver:
    def test_brand_colour_and_section_choices_are_applied(self):
        choices = {"accent": "#C0243B", "colours": {"about": "dark"}, "hidden": ["closing"], "sizes": {"about": "large"}}
        out, report = carry.carry_over(choices, full(), CONTENT, ASSETS, None)
        art = out["art_direction"]
        assert report["accent"] and art["accent_hex"] == "#C0243B" and art["customer_accent"] is True
        assert art["section_colours"] == {"about": "dark"}
        assert art["section_hidden"] == ["closing"] and art["section_size"] == {"about": "large"}
        assert report["skipped"] == []

    def test_sections_the_new_design_does_not_have_are_ignored(self):
        choices = {"colours": {"gallery": "dark"}, "hidden": ["gallery"], "sizes": {"gallery": "small"}}
        out, report = carry.carry_over(choices, full(), CONTENT, ASSETS, None)
        assert out["art_direction"] == full()["art_direction"]
        assert report == {"accent": False, "sections": [], "hidden": [], "sizes": [], "skipped": []}

    def test_a_brand_colour_that_does_not_fit_the_new_page_is_skipped_not_forced(self):
        dark = full()
        dark["tokens"] = {"--accent": "#2F4BFF", "--accent-ink": "#FFFFFF", "--bg": "#0B1020", "--ink": "#F2F4FA"}
        out, report = carry.carry_over({"accent": "#101830"}, dark, CONTENT, ASSETS, None)
        assert not report["accent"] and "brand colour" in report["skipped"]
        assert out["tokens"]["--accent"] == "#2F4BFF"

    def test_one_bad_choice_does_not_block_the_others(self):
        choices = {"colours": {"about": "nonsense"}, "hidden": ["closing"]}
        out, report = carry.carry_over(choices, full(), CONTENT, ASSETS, None)
        assert report["hidden"] == ["closing"] and "about colour" in report["skipped"]

    def test_the_footer_is_never_hidden(self):
        out, report = carry.carry_over({"hidden": ["footer"]}, full(), CONTENT, ASSETS, None)
        assert "footer" not in (out["art_direction"].get("section_hidden") or []) and "footer hidden" in report["skipped"]

    def test_nothing_chosen_changes_nothing(self):
        d = full()
        out, report = carry.carry_over({}, d, CONTENT, ASSETS, None)
        assert out is d and not report["accent"]

    def test_the_note_is_plain_and_only_when_something_was_kept(self):
        assert carry.carried_note(None) is None and carry.carried_note({"accent": False, "sections": []}) is None
        assert "brand colour" in carry.carried_note({"accent": True})
        assert "section choices" in carry.carried_note({"hidden": ["a"]})


class TestCustomerChoices:
    def test_a_colour_the_design_came_with_is_not_a_customer_choice(self):
        db = premium_db()
        db.tables["site_designs"][0]["art_direction"].update(accent_hex="#2F4BFF")
        assert carry.customer_choices(db, ORG, site(db))["accent"] is None

    def test_a_marked_colour_is_carried(self):
        db = premium_db()
        db.tables["site_designs"][0]["art_direction"].update(accent_hex="#c0243b", customer_accent=True)
        assert carry.customer_choices(db, ORG, site(db))["accent"] == "#C0243B"

    def test_an_older_tweak_without_the_mark_is_found_by_looking_back(self):
        db = premium_db()
        _row(db, id="d2", version=2, kind="patch", parent_id="d1", art_direction={"accent_hex": "#C0243B"},
             checks={"tweak": {"changes": {"accent": "#C0243B"}}})
        _row(db, id="d3", version=3, kind="patch", parent_id="d2", art_direction={"accent_hex": "#C0243B"},
             checks={"tweak": {"changes": {"sections": {"about": "dark"}}}})
        db.tables["sites"][0]["current_design_id"] = "d3"
        assert carry.customer_choices(db, ORG, site(db))["accent"] == "#C0243B"

    def test_section_choices_are_read_from_the_live_design(self):
        db = premium_db()
        db.tables["site_designs"][0]["art_direction"].update(section_colours={"about": "dark"}, section_hidden=["faq"], section_size={"about": "small"})
        c = carry.customer_choices(db, ORG, site(db))
        assert c["colours"] == {"about": "dark"} and c["hidden"] == ["faq"] and c["sizes"] == {"about": "small"}


class TestRedesignKeepsChoices:
    def test_a_finished_redesign_carries_the_choices_and_says_so(self):
        db = premium_db()
        d1 = db.tables["site_designs"][0]
        d1["art_direction"].update(accent_hex="#C0243B", customer_accent=True, section_hidden=["closing"])
        row = hist.start_redesign(db, ORG, site(db), "builder:b1")
        with patch("app.routers.sites._render_and_store"):
            out = gen.run_generation(db, row["id"], claude=ScriptedClaude(good_art_reply(), good_build_reply()))
        assert out["outcome"] == "premium_staged"
        saved = [r for r in db.rows("site_designs") if r["id"] == row["id"]][0]
        assert saved["staged"] is True and saved["checks"]["carried"]["hidden"] == ["closing"]
        status = hist.redesign_status(db, ORG, site(db))
        assert status["staged"]["carried_note"] and "checks" not in status["staged"]
        assert site(db)["current_design_id"] == "d1"              # the live site is still untouched

    def test_a_redesign_with_nothing_chosen_has_no_note(self):
        db = premium_db()
        row = hist.start_redesign(db, ORG, site(db), "builder:b1")
        with patch("app.routers.sites._render_and_store"):
            gen.run_generation(db, row["id"], claude=ScriptedClaude(good_art_reply(), good_build_reply()))
        assert hist.redesign_status(db, ORG, site(db))["staged"]["carried_note"] is None

    def test_a_carry_over_bug_never_loses_the_redesign(self):
        db = premium_db()
        row = hist.start_redesign(db, ORG, site(db), "builder:b1")
        with patch("app.routers.sites._render_and_store"), patch.object(carry, "customer_choices", side_effect=RuntimeError("x")):
            out = gen.run_generation(db, row["id"], claude=ScriptedClaude(good_art_reply(), good_build_reply()))
        assert out["ok"] and out["outcome"] == "premium_staged"


class TestTheTweakMarksTheColour:
    def test_choosing_a_colour_marks_it_as_the_customers(self):
        plan = tw.plan_tweak(full(), CONTENT, ASSETS, None, accent="#C0243B")
        assert plan["art_direction"]["customer_accent"] is True
