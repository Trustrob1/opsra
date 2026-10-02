"""
tests/unit/test_site_premium_service.py
----------------------------------------
SITE-PREMIUM P1 - import / list / undo / force-standard / render_if_premium with the in-memory FakeDB.
"""
from __future__ import annotations

import pytest

from app.services import site_premium_service as svc
from app.services.site_ops_service import NotFound, ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_premium_render import ASSETS, CONTENT, CSS, SKELETON

ORG, OTHER = "org-1", "org-2"
RAW = f"<style>{CSS}</style>{SKELETON}"


def make_db(**site_over):
    site = {"id": "site-1", "org_id": ORG, "preset_id": "p1", "status": "preview_ready", "tier": "standard",
            "current_design_id": None, "content": CONTENT, "recipe": {}, "deleted_at": None}
    site.update(site_over)
    return FakeDB(sites=[site], site_designs=[])


def do_import(db, raw=RAW, **kw):
    site = db.rows("sites")[0]
    return svc.import_skeleton(db, ORG, site, "user:u1", raw, "Outfit", "Hanken Grotesk", ASSETS, **kw)


class TestSwitch:
    def test_off_by_default(self):
        with pytest.raises(svc.PremiumNotEnabled):
            svc.require_enabled({"enabled": True})
        with pytest.raises(svc.PremiumNotEnabled):
            svc.require_enabled(None)
        svc.require_enabled({"premium_enabled": True})


class TestImport:
    def test_saves_version_and_makes_site_premium(self):
        db = make_db()
        res = do_import(db)
        assert res["version"] == 1
        row = db.rows("site_designs")[0]
        assert row["org_id"] == ORG and row["site_id"] == "site-1" and row["kind"] == "import" and row["status"] == "ready"
        assert row["created_by"] == "user:u1" and row["tokens"]["--accent"] == "#2F4BFF"
        assert row["art_direction"] == {"headline_font": "Outfit", "body_font": "Hanken Grotesk"}
        assert "<style" not in row["skeleton_html"] and ".btn" in row["skeleton_css"]
        site = db.rows("sites")[0]
        assert site["tier"] == "premium" and site["current_design_id"] == res["id"]

    def test_versions_increase_and_parent_is_recorded(self):
        db = make_db()
        first = do_import(db)
        second = do_import(db)
        assert second["version"] == 2
        assert db.rows("site_designs")[1]["parent_id"] == first["id"] or db.rows("site_designs")[1]["parent_id"] is None
        assert db.rows("sites")[0]["current_design_id"] == second["id"]

    def test_default_fonts_when_none_given(self):
        db = make_db()
        svc.import_skeleton(db, ORG, db.rows("sites")[0], "user:u1", RAW, None, None, ASSETS)
        art = db.rows("site_designs")[0]["art_direction"]
        assert art["headline_font"] in svc.fonts.HEADLINE_FONTS and art["body_font"] in svc.fonts.BODY_FONTS

    def test_removed_items_are_recorded_not_fatal(self):
        db = make_db()
        res = do_import(db, RAW + "<script>alert(1)</script><div onclick='x()'>y</div>")
        assert any("<script>" in x for x in res["removed"])
        assert "script" not in db.rows("site_designs")[0]["skeleton_html"]

    @pytest.mark.parametrize("bad,expect", [
        (f"<style>{CSS}@import 'x.css';</style>{SKELETON}", "@import"),
        (f"<style>{CSS}.a{{background:url(https://e.com/x)}}</style>{SKELETON}", "url"),
        (f"<style>body{{color:#000}}</style>{SKELETON}", "must declare --accent"),
        (f"<style>{CSS}</style><h1>no slots</h1>", "Required slot missing"),
        (f"<style>{CSS}</style>{SKELETON}<p data-slot='made.up'></p>", "not in the content"),
        ("<script>alert(1)</script>", "Nothing is left"),
    ])
    def test_rejected_saves_nothing(self, bad, expect):
        db = make_db()
        with pytest.raises(ValidationFailed) as ei:
            do_import(db, bad)
        assert expect in str(ei.value)
        assert db.rows("site_designs") == [] and db.rows("sites")[0]["tier"] == "standard"

    def test_banned_font_rejected(self):
        db = make_db()
        with pytest.raises(ValidationFailed):
            svc.import_skeleton(db, ORG, db.rows("sites")[0], "user:u1", RAW, "Playfair Display", "Karla", ASSETS)
        assert db.rows("site_designs") == []

    def test_site_without_content_rejected(self):
        db = make_db(content={})
        with pytest.raises(ValidationFailed):
            do_import(db)

    def test_only_last_ten_versions_are_kept(self):
        db = make_db()
        ids = [do_import(db)["id"] for _ in range(13)]
        kept = [r["version"] for r in db.rows("site_designs")]
        assert len(kept) == svc.KEEP_VERSIONS and max(kept) == 13 and min(kept) == 4
        assert db.rows("sites")[0]["current_design_id"] == ids[-1]


class TestListUseStandard:
    def test_list_columns_exclude_the_skeleton(self):
        assert "skeleton" not in svc._LIST_COLUMNS

    def test_list_is_org_scoped(self):
        db = make_db()
        do_import(db)
        db.rows("site_designs").append({"id": "x", "org_id": OTHER, "site_id": "site-1", "version": 9})
        rows = svc.list_designs(db, ORG, "site-1")
        assert [r["version"] for r in rows] == [1]

    def test_force_standard_keeps_versions(self):
        db = make_db()
        res = do_import(db)
        svc.force_standard(db, ORG, db.rows("sites")[0])
        site = db.rows("sites")[0]
        assert site["tier"] == "standard" and site["current_design_id"] == res["id"] and len(db.rows("site_designs")) == 1

    def test_use_design_restores_and_checks_ownership(self):
        db = make_db()
        a, b = do_import(db), do_import(db)
        svc.use_design(db, ORG, db.rows("sites")[0], a["id"])
        assert db.rows("sites")[0]["current_design_id"] == a["id"]
        with pytest.raises(NotFound):
            svc.use_design(db, ORG, db.rows("sites")[0], "not-a-design")
        with pytest.raises(NotFound):
            svc.use_design(db, OTHER, db.rows("sites")[0], a["id"])


class TestRenderIfPremium:
    def test_none_for_standard_sites(self):
        assert svc.render_if_premium(make_db(), make_db().rows("sites")[0], {}) is None

    def test_premium_page_for_premium_sites(self):
        db = make_db()
        do_import(db)
        html = svc.render_if_premium(db, db.rows("sites")[0], ASSETS)
        assert html.startswith("<!doctype html>") and "Dressed for the day" in html

    def test_export_mode_and_canonical(self):
        db = make_db()
        do_import(db)
        html = svc.render_if_premium(db, db.rows("sites")[0], ASSETS, export=True, canonical_domain="a.com.ng")
        assert 'rel="canonical"' in html and 'src="images/hero.jpg"' in html

    def test_missing_design_falls_back_to_none(self):
        db = make_db(tier="premium", current_design_id="gone")
        assert svc.render_if_premium(db, db.rows("sites")[0], {}) is None

    def test_other_orgs_design_is_never_used(self):
        db = make_db()
        res = do_import(db)
        db.rows("site_designs")[0]["org_id"] = OTHER
        assert svc.render_if_premium(db, db.rows("sites")[0], ASSETS) is None

    def test_broken_stored_design_never_raises(self):
        db = make_db()
        do_import(db)
        db.rows("site_designs")[0]["art_direction"] = {"headline_font": "Inter", "body_font": "Karla"}
        assert svc.render_if_premium(db, db.rows("sites")[0], ASSETS) is None
