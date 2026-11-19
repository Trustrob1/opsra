"""ASKBAR-1: the ask bar settings, what the widget is told, and the widget script's hooks."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import patch

from app.routers import public_webchat as router
from app.services import webchat_service as wc

MENU = [{"id": "a", "label": "Websites and prices", "answer": "x"},
        {"id": "b", "label": "Book a call", "action": "booking"},
        {"id": "c", "label": "Learn: AI training", "answer": "y"},
        {"id": "d", "label": "Talk to the team", "action": "human"}]


def _cfg(**kw):
    return wc.sanitise_config({}) | {"menu": MENU, "business_name": "T", "brand_color": "#028090", **kw}


def test_settings_default_off_and_clean():
    assert wc.DEFAULT_CONFIG["ask_bar"] is False
    assert wc.sanitise_config({"ask_bar": 1, "ask_bar_text": "  Ask Chioma  "}) == {"ask_bar": True, "ask_bar_text": "Ask Chioma"}
    assert wc.sanitise_config({"ask_bar_text": "   "})["ask_bar_text"] == wc.DEFAULT_CONFIG["ask_bar_text"]
    assert len(wc.sanitise_config({"ask_bar_text": "x" * 200})["ask_bar_text"]) == 60


def test_view_is_none_when_off():
    assert wc.ask_bar_view(_cfg(ask_bar=False)) is None


def test_view_chips_book_first_and_at_most_three():
    v = wc.ask_bar_view(_cfg(ask_bar=True, ask_bar_text="Ask Chioma"))
    assert v["text"] == "Ask Chioma"
    assert [c["id"] for c in v["chips"]] == ["b", "a", "c"]
    assert v["chips"][0]["primary"] is True and not v["chips"][1]["primary"]
    assert set(v["chips"][0]) == {"id", "label", "primary"}            # no answers leave the server


def test_view_with_no_menu_still_works():
    assert wc.ask_bar_view(_cfg(ask_bar=True, menu=[]))["chips"] == []


def _widget(cfg):
    req = SimpleNamespace(headers={"origin": "https://x.com"})
    found = {"org_id": "o1", "config": cfg}
    with patch.object(wc, "resolve_key", return_value=found), \
         patch("app.services.chat_pause_service.is_paused", return_value=False), \
         patch.object(router.embed, "origin_allowed", return_value=True), \
         patch.object(router.embed, "record_seen"):
        import json
        return json.loads(router.widget_info("wc_abcdefgh1", req, db=None).body)["data"]


def test_widget_info_carries_the_bar_only_when_on():
    assert _widget(_cfg(ask_bar=False))["bar"] is None
    d = _widget(_cfg(ask_bar=True))
    assert d["bar"]["chips"][0]["id"] == "b" and d["allowed"] is True


JS = (pathlib.Path(__file__).resolve().parents[3] / "frontend" / "public" / "widget.js").read_text(encoding="utf-8")


def test_script_has_the_hooks():
    for needle in ("data-chioma-slot", "data-chioma-ask", "d.bar", "opsra_chioma_bar_min_", "IntersectionObserver", "OpsraChat = {", "ask:"):
        assert needle in JS, needle
