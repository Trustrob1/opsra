"""PRODUCT-ASK-1: a typed product name moves the chat's focus product; a vague product question with two or more products in play asks which one."""
from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest

from app.services import webchat_flow_service as flow
from app.services import webchat_service as wc
from app.services import webchat_shop_service as shop
from tests.unit.test_webchat_3b import _cfg, _session, _shop_db

FE = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"


@pytest.fixture(autouse=True)
def _quiet():
    with patch.object(wc, "rate_limited", return_value=False):
        yield


def _chat(viewing="p1", cart=("p2", "v1"), ai=True):
    db = _shop_db(ai=ai)
    s = _session(db)
    s["source"] = "elite"
    s["state"]["viewing"] = viewing
    s["state"]["viewing_title"] = "x"
    if cart:
        shop.add(db, s, cart[0], cart[1])
    return db, s, {**_cfg(db), "shop_enabled": True}


def _say(db, s, cfg, text):
    return flow.handle_message(db, s, cfg, kind="text", text=text)


def _bots(res):
    return [m["text"] for m in res["messages"] if m["role"] == "bot"]


def _ai(reply="ok"):
    return patch("app.services.ai_service.call_claude", return_value=json.dumps({"reply": reply, "handoff": False}))


def test_a_vague_price_question_with_two_products_in_play_asks_which():
    db, s, cfg = _chat()
    with _ai() as ai:
        res = _say(db, s, cfg, "how much is it?")
    ai.assert_not_called()                                              # the question is scripted: no AI call, no credit
    assert _bots(res) == ["Which one do you mean?"]
    assert res["choices"] == [{"id": "say", "label": "Silk Bonnet"}, {"id": "say", "label": "Body Oil"}]
    assert s["state"]["ask_which"] == {"q": "how much is it?", "ids": ["p1", "p2"]}


@pytest.mark.parametrize("q", ["is it firm or soft?", "Is it available?", "what size is it", "what is it made of"])
def test_other_product_specific_questions_ask_too(q):
    db, s, cfg = _chat()
    with _ai():
        assert _bots(_say(db, s, cfg, q)) == ["Which one do you mean?"]


@pytest.mark.parametrize("q", ["do you deliver to Lekki?", "how do I pay?", "what time do you open?"])
def test_questions_that_are_not_about_one_product_are_not_asked(q):
    db, s, cfg = _chat()
    with _ai("sure"):
        res = _say(db, s, cfg, q)
    assert "Which one do you mean?" not in _bots(res) and "ask_which" not in s["state"]


def test_one_product_in_play_is_just_answered():
    db, s, cfg = _chat(cart=None)
    with _ai("It is N5,000.") as ai:
        res = _say(db, s, cfg, "how much is it?")
    ai.assert_called_once()
    assert _bots(res) == ["It is N5,000."]


def test_a_chat_with_no_product_in_focus_or_cart_is_unchanged():
    db, s, cfg = _chat(viewing=None, cart=None)
    s["state"].pop("viewing", None)
    with _ai("Tell me which one."):
        res = _say(db, s, cfg, "how much is it?")
    assert "ask_which" not in s["state"] and "Which one do you mean?" not in _bots(res)


def test_picking_one_answers_the_original_question_about_that_product():
    db, s, cfg = _chat()
    with _ai("Body Oil is N3,000."):
        _say(db, s, cfg, "how much is it?")
    with _ai("Body Oil is N3,000.") as ai:
        res = _say(db, s, cfg, "Body Oil")
    texts = [m["text"] for m in res["messages"]]
    assert texts[0] == "Body Oil" and "Body Oil is N3,000." in texts            # their pick is shown, then the answer
    assert s["state"]["viewing"] == "p2" and s["state"]["ask_which"] is None
    sent = ai.call_args.kwargs
    assert sent["prompt"].rstrip().endswith("<customer_message>\nhow much is it?\n</customer_message>") and "(id=p2)" in sent["system"]          # the AI got the ORIGINAL question and the picked product


def test_not_asked_again_for_the_same_products_but_asked_again_when_a_new_one_arrives():
    db, s, cfg = _chat()
    with _ai("x"):
        _say(db, s, cfg, "how much is it?")
        _say(db, s, cfg, "Silk Bonnet")
        res = _say(db, s, cfg, "is it available?")
    assert "Which one do you mean?" not in _bots(res)
    shop.add(db, s, "p3", None) if False else s["state"].setdefault("cart", []).append({"pid": "p3", "vid": None, "name": "Free Sample", "price": 100, "qty": 1})
    with _ai("x"):
        res = _say(db, s, cfg, "how much is it?")
    assert _bots(res) == ["Which one do you mean?"] and [c["label"] for c in res["choices"]] == ["Silk Bonnet", "Body Oil", "Free Sample"]


def test_typing_a_product_name_moves_the_focus_and_does_not_ask():
    db, s, cfg = _chat()
    with _ai("N3,000 for 100ml.") as ai:
        res = _say(db, s, cfg, "how much is the body oil?")
    assert s["state"]["viewing"] == "p2" and "Which one do you mean?" not in _bots(res)
    assert "(id=p2)" in ai.call_args.kwargs["system"]
    with _ai("x"):
        assert "Which one do you mean?" not in _bots(_say(db, s, cfg, "how much is it?"))          # naming one settled which they mean


def test_typing_something_else_instead_of_picking_drops_the_question():
    db, s, cfg = _chat()
    with _ai("x"):
        _say(db, s, cfg, "how much is it?")
        res = _say(db, s, cfg, "do you deliver to Abuja?")
    assert s["state"]["ask_which"] is None and "Which one do you mean?" not in _bots(res)
    assert s["state"]["viewing"] == "p1"


def test_tapping_a_menu_button_drops_the_question():
    db, s, cfg = _chat()
    cfg["menu"] = [{"id": "hours", "label": "Hours", "answer": "9 to 5"}]
    with _ai("x"):
        _say(db, s, cfg, "how much is it?")
    flow.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    assert s["state"]["ask_which"] is None


def test_no_ai_fallback_for_the_picked_product_not_the_old_one():
    db, s, cfg = _chat(ai=False)
    cfg = {**cfg, "ai_enabled": False, "fallback": "OLD-FOCUS-TEXT", "_fallback_base": "BASE-FALLBACK"}
    _say(db, s, cfg, "how much is it?")
    res = _say(db, s, cfg, "Body Oil")
    bots = _bots(res)
    assert any("Body Oil" in b and "OLD-FOCUS-TEXT" not in b for b in bots)


def test_frontend_needs_no_change_say_buttons_already_exist():
    assert "'say'" in (FE / "utils" / "webchatChoices.js").read_text(encoding="utf-8")
