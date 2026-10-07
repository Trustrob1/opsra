"""
tests/integration/test_sites_import_routes.py
----------------------------------------------
SITE-IMPORT 1a - the staff import routes in routers/sites.py over real HTTP paths through
TestClient + in-memory FakeDB (Pattern 3 / 32): roles, the import switch, dry run, rejection with the report,
the `accepted` override, upload size cap, org scoping and the audit event.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from tests.funnel_fake_db import FakeDB

ORG, OTHER = "org-1", "org-2"
USER = "22222222-2222-2222-2222-222222222222"
BASE = "/api/v1/sites"
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
PAGE = ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'><title>S</title>"
        "<link rel=stylesheet href='css/s.css'></head><body><h1>Hi</h1><img src='img/h.jpg'><script src='js/a.js'></script></body></html>")
GOOD = {"index.html": PAGE, "css/s.css": "body{margin:0}", "js/a.js": "document.title='x';", "img/h.jpg": JPG}


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


class _Bucket:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload(self, path, file, file_options=None):
        self.store[(self.name, path)] = file

    def remove(self, paths):
        for p in paths:
            self.store.pop((self.name, p), None)


class _Storage:
    def __init__(self):
        self.files = {}

    def from_(self, name):
        return _Bucket(self.files, name)


def _org(template="owner", org_id=ORG):
    return {"id": USER, "org_id": org_id, "roles": {"template": template}}


def _seed(enabled=True, import_enabled=True, **site_over):
    site = {"id": "site-1", "org_id": ORG, "preset_id": "p1", "client_business_name": "Adaeze Styles",
            "slug": "adaeze-styles-abc123", "status": "preview_ready", "tier": "standard", "current_design_id": None,
            "deleted_at": None, "content": {}, "recipe": {}}
    site.update(site_over)
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": enabled, "site_import_enabled": import_enabled,
                                "site_import_allowed_hosts": ["cdn.jsdelivr.net"], "site_import_max_zip_mb": 1}],
        sites=[site], site_presets=[{"id": "p1", "org_id": ORG}], site_designs=[], site_events=[], site_assets=[])
    db.storage = _Storage()
    return db


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

    def post(self, files=None, site_id="site-1", **form):
        c = TestClient(app)
        body = make_zip(files or GOOD)
        return c.post(f"{BASE}/{site_id}/import", files={"file": ("site.zip", body, "application/zip")}, data=form)


class TestImportRoute(_Base):
    def test_import_saves_a_staged_design_and_an_event(self):
        r = self.post()
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["saved"] and data["version"] == 1 and data["files"] == 4
        rows = self.db.tables["site_designs"]
        assert len(rows) == 1 and rows[0]["kind"] == "import" and rows[0]["staged"] is True and rows[0]["org_id"] == ORG
        ev = [e for e in self.db.tables["site_events"] if e["event"] == "site_imported"]
        assert len(ev) == 1 and ev[0]["actor"] == f"user:{USER}" and ev[0]["detail"]["version"] == 1
        assert any(b == "site-import-files" for (b, _p) in self.db.storage.files)
        site = self.db.tables["sites"][0]
        assert site["tier"] == "standard" and site["current_design_id"] is None

    def test_dry_run_saves_nothing(self):
        r = self.post(dry_run="true")
        assert r.status_code == 200 and r.json()["data"]["saved"] is False and r.json()["data"]["report"]["ok"]
        assert self.db.tables["site_designs"] == [] and self.db.storage.files == {}

    def test_rejection_returns_422_with_errors_and_report(self):
        bad = {**GOOD, "js/a.js": "document.cookie='a=1'"}
        r = self.post(bad)
        assert r.status_code == 422
        d = r.json()["detail"]
        assert d["code"] == "VALIDATION_ERROR" and d["report"]["errors"][0]["rule"] == "document_cookie"
        assert "js/a.js" in d["errors"][0]
        assert self.db.tables["site_designs"] == [] and self.db.storage.files == {}

    def test_accepted_override_lets_an_overridable_finding_through(self):
        files = {**GOOD, "js/a.js": "eval('1')"}
        assert self.post(files).status_code == 422
        r = self.post(files, accepted=json.dumps({"js/a.js": ["eval"]}))
        assert r.status_code == 200 and r.json()["data"]["report"]["accepted"][0]["rule"] == "eval"
        ev = [e for e in self.db.tables["site_events"] if e["event"] == "site_imported"][0]
        assert ev["detail"]["accepted"][0]["file"] == "js/a.js"

    def test_a_non_overridable_finding_cannot_be_accepted(self):
        r = self.post({**GOOD, "js/a.js": "document.cookie='a'"}, accepted=json.dumps({"js/a.js": ["document_cookie"]}))
        assert r.status_code == 422

    @pytest.mark.parametrize("bad", ["not json", "[1,2]", '{"a": "eval"}'])
    def test_bad_accepted_field(self, bad):
        assert self.post(accepted=bad).status_code == 422

    def test_upload_over_the_cap_is_413(self):
        c = TestClient(app)
        big = b"PK" + b"0" * (2 * 1024 * 1024)       # the test org's cap is 1 MB
        r = c.post(f"{BASE}/site-1/import", files={"file": ("big.zip", big, "application/zip")})
        assert r.status_code == 413 and self.db.tables["site_designs"] == []

    def test_two_pages_rejected_with_a_plain_message(self):
        r = self.post({**GOOD, "about.html": PAGE})
        assert r.status_code == 422 and "Only one page" in r.json()["detail"]["message"]

    def test_unknown_site_is_404_and_other_orgs_site_is_hidden(self):
        assert self.post(site_id="nope").status_code == 404
        self.db.tables["sites"][0]["org_id"] = OTHER
        assert self.post().status_code == 404

    def test_second_import_is_version_two_and_report_route_returns_it(self):
        self.post()
        assert self.post().json()["data"]["version"] == 2
        r = TestClient(app).get(f"{BASE}/site-1/import/report")
        assert r.status_code == 200 and r.json()["data"]["version"] == 2 and r.json()["data"]["report"]["ok"]

    def test_report_404_when_nothing_imported(self):
        assert TestClient(app).get(f"{BASE}/site-1/import/report").status_code == 404


class TestImportAccess(_Base):
    def test_import_switch_off_is_403(self):
        self.db = _seed(import_enabled=False)
        assert self.post().status_code == 403

    def test_engine_off_is_404(self):
        self.db = _seed(enabled=False)
        assert self.post().status_code == 404

    @pytest.mark.parametrize("template", ["sales_agent", "support_agent", "finance", "read_only"])
    def test_staff_without_write_role_cannot_import(self, template):
        self.template = template
        assert self.post().status_code == 403
        assert self.db.tables["site_designs"] == []

    def test_read_role_can_read_the_report_but_not_import(self):
        self.post()
        self.template = "ops_manager"
        assert TestClient(app).get(f"{BASE}/site-1/import/report").status_code == 200
