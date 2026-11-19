"""MATCH-2: with the AI on, a sentence is not taken for one button because of a stray keyword; short button words still match."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import webchat_flow_service as flow
from tests.unit.test_webchat_3 import _cfg, _claude, _db, _no_rate_limit, _session  # noqa: F401

MENU = [
    {"id": "book", "label": "Book a call", "action": "booking", "keywords": ["book", "appointment", "schedule", "call me"]},
    {"id": "websites", "label": "Websites and prices", "answer": "WEBSITES ANSWER", "keywords": ["website", "websites", "price", "prices", "cost", "how much", "quote"]},
    {"id": "learn", "label": "Learn: AI training", "answer": "LEARN ANSWER", "keywords": ["learn", "training", "course", "webinar"]},
    {"id": "human", "label": "Talk to the team", "action": "human", "keywords": []},
]
CFG = {"menu": MENU}


def _id(text, strict):
    it = flow._match_item(CFG, text, strict=strict)
    return it["id"] if it else None


@pytest.mark.parametrize("text", ["learn", "prices", "Learn: AI training", "book a call", "website cost", "how much"])
def test_short_button_words_still_match_with_the_ai_on(text):
    assert _id(text, True) is not None


@pytest.mark.parametrize("text", [
    "I want to learn about your services", "tell me more about your services", "what do you do", "can you tell me more about what you offer",
    "I would like to learn how this works for my shop", "do you have a price for something small",
])
def test_a_sentence_with_one_stray_keyword_goes_to_the_ai(text):
    assert _id(text, True) is None


def test_a_sentence_with_two_keywords_or_the_label_still_matches():
    assert _id("I want training and a course for my team", True) == "learn"
    assert _id("please send me the websites and prices", True) == "websites"


def test_the_old_behaviour_is_kept_when_not_strict():
    assert _id("I would like to learn how this works for my shop", False) == "learn"


def test_the_ai_answers_the_sentence_and_the_button_text_is_not_used():
    db = _db(); s = _session(db); cfg = _cfg(db); cfg["menu"] = MENU
    raw = '{"reply": "We build websites, run AI training and map what to automate. Which would you like to hear about?", "handoff": false}'
    with _claude(raw), patch("app.services.webchat_plan_service.use_ai_allowance", return_value=True):
        r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="I want to learn about your services", reply_to=None)
    bot = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert any("Which would you like" in x for x in bot) and not any("LEARN ANSWER" in x for x in bot)


def test_no_ai_answer_falls_back_to_the_keyword_button_not_the_cannot_answer_line():
    db = _db(); s = _session(db); cfg = _cfg(db); cfg["menu"] = MENU
    with patch.object(flow.webchat_ai_service, "answer", return_value=None):
        r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="I would like to learn how this works for my shop", reply_to=None)
    assert any("LEARN ANSWER" in m["text"] for m in r["messages"] if m["role"] == "bot")


def test_junk_messages_do_not_call_the_ai():
    db = _db(); s = _session(db); cfg = _cfg(db)
    with patch.object(flow.webchat_ai_service, "answer") as a:
        flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="???", reply_to=None)
        flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="😀", reply_to=None)
    assert a.call_count == 0


def test_context_is_trimmed():
    from app.services import webchat_ai_service as ai
    assert ai.HISTORY_MESSAGES == 4


# ── AI off: a broad question shows the buttons, a specific one still answers ──

def test_ai_off_broad_question_shows_the_buttons_not_one_answer():
    db = _db(ai=False); s = _session(db); cfg = _cfg(db); cfg["menu"] = MENU
    r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="I want to learn about your services", reply_to=None)
    bot = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert not any("LEARN ANSWER" in x for x in bot) and "Here is what I can help with" in bot[-1]
    ids = [c["menu_id"] for c in r["choices"] if c["id"] == "item"]
    assert ids == ["book", "websites", "learn"] and all(c["id"] != "human" for c in r["choices"])


def test_ai_off_specific_questions_still_get_the_button_answer():
    db = _db(ai=False); s = _session(db); cfg = _cfg(db); cfg["menu"] = MENU
    r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="I want to learn about your training courses", reply_to=None)
    assert any("LEARN ANSWER" in m["text"] for m in r["messages"] if m["role"] == "bot")
    r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="tell me more about website prices", reply_to=None)
    assert any("WEBSITES ANSWER" in m["text"] for m in r["messages"] if m["role"] == "bot")
