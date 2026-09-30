"""
tests/integration/test_sites_personality_flow.py
SITE-1C-2 — allowed_variants on the preset routes, the personality question in the web form and
the WhatsApp chat, and site_copy_service picking a look (personality, recent looks, AI choice,
design_pick event). In-memory FakeDB; the AI call is patched.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import site_copy_service, site_design_registry as reg, site_design_service as svc, site_renderer
from tests.funnel_fake_db import FakeDB
from tests.integration.test_sites_design_routes import BASE, ORG, SECTIONS, _new_preset, _org, _preset, _site


@contextmanager
def _c():
    yield TestClient(app)


class _Base:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = FakeDB(site_presets=[_preset()], sites=[_site()], site_events=[])
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org("owner")
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)


class TestAllowedVariantsRoutes(_Base):
    def test_create_and_patch_store_allowed_variants(self):
        with _c() as c:
            r = c.post(f"{BASE}/presets", json=_new_preset(allowed_variants={"hero": ["centered"], "items": ["grid", "rows"]}))
            assert r.status_code == 201, r.text
            row = next(x for x in self.db.rows("site_presets") if x["id"] == r.json()["data"]["id"])
            assert row["allowed_variants"] == {"hero": ["centered"], "items": ["grid", "rows"]}
            r2 = c.patch(f"{BASE}/presets/p1", json={"allowed_variants": {"about": ["quote"]}})
            assert r2.status_code == 200, r2.text
        assert next(x for x in self.db.rows("site_presets") if x["id"] == "p1")["allowed_variants"] == {"about": ["quote"]}

    @pytest.mark.parametrize("bad", [{"nope": ["x"]}, {"hero": ["nope"]}])
    def test_bad_allowed_variants_are_rejected(self, bad):
        with _c() as c:
            assert c.post(f"{BASE}/presets", json=_new_preset(allowed_variants=bad)).status_code == 422
            assert c.patch(f"{BASE}/presets/p1", json={"allowed_variants": bad}).status_code == 422

    def test_recipe_route_rejects_a_layout_the_template_does_not_allow(self):
        self.db.rows("site_presets")[0]["allowed_variants"] = {"hero": ["centered"]}
        recipe = {"theme": "atelier", "palette": "berry", "order": SECTIONS, "hidden": [], "variants": {"hero": "collage"}}
        with _c() as c:
            assert c.patch(f"{BASE}/site-1/recipe", json={"recipe": recipe}).status_code == 422
            recipe["variants"] = {"hero": "centered"}
            assert c.patch(f"{BASE}/site-1/recipe", json={"recipe": recipe}).status_code == 200


class TestPersonalityQuestion:
    def test_chat_steps_include_it_once_before_photos(self):
        from app.services import site_chat_service
        preset = {"brief_questions": [{"key": "city", "type": "text"}, {"key": "photos", "type": "photos"}]}
        keys = [s["key"] for s in site_chat_service._steps_for_preset(preset)]
        assert keys == ["business_name", "city", "personality", "photos"]

    def test_chat_prompt_lists_the_five_choices(self):
        from app.services import site_chat_service
        text = site_chat_service._question_prompt(reg.personality_question())
        assert text.startswith(reg.PERSONALITY_PROMPT) and "5. " in text and "Elegant and refined" in text


BRIEF = {"business_name": "Adaeze Styles", "city": "Lagos", "story": "We make ankara.", "personality": "Bold and confident",
         "items": [{"name": f"Dress {i}", "price_ngn": 1000 * (i + 1), "desc": ""} for i in range(5)]}


def _gen_db(recipes=()):
    sites = [{"id": "site-1", "org_id": ORG, "builder_id": "b1", "preset_id": "p1", "recipe": None, "created_at": "2026-09-30T09:00:00+00:00"}]
    for i, rec in enumerate(recipes):
        sites.append({"id": f"old-{i}", "org_id": ORG, "builder_id": "b1", "preset_id": "p1", "recipe": rec, "created_at": f"2026-09-29T09:0{i}:00+00:00"})
    assets = [{"id": f"a{i}", "site_id": "site-1", "slot": "photos", "created_at": f"2026-09-30T09:0{i}:00+00:00"} for i in range(4)]
    return FakeDB(sites=sites, site_assets=assets, site_events=[])


def _site_row():
    return {"id": "site-1", "org_id": ORG, "builder_id": "b1", "preset_id": "p1", "brief": BRIEF}


def _copy(design_pick=None):
    d = {"tagline": "T", "hero_headline": "Dressed for Lagos", "hero_subhead": "s", "about_title": "About", "about_body": ["b"],
         "about_pull_quote": "q", "seo_title": "s", "seo_description": "d", "order_section_title": "How to order"}
    if design_pick is not None:
        d["design_pick"] = design_pick
    return json.dumps(d)


PRESET = {**_preset(), "brief_questions": []}


class TestGenerateUsesTheShortlist:
    def test_personality_read_from_the_brief_and_event_logged(self):
        db = _gen_db()
        with patch.object(site_copy_service, "call_claude", return_value=_copy()):
            _content, recipe, source = site_copy_service.generate_content_and_recipe(db, _site_row(), PRESET, ORG)
        assert source == "ai"
        site_renderer.validate_recipe(PRESET, recipe)
        assert recipe["variants"]
        ev = [e for e in db.rows("site_events") if e["event"] == "design_pick"]
        assert len(ev) == 1
        assert ev[0]["detail"]["personality"] == "bold" and ev[0]["detail"]["chosen_by"] == "seed"
        assert ev[0]["detail"]["fingerprint"] == svc.fingerprint(recipe)

    def test_prompt_lists_looks_and_ai_choice_is_honoured(self):
        db = _gen_db()
        seen = {}

        def fake(prompt, **kw):
            seen["prompt"], seen["system"] = prompt, kw.get("system")
            return _copy(design_pick=3)
        with patch.object(site_copy_service, "call_claude", side_effect=fake):
            _c_, recipe, _s = site_copy_service.generate_content_and_recipe(db, _site_row(), PRESET, ORG)
        assert "<looks>" in seen["prompt"] and "3. " in seen["prompt"] and "design_pick" in seen["system"]
        assert "personality: bold" in seen["prompt"]
        short = svc.design_shortlist(PRESET, "site-1", "", "bold", [], {"photos": 4, "items": 5, "reviews": 0})
        assert recipe == short[2]
        assert [e for e in db.rows("site_events") if e["event"] == "design_pick"][0]["detail"]["chosen_by"] == "ai"

    @pytest.mark.parametrize("pick", ["banana", 0, 99, None, -1])
    def test_a_bad_ai_choice_falls_back_to_the_deterministic_pick(self, pick):
        db = _gen_db()
        with patch.object(site_copy_service, "call_claude", return_value=_copy(design_pick=pick)):
            _c_, recipe, _s = site_copy_service.generate_content_and_recipe(db, _site_row(), PRESET, ORG)
        short = svc.design_shortlist(PRESET, "site-1", None, "bold", [], {"photos": 4, "items": 5, "reviews": 0})
        assert recipe == short[0]

    def test_recent_looks_from_the_same_builder_are_avoided(self):
        first = svc.design_shortlist(PRESET, "site-1", None, "bold", [], {"photos": 4, "items": 5, "reviews": 0})[0]
        db = _gen_db(recipes=[first])
        with patch.object(site_copy_service, "call_claude", return_value=_copy()):
            _c_, recipe, _s = site_copy_service.generate_content_and_recipe(db, _site_row(), PRESET, ORG)
        assert svc.fingerprint(recipe) != svc.fingerprint(first)

    def test_ai_failure_still_gives_a_valid_designed_site(self):
        db = _gen_db()
        with patch.object(site_copy_service, "call_claude", side_effect=RuntimeError("boom")):
            _c_, recipe, source = site_copy_service.generate_content_and_recipe(db, _site_row(), PRESET, ORG)
        assert source == "builder_words"
        site_renderer.validate_recipe(PRESET, recipe)

    def test_photo_poor_site_does_not_get_image_hungry_layouts(self):
        db = _gen_db()
        db.rows("site_assets").clear()
        brief = {**BRIEF, "items": BRIEF["items"][:1]}
        with patch.object(site_copy_service, "call_claude", return_value=_copy()):
            _c_, recipe, _s = site_copy_service.generate_content_and_recipe(db, {**_site_row(), "brief": brief}, PRESET, ORG)
        v = recipe["variants"]
        assert v["hero"] != "collage" and v["items"] != "featured" and v["about"] == "quote"

    def test_prompt_without_a_shortlist_is_unchanged(self):
        facts = site_copy_service._factual_fields(BRIEF, [])
        system, prompt = site_copy_service._ai_prompt(facts, PRESET)
        assert "design_pick" not in system and "<looks>" not in prompt


class TestLookStats(_Base):
    def test_counts_sites_and_distinct_looks_per_template(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        a = {"theme": "atelier", "palette": "berry", "order": ["hero"], "hidden": []}
        b = {"theme": "studio", "palette": "sage", "order": ["hero"], "hidden": []}
        self.db.rows("sites").clear()
        for i, rec in enumerate([a, a, b]):
            self.db.rows("sites").append({"id": f"s{i}", "org_id": ORG, "preset_id": "p1", "recipe": rec, "created_at": now})
        self.db.rows("sites").append({"id": "old", "org_id": ORG, "preset_id": "p1", "recipe": b, "created_at": "2020-01-01T00:00:00+00:00"})
        with _c() as c:
            r = c.get(f"{BASE}/presets/look-stats")
        assert r.status_code == 200, r.text
        assert r.json()["data"] == {"p1": {"sites": 3, "distinct": 2, "repeats": 1}}
