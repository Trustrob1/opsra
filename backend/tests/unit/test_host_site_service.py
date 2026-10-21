"""
tests/unit/test_host_site_service.py
------------------------------------
HOST-1 - "Host with Opsra": a builder uploads a site made outside Opsra. Switches, the site made for the upload, what
happens when the scan refuses, replacing files on a paid site, ownership, limits and the free-site count.
In-memory database and storage; no network.
"""
from __future__ import annotations

import pytest

from app.services import host_site_service as host
from app.services import site_access_service
from app.services import site_import_service as imp
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_import_service import GOOD, HOSTS, PAGE, make_zip

ORG = "org-1"
BUILDER = {"id": "b1", "org_id": ORG, "phone_number": "+2348031234567"}
OTHER = {"id": "b2", "org_id": ORG, "phone_number": "+2348039999999"}
PRESET = {"id": "p1", "org_id": ORG, "is_active": True, "name": "Boutique", "key": "boutique",
          "allowed_themes": [], "sections": ["hero", "items", "about", "reviews"]}
ON = {"org_id": ORG, "enabled": True, "site_import_enabled": True, "host_only_enabled": True,
      "site_import_allowed_hosts": HOSTS, "site_import_max_zip_mb": 25}


class _Bucket:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def upload(self, path, file, file_options=None):
        self.db.files[(self.name, path)] = file

    def remove(self, paths):
        for p in paths:
            self.db.files.pop((self.name, p), None)


class _Storage:
    def __init__(self, db):
        self.db = db

    def from_(self, name):
        return _Bucket(self.db, name)


class HostDB(FakeDB):
    def __init__(self, **tables):
        tables.setdefault("site_builder_settings", [ON])
        tables.setdefault("site_presets", [PRESET])
        super().__init__(**tables)
        self.files = {}
        self.storage = _Storage(self)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(host, "_store_render", lambda db, org_id, site: None)
    host._upload_hits.clear()


def zip_bytes(files=None):
    return make_zip(files or GOOD)


def sites(db):
    return [s for s in db.rows("sites") if not s.get("deleted_at")]


class TestSwitches:
    def test_off_by_default(self):
        db = HostDB(site_builder_settings=[{"org_id": ORG, "enabled": True, "site_import_enabled": True}])
        with pytest.raises(host.HostError) as e:
            host.upload(db, BUILDER, zip_bytes(), "s.zip", name="Shop")
        assert e.value.status_code == 403 and sites(db) == []

    def test_needs_the_import_switch_too(self):
        db = HostDB(site_builder_settings=[{**ON, "site_import_enabled": False}])
        with pytest.raises(host.HostError):
            host.upload(db, BUILDER, zip_bytes(), "s.zip", name="Shop")

    def test_config_reports_the_switch_and_limits(self):
        assert host.config(HostDB(), BUILDER)["enabled"] is True
        off = host.config(HostDB(site_builder_settings=[{**ON, "host_only_enabled": False}]), BUILDER)
        assert off["enabled"] is False and off["used"] == 0 and off["max_upload_mb"] == 25


class TestUploadNewSite:
    def test_makes_a_site_and_switches_the_page_on(self):
        db = HostDB()
        out = host.upload(db, BUILDER, zip_bytes(), "adaeze_styles.zip", name="  Adaeze   Styles ")
        assert out["saved"] and out["switched_on"] and out["files"] == 6
        site = sites(db)[0]
        assert site["client_business_name"] == "Adaeze Styles" and site["tier"] == "imported"
        assert site["builder_id"] == "b1" and site["status"] == "preview_ready"
        assert site["current_design_id"] == out["design_id"] and site["preset_id"] == "p1"
        assert site["content"]["business"]["name"] == "Adaeze Styles" and site["recipe"]["order"]
        design = db.rows("site_designs")[0]
        assert design["staged"] is False and design["kind"] == "import" and design["created_by"] == "builder:b1"
        assert out["site"]["has_preview_link"] is True and out["site"]["design"]["version"] == 1
        assert [e["event"] for e in db.rows("site_events")] == ["host_site_created", "host_site_uploaded"]

    def test_name_falls_back_to_the_file_name(self):
        assert host.clean_name("", "my_cool-shop.zip") == "my cool shop"
        assert host.clean_name(None, "index.html") == "My website"
        assert host.clean_name("x" * 300)[:5] == "xxxxx" and len(host.clean_name("x" * 300)) == 120

    def test_single_html_file_works(self):
        db = HostDB()
        out = host.upload(db, BUILDER, PAGE.replace("<script src='js/app.js'></script>", "").replace("<link rel=stylesheet href='css/style.css'>", "").replace("<img src='img/hero.jpg'>", "").encode(), "page.html", name="One page")
        assert out["saved"] and sites(db)[0]["status"] == "preview_ready"

    def test_a_refused_upload_leaves_no_site_behind(self):
        db = HostDB()
        bad = zip_bytes({**GOOD, "run.exe": b"MZ"})
        with pytest.raises(imp.ImportRejected):
            host.upload(db, BUILDER, bad, "s.zip", name="Shop")
        assert sites(db) == [] and db.rows("site_designs") == [] and db.files == {}

    def test_dry_run_saves_nothing(self):
        db = HostDB()
        out = host.upload(db, BUILDER, zip_bytes(), "s.zip", name="Shop", dry_run=True)
        assert out["saved"] is False and out["report"]["ok"] and db.rows("sites") == [] and db.files == {}

    def test_site_limit(self):
        db = HostDB(site_builder_settings=[{**ON, "host_only_max_sites": 1}])
        host.upload(db, BUILDER, zip_bytes(), "a.zip", name="One")
        with pytest.raises(host.HostError) as e:
            host.upload(db, BUILDER, zip_bytes(), "b.zip", name="Two")
        assert e.value.status_code == 403 and len(sites(db)) == 1

    def test_no_template_means_a_clear_error_and_no_site(self):
        db = HostDB(site_presets=[])
        with pytest.raises(host.HostError) as e:
            host.upload(db, BUILDER, zip_bytes(), "s.zip", name="Shop")
        assert e.value.status_code == 503 and sites(db) == []

    def test_a_builder_without_a_phone_still_gets_a_site(self):
        db = HostDB()
        out = host.upload(db, {**BUILDER, "phone_number": None}, zip_bytes(), "s.zip", name="Shop")
        site = sites(db)[0]
        assert out["saved"] and not site.get("content") and out["site"]["has_preview_link"] is False


class TestReplaceFiles:
    def _first(self, db):
        return host.upload(db, BUILDER, zip_bytes(), "s.zip", name="Shop")["site"]["id"]

    def test_new_version_replaces_the_preview(self):
        db = HostDB()
        sid = self._first(db)
        out = host.upload(db, BUILDER, zip_bytes(), "s2.zip", site_id=sid)
        assert out["version"] == 2 and out["switched_on"] and len(sites(db)) == 1
        assert sites(db)[0]["current_design_id"] == out["design_id"]

    @pytest.mark.parametrize("status", ["paid", "publishing", "live", "renewal_due", "lapsed"])
    def test_a_sold_site_is_not_repointed(self, status):
        db = HostDB()
        sid = self._first(db)
        before = sites(db)[0]["current_design_id"]
        db.table("sites").update({"status": status}).eq("id", sid).execute()
        out = host.upload(db, BUILDER, zip_bytes(), "s2.zip", site_id=sid)
        assert out["saved"] and out["switched_on"] is False and "team will publish" in out["message"]
        site = sites(db)[0]
        assert site["current_design_id"] == before and site["status"] == status
        assert [d for d in db.rows("site_designs") if d["id"] == out["design_id"]][0]["staged"] is True

    def test_failed_replace_keeps_the_site(self):
        db = HostDB()
        sid = self._first(db)
        with pytest.raises(imp.ImportRejected):
            host.upload(db, BUILDER, zip_bytes({**GOOD, "x.exe": b"MZ"}), "s2.zip", site_id=sid)
        assert len(sites(db)) == 1 and len(db.rows("site_designs")) == 1

    def test_cannot_touch_another_builders_site(self):
        db = HostDB()
        sid = self._first(db)
        with pytest.raises(host.HostError) as e:
            host.upload(db, OTHER, zip_bytes(), "s2.zip", site_id=sid)
        assert e.value.status_code == 404

    def test_only_uploaded_sites_can_be_replaced(self):
        db = HostDB(sites=[{"id": "s9", "org_id": ORG, "builder_id": "b1", "tier": "standard", "status": "preview_ready"}])
        with pytest.raises(host.HostError, match="not uploaded here"):
            host.upload(db, BUILDER, zip_bytes(), "s.zip", site_id="s9")

    def test_unknown_site(self):
        with pytest.raises(host.HostError) as e:
            host.upload(HostDB(), BUILDER, zip_bytes(), "s.zip", site_id="nope")
        assert e.value.status_code == 404


class TestListAndReports:
    def test_lists_only_my_uploaded_sites(self):
        db = HostDB(sites=[{"id": "std", "org_id": ORG, "builder_id": "b1", "tier": "standard", "status": "live"}])
        host.upload(db, BUILDER, zip_bytes(), "a.zip", name="Mine")
        host.upload(db, OTHER, zip_bytes(), "b.zip", name="Theirs")
        rows = host.list_sites(db, BUILDER)
        assert [r["client_business_name"] for r in rows] == ["Mine"]
        assert rows[0]["design"]["files"] == 6 and rows[0]["design"]["scripts"] == 1 and rows[0]["design"]["active"] is True

    def test_report_belongs_to_the_owner(self):
        db = HostDB()
        sid = host.upload(db, BUILDER, zip_bytes(), "a.zip", name="Mine")["site"]["id"]
        assert host.report_for(db, BUILDER, sid)["report"]["ok"]
        with pytest.raises(host.HostError):
            host.report_for(db, OTHER, sid)

    def test_report_before_any_upload(self):
        db = HostDB(sites=[{"id": "s1", "org_id": ORG, "builder_id": "b1", "tier": "imported", "status": "brief_complete"}])
        with pytest.raises(host.HostError) as e:
            host.report_for(db, BUILDER, "s1")
        assert e.value.status_code == 404

    def test_preview_of_someone_elses_site_is_refused(self):
        db = HostDB()
        sid = host.upload(db, BUILDER, zip_bytes(), "a.zip", name="Mine")["site"]["id"]
        with pytest.raises(host.HostError):
            host.preview_html(db, OTHER, sid)


class TestFreeSiteCount:
    def test_uploaded_sites_use_no_free_slot(self):
        db = HostDB(sites=[
            {"id": "a", "org_id": ORG, "builder_id": "b1", "tier": "standard", "status": "live"},
            {"id": "b", "org_id": ORG, "builder_id": "b1", "tier": None, "status": "live"},
            {"id": "c", "org_id": ORG, "builder_id": "b1", "tier": "imported", "status": "preview_ready"},
            {"id": "d", "org_id": ORG, "builder_id": "b1", "tier": "imported", "status": "live"},
        ])
        assert site_access_service.count_sites(db, ORG, "b1") == 2


class TestRateLimit:
    def test_twenty_an_hour(self):
        assert not any(host.rate_limited("bx") for _ in range(host.UPLOADS_PER_HOUR))
        assert host.rate_limited("bx") is True
        assert host.rate_limited("other-builder") is False
