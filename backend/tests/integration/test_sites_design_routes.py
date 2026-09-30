"""
tests/integration/test_sites_design_routes.py
------------------------------------------------
SITE-1C-1 — the design-variety fields on the staff routes in routers/sites.py, hit over real
HTTP paths through TestClient with an in-memory FakeDB (Pattern 3 / Pattern 32: override
get_supabase and get_current_org, pop the overrides in teardown):

  POST/PATCH /api/v1/sites/presets      allowed_fonts, token_options, default_palettes validation
  POST       /api/v1/sites/presets/{id}/preview   ?seed= (seeded picker) and explicit recipes
  PATCH      /api/v1/sites/{id}/recipe  fonts + tokens saved, and rejected when not allowed
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import site_design_registry as reg
from tests.funnel_fake_db import FakeDB


@contextmanager
def _c():
    """A TestClient WITHOUT the app lifespan (startup hooks are slow and not needed here)."""
    yield TestClient(app)


ORG = "org-1"
OTHER = "org-2"
USER = "22222222-2222-2222-2222-222222222222"
BASE = "/api/v1/sites"
SECTIONS = ["hero", "categories", "items", "about", "reviews", "order"]


def _org(template="owner", org_id=ORG):
    return {"id": USER, "org_id": org_id, "roles": {"template": template}}


def _preset(**over):
    row = {
        "id": "p1", "org_id": ORG, "key": "boutique", "name": "Boutique / Fashion", "sections": SECTIONS, "labels": {},
        "brief_questions": [], "wa_messages": {}, "allowed_themes": ["atelier", "market", "studio"],
        "default_palettes": reg.palettes_for_niche("boutique"), "allowed_fonts": [], "token_options": {},
        "ai_tone": "", "max_items": 40, "is_active": True,
    }
    row.update(over)
    return row


def _site(**over):
    row = {"id": "site-1", "org_id": ORG, "builder_id": None, "preset_id": "p1", "client_business_name": "Adaeze Styles",
           "slug": "adaeze-styles-abc123", "status": "brief_complete", "deleted_at": None, "content": {},
           "recipe": {"theme": "atelier", "palette": "berry", "order": SECTIONS, "hidden": []}, "design_rolls": 0}
    row.update(over)
    return row


class _Base:
    db: FakeDB
    template = "owner"

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = FakeDB(site_presets=[_preset()], sites=[_site()], site_events=[])
        self.template = "owner"
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org(self.template)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def preset_row(self, preset_id="p1"):
        return next(r for r in self.db.rows("site_presets") if r["id"] == preset_id)


def _new_preset(**over):
    body = {"key": "bakery", "name": "Bakery", "sections": ["hero", "items", "order"], "allowed_themes": ["atelier", "studio"],
            "default_palettes": ["berry", "terracotta", "cocoa"], "allowed_fonts": ["playfair_lato", "dmserif_dmsans"],
            "token_options": {"button": ["solid", "outline"], "divider": ["dot"]}}
    body.update(over)
    return body


# ═══════════════════════════ preset create / update ═══════════════════════════

class TestPresetDesignFields(_Base):
    def test_create_stores_fonts_token_options_and_the_wider_palette_list(self):
        pal = reg.palettes_for_niche("boutique")  # 17 palettes: more than the old limit of 10
        with _c() as c:
            r = c.post(f"{BASE}/presets", json=_new_preset(default_palettes=pal))
        assert r.status_code == 201, r.text
        row = self.preset_row(r.json()["data"]["id"])
        assert row["allowed_fonts"] == ["playfair_lato", "dmserif_dmsans"]
        assert row["token_options"] == {"button": ["solid", "outline"], "divider": ["dot"]}
        assert row["default_palettes"] == pal and len(pal) > 10

    def test_create_without_the_new_fields_defaults_to_everything_allowed(self):
        body = _new_preset()
        body.pop("allowed_fonts"); body.pop("token_options")
        with _c() as c:
            r = c.post(f"{BASE}/presets", json=body)
        assert r.status_code == 201, r.text
        row = self.preset_row(r.json()["data"]["id"])
        assert row["allowed_fonts"] == [] and row["token_options"] == {}

    @pytest.mark.parametrize("over,needle", [
        ({"allowed_fonts": ["comic_sans"]}, "font pairing"),
        ({"token_options": {"sparkle": ["on"]}}, "token"),
        ({"token_options": {"button": ["giant"]}}, "option"),
        ({"default_palettes": ["berry", "neon"]}, "palette"),
    ])
    def test_create_rejects_unknown_design_values(self, over, needle):
        with _c() as c:
            r = c.post(f"{BASE}/presets", json=_new_preset(**over))
        assert r.status_code == 422 and needle in r.json()["detail"]["message"].lower()
        assert len(self.db.rows("site_presets")) == 1  # nothing was inserted

    def test_update_narrows_fonts_and_options(self):
        with _c() as c:
            r = c.patch(f"{BASE}/presets/p1", json={"allowed_fonts": ["jakarta_inter"], "token_options": {"radius": ["soft"]}})
        assert r.status_code == 200, r.text
        row = self.preset_row()
        assert row["allowed_fonts"] == ["jakarta_inter"] and row["token_options"] == {"radius": ["soft"]}

    def test_update_can_clear_back_to_everything_allowed(self):
        self.preset_row().update({"allowed_fonts": ["jakarta_inter"], "token_options": {"radius": ["soft"]}})
        with _c() as c:
            assert c.patch(f"{BASE}/presets/p1", json={"allowed_fonts": [], "token_options": {}}).status_code == 200
        assert self.preset_row()["allowed_fonts"] == [] and self.preset_row()["token_options"] == {}

    def test_update_rejects_unknown_values_and_changes_nothing(self):
        before = dict(self.preset_row())
        with _c() as c:
            assert c.patch(f"{BASE}/presets/p1", json={"allowed_fonts": ["nope"]}).status_code == 422
            assert c.patch(f"{BASE}/presets/p1", json={"token_options": {"button": ["giant"]}}).status_code == 422
            assert c.patch(f"{BASE}/presets/p1", json={"default_palettes": ["neon"]}).status_code == 422
        assert self.preset_row() == before

    def test_an_update_that_does_not_mention_design_fields_leaves_them_alone(self):
        self.preset_row().update({"allowed_fonts": ["jakarta_inter"]})
        with _c() as c:
            assert c.patch(f"{BASE}/presets/p1", json={"name": "Boutique 2"}).status_code == 200
        assert self.preset_row()["allowed_fonts"] == ["jakarta_inter"] and self.preset_row()["name"] == "Boutique 2"

    def test_list_returns_the_new_fields(self):
        with _c() as c:
            rows = c.get(f"{BASE}/presets").json()["data"]
        assert rows[0]["allowed_fonts"] == [] and rows[0]["token_options"] == {}

    def test_a_read_only_role_cannot_write_design_fields(self):
        self.template = "admin"
        with _c() as c:
            assert c.post(f"{BASE}/presets", json=_new_preset()).status_code == 403
            assert c.patch(f"{BASE}/presets/p1", json={"allowed_fonts": []}).status_code == 403


# ═══════════════════════════ preview ═══════════════════════════

BODY = {"theme": "atelier", "palette": "berry", "order": SECTIONS, "hidden": []}


class TestPreview(_Base):
    def test_seed_returns_html_and_the_recipe_that_produced_it(self):
        with _c() as c:
            r = c.post(f"{BASE}/presets/p1/preview?seed=abc", json=BODY)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["html"].startswith("<!doctype html>") and "<script" not in data["html"].lower()
        rec = data["recipe"]
        assert rec["fonts"] in reg.FONT_PAIRINGS and set(rec["tokens"]) == set(reg.TOKENS)
        assert reg.FONT_PAIRINGS[rec["fonts"]]["font_url"] in data["html"]

    def test_same_seed_same_look_different_seeds_different_looks(self):
        with _c() as c:
            a1 = c.post(f"{BASE}/presets/p1/preview?seed=abc", json=BODY).json()["data"]["recipe"]
            a2 = c.post(f"{BASE}/presets/p1/preview?seed=abc", json=BODY).json()["data"]["recipe"]
            others = [c.post(f"{BASE}/presets/p1/preview?seed=s{i}", json=BODY).json()["data"]["recipe"] for i in range(8)]
        assert a1 == a2
        assert len({repr(sorted(o.items(), key=str)) for o in others}) >= 6

    def test_seeded_preview_respects_the_presets_narrowing(self):
        self.preset_row().update({"allowed_themes": ["market"], "allowed_fonts": ["poppins_nunito"],
                                  "default_palettes": ["gold"], "token_options": {"button": ["outline"]}})
        with _c() as c:
            for i in range(6):
                rec = c.post(f"{BASE}/presets/p1/preview?seed=n{i}", json=BODY).json()["data"]["recipe"]
                assert rec["theme"] == "market" and rec["fonts"] == "poppins_nunito"
                assert rec["palette"] == "gold" and rec["tokens"]["button"] == "outline"

    def test_without_a_seed_the_posted_recipe_is_used_as_given(self):
        body = {**BODY, "theme": "market", "fonts": "syne_dmsans", "tokens": {"radius": "sharp", "divider": "dot"}}
        with _c() as c:
            r = c.post(f"{BASE}/presets/p1/preview", json=body)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["recipe"]["tokens"]["radius"] == "sharp" and ":root{--r:0;--br:0}" in data["html"]
        assert reg.FONT_PAIRINGS["syne_dmsans"]["font_url"] in data["html"]

    def test_the_old_call_shape_still_works(self):
        with _c() as c:
            r = c.post(f"{BASE}/presets/p1/preview", json=BODY)
        assert r.status_code == 200 and r.json()["data"]["html"].startswith("<!doctype html>")

    def test_a_theme_that_does_not_support_a_token_is_422(self):
        with _c() as c:
            r = c.post(f"{BASE}/presets/p1/preview", json={**BODY, "tokens": {"radius": "pill"}})
        assert r.status_code == 422 and "does not support" in r.json()["detail"]["message"]

    def test_unknown_token_key_is_422(self):
        with _c() as c:
            assert c.post(f"{BASE}/presets/p1/preview", json={**BODY, "tokens": {"sparkle": "on"}}).status_code == 422

    def test_another_orgs_preset_is_404(self):
        self.db.tables["site_presets"].append(_preset(id="p-other", org_id=OTHER))
        with _c() as c:
            assert c.post(f"{BASE}/presets/p-other/preview?seed=x", json=BODY).status_code == 404


# ═══════════════════════════ site recipe ═══════════════════════════

class TestSiteRecipe(_Base):
    def _recipe(self, **over):
        rec = {"theme": "market", "palette": "gold", "fonts": "archivo_worksans", "order": SECTIONS, "hidden": [],
               "tokens": {"radius": "pill", "density": "airy", "button": "outline", "image_style": "arch"}}
        rec.update(over)
        return {"recipe": rec}

    def test_saves_fonts_and_tokens(self):
        with _c() as c:
            r = c.patch(f"{BASE}/site-1/recipe", json=self._recipe())
        assert r.status_code == 200, r.text
        site = self.db.rows("sites")[0]
        assert site["recipe"]["fonts"] == "archivo_worksans" and site["recipe"]["tokens"]["density"] == "airy"
        assert site["recipe"]["tokens"]["divider"] is None and site["design_rolls"] == 1
        assert [e["event"] for e in self.db.rows("site_events")] == ["recipe_updated"]

    def test_an_old_style_recipe_without_fonts_or_tokens_still_saves(self):
        with _c() as c:
            r = c.patch(f"{BASE}/site-1/recipe", json={"recipe": {"theme": "studio", "palette": "sage", "order": SECTIONS, "hidden": []}})
        assert r.status_code == 200, r.text
        assert self.db.rows("sites")[0]["recipe"]["tokens"] is None

    @pytest.mark.parametrize("over", [
        {"fonts": "comic_sans"},
        {"tokens": {"radius": "wobbly"}},
        {"theme": "atelier", "tokens": {"radius": "pill"}},
    ])
    def test_invalid_values_are_422_and_nothing_is_saved(self, over):
        before = dict(self.db.rows("sites")[0])
        with _c() as c:
            r = c.patch(f"{BASE}/site-1/recipe", json=self._recipe(**over))
        assert r.status_code == 422
        assert self.db.rows("sites")[0] == before and self.db.rows("site_events") == []

    def test_the_presets_allowed_fonts_are_enforced(self):
        self.preset_row().update({"allowed_fonts": ["playfair_lato"]})
        with _c() as c:
            assert c.patch(f"{BASE}/site-1/recipe", json=self._recipe(fonts="archivo_worksans")).status_code == 422
            assert c.patch(f"{BASE}/site-1/recipe", json=self._recipe(theme="atelier", fonts="playfair_lato",
                                                                       tokens={"button": "solid"})).status_code == 200

    def test_the_presets_token_options_are_enforced(self):
        self.preset_row().update({"token_options": {"button": ["solid"]}})
        with _c() as c:
            r = c.patch(f"{BASE}/site-1/recipe", json=self._recipe(tokens={"button": "outline"}))
        assert r.status_code == 422 and "not allowed" in r.json()["detail"]["message"]
