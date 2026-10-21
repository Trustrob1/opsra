"""
tests/integration/test_host_portal_routes.py
HOST-1 - routers/host_portal.py (prefix /api/v1/builder/host). The service has its own unit tests
(tests/unit/test_host_site_service.py); these check the HTTP side: sign-in required, the switch, upload
parsing and size limits, and how refusals reach the browser.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from app.services import host_site_service as host
from app.services import site_import_service as imp

BUILDER = {"id": "b1", "org_id": "org-1", "phone_number": "+2348000000001", "full_name": "Ada", "status": "active"}
ON = {"org_id": "org-1", "enabled": True, "site_import_enabled": True, "host_only_enabled": True, "site_import_max_zip_mb": 1}
URL = "/api/v1/builder/host"


def _chain(data):
    result = MagicMock()
    result.data = data
    m = MagicMock()
    for method in ("select", "insert", "update", "delete", "eq", "neq", "is_", "order", "range", "limit", "maybe_single", "in_"):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db(settings):
    db = MagicMock()
    db.table.side_effect = lambda name: _chain([settings] if name == "site_builder_settings" and settings else [])
    return db


@pytest.fixture
def client():
    original = app.dependency_overrides.copy()
    host._upload_hits.clear()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def signed_in(settings=ON):
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: BUILDER
    app.dependency_overrides[get_supabase] = lambda: _db(settings)


def post_file(client, content=b"PK-zip", name="site.zip", **data):
    return client.post(f"{URL}/upload", files={"file": (name, content, "application/zip")}, data=data)


class TestSignInAndSwitch:
    @pytest.mark.parametrize("method,path", [("get", "/config"), ("get", "/sites"), ("post", "/upload"),
                                             ("get", "/sites/s1/report"), ("get", "/sites/s1/preview")])
    def test_needs_a_builder_session(self, client, method, path):
        app.dependency_overrides[get_supabase] = lambda: _db(ON)
        assert getattr(client, method)(f"{URL}{path}").status_code == 401

    def test_config_works_even_when_off(self, client):
        signed_in({**ON, "host_only_enabled": False})
        r = client.get(f"{URL}/config")
        assert r.status_code == 200 and r.json()["data"]["enabled"] is False

    @pytest.mark.parametrize("path", ["/sites", "/sites/s1/report", "/sites/s1/preview"])
    def test_off_means_403(self, client, path):
        signed_in({**ON, "host_only_enabled": False})
        assert client.get(f"{URL}{path}").status_code == 403

    def test_upload_off_means_403(self, client):
        signed_in({**ON, "site_import_enabled": False})
        assert post_file(client).status_code == 403


class TestUpload:
    def test_success_passes_the_form_through(self, client, monkeypatch):
        seen = {}

        def fake(db, builder, data, filename, **kw):
            seen.update(data=data, filename=filename, **kw)
            return {"saved": True, "message": "Your site is ready to preview.", "site": {"id": "s1"}}
        monkeypatch.setattr(host, "upload", fake)
        signed_in()
        r = client.post(f"{URL}/upload", files={"file": ("shop.zip", b"PKdata", "application/zip")},
                        data={"name": "Adaeze", "dry_run": "false"})
        assert r.status_code == 200 and r.json()["data"]["site"]["id"] == "s1"
        assert seen["filename"] == "shop.zip" and seen["data"] == b"PKdata" and seen["name"] == "Adaeze"
        assert seen["site_id"] is None and seen["dry_run"] is False

    def test_dry_run_and_site_id(self, client, monkeypatch):
        seen = {}
        monkeypatch.setattr(host, "upload", lambda db, b, d, f, **kw: seen.update(kw) or {"saved": False, "report": {}})
        signed_in()
        r = post_file(client, site_id="s7", dry_run="true")
        assert r.status_code == 200 and seen["site_id"] == "s7" and seen["dry_run"] is True

    def test_refused_scan_returns_plain_errors(self, client, monkeypatch):
        def refuse(*a, **k):
            raise imp.ImportRejected(["js/app.js: eval is not allowed", "run.exe: this file type is not allowed"], {"ok": False})
        monkeypatch.setattr(host, "upload", refuse)
        signed_in()
        r = post_file(client)
        d = r.json()["detail"]
        assert r.status_code == 422 and d["errors"][0].startswith("js/app.js") and d["report"] == {"ok": False}

    def test_host_error_status_is_kept(self, client, monkeypatch):
        def full(*a, **k):
            raise host.HostError("limit reached", 403, "ACCESS_LIMIT")
        monkeypatch.setattr(host, "upload", full)
        signed_in()
        r = post_file(client)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "ACCESS_LIMIT"

    def test_storage_failure_is_a_502(self, client, monkeypatch):
        def boom(*a, **k):
            raise imp.ImportFailed("The import could not be saved. Nothing was changed. Try again.")
        monkeypatch.setattr(host, "upload", boom)
        signed_in()
        assert post_file(client).status_code == 502

    def test_empty_file(self, client):
        signed_in()
        assert post_file(client, content=b"").status_code == 422

    def test_file_over_the_limit(self, client, monkeypatch):
        monkeypatch.setattr(host, "upload", lambda *a, **k: pytest.fail("must not be reached"))
        signed_in()
        assert post_file(client, content=b"x" * (1024 * 1024 + 10)).status_code == 413

    def test_rate_limit(self, client, monkeypatch):
        monkeypatch.setattr(host, "rate_limited", lambda *_a, **_k: True)
        signed_in()
        assert post_file(client).status_code == 429

    def test_missing_file(self, client):
        signed_in()
        assert client.post(f"{URL}/upload", data={"name": "x"}).status_code == 422


class TestReadRoutes:
    def test_preview_returns_html(self, client, monkeypatch):
        monkeypatch.setattr(host, "preview_html", lambda db, b, sid, did=None: f"<h1>{sid}</h1>")
        signed_in()
        r = client.get(f"{URL}/sites/s1/preview")
        assert r.status_code == 200 and r.json()["data"]["html"] == "<h1>s1</h1>"

    def test_not_found_maps_to_404(self, client, monkeypatch):
        def nf(*a, **k):
            raise host.HostError("Site not found.", 404, "NOT_FOUND")
        monkeypatch.setattr(host, "report_for", nf)
        signed_in()
        assert client.get(f"{URL}/sites/zz/report").status_code == 404
