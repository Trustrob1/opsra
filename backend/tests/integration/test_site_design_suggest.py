"""
tests/integration/test_site_design_suggest.py
SITE-1C-2b — "Suggest another design".
  builder: POST /api/v1/builder/sites/{id}/design/suggest  (5 free rounds before go-live, uncapped after)
           POST /api/v1/builder/sites/{id}/design/apply    (free before go-live; counts as an edit once live)
  staff:   POST /api/v1/sites/{id}/design/suggest          (uncapped)
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.routers import builder_portal
from app.services import site_design_service as svc, site_renderer
from tests.funnel_fake_db import FakeDB
from tests.integration.test_sites_design_routes import _org, _preset

ORG = "org-1"
BUILDER = {"id": "b1", "org_id": ORG, "phone_number": "+2348000000001", "full_name": "Ada", "business_name": "Ada Web", "status": "active"}
SECTIONS = ["hero", "about", "items", "reviews", "order"]
CUR = {"theme": "atelier", "palette": "berry", "order": SECTIONS, "hidden": ["reviews"]}
BASE = "/api/v1/builder/sites/site-1/design"


@contextmanager
def _c():
    yield TestClient(app)


def _site(status="preview_ready", **over):
    row = {"id": "site-1", "org_id": ORG, "builder_id": "b1", "preset_id": "p1", "status": status, "deleted_at": None,
           "content": {"items": [{"name": f"i{i}"} for i in range(5)], "reviews": [{"text": "x"}]}, "recipe": dict(CUR),
           "brief": {"personality": "Warm and friendly"}, "revision_count": 0, "design_rolls": 0}
    row.update(over)
    return row


class _Base:
    status = "preview_ready"

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = FakeDB(sites=[_site(self.status)], site_presets=[_preset(sections=SECTIONS)], site_events=[], site_revisions=[],
                         site_assets=[{"id": f"a{i}", "site_id": "site-1"} for i in range(4)], site_care_plans=[], site_builder_settings=[])
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[builder_portal.get_current_builder] = lambda: BUILDER
        app.dependency_overrides[get_current_org] = lambda: _org("owner")
        yield
        for k in (get_supabase, builder_portal.get_current_builder, get_current_org):
            app.dependency_overrides.pop(k, None)

    def site(self):
        return self.db.rows("sites")[0]


class TestBuilderSuggestBeforeLive(_Base):
    def test_returns_valid_new_looks_that_keep_order_and_hidden(self):
        with _c() as c:
            r = c.post(f"{BASE}/suggest")
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["cap"] == svc.DESIGN_SUGGESTION_CAP and d["remaining"] == svc.DESIGN_SUGGESTION_CAP - 1 and d["counts_as_edit"] is False
        assert 2 <= len(d["suggestions"]) <= svc.SUGGESTIONS_PER_ROUND
        preset = _preset(sections=SECTIONS)
        cur_fp = svc.fingerprint(CUR)
        for s in d["suggestions"]:
            site_renderer.validate_recipe(preset, s["recipe"])
            assert s["recipe"]["order"] == SECTIONS and s["recipe"]["hidden"] == ["reviews"]
            assert s["fingerprint"] != cur_fp and s["summary"]

    def test_each_round_gives_different_looks(self):
        with _c() as c:
            a = {s["fingerprint"] for s in c.post(f"{BASE}/suggest").json()["data"]["suggestions"]}
            b = {s["fingerprint"] for s in c.post(f"{BASE}/suggest").json()["data"]["suggestions"]}
        assert a != b

    def test_sixth_round_is_refused_with_a_clear_code(self):
        with _c() as c:
            for _ in range(svc.DESIGN_SUGGESTION_CAP):
                assert c.post(f"{BASE}/suggest").status_code == 200
            r = c.post(f"{BASE}/suggest")
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "DESIGN_SUGGEST_LIMIT"

    def test_brand_colour_is_kept(self):
        self.site()["recipe"] = {**CUR, "palette": None, "custom_colour": "#1A7F5A"}
        with _c() as c:
            sug = c.post(f"{BASE}/suggest").json()["data"]["suggestions"]
        assert sug and all(s["recipe"]["custom_colour"] == "#1A7F5A" for s in sug)

    def test_other_builders_site_is_404(self):
        self.site()["builder_id"] = "someone-else"
        with _c() as c:
            assert c.post(f"{BASE}/suggest").status_code == 404


class TestBuilderApplyBeforeLive(_Base):
    def test_apply_saves_for_free_and_snapshots(self):
        with _c() as c:
            pick = c.post(f"{BASE}/suggest").json()["data"]["suggestions"][0]["recipe"]
            r = c.post(f"{BASE}/apply", json={"recipe": pick})
        assert r.status_code == 200, r.text
        assert svc.fingerprint(self.site()["recipe"]) == svc.fingerprint(pick) and self.site()["design_rolls"] == 1
        assert self.db.rows("site_revisions") and self.db.rows("site_care_plans") == []
        ev = [e for e in self.db.rows("site_events") if e["event"] == "design_applied"]
        assert ev and ev[0]["detail"]["counted_as_edit"] is False

    def test_apply_rejects_an_invalid_recipe(self):
        with _c() as c:
            assert c.post(f"{BASE}/apply", json={"recipe": {**CUR, "theme": "nope"}}).status_code == 422


class TestBuilderLive(_Base):
    status = "live"

    def test_browsing_is_free_and_uncapped_after_go_live(self):
        with _c() as c:
            for _ in range(svc.DESIGN_SUGGESTION_CAP + 2):
                r = c.post(f"{BASE}/suggest")
                assert r.status_code == 200
        d = r.json()["data"]
        assert d["cap"] is None and d["remaining"] is None and d["counts_as_edit"] is True

    def test_applying_counts_one_edit(self):
        with _c() as c:
            pick = c.post(f"{BASE}/suggest").json()["data"]["suggestions"][0]["recipe"]
            r = c.post(f"{BASE}/apply", json={"recipe": pick})
        assert r.status_code == 200, r.text
        plan = self.db.rows("site_care_plans")[0]
        assert plan["free_edits_used"] == 1
        assert [e for e in self.db.rows("site_events") if e["event"] == "design_applied"][0]["detail"]["counted_as_edit"] is True

    def test_two_applies_in_one_session_count_once(self):
        with _c() as c:
            sug = c.post(f"{BASE}/suggest").json()["data"]["suggestions"]
            c.post(f"{BASE}/apply", json={"recipe": sug[0]["recipe"]})
            c.post(f"{BASE}/apply", json={"recipe": sug[1]["recipe"]})
        assert self.db.rows("site_care_plans")[0]["free_edits_used"] == 1

    def test_out_of_edits_gives_402_and_changes_nothing(self):
        from app.services import site_care_plan_service as cp
        cfg = cp.get_config({})
        self.db.rows("site_care_plans").append({"id": "cp1", "org_id": ORG, "site_id": "site-1", "free_edits_used": cfg["free_edits"],
                                                "plan_edits_used": 0, "extra_edits": 0, "created_at": "2026-01-01T00:00:00+00:00"})
        before = dict(self.site()["recipe"])
        with _c() as c:
            pick = c.post(f"{BASE}/suggest").json()["data"]["suggestions"][0]["recipe"]
            r = c.post(f"{BASE}/apply", json={"recipe": pick})
        assert r.status_code == 402 and r.json()["detail"]["code"] == "EDIT_LIMIT_REACHED"
        assert self.site()["recipe"] == before and not self.db.rows("site_revisions")


class TestStaffSuggest(_Base):
    def test_uncapped_and_valid(self):
        with _c() as c:
            for _ in range(svc.DESIGN_SUGGESTION_CAP + 2):
                r = c.post("/api/v1/sites/site-1/design/suggest")
                assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["cap"] is None and d["suggestions"] and d["counts_as_edit"] is False
