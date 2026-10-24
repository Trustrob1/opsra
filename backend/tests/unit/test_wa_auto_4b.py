"""WA-AUTO-4b: knowledge from a website address or a public Google Doc."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import knowledge_service as ks
from app.services import knowledge_web_service as web
from app.services.site_import_resolve import FetchError
from tests.unit.test_wa_auto_4a import KDB, ORG

HOME = b"""<html><head><title>Glow Salon - Home</title><style>.x{color:red}</style><script>var secret=1;</script></head>
<body><nav><a href="/">Home</a><a href="/prices">Prices</a><a href="/contact">Contact</a><a href="https://other.com/x">Elsewhere</a>
<a href="/photo.jpg">pic</a><a href="/files/menu.pdf">pdf</a><a href="mailto:a@b.com">mail</a></nav>
<h1>Welcome to Glow Salon</h1><p>We do braids, wigs and nails in Lekki.</p><img alt="Our shopfront" src="a.png"><footer>Call 0801 234 5678</footer></body></html>"""
PRICES = b"""<html><head><title>Prices</title></head><body><nav><a href="/">Home</a></nav><p>Braids cost N15,000. Wigs from N40,000.</p>
<p>We do braids, wigs and nails in Lekki.</p></body></html>"""
CONTACT = b"<html><head><title>Contact</title></head><body><p>Find us at 12 Admiralty Way, Lekki. Open 9 to 6.</p></body></html>"
SITEMAP = b"<urlset><loc>https://glow.example/prices</loc><loc>https://glow.example/contact</loc><loc>https://glow.example/hidden</loc></urlset>"
ROBOTS = b"User-agent: *\nDisallow: /hidden\n"


class Web:
    """A pretend website: answers like safe_fetch (bytes, content type) or raises FetchError."""
    def __init__(self, pages, slow=None):
        self.pages, self.calls = pages, []

    def __call__(self, url, max_bytes=0):
        self.calls.append(url)
        if url in self.pages:
            body = self.pages[url]
            return body, ("text/plain" if url.endswith(".txt") or url.endswith("format=txt") else "application/xml" if url.endswith(".xml") else "text/html")
        raise FetchError("the site answered 404")


def _site():
    return Web({"https://glow.example/": HOME, "https://glow.example/prices": PRICES, "https://glow.example/contact": CONTACT,
                "https://glow.example/sitemap.xml": SITEMAP, "https://glow.example/robots.txt": ROBOTS,
                "https://glow.example/hidden": b"<p>should never be read</p>"})


# -- turning a page into text ------------------------------------------------------------------------------------
def test_page_text_has_no_scripts_or_styles_and_keeps_useful_bits():
    title, text, links = web.parse_html(HOME)
    assert title == "Glow Salon - Home"
    assert "secret" not in text and "color:red" not in text
    assert "Welcome to Glow Salon" in text and "Our shopfront" in text and "Call 0801 234 5678" in text
    assert "/prices" in links and "mailto:a@b.com" in links


def test_broken_html_never_raises():
    assert web.parse_html(b"<p><b>unclosed <div></span>")[1]
    assert web.parse_html(b"\xff\xfe\x00junk")[1] is not None


@pytest.mark.parametrize("raw,ok", [("glow.example", "https://glow.example/"), ("https://www.Glow.example/Shop/", "https://www.glow.example/Shop"),
                                    ("http://glow.example", None), ("javascript:alert(1)", None), ("https://", None), ("localhost", None),
                                    ("https://user:pw@glow.example", None), ("two words.com", None), ("", None)])
def test_start_address_is_cleaned_or_refused(raw, ok):
    if ok is None:
        with pytest.raises(ValueError):
            web.clean_start_url(raw)
    else:
        assert web.clean_start_url(raw) == ok


def test_google_doc_link_becomes_a_text_download():
    doc = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    assert web.gdoc_export_url(f"https://docs.google.com/document/d/{doc}/edit?usp=sharing") == f"https://docs.google.com/document/d/{doc}/export?format=txt"
    for bad in ("https://evil.com/document/d/" + doc, "https://docs.google.com/spreadsheets/d/" + doc, "https://docs.google.com/document/d/short", "x"):
        with pytest.raises(ValueError):
            web.gdoc_export_url(bad)


# -- crawling -----------------------------------------------------------------------------------------------------
def test_crawl_reads_the_same_website_only_and_respects_robots():
    site = _site()
    pages = web.crawl("https://glow.example/", site)
    urls = [p["url"] for p in pages]
    assert urls[0] == "https://glow.example/" and "https://glow.example/prices" in urls and "https://glow.example/contact" in urls
    assert not any("other.com" in u or u.endswith(".jpg") or u.endswith(".pdf") or "hidden" in u for u in urls)
    assert not any("other.com" in c or "hidden" in c and not c.endswith("robots.txt") for c in site.calls)


def test_each_page_is_read_once():
    site = _site()
    web.crawl("https://glow.example/", site)
    page_calls = [c for c in site.calls if not c.endswith((".xml", ".txt"))]
    assert len(page_calls) == len(set(page_calls))


def test_page_limit_is_respected():
    pages = {"https://glow.example/": b"<a href='/p1'>1</a><a href='/p2'>2</a><a href='/p3'>3</a><p>start page text here</p>"}
    for i in range(1, 4):
        pages[f"https://glow.example/p{i}"] = f"<p>page number {i} has some text</p>".encode()
    assert len(web.crawl("https://glow.example/", Web(pages), max_pages=2)) == 2


def test_time_budget_stops_the_crawl():
    assert len(web.crawl("https://glow.example/", _site(), budget_s=0)) == 0


def test_unreadable_start_page_is_an_error_but_a_bad_later_page_is_skipped():
    with pytest.raises(FetchError):
        web.crawl("https://glow.example/", Web({}))
    pages = {"https://glow.example/": b"<a href='/gone'>x</a><a href='/ok'>y</a><p>start page text here</p>", "https://glow.example/ok": b"<p>ok page text here</p>"}
    assert len(web.crawl("https://glow.example/", Web(pages))) == 2


def test_a_website_that_forbids_reading_is_respected():
    site = Web({"https://glow.example/": HOME, "https://glow.example/robots.txt": b"User-agent: *\nDisallow: /\n"})
    with pytest.raises(FetchError):
        web.crawl("https://glow.example/", site)
    assert "https://glow.example/" not in site.calls


def test_a_non_page_start_address_is_refused():
    class Img(Web):
        def __call__(self, url, max_bytes=0):
            if url.endswith("robots.txt"):
                raise FetchError("404")
            return b"\x89PNG", "image/png"
    with pytest.raises(FetchError):
        web.crawl("https://glow.example/", Img({}))


def test_repeated_menus_are_dropped_from_the_text():
    text = web.assemble(web.crawl("https://glow.example/", _site()))
    assert text.count("We do braids, wigs and nails in Lekki.") == 1
    assert "Glow Salon - Home (https://glow.example/)" in text and "Prices (https://glow.example/prices)" in text


# -- jobs ------------------------------------------------------------------------------------------------------
def test_website_job_fills_the_source_as_a_draft():
    db = KDB()
    sid = ks.new_source(db, ORG, "u1", "url", "glow.example", source_url="https://glow.example/", status="processing")
    web.run_website(db, ORG, sid, "https://glow.example/", _site())
    src = db.tables["knowledge_sources"][0]
    assert src["status"] == "draft" and src["page_count"] == 3 and src["chunk_count"] >= 1 and src["error"] is None
    assert "N15,000" in " ".join(c["content"] for c in db.tables["knowledge_chunks"])


def test_website_job_failure_gives_a_plain_message_and_no_chunks():
    db = KDB()
    sid = ks.new_source(db, ORG, "u1", "url", "glow.example", status="processing")
    web.run_website(db, ORG, sid, "https://glow.example/", Web({}))
    src = db.tables["knowledge_sources"][0]
    assert src["status"] == "failed" and "could not read that website" in src["error"] and db.tables["knowledge_chunks"] == []


def test_google_doc_job_reads_text_and_explains_private_docs():
    export = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/export?format=txt"
    db = KDB()
    sid = ks.new_source(db, ORG, "u1", "gdoc", "Google Doc", status="processing")
    web.run_gdoc(db, ORG, sid, export, Web({export: b"Delivery is free above N50,000. Returns within 7 days."}))
    assert db.tables["knowledge_sources"][0]["status"] == "draft"
    sid2 = ks.new_source(db, ORG, "u1", "gdoc", "Google Doc", status="processing")
    class Login(Web):
        def __call__(self, url, max_bytes=0):
            return b"<html>Sign in</html>", "text/html"
    web.run_gdoc(db, ORG, sid2, export, Login({}))
    bad = [s for s in db.tables["knowledge_sources"] if s["id"] == sid2][0]
    assert bad["status"] == "failed" and "Anyone with the link" in bad["error"]


def test_a_source_still_reading_cannot_be_started_and_old_ones_show_as_failed():
    db = KDB()
    sid = ks.new_source(db, ORG, "u1", "url", "glow.example", status="processing")
    with pytest.raises(Exception) as e:
        ks.activate(db, ORG, sid)
    assert e.value.status_code == 409
    db.tables["knowledge_sources"][0]["created_at"] = "2020-01-01T00:00:00+00:00"
    out = ks.list_sources(db, ORG)
    assert out[0]["status"] == "failed" and "too long" in out[0]["error"]


# -- the routes -------------------------------------------------------------------------------------------------
def _client(db, monkeypatch, ran):
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    from app.services import plan_gate_service
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: {"org_id": ORG, "id": "user-1", "roles": {"template": "owner"}}
    monkeypatch.setattr(plan_gate_service, "allowed", lambda *a, **k: True)
    monkeypatch.setattr(web, "run_website", lambda *a, **k: ran.append(("url", a[2:])))
    monkeypatch.setattr(web, "run_gdoc", lambda *a, **k: ran.append(("gdoc", a[2:])))
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    yield
    from app.main import app
    app.dependency_overrides.clear()


def test_website_route_starts_a_background_read(monkeypatch):
    db, ran = KDB(), []
    r = _client(db, monkeypatch, ran).post("/api/v1/knowledge/sources/url", json={"url": "glow.example"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "processing" and r.json()["data"]["kind"] == "url"
    assert ran and ran[0][0] == "url" and ran[0][1][1] == "https://glow.example/"


def test_google_doc_route(monkeypatch):
    db, ran = KDB(), []
    doc = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    r = _client(db, monkeypatch, ran).post("/api/v1/knowledge/sources/gdoc", json={"url": f"https://docs.google.com/document/d/{doc}/edit"})
    assert r.status_code == 200 and ran[0][0] == "gdoc" and ran[0][1][1].endswith("/export?format=txt")


def test_bad_addresses_get_plain_422s_and_start_nothing(monkeypatch):
    db, ran = KDB(), []
    c = _client(db, monkeypatch, ran)
    assert c.post("/api/v1/knowledge/sources/url", json={"url": "http://glow.example"}).status_code == 422
    assert c.post("/api/v1/knowledge/sources/gdoc", json={"url": "https://evil.com/x"}).status_code == 422
    assert ran == [] and db.tables["knowledge_sources"] == []


def test_only_one_read_at_a_time(monkeypatch):
    db, ran = KDB(), []
    c = _client(db, monkeypatch, ran)
    assert c.post("/api/v1/knowledge/sources/url", json={"url": "glow.example"}).status_code == 200
    r = c.post("/api/v1/knowledge/sources/url", json={"url": "other.example"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "BUSY" and len(ran) == 1
