"""Chioma never points at a button the visitor cannot see: the team button is shown with her reply; a question about where the
button is gets the button (no hand-over, no AI call); the AI is told not to name buttons."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import webchat_ai_service as ai_svc
from app.services import webchat_flow_service as f
from app.services import webchat_handover_service as h
from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _claude, _db, _session, _no_rate_limit  # noqa: F401
from tests.unit.test_web_chat_only_1c_greet import _answer_first_db


def _ids(r):
    return [c["id"] for c in r.get("choices", [])]


def test_parse_reply_keeps_offer_team_only_when_not_a_handoff():
    assert ai_svc.parse_reply('{"reply": "I can pass you to the team.", "handoff": false, "offer_team": true}')["offer_team"] is True
    assert "offer_team" not in ai_svc.parse_reply('{"reply": "Hi", "handoff": false}')
    assert "offer_team" not in ai_svc.parse_reply('{"reply": "A person will reply.", "handoff": true, "offer_team": true}')


def test_the_prompt_tells_the_ai_never_to_name_a_button():
    db = _answer_first_db()
    s, cfg = _session(db), _cfg(db)
    p = ai_svc.build_system_prompt(db, s, cfg, "hello")
    assert "Never tell the visitor to tap" in p and "offer_team" in p


def test_an_offer_shows_the_team_button_under_the_reply():
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "I can pass you to the team for that.", "handoff": false, "offer_team": true}'):
        r = f.handle_message(db, s, cfg, kind="text", text="I want a custom logo with my own story")
    assert "human" in _ids(r) and r["human"] is False


def test_a_named_button_is_shown_even_if_the_ai_forgot_the_flag():
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "Tap Talk to the team and we can discuss your needs.", "handoff": false}'):
        r = f.handle_message(db, s, cfg, kind="text", text="I need something tailored")
    assert "human" in _ids(r)
    with _claude('{"reply": "You can tap Menu to see more.", "handoff": false}'):
        r = f.handle_message(db, s, cfg, kind="text", text="what else do you have")
    assert "menu" in _ids(r)


def test_a_plain_answer_shows_no_buttons():
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "Yes we do braids.", "handoff": false}'):
        r = f.handle_message(db, s, cfg, kind="text", text="do you do braids")
    assert not r.get("choices")


def test_no_team_item_in_the_menu_means_no_team_button():
    cfg = {"menu": [{"id": "x", "label": "Hours", "action": "answer"}]}
    assert h.team_choice(cfg) is None and h.reply_choices(cfg, "Tap Talk to the team", True) == [] and h.where_team(cfg) is None


@pytest.mark.parametrize("text", ["where do i tap talk to the team", "Where can I find the talk to team button?", "how do I reach the team", "where is the team button",
                                  "how do i click talk to us"])
def test_where_is_the_button_questions_are_recognised(text):
    assert h.asks_where_team(text), text


@pytest.mark.parametrize("text", ["can I talk to the team", "talk to the team", "I want to speak to someone", "where are you located", "how much is the team package",
                                  "where is your office", "how do i pay"])
def test_other_questions_are_not(text):
    assert not h.asks_where_team(text), text


def test_where_is_the_button_shows_it_without_a_handover_or_an_ai_call():
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "x", "handoff": true}') as cc, patch.object(wc, "notify_managers") as nm:
        r = f.handle_message(db, s, cfg, kind="text", text="where do i tap talk to the team")
    assert not cc.called and not nm.called                      # no AI, no credit, the team is not notified
    assert r["human"] is False and not (s.get("state") or {}).get("human")
    assert "human" in _ids(r) and "menu" in _ids(r)
    assert "below" in r["messages"][-1]["text"]


def test_after_hours_the_button_says_leave_a_message():
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with patch.object(h, "team_state", return_value=(h.TEAM_CLOSED, "tomorrow at 8:00 am")):
        wt = h.where_team(cfg)
        assert [c["label"] for c in wt["choices"] if c["id"] == "human"] == ["Leave a message"]
        assert "away until tomorrow at 8:00 am" in wt["text"]
