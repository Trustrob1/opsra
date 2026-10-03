"""
tests/unit/test_site_premium_checks.py
---------------------------------------
SITE-PREMIUM P1b - the static design checks (spec 13A) and their wiring into the staff import.
Pure functions plus the in-memory FakeDB; no network, no browser.
"""
from __future__ import annotations

import pytest

from app.services import site_premium_checks as c
from app.services import site_premium_service as svc
from app.services.site_ops_service import ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_premium_render import ASSETS, CONTENT, SKELETON

GOOD_CSS = (":root{--accent:#CE8EE3;--accent-ink:#1B0E20;--bg:#150B19;--ink:#F6EEF1;--muted:#B9AABF}"
            "body{font-family:var(--font-body);background:var(--bg);color:var(--ink)}"
            "h1,h2{font-family:var(--font-head)}.btn{background:var(--accent);color:var(--accent-ink)}"
            "@media (prefers-reduced-motion:reduce){*{animation:none}}")


def run(css=GOOD_CSS, html=SKELETON, head="Bodoni Moda", body="Hanken Grotesk", **kw):
    return c.run_static_checks(html, css, head, body, **kw)


class TestColourMaths:
    def test_contrast_ratio(self):
        assert c.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, rel=1e-3)
        assert c.contrast_ratio("#777777", "#777777") == pytest.approx(1.0)

    def test_brown_gold_range(self):
        for tan in ("#C8A165", "#B08D57", "#A67C52", "#D4AF37", "#C3A27A"):
            assert c.is_brown_gold(tan), tan
        for ok in ("#2438A8", "#CE8EE3", "#C8D400", "#7A1F2B", "#0F9D58", "#FF4500"):
            assert not c.is_brown_gold(ok), ok


class TestAccepted:
    def test_a_good_design_has_no_findings(self):
        assert run() == {"errors": [], "warnings": []}


class TestHardErrors:
    def test_brown_gold_accent(self):
        out = run(GOOD_CSS.replace("#CE8EE3", "#C8A165"))
        assert any("brown-gold" in e for e in out["errors"])

    def test_text_contrast_too_low(self):
        out = run(GOOD_CSS.replace("--ink:#F6EEF1", "--ink:#3A2A40"))
        assert any("Text colour" in e for e in out["errors"])

    def test_button_contrast_too_low(self):
        out = run(GOOD_CSS.replace("--accent-ink:#1B0E20", "--accent-ink:#D9A8EA"))
        assert any("Button text" in e for e in out["errors"])

    def test_css_cannot_name_a_font(self):
        out = run(GOOD_CSS + "p{font-family:Arial,sans-serif}")
        assert any("names the font" in e for e in out["errors"])

    def test_generic_and_variable_families_are_fine(self):
        assert run(GOOD_CSS + "code{font-family:monospace}")["errors"] == []

    def test_pairing_rule(self):
        out = run(head="Anton", body="Karla")           # condensed pairs only with Hanken Grotesk / Figtree
        assert any("cannot be paired" in e for e in out["errors"])
        assert run(head="Anton", body="Figtree")["errors"] == []
        assert run(head="Bodoni Moda", body="DM Sans")["errors"] == []
        assert run(head="Outfit", body="DM Sans")["errors"] != []      # geometric sans avoids DM Sans


class TestWarnings:
    def test_pure_black_or_white(self):
        out = run(GOOD_CSS + "a{color:#FFFFFF}")
        assert any("pure #000000 or #FFFFFF" in w for w in out["warnings"])

    def test_cream_and_brass(self):
        assert any("cream" in w for w in run(GOOD_CSS + ".x{background:#F4F1EA}")["warnings"])
        assert any("Brass" in w for w in run(GOOD_CSS + ".x{color:#B08D57}")["warnings"])

    def test_missing_reduced_motion(self):
        out = run(GOOD_CSS.replace("@media (prefers-reduced-motion:reduce){*{animation:none}}", ""))
        assert any("reduced-motion" in w for w in out["warnings"])

    def test_height_100vh_and_cursor(self):
        out = run(GOOD_CSS + ".hero{height:100vh}body{cursor:none}")
        text = " ".join(out["warnings"])
        assert "100vh" in text and "cursor" in text
        assert not any("100vh" in w for w in run(GOOD_CSS + ".hero{min-height:100vh}")["warnings"])

    def test_two_marquees(self):
        out = run(GOOD_CSS + "@keyframes marquee-a{from{opacity:0}to{opacity:1}}@keyframes ticker-b{from{opacity:0}to{opacity:1}}")
        assert any("marquee" in w for w in out["warnings"])

    def test_static_wording(self):
        html = '<section data-section="hero"><h1 data-slot="hero.headline"></h1><p>Elevate your look — seamlessly \U0001F600</p></section>'
        text = " ".join(run(html=html)["warnings"])
        assert "em-dash" in text and "emoji" in text and "filler" in text

    def test_client_content_is_never_scanned(self):
        # the em-dash sits in a slot element, which is client content filled at render time
        html = '<section data-section="hero"><h1 data-slot="hero.headline">A — B</h1></section>'
        assert run(html=html)["warnings"] == []

    def test_too_many_eyebrows(self):
        html = "".join(f'<section data-section="s{i}"><span data-role="eyebrow">x</span></section>' for i in range(3))
        assert any("eyebrow" in w for w in run(html=html)["warnings"])

    def test_crowded_hero(self):
        html = ('<section data-section="hero"><span>a</span><h1>b</h1><p>c</p><p>d</p><p>e</p></section>')
        assert any("text elements" in w for w in run(html=html)["warnings"])

    def test_long_static_subtext(self):
        html = '<section data-section="hero"><h1>x</h1><p>' + " ".join(["word"] * 25) + "</p></section>"
        assert any("20 or fewer" in w for w in run(html=html)["warnings"])

    def test_layout_variety_and_split_runs(self):
        same = "".join(f'<section data-section="s{i}" data-layout="grid"></section>' for i in range(8))
        assert any("at least 4 different layouts" in w for w in run(html=same)["warnings"])
        splits = "".join(f'<section data-section="s{i}" data-layout="image-split"></section>' for i in range(3))
        assert any("split sections in a row" in w for w in run(html=splits)["warnings"])


class TestStrictMode:
    def test_warnings_become_errors(self):
        out = run(GOOD_CSS + "a{color:#FFFFFF}", strict=True)
        assert out["warnings"] == [] and any("pure #000000" in e for e in out["errors"])


def make_db():
    site = {"id": "site-1", "org_id": "org-1", "preset_id": "p1", "status": "preview_ready", "tier": "standard",
            "current_design_id": None, "content": CONTENT, "recipe": {}, "deleted_at": None}
    return FakeDB(sites=[site], site_designs=[])


GOOD_RAW = f"<style>{GOOD_CSS}</style>{SKELETON}"


class TestImportWiring:
    def test_clean_import_stores_static_result(self):
        db = make_db()
        out = svc.import_skeleton(db, "org-1", db.rows("sites")[0], "user:u1", GOOD_RAW, "Bodoni Moda", "Hanken Grotesk", ASSETS)
        row = db.rows("site_designs")[0]
        assert row["checks"]["static"] == {"errors": [], "warnings": []}
        assert out["warnings"] == []

    def test_warnings_are_saved_but_do_not_block(self):
        db = make_db()
        raw = GOOD_RAW.replace("</style>", "a{color:#FFFFFF}</style>")
        out = svc.import_skeleton(db, "org-1", db.rows("sites")[0], "user:u1", raw, "Bodoni Moda", "Hanken Grotesk", ASSETS)
        assert out["warnings"] and "pure #000000" in db.rows("site_designs")[0]["checks"]["static"]["warnings"][0]

    def test_hard_error_saves_nothing(self):
        db = make_db()
        raw = GOOD_RAW.replace("#CE8EE3", "#C8A165")
        with pytest.raises(ValidationFailed) as exc:
            svc.import_skeleton(db, "org-1", db.rows("sites")[0], "user:u1", raw, "Bodoni Moda", "Hanken Grotesk", ASSETS)
        assert "brown-gold" in str(exc.value)
        assert db.rows("site_designs") == []
        assert db.rows("sites")[0]["tier"] == "standard"

    def test_font_pair_is_enforced_on_import(self):
        db = make_db()
        with pytest.raises(ValidationFailed):
            svc.import_skeleton(db, "org-1", db.rows("sites")[0], "user:u1", GOOD_RAW, "Anton", "Karla", ASSETS)
