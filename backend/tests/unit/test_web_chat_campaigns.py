"""OPENING-CTA-2: ads ("campaigns"): per-ad greeting and starting button keyed by the link's tag, and the pieces that carry the tag."""
from __future__ import annotations

import pathlib

from app.routers import public_webchat as router
from app.services import webchat_service as wc

MENU = [{"id": "buy", "label": "Place an order", "answer": "x"},
        {"id": "inspect", "label": "Book inspection", "action": "booking"},
        {"id": "faq", "label": "Prices", "answer": "y"},
        {"id": "talk", "label": "Talk to the team", "action": "human"}]
CAMPS = [{"tag": "lekki-3bed", "label": "Lekki 3-bed", "main": "inspect", "main_label": "", "greeting": "Hi, asking about the Lekki 3-bed?"},
         {"tag": "promo", "label": "Promo", "main": "buy", "main_label": "Buy now", "greeting": ""},
         {"tag": "gone", "label": "Gone", "main": "deleted", "main_label": "", "greeting": "Old ad greeting"}]


def _cfg(**kw):
    return wc.sanitise_config({}) | {"menu": MENU, "business_name": "T", "brand_color": "#028090", "greeting": "Hi, I'm Chioma.", "contact_prompt": "c",
                                     "consent_text": "c", "fallback": "f", "booking_fields": [], "campaigns": CAMPS, **kw}


# ── settings ────────────────────────────────────────────────────────────────

def test_default_has_no_campaigns():
    assert wc.DEFAULT_CONFIG["campaigns"] == []


def test_clean_keeps_good_entries_and_defaults_the_label():
    out = wc.sanitise_config({"campaigns": [{"tag": "Lekki-3-Bed", "label": "  Lekki  ", "main": "Inspect", "greeting": " Hello "}, {"tag": "x1"}]})["campaigns"]
    assert out[0] == {"tag": "lekki-3-bed", "label": "Lekki", "main": "inspect", "main_label": "", "greeting": "Hello"}
    assert out[1]["label"] == "x1" and out[1]["main"] == "" and out[1]["greeting"] == ""


def test_clean_drops_reserved_duplicate_empty_and_junk():
    raw = [{"tag": "instagram"}, {"tag": "whatsapp"}, {"tag": "link"}, {"tag": "a"}, {"tag": "A"}, {"tag": "!!!"}, {}, "x", None, 5]
    assert [c["tag"] for c in wc.sanitise_config({"campaigns": raw})["campaigns"]] == ["a"]
    assert wc.sanitise_config({"campaigns": "nope"})["campaigns"] == []


def test_clean_caps_count_and_lengths():
    many = [{"tag": f"t{i}"} for i in range(80)]
    assert len(wc.sanitise_config({"campaigns": many})["campaigns"]) == wc.CAMPAIGNS_MAX
    c = wc.sanitise_config({"campaigns": [{"tag": "t" * 80, "label": "l" * 200, "main_label": "m" * 200, "greeting": "g" * 900}]})["campaigns"][0]
    assert len(c["tag"]) == 30 and len(c["label"]) == 60 and len(c["main_label"]) == 40 and len(c["greeting"]) == 400


# ── lookup by the link's tag ────────────────────────────────────────────────

def test_campaign_for_matches_the_tag_and_ignores_the_rest():
    cfg = _cfg()
    assert wc.campaign_for(cfg, "lekki-3bed")["label"] == "Lekki 3-bed"
    assert wc.campaign_for(cfg, "LEKKI-3BED")["tag"] == "lekki-3bed"
    for none in (None, "", "instagram", "unknown", "website"):
        assert wc.campaign_for(cfg, none) is None


def test_greeting_for_uses_the_ad_greeting_else_the_normal_one():
    cfg = _cfg()
    assert wc.greeting_for(cfg, "lekki-3bed") == "Hi, asking about the Lekki 3-bed?"
    assert wc.greeting_for(cfg, "promo") == "Hi, I'm Chioma."             # the ad has no words of its own
    assert wc.greeting_for(cfg, "unknown") == "Hi, I'm Chioma." and wc.greeting_for(cfg) == "Hi, I'm Chioma."


def test_opening_for_ad_main_button_leads_even_on_the_list_style():
    cfg = _cfg(opening={"style": "list"})
    v = wc.opening_for(cfg, "lekki-3bed")
    assert v["style"] == "pair" and v["main"] == {"id": "inspect", "kind": "menu", "label": "Book inspection"}
    assert wc.opening_for(cfg, "promo")["main"]["label"] == "Buy now"
    assert wc.opening_for(cfg, "direct") == {"style": "list"}


def test_opening_for_keeps_the_business_second_button_words():
    cfg = _cfg(opening={"style": "pair", "main": "buy", "speak_label": "Talk to Chioma", "speak_reply": "Ask away"})
    v = wc.opening_for(cfg, "lekki-3bed")
    assert v["main"]["id"] == "inspect" and v["speak_label"] == "Talk to Chioma" and v["speak_reply"] == "Ask away"


def test_opening_for_falls_back_when_the_ad_button_is_gone_or_shop_is_off():
    cfg = _cfg(opening={"style": "pair", "main": "buy"})
    assert wc.opening_for(cfg, "gone")["main"]["id"] == "buy"                  # the business's own first screen
    cfg2 = _cfg(campaigns=[{"tag": "s", "main": "shop"}], shop_enabled=False)
    assert wc.opening_for(cfg2, "s") == {"style": "list"}


# ── what the visitor's browser gets ─────────────────────────────────────────

def test_public_view_applies_the_ad_and_leaks_no_other_ad():
    pv = wc.public_view(_cfg(), "lekki-3bed")
    assert pv["greeting"] == "Hi, asking about the Lekki 3-bed?" and pv["opening"]["main"]["id"] == "inspect"
    text = str(pv)
    assert "Old ad greeting" not in text and "promo" not in text and "campaigns" not in pv


def test_public_view_without_a_source_is_unchanged():
    pv = wc.public_view(_cfg())
    assert pv["greeting"] == "Hi, I'm Chioma." and pv["opening"] == {"style": "list"}


def test_snapshot_uses_the_session_source():
    s = {"source": "lekki-3bed", "id": "s1", "state": {}, "status": "active"}
    snap = router._snapshot(s, _cfg(), [])
    assert snap["config"]["greeting"] == "Hi, asking about the Lekki 3-bed?"
    assert router._snapshot({**s, "source": "instagram"}, _cfg(), [])["config"]["greeting"] == "Hi, I'm Chioma."


# ── the pieces that carry the tag ───────────────────────────────────────────

ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_session_start_uses_the_ad_greeting():
    src = (ROOT / "backend" / "app" / "routers" / "public_webchat.py").read_text(encoding="utf-8")
    assert 'wc.greeting_for(cfg, s.get("source"))' in src and 'wc.public_view(cfg, s.get("source"))' in src


def test_widget_reads_the_chioma_address_tag_and_keeps_old_hooks():
    js = (ROOT / "frontend" / "public" / "widget.js").read_text(encoding="utf-8")
    assert "get('chioma')" in js and "opsra_chioma_src" in js
    assert "&o=menu" in js and "data-chioma-menu" in js


def test_ad_links_screen_is_wired_in():
    admin = ROOT / "frontend" / "src" / "modules" / "admin"
    comp = (admin / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    for needle in ("Links for ads", "1. Ad with no website", "2. Ad that opens WhatsApp", "3. Ad that goes to your website", "?chioma=", "data-chioma-menu", "data-chioma-open=\"shop\""):
        assert needle in comp or needle.replace("?chioma=", "chioma=") in comp, needle
    settings = (admin / "WebChatSettings.jsx").read_text(encoding="utf-8")
    assert "import WebChatAdLinks" in settings and "<WebChatAdLinks " in settings


def test_reserved_tags_match_the_built_in_share_links():
    for t in ("instagram", "qr", "site", "facebook", "google", "whatsapp_status", "email", "sms"):
        assert t in wc.RESERVED_TAGS                                         # the six channel links + QR + site keep their own stats lines
    comp = (ROOT / "frontend" / "src" / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    for t in wc.RESERVED_TAGS:
        assert f"'{t}'" in comp, t                                           # the screen warns about the same names the server drops
