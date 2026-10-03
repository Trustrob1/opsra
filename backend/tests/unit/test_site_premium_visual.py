"""
tests/unit/test_site_premium_visual.py
---------------------------------------
SITE-PREMIUM P1b - the browser layout checks. Each test builds a small page, either clean or broken in
exactly the way we have met on real sites, and asserts the check says so. Skipped when Playwright or
Chromium is not installed (they are optional; run `pip install playwright` and `playwright install chromium`).
"""
from __future__ import annotations

import base64

import pytest

from app.services import site_premium_visual as v

# a 4x5 grey png, inline so the page needs no network
_PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000004000000050802000000e0b3d5dd0000000f49444154789c63"
    "646464f8cfc0c0c0f0ff3f0300a9b21c230000000049454e44ae426082")).decode()
IMG = f'<img alt="" src="data:image/png;base64,{_PNG}">'

BASE_CSS = ("*{box-sizing:border-box}body{margin:0;font:18px/1.5 sans-serif;background:#150B19;color:#F6EEF1}"
            "h1{font-size:clamp(34px,8vw,96px);line-height:1;margin:0}p{margin:0}"
            ".wrap{max-width:1200px;margin:0 auto;padding:0 24px}.btn{display:inline-block;padding:12px 24px;background:#CE8EE3;color:#1B0E20}"
            "header{height:64px;display:flex;align-items:center;padding:0 24px}")


def page(css: str, body: str) -> str:
    return f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><style>{BASE_CSS}{css}</style>{body}"


GOOD = page(
    ".hero .wrap{display:grid;gap:32px;grid-template-columns:1fr}.hero figure{margin:0;aspect-ratio:4/5;overflow:hidden}"
    ".hero img{width:100%;height:100%;object-fit:cover}"
    "@media(min-width:900px){.hero .wrap{grid-template-columns:7fr 5fr;align-items:center}}",
    f'<header data-section="nav"><b>Salon</b></header><section class="hero" data-section="hero"><div class="wrap">'
    f'<div><h1>The best natural hair salon in Lekki</h1><p>Best experience in town</p><a class="btn" href="#x">Book now</a></div>'
    f"<figure>{IMG}</figure></div></section>")

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("playwright"), reason="playwright not installed")


@pytest.fixture(scope="module")
def check():
    def _run(html, **kw):
        try:
            return v.run_visual_check(html, **kw)
        except v.VisualCheckUnavailable as exc:
            pytest.skip(str(exc))
    return _run


def checks_of(report, kind="errors"):
    return {e["check"] for e in report[kind]}


def test_clean_page_passes(check):
    rep = check(GOOD)
    assert rep["ok"], rep["errors"]
    assert rep["errors"] == []


def test_headline_running_under_the_photo(check):
    # the real bug of 2 Oct 2026: the headline spanned columns the photo also occupied
    bad = page(
        ".hero .wrap{position:relative;min-height:520px}.hero h1{width:90%;font-size:72px}"
        ".hero figure{position:absolute;right:24px;top:0;width:40%;height:500px;margin:0}.hero img{width:100%;height:100%}",
        '<header data-section="nav"><b>Salon</b></header><section class="hero" data-section="hero"><div class="wrap">'
        f"<h1>The best natural hair salon in Lekki</h1><figure>{IMG}</figure></div></section>")
    rep = check(bad, widths=(1440,))
    assert "text-over-photo" in checks_of(rep), rep


def test_a_caption_inside_its_own_photo_is_allowed(check):
    ok = page(".f{position:relative;width:400px;height:300px}.f img{width:100%;height:100%}.f span{position:absolute;left:12px;bottom:12px}",
              f'<figure class="f">{IMG}<span>Silk press</span></figure>')
    assert check(ok, widths=(1024,))["ok"]


def test_big_empty_gap_between_headline_and_copy(check):
    # the real bug of 3 Oct 2026: copy pushed to the bottom of a tall photo row
    bad = page(
        ".hero .wrap{display:grid;grid-template-columns:7fr 5fr;gap:32px;align-items:start}"
        ".hero h1{grid-column:1;grid-row:1}.hero .copy{grid-column:1;grid-row:2;align-self:end}"
        ".hero figure{grid-column:2;grid-row:1 / span 2;margin:0;height:900px}.hero img{width:100%;height:100%}",
        '<header data-section="nav"><b>Salon</b></header><section class="hero" data-section="hero"><div class="wrap">'
        f'<h1>The best natural hair salon</h1><div class="copy"><p>Best experience in town</p></div><figure>{IMG}</figure></div></section>')
    rep = check(bad, widths=(1440,))
    assert "empty-gap" in checks_of(rep), rep


def test_sideways_scroll_and_text_off_screen(check):
    bad = page(".w{width:1400px;white-space:nowrap}", '<header data-section="nav"><b>S</b></header><div class="w"><p>A very wide line</p></div>')
    rep = check(bad, widths=(390,))
    assert {"horizontal-scroll"} <= checks_of(rep)


def test_text_overlapping_text(check):
    bad = page(".a,.b{position:absolute;left:40px}.a{top:100px}.b{top:110px}",
               '<header data-section="nav"><b>S</b></header><p class="a">First line of text here</p><p class="b">Second line on top</p>')
    assert "text-overlap" in checks_of(check(bad, widths=(1024,)))


def test_text_clipped_by_its_container(check):
    bad = page(".box{height:24px;overflow:hidden;width:200px}", '<header data-section="nav"><b>S</b></header><div class="box"><p>This sentence is long enough to wrap onto several lines inside a narrow box.</p></div>')
    assert "text-clipped" in checks_of(check(bad, widths=(1024,)))


def test_ellipsis_text_is_not_clipping(check):
    ok = page(".b{width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}", '<header data-section="nav"><b>S</b></header><span class="b">A long business name here</span>')
    assert "text-clipped" not in checks_of(check(ok, widths=(1024,)))


def test_collapsed_photo_frame(check):
    bad = page("figure{margin:0;height:0}img{height:0}", f'<header data-section="nav"><b>S</b></header><figure>{IMG}</figure><p>Text</p>')
    assert "empty-photo-frame" in checks_of(check(bad, widths=(1024,)))


def test_hidden_phone_only_frame_is_ignored(check):
    ok = page(".aside{display:none}@media(min-width:900px){.aside{display:block;height:200px}}",
              f'<header data-section="nav"><b>S</b></header><figure class="aside"><div class="slot-ph" style="height:100%"></div></figure><p>x</p>')
    assert "empty-photo-frame" not in checks_of(check(ok, widths=(390,)))


def test_tall_nav_and_small_phone_headline(check):
    bad = page("header{height:120px}h1{font-size:20px}", '<header data-section="nav"><b>S</b></header><h1>Small headline</h1>')
    got = checks_of(check(bad, widths=(390,)))
    assert {"nav-too-tall", "headline-too-small"} <= got


def test_warnings(check):
    page_html = page(".btn{width:70px}.tiny{font-size:9px}.fab{display:inline-block;height:30px;padding:0 10px}",
                     '<header data-section="nav"><b>S</b></header><a class="btn" href="#x">Book on WhatsApp now</a>'
                     '<p class="tiny">Fine print</p><a class="fab" href="#y">Go</a>')
    rep = check(page_html, widths=(390,))
    assert {"button-wraps", "tiny-text", "small-tap-target"} <= checks_of(rep, "warnings")


def test_placeholders_are_counted_not_failed(check):
    ok = page(".slot-ph{width:100%;height:200px;background:#333}", '<header data-section="nav"><b>S</b></header><figure><div class="slot-ph"></div></figure><p>x</p>')
    rep = check(ok, widths=(1024,))
    assert rep["ok"] and rep["info"]["placeholders"] == 1


def test_screenshots_are_written(check, tmp_path):
    rep = check(GOOD, screenshot_dir=str(tmp_path), label="t")
    assert len(rep["screenshots"]) == 3 and all((tmp_path / f"t-{w}.png").exists() for w in v.WIDTHS)


def test_summary_text(check):
    rep = check(GOOD, widths=(1024,))
    assert v.summarise(rep).startswith("VISUAL CHECK: PASSED")
