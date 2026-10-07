"""
tests/integration/test_site_import_1b.py
-----------------------------------------
SITE-IMPORT 1b - rendering an imported design (preview / export), the policy header, publish and export of the file
tree, activation, the staff routes, and copying of external files. In-memory FakeDB + fake storage; no network.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import site_import_render as R
from app.services import site_import_resolve as RES
from app.services import site_import_service as svc
from app.services import site_ops_service, site_publish_service, site_premium_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
USER = "22222222-2222-2222-2222-222222222222"
BASE = "/api/v1/sites"
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PUBLIC = "https://x.supabase.co/storage/v1/object/public/site-import-files"
HOSTS = ["cdn.jsdelivr.net", "fonts.googleapis.com"]
PAGE = ("<!doctype html><html><head><meta charset=utf-8><title>S</title><link rel=stylesheet href='css/s.css'></head>"
        "<body><a href='#top'>Top</a><a href='index.html'>Home</a><img src='img/h.jpg' srcset='img/h.jpg 1x, img/h2.jpg 2x'>"
        "<div style=\"background:url('img/h.jpg')\"></div><img src='https://pics.example/x.jpg'><script src='js/a.js'></script></body></html>")


class _Bucket:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload(self, path, file, file_options=None):
        self.store[(self.name, path)] = file

    def download(self, path):
        if (self.name, path) not in self.store:
            raise RuntimeError("missing")
        return self.store[(self.name, path)]

    def remove(self, paths):
        for p in paths:
            self.store.pop((self.name, p), None)

    def get_public_url(self, path):
        return f"{PUBLIC}/{path}"


class _Storage:
    def __init__(self):
        self.files = {}

    def from_(self, name):
        return _Bucket(self.files, name)


def _files(prefix):
    return [
        {"path": "css/s.css", "stored": True, "storage_path": f"{prefix}/css/s.css"},
        {"path": "js/a.js", "stored": True, "storage_path": f"{prefix}/js/a.js"},
        {"path": "img/h.jpg", "stored": True, "storage_path": f"{prefix}/img/h.jpg"},
        {"path": "img/h2.jpg", "stored": True, "storage_path": f"{prefix}/img/h2.jpg"},
        {"path": "index.html", "stored": False},
    ]


def _seed(tier="standard", current="d1", accepted=None, unknown=None):
    prefix = f"{ORG}/site-1/tok/v1"
    report = {"entry": "index.html", "accepted": accepted or [], "counts": {"files": 5},
              "warnings": [], "scripts": ["js/a.js"], "page": {"inline_scripts": 0},
              "external": {"unknown": unknown if unknown is not None else
                           [{"url": "https://pics.example/x.jpg", "tag": "img", "attr": "src", "kind": "image",
                             "class": "external_unknown", "file": "index.html"}]}}
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "site_import_enabled": True,
                                "site_import_allowed_hosts": HOSTS, "site_import_max_zip_mb": 25}],
        sites=[{"id": "site-1", "org_id": ORG, "preset_id": "p1", "slug": "s-abc", "status": "preview_ready",
                "tier": tier, "current_design_id": current, "deleted_at": None, "content": {"a": 1}, "recipe": {"b": 1}}],
        site_presets=[{"id": "p1", "org_id": ORG}],
        site_designs=[{"id": "d1", "org_id": ORG, "site_id": "site-1", "version": 1, "kind": "import", "status": "ready",
                       "staged": True, "skeleton_html": PAGE, "files_prefix": prefix, "created_at": "2026-10-07T10:00:00Z",
                       "created_by": "user:u", "import_meta": {"report": report, "files": _files(prefix), "filename": "s.zip"}}],
        site_assets=[], site_orders=[{"org_id": ORG, "site_id": "site-1", "domain": "shop.com.ng", "status": "active",
                                      "created_at": "2026-10-07T10:00:00Z"}],
        site_events=[])
    db.storage = _Storage()
    for f in _files(prefix):
        if f["stored"]:
            db.storage.files[("site-import-files", f["storage_path"])] = JPG if f["path"].endswith("jpg") else b"x"
    return db


class TestCsp:
    def test_published_policy_names_self_and_allow_list(self):
        csp = R.build_csp(HOSTS)
        assert "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in csp
        assert "'unsafe-eval'" not in csp and "base-uri 'none'" in csp and "object-src 'none'" in csp
        assert "connect-src 'self'" in csp and "default-src 'none'" in csp

    def test_eval_only_when_staff_accepted_it(self):
        assert "'unsafe-eval'" in R.build_csp(HOSTS, ["eval"])
        assert "'unsafe-eval'" not in R.build_csp(HOSTS, ["web_storage"])

    def test_preview_names_the_storage_origin_not_self(self):
        csp = R.build_csp(HOSTS, preview_origin="https://x.supabase.co")
        assert "'self'" not in csp and "script-src https://x.supabase.co" in csp

    def test_preview_headers_sandbox(self):
        h = R.preview_headers(HOSTS, "https://x.supabase.co")
        assert "sandbox allow-scripts" in h["Content-Security-Policy"] and "allow-same-origin" not in h["Content-Security-Policy"]
        assert h["X-Robots-Tag"] == "noindex, nofollow"

    def test_hostile_host_value_cannot_break_the_policy(self):
        assert "evil" not in R.build_csp(["a.com; script-src https://evil.com"])


class TestRewrite:
    def test_known_files_are_pointed_at_storage_and_others_left(self):
        out = R.rewrite_for_preview(PAGE, ["css/s.css", "js/a.js", "img/h.jpg", "img/h2.jpg"], PUBLIC + "/p")
        assert f"href='{PUBLIC}/p/css/s.css'" in out and f"src='{PUBLIC}/p/js/a.js'" in out
        assert f"{PUBLIC}/p/img/h.jpg 1x, {PUBLIC}/p/img/h2.jpg 2x" in out
        assert f"url('{PUBLIC}/p/img/h.jpg')" in out
        assert "href='#top'" in out and "href='index.html'" in out and "https://pics.example/x.jpg" in out

    def test_case_and_query_are_kept(self):
        out = R.rewrite_for_preview("<img src='/IMG/a.png?v=2#x'>", ["img/a.png"], PUBLIC)
        assert f"{PUBLIC}/img/a.png?v=2#x" in out

    def test_nothing_stored_changes_nothing(self):
        assert R.rewrite_for_preview(PAGE, [], PUBLIC) == PAGE


class TestRender:
    def test_preview_has_meta_policy_and_storage_addresses(self):
        db = _seed()
        html = R.render_imported_page(db, db.tables["site_designs"][0], HOSTS, export=False)
        assert html.index("Content-Security-Policy") < html.index("<link")
        assert f"{PUBLIC}/{ORG}/site-1/tok/v1/css/s.css" in html

    def test_export_keeps_original_addresses(self):
        db = _seed()
        html = R.render_imported_page(db, db.tables["site_designs"][0], HOSTS, export=True)
        assert "href='css/s.css'" in html and "supabase" not in html and "'self'" in html

    def test_render_if_imported_only_for_imported_tier(self):
        db = _seed(tier="standard")
        assert R.render_if_imported(db, db.tables["sites"][0], {}) is None

    def test_through_render_if_premium(self):
        db = _seed(tier="imported")
        html = site_premium_service.render_if_premium(db, db.tables["sites"][0], {}, export=True, canonical_domain="shop.com.ng")
        assert html and "css/s.css" in html

    def test_missing_design_falls_back_to_none_for_preview(self):
        db = _seed(tier="imported", current="nope")
        assert R.render_if_imported(db, db.tables["sites"][0], {}) is None

    def test_failed_storage_url_is_none_not_a_crash(self):
        db = _seed(tier="imported")
        db.storage.from_ = lambda n: (_ for _ in ()).throw(RuntimeError("down"))
        assert R.render_if_imported(db, db.tables["sites"][0], {}) is None


class TestExport:
    def test_bundle_has_index_and_every_stored_file(self):
        db = _seed(tier="imported")
        files, site, domain = site_ops_service.collect_export_files(db, ORG, "site-1")
        names = [p for p, _ in files]
        assert names[0] == "index.html" and {"css/s.css", "js/a.js", "img/h.jpg", "img/h2.jpg", "robots.txt", "sitemap.xml"} <= set(names)
        assert domain == "shop.com.ng" and names.count("index.html") == 1

    def test_missing_file_blocks_the_export(self):
        db = _seed(tier="imported")
        db.storage.files.pop(("site-import-files", f"{ORG}/site-1/tok/v1/js/a.js"))
        with pytest.raises(site_ops_service.ValidationFailed):
            site_ops_service.collect_export_files(db, ORG, "site-1")

    def test_missing_design_never_publishes_standard(self):
        db = _seed(tier="imported", current="nope")
        with pytest.raises(site_ops_service.ValidationFailed):
            site_ops_service.collect_export_files(db, ORG, "site-1")

    def test_own_robots_file_is_not_duplicated(self):
        db = _seed(tier="imported")
        db.tables["site_designs"][0]["import_meta"]["files"].append(
            {"path": "robots.txt", "stored": True, "storage_path": f"{ORG}/site-1/tok/v1/robots.txt"})
        db.storage.files[("site-import-files", f"{ORG}/site-1/tok/v1/robots.txt")] = b"User-agent: *\nDisallow: /x\n"
        files, _s, _d = site_ops_service.collect_export_files(db, ORG, "site-1")
        assert [p for p, _ in files].count("robots.txt") == 1

    def test_standard_site_export_unchanged(self):
        db = _seed(tier="standard")
        db.tables["sites"][0]["content"] = None
        with pytest.raises(Exception):
            site_ops_service.collect_export_files(db, ORG, "site-1")   # still goes the Standard way (needs real content)

    def test_zip_download_contains_tree(self):
        db = _seed(tier="imported")
        data, name = site_ops_service.build_export_zip(db, ORG, "site-1")
        assert "js/a.js" in zipfile.ZipFile(io.BytesIO(data)).namelist() and name.endswith("-export.zip")

    @pytest.mark.parametrize("path,ct", [("a.css", "text/css; charset=utf-8"), ("a.js", "text/javascript; charset=utf-8"),
                                         ("f.woff2", "font/woff2"), ("i.svg", "image/svg+xml"), ("i.gif", "image/gif")])
    def test_publish_content_types(self, path, ct):
        assert site_publish_service._content_type(path) == ct

    def test_css_and_js_use_the_short_cache(self):
        assert site_publish_service._cache_control("js/a.js") == site_publish_service._PAGE_CACHE
        assert site_publish_service._cache_control("img/a.png") == site_publish_service._FILE_CACHE


class _Put:
    def __init__(self):
        self.keys = {}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        self.keys[Key] = (ContentType, len(Body))

    def get_paginator(self, name):
        class P:
            def paginate(self_inner, **k):
                return [{"Contents": []}]
        return P()


class TestPublish:
    def test_publish_uploads_tree_with_types(self):
        db = _seed(tier="imported")
        c = _Put()
        try:
            site_publish_service.publish_site(db, ORG, "site-1", client=c, bucket="b")
        except Exception:
            pass
        assert c.keys["shop.com.ng/css/s.css"][0] == "text/css; charset=utf-8"
        assert c.keys["shop.com.ng/js/a.js"][0].startswith("text/javascript")
        assert "shop.com.ng/index.html" in c.keys


class _Routes:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db = _seed()
        self.template = "owner"
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: {"id": USER, "org_id": ORG, "roles": {"template": self.template}}
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)


class TestRoutes(_Routes):
    def test_list_designs(self):
        r = TestClient(app).get(f"{BASE}/site-1/import/designs")
        d = r.json()["data"]
        assert r.status_code == 200 and d["designs"][0]["id"] == "d1" and d["designs"][0]["active"] is False
        assert d["designs"][0]["external_unknown"] == 1 and d["designs"][0]["scripts"] == 1

    def test_preview_returns_html(self):
        r = TestClient(app).get(f"{BASE}/site-1/import/designs/d1/preview")
        assert r.status_code == 200 and "Content-Security-Policy" in r.json()["data"]["html"]

    def test_preview_unknown_design_is_422(self):
        assert TestClient(app).get(f"{BASE}/site-1/import/designs/nope/preview").status_code == 422

    def test_activate_switches_tier_and_stores_html(self):
        r = TestClient(app).post(f"{BASE}/site-1/import/activate", json={"design_id": "d1"})
        assert r.status_code == 200
        site = self.db.tables["sites"][0]
        assert site["tier"] == "imported" and site["current_design_id"] == "d1" and "supabase.co" in site["rendered_html"]
        assert self.db.tables["site_designs"][0]["staged"] is False
        assert any(e.get("event_type") == "site_import_activated" or "activated" in str(e) for e in self.db.tables["site_events"])

    def test_activate_unknown_design(self):
        assert TestClient(app).post(f"{BASE}/site-1/import/activate", json={"design_id": "zz"}).status_code == 422

    def test_activate_needs_write_role(self):
        self.template = "sales_agent"
        assert TestClient(app).post(f"{BASE}/site-1/import/activate", json={"design_id": "d1"}).status_code in (401, 403)

    def test_switched_off_blocks_everything(self):
        self.db.tables["site_builder_settings"][0]["site_import_enabled"] = False
        c = TestClient(app)
        assert c.get(f"{BASE}/site-1/import/designs").status_code == 403
        assert c.post(f"{BASE}/site-1/import/activate", json={"design_id": "d1"}).status_code == 403

    def test_back_to_standard_uses_existing_route(self):
        c = TestClient(app)
        c.post(f"{BASE}/site-1/import/activate", json={"design_id": "d1"})
        assert c.post(f"{BASE}/site-1/premium/standard").status_code in (200, 403, 404)

    def test_resolve_route_reports_failures_without_network(self, monkeypatch):
        monkeypatch.setattr(RES, "safe_fetch", lambda url, max_bytes=0: (_ for _ in ()).throw(RES.FetchError("the address points to a private network")))
        r = TestClient(app).post(f"{BASE}/site-1/import/resolve", json={"design_id": "d1"})
        d = r.json()["data"]
        assert r.status_code == 200 and d["resolved"] == [] and d["failed"][0]["reason"].startswith("the address")


class TestPreviewHeaders:
    def test_imported_site_gets_sandbox_headers(self):
        db = _seed(tier="imported")
        db.tables["sites"][0].update({"status": "live"})
        app.dependency_overrides[get_supabase] = lambda: db
        try:
            r = TestClient(app).get("/s/s-abc")
        finally:
            app.dependency_overrides.pop(get_supabase, None)
        assert r.status_code == 200
        assert "sandbox allow-scripts" in r.headers["content-security-policy"]


class TestResolve:
    def fetcher(self, mapping):
        def f(url):
            if url not in mapping:
                raise RES.FetchError("the download failed")
            return mapping[url]
        return f

    def test_copies_image_and_rewrites_page(self):
        db = _seed()
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({"https://pics.example/x.jpg": (JPG, "image/jpeg")}))
        row = db.tables["site_designs"][0]
        assert out["resolved"][0]["path"].startswith("external/") and out["remaining"] == 0
        assert "pics.example" not in row["skeleton_html"] and out["resolved"][0]["path"] in row["skeleton_html"]
        assert row["import_meta"]["report"]["external"]["unknown"] == []
        assert ("site-import-files", f"{ORG}/site-1/tok/v1/{out['resolved'][0]['path']}") in db.storage.files
        assert any(f["path"] == out["resolved"][0]["path"] and f["source_url"] for f in row["import_meta"]["files"])

    def test_lying_content_type_refused(self):
        db = _seed()
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({"https://pics.example/x.jpg": (b"<html>", "image/jpeg")}))
        assert out["resolved"] == [] and "contents" in out["failed"][0]["reason"]
        assert "pics.example" in db.tables["site_designs"][0]["skeleton_html"]

    def test_script_type_refused(self):
        db = _seed()
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({"https://pics.example/x.jpg": (b"alert(1)", "text/javascript")}))
        assert out["resolved"] == [] and "cannot be hosted" in out["failed"][0]["reason"]

    def test_svg_with_script_refused(self):
        db = _seed()
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({"https://pics.example/x.jpg": (svg, "image/svg+xml")}))
        assert out["resolved"] == []

    def test_stylesheet_with_unlisted_import_refused(self):
        _ok = RES._check_file("u", b"body{color:red}", "text/css", HOSTS)
        assert _ok[0] == ".css"
        with pytest.raises(RES.FetchError):
            RES._check_file("u", b"@import url('https://evil.example/a.css');", "text/css", HOSTS)

    def test_stylesheet_with_js_url_refused(self):
        with pytest.raises(RES.FetchError):
            RES._check_file("u", b"a{background:url(javascript:alert(1))}", "text/css", HOSTS)

    def test_refs_inside_css_files_are_not_resolved(self):
        unknown = [{"url": "https://pics.example/y.png", "tag": "css", "attr": "url", "kind": "image", "class": "external_unknown", "file": "css/s.css"}]
        db = _seed(unknown=unknown)
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({}))
        assert out["resolved"] == [] and out["not_resolvable"] == 1 and out["remaining"] == 1

    def test_unknown_design(self):
        db = _seed()
        with pytest.raises(svc.ImportRejected):
            RES.resolve(db, ORG, db.tables["sites"][0], "zz", HOSTS, fetcher=self.fetcher({}))

    def test_storage_failure_changes_nothing(self):
        db = _seed()
        db.storage.from_ = lambda n: (_ for _ in ()).throw(RuntimeError("down"))
        out = RES.resolve(db, ORG, db.tables["sites"][0], "d1", HOSTS, fetcher=self.fetcher({"https://pics.example/x.jpg": (JPG, "image/jpeg")}))
        assert out["resolved"] == [] and out["failed"][0]["reason"] == "it could not be saved"
        assert "pics.example" in db.tables["site_designs"][0]["skeleton_html"]

    def test_replace_only_touches_addresses(self):
        out = RES._replace_url("<p>https://a.com/x.png</p><img src='https://a.com/x.png'>", "https://a.com/x.png", "external/z.png")
        assert out == "<p>https://a.com/x.png</p><img src='external/z.png'>"

    def test_replace_handles_escaped_ampersand_and_srcset(self):
        out = RES._replace_url("<img src='https://a.com/x?a=1&amp;b=2' srcset='https://a.com/x?a=1&amp;b=2 1x'>",
                               "https://a.com/x?a=1&b=2", "external/z.jpg")
        assert out.count("external/z.jpg") == 2


class TestSafeFetch:
    @pytest.mark.parametrize("url", ["http://pics.example/a.png", "ftp://x.com/a", "https://user:pw@pics.example/a.png",
                                     "https://pics.example:8443/a.png", "https:///a.png"])
    def test_bad_addresses_refused(self, url, monkeypatch):
        monkeypatch.setattr(RES.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
        with pytest.raises(RES.FetchError):
            RES.safe_fetch(url)

    @pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "172.16.0.9"])
    def test_private_addresses_refused(self, ip, monkeypatch):
        monkeypatch.setattr(RES.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))])
        with pytest.raises(RES.FetchError, match="private"):
            RES.safe_fetch("https://pics.example/a.png")

    def test_one_private_address_among_public_is_enough_to_refuse(self, monkeypatch):
        monkeypatch.setattr(RES.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.1", 443))])
        with pytest.raises(RES.FetchError):
            RES.safe_fetch("https://pics.example/a.png")

    def test_unknown_host(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("nope")
        monkeypatch.setattr(RES.socket, "getaddrinfo", boom)
        with pytest.raises(RES.FetchError):
            RES.safe_fetch("https://nowhere.invalid/a.png")
