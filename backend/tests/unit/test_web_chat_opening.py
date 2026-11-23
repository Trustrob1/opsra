"""OPENING-CTA-1: the two-button first screen (one main action + Speak to Chioma), its settings, and the starter presets."""
from __future__ import annotations

import pathlib
from unittest.mock import patch

from app.routers import webchat as admin_router
from app.services import webchat_service as wc
from app.services import webchat_smart_service as smart

MENU = [{"id": "buy", "label": "Place an order", "answer": "x"},
        {"id": "book", "label": "Book inspection", "action": "booking"},
        {"id": "faq", "label": "Prices", "answer": "y"},
        {"id": "talk", "label": "Talk to the team", "action": "human"}]


def _cfg(**kw):
    return wc.sanitise_config({}) | {"menu": MENU, "business_name": "T", "brand_color": "#028090", "greeting": "Hi", "contact_prompt": "c",
                                     "consent_text": "c", "fallback": "f", "booking_fields": [], **kw}


# ── settings ────────────────────────────────────────────────────────────────

def test_default_is_the_plain_list():
    assert wc.DEFAULT_CONFIG["opening"] == {"style": "list"}
    assert wc.opening_view(_cfg()) == {"style": "list"}


def test_sanitise_pair_keeps_clean_values():
    out = wc.sanitise_config({"opening": {"style": "pair", "main": " Book ", "main_label": "  Buy now ", "speak_label": "Talk to Chioma", "speak_reply": "Ask away"}})
    assert out["opening"] == {"style": "pair", "main": "book", "main_label": "Buy now", "speak_label": "Talk to Chioma", "speak_reply": "Ask away"}


def test_sanitise_defaults_and_lengths():
    op = wc.sanitise_config({"opening": {"style": "pair", "main": "book", "speak_label": "", "main_label": "x" * 200, "speak_reply": "y" * 500}})["opening"]
    assert op["speak_label"] == wc.SPEAK_LABEL and op["speak_reply"] == "y" * 200 and len(op["main_label"]) == 40


def test_sanitise_bad_input_falls_back_to_list():
    for bad in (None, "pair", 5, [], {}, {"style": "grid", "main": "book"}, {"style": "pair"}, {"style": "pair", "main": "!!!"}, {"style": "list", "main": "book"}):
        assert wc.sanitise_config({"opening": bad})["opening"] == {"style": "list"}


# ── what the visitor's browser gets ─────────────────────────────────────────

def test_view_pair_on_a_menu_button():
    v = wc.opening_view(_cfg(opening={"style": "pair", "main": "book"}))
    assert v["style"] == "pair"
    assert v["main"] == {"id": "book", "kind": "menu", "label": "Book inspection"}
    assert v["speak_label"] == "Speak to Chioma" and v["speak_reply"] == wc.SPEAK_REPLY


def test_view_main_label_overrides_the_button_label():
    v = wc.opening_view(_cfg(opening={"style": "pair", "main": "buy", "main_label": "Buy now"}))
    assert v["main"]["label"] == "Buy now" and v["main"]["id"] == "buy"


def test_view_shop_main_needs_the_shop_on():
    op = {"style": "pair", "main": "shop"}
    assert wc.opening_view(_cfg(opening=op, shop_enabled=False)) == {"style": "list"}
    v = wc.opening_view(_cfg(opening=op, shop_enabled=True))
    assert v["main"] == {"id": "shop", "kind": "shop", "label": "Shop now"}


def test_view_falls_back_when_the_main_button_is_gone():
    assert wc.opening_view(_cfg(opening={"style": "pair", "main": "deleted"})) == {"style": "list"}


def test_public_view_carries_opening_and_leaks_nothing_else():
    pv = wc.public_view(_cfg(opening={"style": "pair", "main": "book"}))
    assert pv["opening"]["style"] == "pair"
    assert set(pv["opening"]) == {"style", "main", "speak_label", "speak_reply"}
    assert set(pv["opening"]["main"]) == {"id", "kind", "label"}
    assert "answer" not in str(pv["menu"])


def test_a_saved_old_business_without_the_key_is_unchanged():
    assert wc.public_view(_cfg())["opening"] == {"style": "list"}


# ── starter presets ─────────────────────────────────────────────────────────

def test_every_starter_has_a_working_pair_and_a_team_button():
    assert {"salon", "services", "restaurant", "shop", "clinic", "real_estate", "school", "events", "travel"} <= set(smart.STARTERS)
    for key, st in smart.STARTERS.items():
        cfg = wc.sanitise_config({"menu": st["menu"], "opening": st.get("opening")})
        ids = [m["id"] for m in cfg["menu"]]
        assert len(ids) == len(st["menu"]), key                                    # nothing dropped by the sanitiser
        assert cfg["opening"]["style"] == "pair" and cfg["opening"]["main"] in ids, key
        assert any(m.get("action") == "human" for m in cfg["menu"]), key


def test_real_estate_is_book_inspection_and_speak_to_chioma():
    st = smart.STARTERS["real_estate"]
    cfg = wc.sanitise_config({"menu": st["menu"], "opening": st["opening"]})
    v = wc.opening_view(_cfg(menu=cfg["menu"], opening=cfg["opening"]))
    assert v["main"]["label"] == "Book inspection" and v["speak_label"] == "Speak to Chioma"
    assert [m for m in cfg["menu"] if m["id"] == v["main"]["id"]][0]["action"] == "booking"


def test_shop_starter_says_buy_now():
    st = smart.STARTERS["shop"]
    v = wc.opening_view(_cfg(menu=wc.sanitise_config({"menu": st["menu"]})["menu"], opening=wc.sanitise_config({"opening": st["opening"]})["opening"]))
    assert v["main"]["label"] == "Buy now"


def test_applying_a_starter_saves_its_opening_with_its_menu():
    saved = {}
    with patch.object(admin_router.wc, "save_config", side_effect=lambda db, org_id, ch: saved.update(ch) or {}):
        admin_router.apply_template(admin_router.TemplateBody(template="real_estate"), db=None, org={"org_id": "o1", "roles": {"template": "owner"}})
    assert saved["opening"] == {"style": "pair", "main": "inspect"}
    assert [m["id"] for m in saved["menu"]][0] == "listings"


# ── the chat page and settings screen carry the feature ─────────────────────

def test_chat_page_and_settings_have_the_hooks():
    root = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"
    page = (root / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "pairOpening" in page and "setSpeakOpen(true)" in page and "pairOpening.main.kind === 'shop' ? openShop()" in page
    assert "!pairOpening && cfg.menu.length > 0 && !visitorSpoke" in page          # the old list stays for businesses on the list style
    inst = (root / "modules" / "admin" / "WebChatInstall.jsx").read_text(encoding="utf-8")
    assert "First screen of the chat" in inst and "set('opening'" in inst
