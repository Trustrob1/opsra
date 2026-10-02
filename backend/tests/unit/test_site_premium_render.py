"""
tests/unit/test_site_premium_render.py
---------------------------------------
SITE-PREMIUM P1 - fonts, slot checks, slot rendering and the page head. Pure functions, no network.
"""
from __future__ import annotations

import json
import re

import pytest

from app.services import site_premium_fonts as fonts
from app.services import site_premium_renderer as r
from app.services import site_premium_slots as slots

CSS = (":root{--accent:#2F4BFF;--accent-ink:#FFFFFF;--bg:#F5F6F4;--ink:#0E1B2C}"
       "body{font-family:var(--font-body);background:var(--bg)}h1,h2{font-family:var(--font-head);color:var(--ink)}"
       ".btn{background:var(--accent);color:var(--accent-ink)}")

SKELETON = """
<header data-section="nav"><b data-slot="business.name"></b>
<a class="btn" data-slot-href="whatsapp" href="#x">Order on WhatsApp</a></header>
<section data-section="hero" data-layout="split"><h1 data-slot="hero.headline"></h1>
<p data-slot="hero.subhead"></p><img data-slot-img="hero.image" data-priority="high" alt="The shop">
<a class="btn" data-slot-href="whatsapp">Chat now</a></section>
<section data-section="items"><ul>
<li data-repeat="items"><h3 data-slot="name"></h3><span data-slot="price_ngn" data-format="price"></span>
<span data-if="tag" data-slot="tag"></span><img data-slot-img="image" alt="item">
<a data-slot-href="whatsapp">Order this</a></li></ul></section>
<section data-if="about.owner"><p data-repeat="about.body" data-slot="."></p><i data-slot="about.owner"></i></section>
<footer><a data-slot-href="instagram">Instagram</a><a data-slot-href="maps">Find us</a></footer>
"""

CONTENT = {
    "business": {"name": "Adaeze <Styles> & Co", "city": "Lagos", "whatsapp_e164": "+2348030000000",
                 "phone_display": "0803 000 0000", "instagram": "@adaezastyles"},
    "hero": {"headline": "Dressed for the day", "subhead": "", "image_asset_id": "a-hero"},
    "about": {"title": "", "body": ["Para one.", "Para <two>."], "owner": "Adaeze", "pull_quote": ""},
    "items": [
        {"name": "Ankara dress", "price_ngn": 15000, "price_style": "exact", "tag": "New", "image_asset_id": "a-1"},
        {"name": "Custom gown", "price_ngn": 0, "price_style": "on_request", "image_asset_id": None},
        {"name": "Lace set", "price_ngn": 42500.5, "price_style": "from"},
    ],
    "location": {"address": "12 Admiralty Way, Lekki", "landmark": ""},
    "seo": {"title": "Adaeze Styles | Fashion, Lagos", "description": "Ready-to-wear and made-to-measure fashion in Lekki."},
}
ASSETS = {"a-hero": {"public_url": "https://cdn.example/hero.jpg", "export_path": "images/hero.jpg", "width": 1600, "height": 900},
          "a-1": {"public_url": "https://cdn.example/1.jpg", "export_path": "images/1.jpg"}}


def design(**over):
    d = {"skeleton_html": SKELETON, "skeleton_css": CSS, "tokens": r.extract_root_tokens(CSS),
         "art_direction": {"headline_font": "Outfit", "body_font": "Hanken Grotesk"}}
    d.update(over)
    return d


def page(content=CONTENT, export=False, **kw):
    return r.render_premium_page(content=content, design=design(), assets_by_id=ASSETS, export=export, **kw)


# ---------------------------------------------------------------- fonts

class TestFonts:
    def test_registry_sizes(self):
        assert len(fonts.HEADLINE_FONTS) == 20 and len(fonts.BODY_FONTS) == 6

    def test_no_banned_font_is_in_the_registry(self):
        names = {n.lower() for n in list(fonts.HEADLINE_FONTS) + list(fonts.BODY_FONTS)}
        assert not (names & fonts.BANNED_FONTS)

    @pytest.mark.parametrize("name", ["Playfair Display", "Fraunces", "Instrument Serif", "Inter", "Roboto",
                                      "Arial", "Open Sans", "Poppins", "Space Grotesk", "inter"])
    def test_banned_fonts_rejected(self, name):
        with pytest.raises(fonts.FontError):
            fonts.validate_fonts(name, "Hanken Grotesk")
        with pytest.raises(fonts.FontError):
            fonts.validate_fonts("Outfit", name)

    def test_unknown_font_rejected_and_headline_cannot_be_a_body_font(self):
        with pytest.raises(fonts.FontError):
            fonts.validate_fonts("Comic Sans", "Hanken Grotesk")
        with pytest.raises(fonts.FontError):
            fonts.validate_fonts("Hanken Grotesk", "Hanken Grotesk")

    def test_url_is_one_stylesheet_with_two_families(self):
        url = fonts.font_url("Bricolage Grotesque", "Karla")
        assert url.startswith("https://fonts.googleapis.com/css2?") and url.count("family=") == 2
        assert "Bricolage+Grotesque" in url and url.endswith("&display=swap")

    def test_every_headline_has_a_proposed_body_pair(self):
        for name, spec in fonts.HEADLINE_FONTS.items():
            assert fonts.PROPOSED_PAIRS[spec["group"]], name

    def test_niche_table_uses_registry_fonts_only(self):
        for niche, names in fonts.NICHE_HEADLINES.items():
            assert all(n in fonts.HEADLINE_FONTS for n in names), niche

    def test_default_pair_is_valid(self):
        h, b = fonts.default_pair()
        fonts.validate_fonts(h, b)


# ---------------------------------------------------------------- slot checks

class TestSlotChecks:
    def test_good_skeleton_has_no_errors(self):
        manifest, errors = slots.analyse(SKELETON, CONTENT)
        assert errors == []
        assert manifest["whatsapp_links"] == 3
        kinds = {(s["path"], s["kind"]) for s in manifest["slots"]}
        assert ("items", "repeat") in kinds and ("hero.image", "image") in kinds

    def test_required_slots(self):
        _, errors = slots.analyse("<p>hello</p>", CONTENT)
        text = " ".join(errors)
        assert "business.name" in text and "hero.headline" in text and "WhatsApp link" in text and "data-repeat='items'" in text

    def test_items_repeat_not_required_when_site_has_no_items(self):
        _, errors = slots.analyse(SKELETON.replace('data-repeat="items"', ""), {**CONTENT, "items": []})
        assert not any("items" in e for e in errors)

    @pytest.mark.parametrize("snippet,expect", [
        ('<p data-slot="made.up.path"></p>', "not in the content"),
        ('<ul><li data-repeat="business.name"></li></ul>', "not a list"),
        ('<p data-slot="items"></p>', "group"),
        ('<div data-slot-img="hero.image"></div>', "<img>"),
        ('<div data-slot-href="whatsapp"></div>', "<a>"),
        ('<a data-slot-href="https"></a>', "not one of"),
        ('<a data-slot-href="whatsapp:nope"></a>', "unknown"),
        ('<p data-slot="hero.headline" data-format="euro"></p>', "data-format"),
        ('<p data-if="nope.nope"></p>', "data-if"),
    ])
    def test_invalid_markers(self, snippet, expect):
        _, errors = slots.analyse(SKELETON + snippet, CONTENT)
        assert any(expect in e for e in errors), errors

    def test_custom_fields_are_allowed_and_listed(self):
        manifest, errors = slots.analyse(SKELETON + '<p data-slot="custom.badge_text"></p>', CONTENT)
        assert errors == [] and manifest["custom"] == ["custom.badge_text"]

    def test_paths_inside_a_repeat_resolve_against_the_item(self):
        _, errors = slots.analyse(SKELETON.replace('data-slot="name"', 'data-slot="price_ngn" data-format="naira"'), CONTENT)
        assert errors == []
        _, errors = slots.analyse(SKELETON.replace('data-slot="name"', 'data-slot="nonsense"'), CONTENT)
        assert errors


# ---------------------------------------------------------------- css contract

class TestCssContract:
    def test_good(self):
        assert r.css_contract_errors(CSS) == []

    def test_missing_declaration_and_use(self):
        errs = r.css_contract_errors("body{color:#000}")
        assert any("--accent" in e for e in errs) and any("var(--font-head)" in e for e in errs)

    def test_colour_must_be_hex_in_root(self):
        errs = r.css_contract_errors(CSS.replace("--accent:#2F4BFF", "--accent:blue"))
        assert any("declare --accent" in e for e in errs)

    def test_tokens_extracted(self):
        assert r.extract_root_tokens(CSS) == {"--accent": "#2F4BFF", "--accent-ink": "#FFFFFF", "--bg": "#F5F6F4", "--ink": "#0E1B2C"}


# ---------------------------------------------------------------- slot rendering

class TestRendering:
    def test_text_is_escaped(self):
        html = page()
        assert "Adaeze &lt;Styles&gt; &amp; Co" in html and "Para &lt;two&gt;." in html
        assert "<Styles>" not in html

    def test_script_in_content_cannot_execute(self):
        c = json.loads(json.dumps(CONTENT))
        c["hero"]["headline"] = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        c["business"]["name"] = '"><script>alert(2)</script>'
        html = page(c)
        assert "<script>alert" not in html and "<img src=x" not in html
        assert html.count("<script") == 1                      # only the JSON-LD block

    def test_repeat_renders_one_block_per_item_and_relative_paths_work(self):
        html = page()
        assert html.count("<h3>") == 3
        assert "Ankara dress" in html and "Custom gown" in html and "Lace set" in html

    def test_price_formats(self):
        html = page()
        assert "₦15,000" in html and "Price on request" in html and "From ₦42,500" in html

    def test_if_drops_when_value_missing(self):
        html = page()
        assert html.count(">New<") == 1                         # only the first item has a tag

    def test_data_if_on_section_hides_it(self):
        c = json.loads(json.dumps(CONTENT)); c["about"]["owner"] = ""
        assert "Para one." not in page(c)

    def test_empty_slot_drops_element(self):
        html = page()                                           # hero.subhead is ""
        assert "<p></p>" not in html

    def test_repeat_of_plain_strings(self):
        html = page()
        assert "<p>Para one.</p>" in html

    def test_images_resolve_to_the_sites_own_assets(self):
        html = page()
        assert 'src="https://cdn.example/hero.jpg"' in html and 'fetchpriority="high"' in html
        assert 'width="1600"' in html and 'height="900"' in html
        assert 'src="https://cdn.example/1.jpg"' in html and 'loading="lazy"' in html

    def test_export_uses_local_paths(self):
        html = page(export=True)
        assert 'src="images/hero.jpg"' in html and "cdn.example" not in html

    def test_foreign_asset_id_gets_a_placeholder_not_a_url(self):
        c = json.loads(json.dumps(CONTENT)); c["hero"]["image_asset_id"] = "someone-elses-asset"
        html = page(c)
        assert "someone-elses-asset" not in html and "slot-ph" in html and 'role="img"' in html

    def test_missing_image_gets_a_labelled_placeholder(self):
        assert page().count('class="slot-ph"') == 2                     # item 2 and item 3 have no photo

    def test_whatsapp_links_are_built_here(self):
        html = page()
        links = re.findall(r'href="(https://wa\.me/[^"]+)"', html)
        assert links and all(l.startswith("https://wa.me/2348030000000?text=") for l in links)
        assert any("Ankara%20dress" in l for l in links)       # item-specific message
        assert 'rel="noopener"' in html and 'target="_blank"' in html

    def test_skeleton_href_never_overrides_the_slot(self):
        html = page()
        assert 'href="#x"' not in html

    def test_other_links(self):
        html = page()
        assert 'href="https://instagram.com/adaezastyles"' in html
        assert "google.com/maps/search/?api=1&amp;query=12%20Admiralty%20Way%2C%20Lekki" in html

    def test_link_dropped_when_content_cannot_support_it(self):
        c = json.loads(json.dumps(CONTENT)); c["business"]["instagram"] = ""; c["location"]["address"] = ""
        html = page(c)
        assert "instagram.com" not in html and "Find us" not in html

    def test_unsafe_instagram_handle_is_ignored(self):
        c = json.loads(json.dumps(CONTENT)); c["business"]["instagram"] = 'x"><script>'
        assert "instagram.com" not in page(c)

    def test_no_slot_markers_leak_into_output(self):
        html = page()
        for marker in ("data-slot", "data-repeat", "data-if", "data-format", "data-section", "data-layout", "data-priority"):
            assert marker not in html

    def test_repeat_is_capped(self):
        c = json.loads(json.dumps(CONTENT)); c["items"] = [{"name": f"n{i}", "price_ngn": 1} for i in range(200)]
        assert page(c).count("<h3>") == r.MAX_REPEAT


# ---------------------------------------------------------------- page head

class TestPageHead:
    def test_preview_is_noindex_with_bar_and_no_canonical(self):
        html = page()
        assert 'content="noindex, nofollow"' in html and "PREVIEW" in html and "canonical" not in html

    def test_export_is_indexable_with_canonical_and_og(self):
        html = page(export=True, canonical_domain="adaezastyles.com.ng")
        assert 'content="index, follow, max-image-preview:large"' in html and "PREVIEW" not in html
        assert '<link rel="canonical" href="https://adaezastyles.com.ng/">' in html
        assert 'property="og:url" content="https://adaezastyles.com.ng/"' in html
        assert '<title>Adaeze Styles | Fashion, Lagos</title>' in html

    def test_fonts_come_from_the_registry_and_variables_are_written_last(self):
        html = page()
        assert "family=Outfit" in html and "family=Hanken+Grotesk" in html
        style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
        assert style.index(".btn{") < style.index("--font-head:'Outfit'")

    def test_unregistered_font_cannot_be_rendered(self):
        with pytest.raises(fonts.FontError):
            r.render_premium_page(content=CONTENT, design=design(art_direction={"headline_font": "Inter", "body_font": "Karla"}),
                                  assets_by_id={}, export=False)

    def test_json_ld_is_valid_json_and_cannot_break_out(self):
        c = json.loads(json.dumps(CONTENT)); c["business"]["name"] = "</script><script>alert(1)</script>"
        html = page(c, export=True, canonical_domain="x.com.ng")
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(block)
        assert data["@type"] == "LocalBusiness" and data["name"].startswith("</script>")
        assert "<" not in block

    def test_json_ld_uses_only_real_content(self):
        c = json.loads(json.dumps(CONTENT)); c["business"]["instagram"] = ""
        html = page(c, export=True, canonical_domain="x.com.ng")
        data = json.loads(re.search(r'ld\+json">(.*?)</script>', html, re.S).group(1))
        assert data["telephone"] == "+08030000000".replace("+0", "+0") or data["telephone"].startswith("+")
        assert "sameAs" not in data and data["address"]["streetAddress"] == "12 Admiralty Way, Lekki"

    def test_reduced_motion_backstop_present(self):
        assert "prefers-reduced-motion" in page()

    def test_theme_color_from_tokens(self):
        assert '<meta name="theme-color" content="#F5F6F4">' in page()

    def test_no_external_scripts_or_handlers_in_the_whole_page(self):
        html = page()
        assert "<script src" not in html and " onclick" not in html
