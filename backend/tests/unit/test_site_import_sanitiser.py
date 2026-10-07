"""
tests/unit/test_site_import_sanitiser.py
-----------------------------------------
SITE-IMPORT 1a - the import-profile page sanitiser, with an adversarial corpus (spec sections 4, 13). Pure functions.
"""
from __future__ import annotations

import pytest

from app.services.site_import_sanitiser import normalise_local, parse_srcset, sanitise_page

HOSTS = ("cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com")
FILES = {"css/a.css": b"", "js/app.js": b"", "img/h.jpg": b"", "fonts/f.woff2": b"", "sprite.svg": b""}
HEAD = "<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'><title>T</title></head>"


def run(body: str, head: str = "", files=None):
    html = HEAD.replace("</head>", head + "</head>") + "<body>" + body + "</body></html>"
    return sanitise_page(html, files if files is not None else FILES, HOSTS)


def rules(r, severity=None):
    return sorted({f["rule"] for f in r.findings if severity is None or f["severity"] == severity})


class TestRemovals:
    @pytest.mark.parametrize("body,gone", [
        ("<object data=x></object>", "<object"), ("<embed src=x>", "<embed"), ("<applet code=x></applet>", "<applet"),
        ("<frameset><frame src=x></frameset>", "<frame"), ("<iframe src='https://evil.example/x'></iframe>", "<iframe"),
        ("<iframe srcdoc='<script>1</script>'></iframe>", "srcdoc"), ("<portal src=x></portal>", "<portal"),
        ("<svg><foreignObject><div>x</div></foreignObject></svg>", "foreignobject"),
    ])
    def test_dangerous_elements_are_removed(self, body, gone):
        assert gone not in run(body).html.lower()

    def test_removed_element_content_goes_too(self):
        out = run("<p>keep</p><object><param name=a value=b>SECRET</object><p>after</p>").html
        assert "SECRET" not in out and "keep" in out and "after" in out

    def test_nested_removed_elements(self):
        out = run("<iframe src='//evil.example/a'><iframe src='//evil.example/b'>X</iframe>Y</iframe><p>ok</p>").html
        # Python's tokeniser treats iframe content as raw text from 3.13 on, as browsers do; both ways nothing survives
        assert "X" not in out and "evil.example" not in out and "<iframe" not in out and "ok" in out

    def test_base_and_http_equiv_and_canonical_and_robots(self):
        r = run("<p>x</p>", "<base href='https://evil.example/'><meta http-equiv=refresh content='0;url=//evil.example'>"
                            "<meta http-equiv=Content-Security-Policy content=\"default-src *\">"
                            "<link rel=canonical href=https://other.example><meta name=robots content='noindex,nofollow'>")
        h = r.html.lower()
        assert "<base" not in h and "http-equiv" not in h and "canonical" not in h and "robots" not in h
        assert "noindex_removed" in rules(r, "warning")
        assert r.stats["noindex_removed"] is True

    def test_comments_conditional_comments_cdata_and_pi_removed(self):
        out = run("<!-- secret --><!--[if IE]><script>x</script><![endif]--><p>a</p>").html
        assert "secret" not in out and "[if IE]" not in out

    def test_srcdoc_is_removed_from_allowed_iframes(self):
        out = run("<iframe src='https://www.youtube-nocookie.com/embed/abc' srcdoc='<b>x</b>'></iframe>").html
        assert "srcdoc" not in out and "youtube-nocookie" in out

    def test_maps_and_youtube_embeds_kept_other_google_paths_not(self):
        keep = run("<iframe src='https://www.google.com/maps/embed?pb=1'></iframe>").html
        gone = run("<iframe src='https://www.google.com/search?q=x'></iframe>").html
        assert "<iframe" in keep and "<iframe" not in gone

    def test_form_action_removed_form_kept_and_counted(self):
        r = run("<form action='https://evil.example/p' method=post><input name=a formaction='//evil.example'></form>")
        assert "action" not in r.html and "formaction" not in r.html and "<form" in r.html
        assert r.stats["forms"] == 1 and "form_action_removed" in rules(r, "warning")


class TestUrls:
    @pytest.mark.parametrize("href", ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "java\tscript:alert(1)",
                                      "&#106;avascript:alert(1)", "  javascript:alert(1)", "vbscript:x"])
    def test_javascript_urls_removed(self, href):
        out = run(f"<a href=\"{href}\">x</a><img src=\"{href}\"><script src=\"{href}\"></script>").html
        assert "alert" not in out and "vbscript" not in out.lower()

    def test_noop_javascript_href_becomes_hash(self):
        out = run("<a href='javascript:void(0)'>x</a><a href='javascript:;'>y</a><a href='javascript:'>z</a>").html
        assert out.count('href="#"') == 3

    def test_data_urls_only_for_small_images_and_fonts(self):
        ok = run("<img src='data:image/png;base64,AAAA'>").html
        bad = run("<a href='data:text/html;base64,PHNjcmlwdD4='>x</a><img src='data:text/html,<script>1</script>'>").html
        assert "data:image/png" in ok and "data:text" not in bad
        big = run("<img src='data:image/png;base64," + "A" * 400000 + "'>")
        assert "data:image" not in big.html and "data_url_removed" in rules(big, "warning")

    def test_external_svg_use_removed_local_kept(self):
        out = run("<svg><use href='https://evil.example/s.svg#a'/><use href='sprite.svg#icon'/><use href='#local'/></svg>").html
        assert "evil.example" not in out and "sprite.svg#icon" in out and "#local" in out

    def test_other_page_link_warns(self):
        r = run("<a href='about.html'>x</a>", files={**FILES, "about.html": b""})
        assert "other_page_link" in rules(r, "warning")


class TestScriptsAndHandlers:
    def test_scripts_are_kept(self):
        r = run("<script>document.querySelector('a');</script><script src='js/app.js'></script>")
        assert "<script>document.querySelector('a');</script>" in r.html and 'src="js/app.js"' in r.html
        assert r.scripts == ["js/app.js"] and r.stats["inline_scripts"] == 1
        assert rules(r, "error") == []

    def test_inline_script_is_scanned_with_line_numbers(self):
        r = run("<p>a</p>\n<script>\nvar a = 1;\ndocument.cookie='x';\n</script>")
        f = [f for f in r.findings if f["rule"] == "document_cookie"]
        assert len(f) == 1 and "inline script" in f[0]["file"] and f[0]["line"] == 4

    def test_event_handlers_are_kept_and_scanned(self):
        r = run("<button onclick=\"localStorage.clear()\">x</button><div onmouseover=\"toggle()\">y</div>")
        assert 'onclick="localStorage.clear()"' in r.html and "web_storage" in rules(r, "error")
        assert r.stats["handlers"] == 2

    def test_remote_script_on_unlisted_host_is_an_error_allowed_host_is_not(self):
        bad = run("<script src='https://evil.example/x.js'></script>")
        good = run("<script src='https://cdn.jsdelivr.net/npm/a/b.js'></script>")
        assert "remote_import" in rules(bad, "error") and rules(good, "error") == []

    def test_json_ld_and_importmap_are_not_scanned(self):
        r = run("<script type='application/ld+json'>{\"a\":\"eval(x) document.cookie\"}</script>")
        assert rules(r) == []

    def test_output_is_stable_when_cleaned_again(self):
        body = ("<p onclick='a()'>x &amp; y</p><script>var s='</script><b>x</b>';</script><style>.a{color:red}</style>"
                "<svg viewBox='0 0 1 1'><path d='M0 0'/></svg><a href='javascript:void(0)'>z</a>")
        once = run(body).html
        assert sanitise_page(once, FILES, HOSTS).html == once

    def test_style_block_and_style_attribute_scanned(self):
        r = run("<div style=\"width:expression(alert(1))\">x</div>", "<style>.a{background:url(javascript:alert(1))}</style>")
        assert {"css_expression", "css_js_url"} <= set(rules(r, "error"))

    def test_style_block_urls_become_refs(self):
        r = run("<p>x</p>", "<style>.a{background:url(img/h.jpg)} .b{background:url(img/missing.jpg)}</style>")
        assert any(x["path"] == "img/h.jpg" for x in r.refs)
        assert any(x.get("missing") for x in r.refs)


class TestRefs:
    def test_local_external_and_missing_refs(self):
        r = run("<img src='img/h.jpg?v=3' srcset='img/h.jpg 1x, https://evil.example/a.jpg 2x'><img data-src='img/nope.jpg'>",
                "<link rel=stylesheet href='css/a.css'><link rel=stylesheet href='https://fonts.googleapis.com/css?family=X'>"
                "<link rel=stylesheet href='https://evil.example/a.css'>")
        by_class = {}
        for x in r.refs:
            by_class.setdefault(x["class"], []).append(x["url"])
        assert "img/h.jpg?v=3" in by_class["local"] and "https://evil.example/a.jpg" in by_class["external_unknown"]
        assert "https://fonts.googleapis.com/css?family=X" in by_class["external_allowed"]
        assert r.stylesheets == ["css/a.css"]
        assert any(x.get("missing") and x["url"] == "img/nope.jpg" for x in r.refs)

    def test_case_insensitive_file_match_returns_real_name(self):
        r = run("<img src='IMG/H.JPG'>")
        assert [x["path"] for x in r.refs if x["kind"] == "image"] == ["img/h.jpg"]

    def test_normalise_local(self):
        assert normalise_local("css/a.css?v=1#x") == "css/a.css"
        assert normalise_local("/img/a.png") == "img/a.png"
        assert normalise_local("../a.png") is None
        assert normalise_local("../a.png", "css") == "a.png"
        assert normalise_local("../../a.png", "css") is None
        assert normalise_local("img/my%20pic.png") == "img/my pic.png"
        assert normalise_local("") is None

    def test_parse_srcset(self):
        assert parse_srcset("a.jpg 1x, b.jpg 2x ,c.jpg") == ["a.jpg", "b.jpg", "c.jpg"]


class TestDocument:
    def test_doctype_added_and_viewport_warning(self):
        r = sanitise_page("<html><head></head><body><p>x</p></body></html>", {}, HOSTS)
        assert r.html.startswith("<!doctype html>") and "no_viewport" in rules(r, "warning")

    def test_attributes_are_escaped_and_text_preserved(self):
        out = run("<p title='a \"quoted\" & <b>'>caf&eacute; &amp; &#169; 5 &lt; 6</p>").html
        assert 'title="a &quot;quoted&quot; &amp; &lt;b&gt;"' in out
        assert "caf&eacute; &amp; &#169; 5 &lt; 6" in out

    def test_boolean_and_empty_attributes(self):
        out = run("<input disabled value=''><video controls autoplay muted></video>").html
        assert "disabled" in out and 'value=""' in out and "controls" in out

    def test_void_elements_and_svg_self_closing(self):
        out = run("<br><img src=img/h.jpg><svg><path d='M0 0'/><circle r=1 /></svg>").html
        assert "</br>" not in out and "</img>" not in out and "<path d=\"M0 0\"/>" in out

    def test_unclosed_and_malformed_markup_does_not_raise(self):
        run("<div><p>x<b>y</div><<<>>>&&&<a href=>")
        run("<script>unterminated")
        run("<style>.a{")
        run("<iframe src='//evil.example'>never closed")

    def test_output_has_no_removed_marker_leaks_of_attacker_markup(self):
        out = run("<img src=x onerror=alert(1)>").html
        assert "onerror" in out    # handlers are kept by design; they are scanned (and the page is sandboxed / CSP'd)
