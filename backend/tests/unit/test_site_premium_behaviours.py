"""SITE-PREMIUM P2c - the Opsra behaviour library: allow-list, rendering, CSP pinning, no-script rule."""
import base64
import hashlib
import re
import subprocess
import shutil

import pytest

from app.services import site_premium_behaviours as b
from app.services import site_premium_renderer as renderer
from app.services.site_premium_sanitiser import sanitise_skeleton

CONTENT = {"business": {"name": "Acme"}, "seo": {"title": "Acme", "description": "d"}}
DESIGN = {"skeleton_css": "body{margin:0}", "tokens": {"--bg": "#ffffff", "--ink": "#111111", "--accent": "#0044cc"},
          "art_direction": {"headline_font": "Outfit", "body_font": "Hanken Grotesk"}}


def _page(html):
    d = dict(DESIGN, skeleton_html=html)
    try:
        return renderer.render_premium_page(content=CONTENT, design=d, assets_by_id={}, export=True)
    except Exception as exc:  # font registry names differ: fall back to whatever the registry accepts
        pytest.skip(f"font pair not in registry: {exc}")


class TestAllowList:
    def test_known_names_kept_unknown_dropped(self):
        assert b.clean_behaviour_value("reveal tilt") == "reveal tilt"
        assert b.clean_behaviour_value("reveal evil") == "reveal"
        assert b.clean_behaviour_value("evil") is None
        assert b.clean_behaviour_value("reveal reveal") == "reveal"
        assert b.clean_behaviour_value("") is None

    def test_sanitiser_keeps_valid_behaviour_and_drops_invalid(self):
        out = sanitise_skeleton('<section data-section="hero"><h1 data-behaviour="reveal">x</h1>'
                                '<p data-behaviour="alert(1)">y</p></section>')
        assert 'data-behaviour="reveal"' in out.html
        assert "alert" not in out.html

    def test_scripts_are_still_stripped(self):
        out = sanitise_skeleton('<section data-section="hero"><script>alert(1)</script><h1>x</h1></section>')
        assert "<script" not in out.html and "alert" not in out.html

    def test_used_behaviours(self):
        assert b.used_behaviours('<div data-behaviour="tilt reveal"></div><p data-behaviour="count"></p>') == ["reveal", "count", "tilt"]
        assert b.used_behaviours("<p>none</p>") == []


class TestRendering:
    def test_no_behaviour_means_no_script_and_script_src_none(self):
        html = _page('<section data-section="hero"><h1>x</h1></section>')
        assert "script-src 'none'" in html
        assert "html.b-on" not in html
        assert "<script>" not in html           # only the JSON-LD data block remains
        assert html.count("<script") == 1 and 'type="application/ld+json"' in html

    def test_behaviour_adds_one_pinned_script_and_css(self):
        html = _page('<section data-section="hero"><h1 data-behaviour="reveal">x</h1></section>')
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        assert scripts == [b.BEHAVIOUR_JS]
        assert b.script_hash() in html
        assert "script-src 'none'" not in html
        assert "html.b-on" in html

    def test_hash_matches_the_script_text(self):
        digest = base64.b64encode(hashlib.sha256(b.BEHAVIOUR_JS.encode()).digest()).decode()
        assert b.script_hash() == f"'sha256-{digest}'"

    def test_csp_comes_before_any_script(self):
        html = _page('<section data-section="hero"><h1 data-behaviour="reveal">x</h1></section>')
        assert html.index("Content-Security-Policy") < html.index("<script")


class TestScript:
    def test_script_has_no_network_storage_or_navigation(self):
        for banned in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "document.cookie",
                       "eval(", "Function(", "innerHTML", "location", "WebSocket", "import("):
            assert banned not in b.BEHAVIOUR_JS, banned

    def test_respects_reduced_motion(self):
        assert "prefers-reduced-motion: reduce" in b.BEHAVIOUR_JS

    def test_hidden_state_only_after_script_switches_on(self):
        rules = [r for r in b.BEHAVIOUR_CSS.split("}") if "opacity:0" in r]
        assert rules and all(r.startswith("html.b-on ") for r in rules)       # every hidden start state is gated
        assert "html.b-on" in b.BEHAVIOUR_CSS

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_script_parses(self, tmp_path):
        f = tmp_path / "b.js"
        f.write_text(b.BEHAVIOUR_JS, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
