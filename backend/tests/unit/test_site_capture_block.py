"""
tests/unit/test_site_capture_block.py
SITE-ADDONS A1b - the enquiry form and tracked links on Premium and imported pages. Pure functions, no network.
"""
from __future__ import annotations

import re

from app.services import site_capture_block as block
from app.services import site_import_render as ir
from app.services import site_premium_renderer as r
from tests.unit.test_site_premium_render import CONTENT, design

CAP = {"key": "sk_abc", "form": True, "track": True, "form_action": "https://api.opsra.test/api/v1/public/site-leads/sk_abc",
       "wa_base": "https://api.opsra.test/sl/sk_abc/wa", "return_to": "https://adaeze.ng/"}
OFF = {**CAP, "form": False, "track": False}


# -- Premium --------------------------------------------------------------------------------

def page(cap, export=False):
    return r.render_premium_page(content=CONTENT, design=design(), assets_by_id={}, export=export,
                                 canonical_domain="adaeze.ng", capture=cap)


def test_premium_page_without_capture_is_unchanged():
    assert page(None) == page(None) and "opsra-enq" not in page(None) and "/sl/" not in page(None)
    assert "opsra-enq" not in page(OFF)


def test_premium_page_gets_one_form_before_the_footer_and_its_css():
    html = page(CAP, export=True)
    assert html.count("<form") == 1 and html.index("opsra-enq-sec") < html.index("<footer")
    assert 'action="https://api.opsra.test/api/v1/public/site-leads/sk_abc"' in html and 'name="website"' in html
    assert 'name="consent"' in html and "<script" not in html.split("opsra-enq-sec")[1].split("</section>")[0]
    assert ".opsra-enq{" in html and 'name="return_to" value="https://adaeze.ng/"' in html


def test_premium_business_name_is_escaped_in_the_form():
    html = page(CAP)
    assert "Adaeze &lt;Styles&gt; &amp; Co may contact me" in html


def test_premium_whatsapp_buttons_go_through_the_tracked_link_with_their_product():
    html = page(CAP)
    assert "wa.me/" not in html
    hrefs = re.findall(r'href="(https://api\.opsra\.test/sl/sk_abc/wa[^"]*)"', html)
    assert hrefs and any("src=product%3AAnkara%20dress" in h for h in hrefs) and any("src=premium" in h for h in hrefs)


def test_premium_form_only_plan_keeps_plain_whatsapp_links():
    html = page({**CAP, "track": False})
    assert "wa.me/2348030000000" in html and "/sl/sk_abc/wa" not in html and html.count("<form") == 1


def test_premium_track_only_plan_has_no_form():
    html = page({**CAP, "form": False})
    assert "<form" not in html and "/sl/sk_abc/wa" in html


# -- imported pages ---------------------------------------------------------------------------

CONTACT = ('<form action="https://formspree.io/f/x" method="post"><input name="your-name"><input type="email" name="email">'
           '<textarea name="message"></textarea><button>Send</button></form>')
SEARCH = '<form action="/search"><input type="search" name="q" placeholder="Search"></form>'
LOGIN = '<form><input name="email"><input type="password" name="pw"></form>'
NEWS = '<form><input type="email" name="email" placeholder="Your email"><button>Join</button></form>'


def test_only_contact_forms_are_replaced():
    html, n = block.replace_contact_forms(f"<main>{CONTACT}{SEARCH}{LOGIN}{NEWS}</main>", "Alfa <b>Cakes</b>", CAP)
    assert n == 1 and "formspree" not in html and SEARCH in html and LOGIN in html and NEWS in html
    assert html.count("opsra-enq") >= 1 and html.count("<style>") == 1
    assert "Alfa &lt;b&gt;Cakes&lt;/b&gt; may contact me" in html and 'name="src" value="imported-form"' in html


def test_two_contact_forms_share_one_style_block():
    html, n = block.replace_contact_forms(CONTACT + "<p>x</p>" + CONTACT, "Alfa", CAP)
    assert n == 2 and html.count("<style>") == 1 and html.count("opsra-hp") == 2 + html.count(".opsra-hp{")


def test_no_form_plan_leaves_the_page_alone():
    assert block.replace_contact_forms(CONTACT, "Alfa", OFF) == (CONTACT, 0)
    assert block.replace_contact_forms(CONTACT, "Alfa", None) == (CONTACT, 0)


def test_whatsapp_links_to_the_sites_own_number_are_tracked_others_are_not():
    page_html = ('<a href="https://wa.me/2348030000000?text=Hello%20there">a</a>'
                 '<a href="https://wa.me/2347000000000?text=x">other</a>'
                 '<a href="https://api.whatsapp.com/send?phone=2348030000000&amp;text=Hi">b</a>')
    out, n = block.track_wa_links(page_html, CAP, "+234 803 000 0000")
    assert n == 2 and "wa.me/2347000000000" in out and "wa.me/2348030000000" not in out
    assert 'href="https://api.opsra.test/sl/sk_abc/wa?src=imported&amp;t=Hello%20there"' in out
    assert "t=Hi" in out


def test_tracking_is_off_without_the_feature_or_a_number():
    h = '<a href="https://wa.me/2348030000000">a</a>'
    assert block.track_wa_links(h, {**CAP, "track": False}, "+2348030000000") == (h, 0)
    assert block.track_wa_links(h, CAP, "") == (h, 0)


def test_form_target_origin():
    assert block.form_target_origin(CAP) == "https://api.opsra.test"
    assert block.form_target_origin(OFF) is None and block.form_target_origin({**CAP, "form_action": "http://x/y"}) is None


def test_csp_allows_the_opsra_host_only_when_asked():
    assert "form-action https://wa.me https://api.whatsapp.com;" in ir.build_csp([]) + ";"
    csp = ir.build_csp([], extra_form_targets=("https://api.opsra.test",))
    assert "form-action https://wa.me https://api.whatsapp.com https://api.opsra.test;" in csp + ";"


def test_import_capture_step_returns_extra_form_origin_only_when_a_form_was_replaced():
    ident = {"name": "Alfa", "wa": "+2348030000000"}
    html, extra = ir._apply_capture(f"<body>{CONTACT}</body>", CAP, ident)
    assert extra == ("https://api.opsra.test",) and "opsra-enq" in html
    html2, extra2 = ir._apply_capture(f"<body>{SEARCH}</body>", CAP, ident)
    assert extra2 == () and html2 == f"<body>{SEARCH}</body>"
    assert ir._apply_capture("<p>x</p>", None, ident) == ("<p>x</p>", ())


# -- the real render path (plan check included) ------------------------------------------------

def _premium_db(with_plan=True):
    from tests.unit.test_site_capture_service import _db, _tier
    db = _db(tiers=[_tier()] if with_plan else [])
    db.tables["site_designs"] = [{"id": "d1", "org_id": "org-1", "site_id": "site-1", "status": "ready", **design()}]
    return db


def _site(tier="premium"):
    return {"id": "site-1", "org_id": "org-1", "tier": tier, "current_design_id": "d1", "client_business_name": "Adaeze",
            "content": CONTENT}


def test_render_if_premium_adds_the_form_only_when_the_plan_has_it():
    from app.services import site_premium_service as svc
    on = svc.render_if_premium(_premium_db(True), _site(), {}, export=True, canonical_domain="adaeze.ng")
    off = svc.render_if_premium(_premium_db(False), _site(), {}, export=True, canonical_domain="adaeze.ng")
    assert on and "opsra-enq" in on and "/sl/sk_" in on and 'name="return_to" value="https://adaeze.ng/"' in on
    assert off and "opsra-enq" not in off and "/sl/" not in off
