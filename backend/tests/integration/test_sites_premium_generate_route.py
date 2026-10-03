"""
tests/integration/test_sites_premium_generate_route.py
-------------------------------------------------------
SITE-PREMIUM P2 - POST /sites/{id}/premium/generate over real HTTP paths through TestClient + in-memory FakeDB
(Pattern 3 / 32). The Celery queue is mocked; the pipeline itself is covered in tests/unit/test_site_premium_generation.py.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_premium_render import CONTENT

ORG = "org-1"
USER = "22222222-2222-2222-2222-222222222222"
URL = "/api/v1/sites/site-1/premium/generate"


@contextmanager
def _c():
    yield TestClient(app)


def _org(template="owner"):
    return {"id": USER, "org_id": ORG, "roles": {"template": template}}


def _seed(premium=True, enabled=True, settings=None, **site_over):
    site = {"id": "site-1", "org_id": ORG, "builder_id": "b1", "preset_id": "p1", "client_business_name": "Adaeze Styles", "slug": "adaeze-abc",
            "status": "preview_ready", "tier": "standard", "current_design_id": None, "deleted_at": None, "content": CONTENT,
            "recipe": {"theme": "atelier"}, "revision_count": 0}
    site.update(site_over)
    return FakeDB(site_builder_settings=[{"org_id": ORG, "enabled": enabled, "premium_enabled": premium, **(settings or {})}],
                  sites=[site], site_presets=[{"id": "p1", "org_id": ORG, "key": "boutique"}], site_designs=[], site_events=[], site_assets=[])


class _Base:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = _seed()
        self.template = "owner"
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org(self.template)
        with patch("app.workers.site_premium_worker.run_premium_generation.apply_async") as q:
            self.queue = q
            yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)


class TestGenerateRoute(_Base):
    def test_accepts_creates_the_row_and_queues_the_job(self):
        with _c() as c:
            r = c.post(URL)
        assert r.status_code == 202, r.text
        data = r.json()["data"]
        row = self.db.rows("site_designs")[0]
        assert data["status"] == "generating" and data["design_id"] == row["id"] and data["version"] == 1
        assert row["status"] == "generating" and row["org_id"] == ORG and row["created_by"] == f"user:{USER}"
        self.queue.assert_called_once()
        assert self.queue.call_args.kwargs["args"] == [row["id"]]
        assert [e["event"] for e in self.db.rows("site_events")] == ["premium_generation_started"]

    def test_the_site_is_untouched_until_the_job_finishes(self):
        with _c() as c:
            c.post(URL)
        site = self.db.rows("sites")[0]
        assert site["tier"] == "standard" and site["current_design_id"] is None

    def test_second_request_while_one_runs_is_a_409(self):
        with _c() as c:
            assert c.post(URL).status_code == 202
            r = c.post(URL)
        assert r.status_code == 409 and self.queue.call_count == 1

    def test_premium_off_is_403(self):
        self.db = _seed(premium=False)
        with _c() as c:
            assert c.post(URL).status_code == 403
        assert self.queue.call_count == 0 and not self.db.rows("site_designs")

    def test_site_engine_off_is_404(self):
        self.db = _seed(enabled=False)
        with _c() as c:
            assert c.post(URL).status_code == 404

    def test_unknown_site_is_404(self):
        with _c() as c:
            assert c.post("/api/v1/sites/nope/premium/generate").status_code == 404

    def test_read_only_roles_cannot_start_a_design(self):
        self.template = "admin"
        with _c() as c:
            assert c.post(URL).status_code == 403

    def test_site_without_content_is_422(self):
        self.db = _seed(content={})
        with _c() as c:
            assert c.post(URL).status_code == 422
        assert self.queue.call_count == 0

    def test_per_builder_daily_cap_is_429(self):
        self.db = _seed(settings={"site_premium_daily_per_builder": 1})
        self.db.tables["site_designs"].append({"id": "d0", "org_id": ORG, "site_id": "site-1", "version": 1, "kind": "generate", "status": "failed",
                                               "cost_usd": 0, "created_at": datetime.now(timezone.utc).isoformat()})
        with _c() as c:
            r = c.post(URL)
        assert r.status_code == 429 and "1 Premium" in r.json()["detail"]["message"]
        assert self.queue.call_count == 0

    def test_org_cost_cap_is_429_and_alerts_managers_once(self):
        self.db = _seed(settings={"site_premium_daily_cost_cap": 1})
        self.db.tables["site_designs"].append({"id": "d0", "org_id": ORG, "site_id": "other", "version": 1, "kind": "generate", "status": "ready",
                                               "cost_usd": 2, "created_at": datetime.now(timezone.utc).isoformat()})
        with patch("app.services.funnel_service._get_manager_ids", return_value=["m1"]), \
             patch("app.routers.push_notifications.send_push_notification") as push, _c() as c:
            r1, r2 = c.post(URL), c.post(URL)
        assert r1.status_code == 429 and r2.status_code == 429 and "paused" in r1.json()["detail"]["message"]
        assert push.call_count == 1 and self.queue.call_count == 0

    def test_queue_down_marks_the_row_failed_and_does_not_block_the_site(self):
        self.queue.side_effect = ConnectionError("redis down")
        with _c() as c:
            r = c.post(URL)
        assert r.status_code == 503
        assert self.db.rows("site_designs")[0]["status"] == "failed"
        self.queue.side_effect = None
        with _c() as c:
            assert c.post(URL).status_code == 202

    def test_other_orgs_site_is_not_reachable(self):
        self.db = _seed()
        self.db.tables["sites"][0]["org_id"] = "org-2"
        with _c() as c:
            assert c.post(URL).status_code == 404

    def test_the_new_version_shows_in_the_designs_list_with_its_status(self):
        with _c() as c:
            c.post(URL)
            r = c.get("/api/v1/sites/site-1/premium/designs")
        assert r.status_code == 200
        assert [d["status"] for d in r.json()["data"]["designs"]] == ["generating"]
