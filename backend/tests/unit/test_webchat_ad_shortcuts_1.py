"""AD-SHORTCUTS-1: an ad's first screen shows its main button, up to four quick-question chips and a More options chip."""
from __future__ import annotations

import pathlib

from app.services import webchat_service as wc

FE = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"

MENU = [
    {"id": "prices", "label": "Mattress and pillow prices", "answer": "x"},
    {"id": "choose", "label": "Help me choose a mattress", "answer": "x"},
    {"id": "delivery", "label": "Delivery and shipping", "answer": "x"},
    {"id": "warranty", "label": "Warranty and lifespan", "answer": "x"},
    {"id": "extra", "label": "Extra", "answer": "x"},
    {"id": "human", "label": "Talk to a sales rep", "action": "human"},
]


def _cfg(**camp):
    c = {"tag": "elite", "label": "Elite", "main": "shop", **camp}
    return {**wc.DEFAULT_CONFIG, "shop_enabled": True, "menu": MENU, "campaigns": wc.clean_campaigns([c])}


def test_clean_shortcuts_caps_at_four_dedupes_and_cleans():
    out = wc.clean_shortcuts([{"id": "A b"}, {"id": "ab"}, "prices", {"id": "x", "label": "L" * 50}, {"id": "y"}, {"id": "z"}, {"id": "w"}])
    assert [s["id"] for s in out] == ["ab", "prices", "x", "y"]
    assert len(out[2]["label"]) == 30
    assert wc.clean_shortcuts("nope") == [] and wc.clean_shortcuts(None) == []


def test_campaign_keeps_its_shortcuts():
    cfg = _cfg(shortcuts=[{"id": "prices", "label": "Prices"}, {"id": "choose"}])
    assert cfg["campaigns"][0]["shortcuts"] == [{"id": "prices", "label": "Prices"}, {"id": "choose", "label": ""}]
    assert wc.sanitise_config({"campaigns": [{"tag": "t", "main": "shop", "shortcuts": [{"id": "prices"}]}]})["campaigns"][0]["shortcuts"][0]["id"] == "prices"


def test_ad_opening_has_chips_with_owner_wording_and_more_options():
    cfg = _cfg(shortcuts=[{"id": "prices", "label": "Prices and sizes"}, {"id": "choose"}, {"id": "delivery"}, {"id": "warranty"}])
    ov = wc.opening_for(cfg, "elite")
    assert ov["style"] == "pair" and ov["main"]["kind"] == "shop"
    assert [c["label"] for c in ov["shortcuts"]] == ["Prices and sizes", "Help me choose a mattress", "Delivery and shipping", "Warranty and lifespan"]
    assert ov["more_label"] == "More options"


def test_missing_human_and_main_items_are_never_shown():
    cfg = _cfg(main="prices", shortcuts=[{"id": "gone"}, {"id": "human"}, {"id": "prices"}, {"id": "choose"}])
    ov = wc.opening_for(cfg, "elite")
    assert [c["id"] for c in ov["shortcuts"]] == ["choose"]


def test_an_ad_without_shortcuts_keeps_the_old_two_button_screen():
    ov = wc.opening_for(_cfg(), "elite")
    assert ov["style"] == "pair" and "shortcuts" not in ov and ov["speak_label"]


def test_a_visitor_with_no_ad_is_not_affected():
    cfg = _cfg(shortcuts=[{"id": "prices"}])
    assert "shortcuts" not in wc.opening_for(cfg, None) and "shortcuts" not in wc.opening_for(cfg, "unknown")


def test_frontend_wiring():
    p = (FE / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "{pairOpening.shortcuts && pairOpening.shortcuts.length > 0 ? (" in p
    assert "onClick={() => openMenu(true)}>{pairOpening.more_label || 'More options'}</button>" in p
    a = (FE / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    assert "Quick questions under the main button (up to 4)" in a
    assert "slice(0, 4).map((m) => ({ id: m.id, label: '' }))" in a
    assert "cur.length >= 4 ? cur" in a
