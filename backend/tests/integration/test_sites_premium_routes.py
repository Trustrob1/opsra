"""
tests/integration/test_sites_premium_routes.py
-----------------------------------------------
SITE-PREMIUM P1 - the staff Premium routes in routers/sites.py (import, list, restore, back to Standard)
over real HTTP paths through TestClient + in-memory FakeDB (Pattern 3 / 32), plus the public preview and
the export bundle picking up the Premium page.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import site_ops_service as ops
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_premium_render import CONTENT, CSS, SKELETON

ORG, OTHER = "org-1", "org-2"
USER = "22222222-2222-2222-2222-222222222222"
BASE = "/api/v1/sites"
RAW = f"<style>{CSS}</style>{SKELETON}"


@contextmanager
def _c():
    yield TestClient(app)


def _org(template="owner", org_id=ORG):
    return {"id": USER, "org_id": org_id, "roles": {"template": template}}


def _seed(premium=True, enabled=True, **site_over):
    site = {"id": "site-1", "org_id": ORG, "preset_id": "p1", "client_business_name": "Adaeze Styles",
            "slug": "adaeze-styles-abc123", "status": "preview_ready", "tier": "standard", "current_design_id": None,
            "deleted_at": None, "content": CONTENT, "recipe": {"theme": "atelier"}, "revision_count": 0, "preview_expires_at": None}
    site.update(site_over)
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": enabled, "premium_enabled": premium}],
        sites=[site], site_presets=[{"id": "p1", "org_id": ORG}], site_designs=[], site_events=[], site_assets=[],
        site_orders=[])


class _Base:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = _seed()
        self.template = "owner"
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: _org(self.template)
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def import_(self, c, **body):
        return c.post(f"{BASE}/site-1/premium/import", json={"html": RAW, "headline_font": "Outfit",
                                                              "body_font": "Hanken Grotesk", **body})


class TestGating(_Base):
    def test_404_when_site_engine_is_off(self):
        self.db = _seed(enabled=False)
        with _c() as c:
            assert c.get(f"{BASE}/site-1/premium/designs").status_code == 404

    def test_403_when_premium_is_not_switched_on(self):
        self.db = _seed(premium=False)
        with _c() as c:
            r = self.import_(c)
        assert r.status_code == 403 and "not switched on" in r.text
        assert self.db.rows("site_designs") == []

    def test_other_roles_cannot_write(self):
        self.template = "sales_agent"
        with _c() as c:
            assert self.import_(c).status_code == 403

    def test_site_of_another_org_is_a_404(self):
        self.db = _seed(org_id=OTHER)
        with _c() as c:
            assert self.import_(c).status_code == 404


class TestImportRoute(_Base):
    def test_import_makes_the_site_premium_and_refreshes_the_preview(self):
        with _c() as c:
            r = self.import_(c)
        assert r.status_code == 201, r.text
        data = r.json()["data"]
        assert data["version"] == 1 and data["design_id"]
        site = self.db.rows("sites")[0]
        assert site["tier"] == "premium" and site["current_design_id"] == data["design_id"]
        assert "Dressed for the day" in site["rendered_html"] and "PREVIEW" in site["rendered_html"]
        ev = self.db.rows("site_events")
        assert ev and ev[-1]["event"] == "premium_design_imported" and ev[-1]["actor"] == f"user:{USER}"

    def test_rejected_import_is_422_with_reasons_and_changes_nothing(self):
        with _c() as c:
            r = self.import_(c, html=f"<style>{CSS}@import 'x.css';</style>{SKELETON}")
        assert r.status_code == 422 and "@import" in r.text
        assert self.db.rows("site_designs") == [] and self.db.rows("sites")[0]["tier"] == "standard"
        assert self.db.rows("sites")[0].get("rendered_html") is None

    def test_banned_font_is_422(self):
        with _c() as c:
            r = self.import_(c, headline_font="Inter")
        assert r.status_code == 422

    def test_unknown_body_fields_validate(self):
        with _c() as c:
            r = c.post(f"{BASE}/site-1/premium/import", json={"html": "short"})
        assert r.status_code == 422


class TestListUseStandard(_Base):
    def test_list_then_restore_then_standard(self):
        with _c() as c:
            first = self.import_(c).json()["data"]["design_id"]
            second = self.import_(c).json()["data"]["design_id"]
            listing = c.get(f"{BASE}/site-1/premium/designs").json()["data"]
            assert listing["tier"] == "premium" and listing["current_design_id"] == second
            assert [d["version"] for d in listing["designs"]] == [2, 1]
            r = c.post(f"{BASE}/site-1/premium/use-design", json={"design_id": first})
            assert r.status_code == 200 and self.db.rows("sites")[0]["current_design_id"] == first
            r = c.post(f"{BASE}/site-1/premium/use-design", json={"design_id": "0" * 36})
            assert r.status_code == 404

    def test_back_to_standard_keeps_designs(self, monkeypatch):
        from app.services import site_renderer
        monkeypatch.setattr(site_renderer, "render_page", lambda *a, **k: "<html>standard</html>")
        with _c() as c:
            self.import_(c)
            r = c.post(f"{BASE}/site-1/premium/standard")
        assert r.status_code == 200 and self.db.rows("sites")[0]["tier"] == "standard"
        assert self.db.rows("sites")[0]["rendered_html"] == "<html>standard</html>"
        assert len(self.db.rows("site_designs")) == 1
        assert self.db.rows("site_events")[-1]["event"] == "premium_switched_to_standard"


class TestPublicPreviewAndExport(_Base):
    def test_public_preview_serves_the_premium_page(self):
        with _c() as c:
            self.import_(c)
            r = c.get("/s/adaeze-styles-abc123")
        assert r.status_code == 200 and "Dressed for the day" in r.text
        assert "Content-Security-Policy" in r.headers or "content-security-policy" in r.headers

    def test_export_bundle_has_the_premium_index(self):
        with _c() as c:
            self.import_(c)
        files, site, domain = ops.collect_export_files(self.db, ORG, "site-1")
        index = dict(files)["index.html"]
        assert "Dressed for the day" in index and "PREVIEW" not in index and "index, follow" in index


class TestImportScript(_Base):
    def test_check_only_saves_nothing(self):
        import premium_import
        out = premium_import.run(self.db, "site-1", RAW, "Outfit", "Hanken Grotesk", check_only=True)
        assert out["ok"] and out["saved"] is False and out["slots"] > 5
        assert self.db.rows("site_designs") == [] and self.db.rows("sites")[0]["tier"] == "standard"

    def test_import_saves_renders_and_writes_the_preview_file(self, tmp_path):
        import premium_import
        f = tmp_path / "preview.html"
        out = premium_import.run(self.db, "site-1", RAW, None, None, out_path=str(f))
        assert out["saved"] and self.db.rows("sites")[0]["tier"] == "premium"
        assert "Dressed for the day" in f.read_text(encoding="utf-8")
        assert self.db.rows("site_events")[-1]["actor"] == "script:premium_import"

    def test_refuses_when_premium_is_off(self):
        import premium_import
        from app.services.site_premium_service import PremiumNotEnabled
        self.db = _seed(premium=False)
        with pytest.raises(PremiumNotEnabled):
            premium_import.run(self.db, "site-1", RAW)


_HAS_PLAYWRIGHT = __import__("importlib").util.find_spec("playwright") is not None


class TestVisualScripts(_Base):
    def test_visual_flag_reports_in_check_mode(self, tmp_path, monkeypatch):
        if not _HAS_PLAYWRIGHT:
            pytest.skip("playwright not installed")
        import premium_import
        from app.services.site_premium_visual import VisualCheckUnavailable
        monkeypatch.chdir(tmp_path)
        try:
            out = premium_import.run(self.db, "site-1", RAW, "Outfit", "Hanken Grotesk", check_only=True, visual=True)
        except VisualCheckUnavailable:
            pytest.skip("chromium not installed")
        assert out["saved"] is False and "VISUAL CHECK" in out["visual"]
        assert (tmp_path / "premium-checks" / "site-1" / "report.json").exists()
        assert self.db.rows("site_designs") == []

    def test_check_current_design(self, tmp_path):
        if not _HAS_PLAYWRIGHT:
            pytest.skip("playwright not installed")
        import premium_import
        import premium_visual_check
        from app.services.site_premium_visual import VisualCheckUnavailable
        premium_import.run(self.db, "site-1", RAW, "Outfit", "Hanken Grotesk")
        try:
            report = premium_visual_check.run(self.db, "site-1", out_dir=str(tmp_path))
        except VisualCheckUnavailable:
            pytest.skip("chromium not installed")
        assert report["info"]["source"].startswith("current design version 1")
        assert (tmp_path / "page-390.png").exists() and (tmp_path / "report.json").exists()

    def test_no_current_design_is_explained(self, tmp_path):
        import premium_visual_check
        with pytest.raises(SystemExit) as exc:
            premium_visual_check.build_page(self.db, "site-1")
        assert "no current Premium design" in str(exc.value)

    def test_unknown_site(self):
        import premium_visual_check
        with pytest.raises(SystemExit):
            premium_visual_check.build_page(self.db, "nope")
