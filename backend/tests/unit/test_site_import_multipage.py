"""
tests/unit/test_site_import_multipage.py
-----------------------------------------
MULTIPAGE-1 - several pages in one imported site: analysis, SEO report, canonical, absolute share images, sitemap,
links between pages in preview. No network, no database.
"""
from __future__ import annotations

import json

import pytest

from app.services import site_import_render as rnd
from app.services import site_import_service as svc

HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"]
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def page(title, desc="A description of the page.", og="images/og.jpg", body="<h1>Hello</h1>", extra=""):
    return ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{title}</title><meta name=description content=\"{desc}\">"
            f"<meta property='og:image' content='{og}'><meta name=robots content='noindex,nofollow'>"
            "<link rel=canonical href='https://old.example/'><link rel=stylesheet href='/css/s.css'>"
            f"{extra}</head><body>{body}<img src='/images/a.jpg'><a href='/about/'>About</a><a href='/'>Home</a>"
            "<a href='/contact.html#f'>Contact</a></body></html>")


SITE = {
    "index.html": page("Home page"),
    "about/index.html": page("About us", body="<h1>About</h1><img src='../images/a.jpg'>"),
    "contact.html": page("Contact us"),
    "css/s.css": "body{background:url(../images/a.jpg)}",
    "images/a.jpg": JPG, "images/og.jpg": JPG,
}


def analyse(files):
    return svc.analyse({k: (v.encode() if isinstance(v, str) else v) for k, v in files.items()}, HOSTS)


class TestAnalyse:
    def test_pages_are_all_cleaned_and_listed(self):
        r = analyse(SITE)
        rep = r["report"]
        assert rep["ok"] and rep["entry"] == "index.html"
        assert [p["url"] for p in rep["pages"]] == ["/about/", "/contact.html", "/"]
        assert set(r["pages"]) == {"about/index.html", "contact.html"}
        for html in [r["html"], *r["pages"].values()]:
            assert "canonical" not in html and "noindex" not in html          # Opsra owns these on the live page
        assert rep["page"]["noindex_removed"] is True

    def test_index_must_be_home_and_at_top(self):
        with pytest.raises(svc.ImportRejected, match="index.html"):
            analyse({"home.html": page("x"), "about/index.html": page("y")})

    def test_same_address_twice_is_refused(self):
        with pytest.raises(svc.ImportRejected, match="same address"):
            analyse({**SITE, "about.html": page("About two")})          # /about.html vs /about/ differ ...
            analyse({"index.html": page("a"), "x/index.html": page("b"), "X/index.html": page("c")})

    def test_page_limit(self):
        files = {"index.html": page("home")}
        files.update({f"p{i}.html": page(f"P{i}") for i in range(svc.LIMITS["max_pages"])})
        with pytest.raises(svc.ImportRejected, match="pages"):
            analyse(files)

    def test_files_resolve_from_each_pages_own_folder(self):
        r = analyse(SITE)
        assert "images/a.jpg" not in r["report"]["missing_files"]
        assert not r["report"]["missing_files"]
        assert "images/a.jpg" not in r["report"]["unreferenced"]

    def test_broken_link_is_a_warning(self):
        r = analyse({**SITE, "contact.html": page("Contact us", body="<h1>c</h1><a href='/nope/'>x</a>")})
        assert any(w["rule"] == "broken_page_link" and w["file"] == "contact.html" for w in r["report"]["warnings"])


class TestSeoReport:
    def test_flags_missing_and_duplicate_things(self):
        r = analyse({"index.html": "<!doctype html><html><head><meta name=viewport content=x></head><body><p>x</p></body></html>",
                     "a.html": page("Same", og="https://other.example/og.jpg"), "b.html": page("Same")})
        by = {p["path"]: p["issues"] for p in r["report"]["seo"]}
        assert {"no_title", "no_description", "no_share_image", "no_h1"} <= set(by["index.html"])
        assert "absolute_share_image" in by["a.html"]
        rules = {w["rule"] for w in r["report"]["warnings"]}
        assert "seo_duplicate_title" in rules and "seo_no_title" in rules

    def test_clean_site_has_no_seo_issues(self):
        assert all(not p["issues"] for p in analyse(SITE)["report"]["seo"])


class TestPageUrls:
    def test_urls(self):
        assert svc.page_url_path("index.html") == "/"
        assert svc.page_url_path("about/index.html") == "/about/"
        assert svc.page_url_path("contact.html") == "/contact.html"


class TestShareTags:
    HTML = ("<html><head><meta property='og:image' content='images/og.jpg'><meta name='twitter:image' content='/images/og.jpg'>"
            "<meta property='og:title' content='images/not-touched'>"
            "<meta property='og:image:alt' content='alt text'>"
            "<script type='application/ld+json'>{\"@type\":\"Person\",\"image\":\"images/og.jpg\",\"url\":\"/\","
            "\"sameAs\":[\"https://x.example/a\"],\"logo\":{\"url\":\"images/l.png\"}}</script></head></html>")

    def test_relative_become_absolute_for_the_page(self):
        from urllib.parse import urljoin
        base = "https://site.example/about/"
        out = rnd.absolutise_meta(self.HTML, lambda u: urljoin(base, u.strip()))
        flat = out.replace("'", '"')
        assert 'content="https://site.example/about/images/og.jpg"' in flat
        assert 'content="https://site.example/images/og.jpg"' in flat
        assert "images/not-touched" in out and "alt text" in out
        ld = json.loads(out.split('ld+json\'>')[1].split("</script>")[0])
        assert ld["image"] == "https://site.example/about/images/og.jpg" and ld["url"] == "https://site.example/"
        assert ld["logo"]["url"] == "https://site.example/about/images/l.png" and ld["sameAs"] == ["https://x.example/a"]

    def test_absolute_values_are_left_alone(self):
        h = "<meta property='og:image' content='https://cdn.example/x.jpg'>"
        assert rnd.absolutise_meta(h, lambda u: "BAD") == h

    def test_seo_head(self):
        out = rnd.seo_head("<head></head>", "https://s.example/about/")
        assert '<link rel="canonical" href="https://s.example/about/">' in out and 'property="og:url"' in out
        keep = rnd.seo_head("<meta property='og:url' content='https://s.example/x'>", "https://s.example/about/")
        assert "canonical" in keep and "og:url" not in keep
        assert rnd.seo_head("<head></head>", None) == ""

    def test_sitemap_lists_every_page(self):
        x = rnd.sitemap_xml("https://s.example", ["index.html", "about/index.html", "contact.html"])
        assert "<loc>https://s.example/</loc>" in x and "<loc>https://s.example/about/</loc>" in x
        assert "<loc>https://s.example/contact.html</loc>" in x


class TestPreviewLinks:
    def test_links_between_pages_go_to_the_page_route(self):
        pages = ["index.html", "about/index.html", "contact.html"]
        html = "<a href='/about/'>a</a><a href=\"../\">h</a><a href='/contact.html#f'>c</a><a href='https://wa.me/1'>w</a><a href='#x'>x</a>"
        out = rnd.rewrite_page_links(html, "about/index.html", pages, "my-site", "https://api.example")
        assert "https://api.example/s/my-site/p/about/index.html" in out
        assert out.replace("'", '"').count('href="https://api.example/s/my-site"') == 1          # the ../ link goes home
        assert "https://api.example/s/my-site/p/contact.html#f" in out
        assert "https://wa.me/1" in out and "#x" in out

    def test_file_addresses_resolve_from_the_pages_folder(self):
        out = rnd.rewrite_for_preview("<img src='../images/a.jpg'><img src='/images/a.jpg'><img src='images/a.jpg'>",
                                      ["images/a.jpg"], "https://st.example/b", "about")
        assert out.count("https://st.example/b/images/a.jpg") == 2          # '../images' and '/images'
        assert "src='images/a.jpg'" in out.replace('"', "'")                # 'images/a.jpg' from /about/ is about/images/a.jpg: not stored


# ---- render / export with a tiny fake storage -------------------------------------------------------------------

class _Bucket:
    def __init__(self, store):
        self.store = store

    def download(self, key):
        return self.store[key]

    def get_public_url(self, key):
        return "https://st.example/storage/v1/object/public/site-import-files/" + key


class _Storage:
    def __init__(self, store):
        self.store = store

    def from_(self, _name):
        return _Bucket(self.store)


class _Db:
    def __init__(self, store):
        self.storage = _Storage(store)


def design_and_db():
    r = analyse(SITE)
    prefix = "org/site/tok/v1"
    store, manifest = {}, []
    for path, body in SITE.items():
        body = body.encode() if isinstance(body, str) else body
        if path == "index.html":
            manifest.append({"path": path, "stored": False, "page": True})
            continue
        if path in r["pages"]:
            body = r["pages"][path].encode()
        store[f"{prefix}/{path}"] = body
        manifest.append({"path": path, "stored": True, "storage_path": f"{prefix}/{path}", **({"page": True} if path in r["pages"] else {})})
    design = {"id": "d1", "skeleton_html": r["html"], "files_prefix": prefix, "kind": "import", "status": "ready",
              "import_meta": {"files": manifest, "report": r["report"]}, "editable": False}
    return design, _Db(store)


class TestRender:
    def test_page_order_home_first(self):
        d, _ = design_and_db()
        assert rnd.page_paths(d)[0] == "index.html" and set(rnd.page_paths(d)) == {"index.html", "about/index.html", "contact.html"}
        assert rnd.page_paths({"import_meta": {"files": []}}) == ["index.html"]          # a design from before multi-page

    def test_export_gives_each_page_its_own_canonical_and_absolute_share_image(self):
        d, db = design_and_db()
        home = rnd.render_imported_page(db, d, HOSTS, export=True, domain="coach.example")
        about = rnd.render_imported_page(db, d, HOSTS, export=True, domain="coach.example", page_path="about/index.html")
        assert '<link rel="canonical" href="https://coach.example/">' in home
        assert '<link rel="canonical" href="https://coach.example/about/">' in about
        assert 'content="https://coach.example/images/og.jpg"' in home
        assert 'content="https://coach.example/about/images/og.jpg"' in about          # relative to the page, as a browser would
        assert "Content-Security-Policy" in about and "old.example" not in about

    def test_export_without_a_domain_adds_no_canonical(self):
        d, db = design_and_db()
        assert "canonical" not in rnd.render_imported_page(db, d, HOSTS, export=True)

    def test_unknown_page_is_refused(self):
        d, db = design_and_db()
        with pytest.raises(rnd.ImportRenderError):
            rnd.render_imported_page(db, d, HOSTS, export=True, page_path="secret.html")

    def test_preview_points_links_and_images_at_the_right_places(self):
        d, db = design_and_db()
        out = rnd.render_imported_page(db, d, HOSTS, export=False, page_path="about/index.html", slug="my-site")
        assert "/s/my-site/p/contact.html#f" in out
        assert "https://st.example/storage/v1/object/public/site-import-files/org/site/tok/v1/images/a.jpg" in out
        assert 'content="images/og.jpg"' in out.replace("'", '"')          # relative to /about/ it is about/images/og.jpg: not stored, left as written
        assert "canonical" not in out

    def test_export_bundle_ships_every_page_files_and_sitemap(self, monkeypatch):
        d, db = design_and_db()
        monkeypatch.setattr(rnd, "_current_design", lambda _db, _site, _id=None: d)
        monkeypatch.setattr(rnd, "_allowed_hosts", lambda _db, _org: HOSTS)
        files = dict(rnd.export_bundle(db, {"id": "s1", "org_id": "o1", "content": None}, domain="coach.example"))
        assert {"index.html", "about/index.html", "contact.html", "css/s.css", "images/a.jpg", "sitemap.xml"} <= set(files)
        assert "https://coach.example/about/" in files["sitemap.xml"] and files["about/index.html"].count("canonical") == 1
        no_domain = dict(rnd.export_bundle(db, {"id": "s1", "org_id": "o1", "content": None}))
        assert "sitemap.xml" not in no_domain


# ---- the /s/{slug}/p/{page} route ------------------------------------------------------------------------------

class _Q:
    def __init__(self, data):
        self._data = data

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self._data
        return r


class _RouteDb:
    def __init__(self, site):
        self.site = site

    def table(self, _name):
        return _Q(self.site)


def _client(site, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_supabase
    from app.routers import public_sites
    app = FastAPI()
    app.include_router(public_sites.router)
    app.dependency_overrides[get_supabase] = lambda: _RouteDb(site)
    public_sites._rate_store.clear()
    d, _db = design_and_db()
    monkeypatch.setattr(rnd, "_current_design", lambda _db, _site, _id=None: d)
    monkeypatch.setattr(rnd, "_allowed_hosts", lambda _db, _org: HOSTS)
    monkeypatch.setattr(rnd, "public_base", lambda _db, _d: "https://st.example/storage/v1/object/public/site-import-files/org/site/tok/v1")
    monkeypatch.setattr(rnd, "preview_page", lambda _db, _site, page: _db_page(page))
    return TestClient(app)


def _db_page(page):
    if page != "about/index.html":
        raise rnd.ImportRenderError("not a page")
    return "<html><body>about page</body></html>"


SITE_ROW = {"id": "s1", "org_id": "o1", "slug": "my-site", "status": "preview_ready", "tier": "imported",
            "content": None, "preview_expires_at": None, "current_design_id": "d1"}


class TestPageRoute:
    def test_serves_a_page_with_noindex_and_sandbox_headers(self, monkeypatch):
        r = _client(SITE_ROW, monkeypatch).get("/s/my-site/p/about/index.html")
        assert r.status_code == 200 and "about page" in r.text
        assert "noindex" in r.headers["x-robots-tag"] and "sandbox" in r.headers["content-security-policy"]

    def test_unknown_page_is_404(self, monkeypatch):
        assert _client(SITE_ROW, monkeypatch).get("/s/my-site/p/secret.html").status_code == 404

    def test_only_imported_sites_have_page_routes(self, monkeypatch):
        assert _client({**SITE_ROW, "tier": "standard"}, monkeypatch).get("/s/my-site/p/about/index.html").status_code == 404

    def test_cancelled_site_is_gone(self, monkeypatch):
        assert _client({**SITE_ROW, "status": "cancelled"}, monkeypatch).get("/s/my-site/p/about/index.html").status_code == 410
