"""
tests/unit/test_site_renderer_capture.py
SITE-ADDONS A1-2 - the enquiry form and the tracked WhatsApp links in the Standard renderer, and the capture settings
helper. Pure unit tests (FakeDB for the helper).
"""
from __future__ import annotations

import copy
import re

from app.services import site_capture_service as cap
from app.services import site_renderer as r
from tests.funnel_fake_db import FakeDB
from tests.unit.test_site_sections import BASE, PRESET_OLD, _recipe

KEY = "sk_testkey123"
CAP = {"key": KEY, "form": True, "track": True, "form_action": f"https://api.example/api/v1/public/site-leads/{KEY}",
       "wa_base": f"https://api.example/sl/{KEY}/wa", "return_to": "https://bolabakes.ng/"}
RECIPE = _recipe(order=["hero", "items", "about", "order"])


def _render(capture=None, content=BASE, export=False):
    fn = r.render_export if export else r.render_page
    return fn(copy.deepcopy(content), RECIPE, PRESET_OLD, {}, capture=capture)


def test_without_capture_the_page_is_exactly_as_before():
    assert _render(None) == r.render_page(copy.deepcopy(BASE), RECIPE, PRESET_OLD, {})
    html = _render(None)
    assert "enq-form" not in html and "https://wa.me/2348012345678" in html and "/sl/" not in html


def test_the_form_is_a_plain_post_with_consent_and_a_hidden_trap_field():
    html = _render(CAP)
    assert f'<form class="enq-form" method="post" action="{CAP["form_action"]}"' in html
    for name in ("name", "phone", "email", "message", "website", "consent", "src", "return_to"):
        assert f'name="{name}"' in html
    assert 'name="consent" value="on" required' in html and 'class="enq-hp" aria-hidden="true"' in html
    assert "<script" not in html and "Bola Bakes may contact me" in html
    assert html.index('id="enquire"') < html.index("<footer")


def test_the_form_can_be_off_while_tracking_is_on_and_the_other_way_round():
    only_track = _render({**CAP, "form": False})
    assert "enq-form" not in only_track and f"/sl/{KEY}/wa" in only_track
    only_form = _render({**CAP, "track": False})
    assert "enq-form" in only_form and "/sl/" not in only_form and "https://wa.me/2348012345678" in only_form


def test_every_whatsapp_button_goes_through_the_tracked_link_with_where_it_sits():
    html = _render(CAP)
    assert "https://wa.me/" not in html
    hrefs = re.findall(r'href="([^"]*sl/sk_testkey123/wa[^"]*)"', html)
    assert hrefs and all(h.startswith(CAP["wa_base"] + "?src=") and "&amp;t=" in h for h in hrefs)
    srcs = {re.search(r"src=([^&]*)", h).group(1) for h in hrefs}
    assert "nav" in srcs and "hero" in srcs and any(s.startswith("product%3AChocolate") for s in srcs)


def test_the_message_text_travels_in_the_link_and_is_escaped():
    content = copy.deepcopy(BASE)
    content["items"][0]["name"] = 'Cake "X" <b>'
    html = _render(CAP, content)
    assert "<b>" not in html and "Cake &quot;X&quot; &lt;b&gt;" in html
    hrefs = re.findall(r'href="([^"]*sl/sk_testkey123/wa[^"]*)"', html)
    assert any("%3Cb%3E" in h and "Cake%20%22X%22" in h for h in hrefs)


def test_the_return_address_is_only_added_when_known():
    assert 'name="return_to" value="https://bolabakes.ng/"' in _render(CAP)
    assert 'name="return_to"' not in _render({**CAP, "return_to": None})


def test_the_export_gets_the_form_too_and_the_capture_data_never_lands_in_the_content():
    content = copy.deepcopy(BASE)
    html = _render(CAP, content, export=True)
    assert "enq-form" in html and "PREVIEW" not in html
    assert "_capture" not in content["business"]


def test_the_form_styles_are_in_the_page_only_when_the_form_is():
    assert ".enq-form" in _render(CAP) and ".enq-form" not in _render(None)


# -- the settings helper ------------------------------------------------------------------

def _db(tier_status="active", features=None):
    pricing = {"tiers": {"capture": {"features": features}}} if features is not None else {}
    return FakeDB(
        site_builder_settings=[{"org_id": "org-1", "enabled": True, "pricing": pricing}],
        sites=[{"id": "site-1", "org_id": "org-1", "deleted_at": None}],
        site_addons=[{"id": "t1", "org_id": "org-1", "site_id": "site-1", "kind": "tier", "key": "capture",
                      "status": tier_status, "source": "staff", "billing_mode": "link", "paid_until": None, "config": {}}]
        if tier_status else [],
        site_usage_counters=[], site_events=[], site_keys=[])


def test_render_config_for_a_capture_site_has_the_key_and_both_switches():
    db = _db()
    c = cap.render_config(db, "org-1", {"id": "site-1"}, return_to="https://x.ng/")
    assert c["form"] and c["track"] and c["key"].startswith("sk_") and c["return_to"] == "https://x.ng/"
    assert c["form_action"].endswith("/api/v1/public/site-leads/" + c["key"]) and c["wa_base"].endswith(f"/sl/{c['key']}/wa")
    assert cap.render_config(db, "org-1", {"id": "site-1"})["key"] == c["key"]          # same key every time


def test_render_config_follows_the_plan():
    assert cap.render_config(_db(tier_status=None), "org-1", {"id": "site-1"}) is None
    assert cap.render_config(_db(tier_status="paused"), "org-1", {"id": "site-1"}) is None
    c = cap.render_config(_db(features=["source_tracking"]), "org-1", {"id": "site-1"})
    assert c["track"] is True and c["form"] is False


def test_render_config_never_raises():
    class Broken:
        def table(self, *_):
            raise RuntimeError("db down")
    assert cap.render_config(Broken(), "org-1", {"id": "site-1"}) is None
