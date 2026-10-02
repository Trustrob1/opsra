"""
tests/unit/test_site_premium_sanitiser.py
------------------------------------------
SITE-PREMIUM P1 - the adversarial corpus for the sanitiser (spec section 14). Pure functions.
"""
from __future__ import annotations

import pytest

from app.services.site_premium_sanitiser import (
    MAX_TOTAL_BYTES, SanitiseError, sanitise_css, sanitise_html, sanitise_skeleton)

GOOD_CSS = ":root{--accent:#2F4BFF;--bg:#FFFFFF}.h{color:var(--accent)}@media (max-width:600px){.h{display:none}}"


def clean(html: str, css: str = "") -> str:
    raw = (f"<style>{css}</style>" if css else "") + html
    return sanitise_skeleton(raw).html


class TestHtmlAttacks:
    @pytest.mark.parametrize("payload", [
        "<script>alert(1)</script>",
        "<SCRIPT SRC=//evil.js></SCRIPT>",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)><path d='M0 0'/></svg>",
        "<svg><script>alert(1)</script></svg>",
        "<a href='javascript:alert(1)'>x</a>",
        "<a href='JaVaScRiPt:alert(1)'>x</a>",
        "<a href='&#106;avascript:alert(1)'>x</a>",
        "<a href='data:text/html;base64,PHNjcmlwdD4='>x</a>",
        "<iframe src='https://evil.example'></iframe>",
        "<object data='x'></object><embed src='x'>",
        "<form action='https://evil.example'><input name=p></form>",
        "<meta http-equiv='refresh' content='0;url=https://evil.example'>",
        "<base href='https://evil.example/'>",
        "<div onclick='x()' onmouseover='y()'>x</div>",
        "<div style='background:url(javascript:alert(1))'>x</div>",
        "<svg><foreignObject><div>x</div></foreignObject></svg>",
        "<svg><use href='https://evil.example/s.svg#a'/></svg>",
        "<math><mi xlink:href='javascript:alert(1)'>x</mi></math>",
        "<noscript><img src=x onerror=alert(1)></noscript>",
        "<a href='https://evil.example'>external</a>",
    ])
    def test_nothing_dangerous_survives(self, payload):
        out = clean("<section>" + payload + "</section>").lower()
        for bad in ("<script", "onerror", "onload", "onclick", "onmouseover", "javascript:", "<iframe", "<object",
                    "<embed", "<form", "<input", "<meta", "<base", "<foreignobject", "<use", "evil.example",
                    "data:text", "style=", "src="):
            assert bad not in out, f"{bad!r} survived in {out!r}"

    def test_entity_and_unicode_tricks_do_not_resurrect_a_handler(self):
        out = clean("<div on&#x63;lick='x()'>a</div><img src=x on&#101;rror=y()>")
        assert "onclick" not in out and "onerror" not in out

    def test_malformed_nesting_is_repaired_not_passed_through(self):
        out = clean("<div><p>one<div>two</p></span><script>x</script>")
        assert "<script" not in out and "two" in out

    def test_comments_are_removed(self):
        assert "<!--" not in clean("<p>a</p><!-- <script>x</script> -->")

    def test_pasted_document_head_and_title_do_not_leak(self):
        out = sanitise_skeleton("<!doctype html><html><head><title>LEAK</title><meta charset=utf-8></head>"
                                "<body><p>hi</p></body></html>").html
        assert "LEAK" not in out and "hi" in out

    def test_removed_things_are_reported_for_the_retry_feedback(self):
        r = sanitise_skeleton("<script>x</script><div onclick='a()' style='color:red'>x</div><a href='https://e.com'>l</a>")
        text = " ".join(r.removed)
        assert "<script>" in text and "onclick" in text and "inline style" in text and "links come from slots" in text

    def test_in_page_anchors_and_slot_markers_are_kept(self):
        out = clean('<nav><a href="#about">About</a></nav><h1 data-slot="hero.headline" data-section="hero">x</h1>'
                    '<a data-slot-href="whatsapp">Chat</a><li data-repeat="items"></li>')
        assert 'href="#about"' in out and 'data-slot="hero.headline"' in out
        assert 'data-slot-href="whatsapp"' in out and 'data-repeat="items"' in out

    def test_bad_slot_path_is_dropped(self):
        out = clean('<h1 data-slot="a b<c">x</h1>')
        assert "data-slot" not in out

    def test_safe_svg_is_kept_with_case(self):
        out = clean('<svg viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g">'
                    '<stop offset="0" stop-color="#fff"/></linearGradient></defs><path d="M0 0L1 1" fill="url(#g)"/></svg>')
        assert "viewBox" in out and "<linearGradient" in out and 'fill="url(#g)"' in out

    def test_svg_paint_with_external_url_is_dropped(self):
        out = clean('<svg><path d="M0 0" fill="url(https://evil.example/x)"/></svg>')
        assert "evil.example" not in out

    def test_wrong_xmlns_is_dropped(self):
        assert "evil" not in clean('<svg xmlns="http://evil.example/ns"><path d="M0 0"/></svg>')

    def test_aria_attributes_allowed(self):
        assert 'aria-label="x"' in clean('<div aria-label="x">a</div>')

    def test_empty_input_rejected(self):
        with pytest.raises(SanitiseError):
            sanitise_skeleton("   ")

    def test_only_unsafe_content_is_rejected(self):
        with pytest.raises(SanitiseError):
            sanitise_skeleton("<script>alert(1)</script>")

    def test_oversize_rejected(self):
        with pytest.raises(SanitiseError) as ei:
            sanitise_skeleton("<p>" + "a" * (MAX_TOTAL_BYTES + 10) + "</p>")
        assert "too large" in str(ei.value)

    def test_sanitise_html_is_idempotent(self):
        once = sanitise_html('<div class="a"><p data-slot="hero.headline">x</p></div>')
        assert sanitise_html(once) == once


class TestCssAttacks:
    @pytest.mark.parametrize("css,why", [
        ("@import url('https://evil.example/x.css');", "@import"),
        ("@import 'x.css';", "@import"),
        (".a{background:url(https://evil.example/x.png)}", "url"),
        (".a{background:url('https://evil.example/x.png')}", "url"),
        (".a{background:\\75rl(https://evil.example/x.png)}", "url"),       # escaped 'url'
        (".a{background:u\\72l(x)}", "url"),
        (".a{background-image:image-set('x.png' 1x)}", "image-set"),
        ("@media screen{.a{background:-webkit-image-set(url(x) 1x)}}", "url"),
        (".a{width:expression(alert(1))}", "expression"),
        (".a{behavior:url(x.htc)}", "behavior"),
        (".a{-moz-binding:url(x)}", "-moz-binding"),
        ("@font-face{font-family:x;src:local('x')}", "@font-face"),
        ("@charset 'utf-8';.a{color:red}", "@charset"),
        ("@namespace svg url(http://www.w3.org/2000/svg);", "@namespace"),
        (".a{content:'</style><script>alert(1)</script>'}", "<"),
        ("/* </style><script>alert(1)</script> */.a{color:red}", "<"),
        (":root{--x:url(https://evil.example/x)}", "url"),
        (".a{background:var(--x,url(https://evil.example/x))}", "url"),
        ("@supports (background:url(x)){.a{color:red}}", "url"),
        ("@keyframes k{from{background:url(x)}to{color:red}}", "url"),
    ])
    def test_rejected(self, css, why):
        with pytest.raises(SanitiseError):
            sanitise_css(css)

    def test_good_css_passes_and_keeps_media_and_keyframes(self):
        out = sanitise_css(GOOD_CSS + "@keyframes k{from{opacity:0}to{opacity:1}}")
        assert "@media" in out and "@keyframes" in out and "--accent:#2F4BFF" in out

    def test_comments_are_dropped(self):
        assert "hello" not in sanitise_css("/* hello */.a{color:red}")

    def test_output_has_no_angle_bracket(self):
        assert "<" not in sanitise_css(GOOD_CSS)

    def test_oversize_css_rejected(self):
        with pytest.raises(SanitiseError):
            sanitise_css(".a{color:red}" * 20_000)

    def test_css_in_style_tag_is_validated_in_the_full_pipeline(self):
        with pytest.raises(SanitiseError):
            sanitise_skeleton("<style>.a{background:url(https://evil.example/x)}</style><p>hi</p>")

    def test_all_errors_are_listed_once(self):
        with pytest.raises(SanitiseError) as ei:
            sanitise_css("@import 'a';@import 'b';.a{background:url(x)}")
        assert len(ei.value.errors) == len(set(ei.value.errors))
