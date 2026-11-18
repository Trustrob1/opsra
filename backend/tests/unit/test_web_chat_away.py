"""WEB-ONLY-1c-AWAY: Chioma never promises a person who is away, the Leave a message tap invites the message, and she does not go silent."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import webchat_ai_service as ai
from app.services import webchat_flow_service as flow
from app.services import webchat_handover_service as ho
from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _claude, _db, _no_rate_limit, _session  # noqa: F401

def _plan_ok():
    return patch("app.services.webchat_plan_service.use_ai_allowance", return_value=True)


CLOSED = ("closed", "today at 8:00 am")
OPEN = ("open", "")


def _human_menu_id(cfg):
    return next(m["id"] for m in cfg["menu"] if m.get("action") == "human")


# ── the AI is told, and a reply that says "now" is corrected ────────────────

def test_prompt_line_matches_the_clock():
    with patch.object(ho, "team_state", return_value=CLOSED):
        assert "away until today at 8:00 am" in ho.team_prompt_line({}) and "Never say the team can chat now" in ho.team_prompt_line({})
    with patch.object(ho, "team_state", return_value=OPEN):
        assert "online now" in ho.team_prompt_line({})
    with patch.object(ho, "team_state", return_value=("unknown", "")):
        assert "do not know" in ho.team_prompt_line({})


def test_system_prompt_carries_the_team_line():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=CLOSED):
        assert "The team is away until today at 8:00 am" in ai.build_system_prompt(db, s, cfg, "hello")


@pytest.mark.parametrize("reply", [
    "Yes, I can pass you to the team and they can chat with you now.",
    "A team member is available now to help.",
    "The team can speak to you right now.",
    "Our team is online now.",
])
def test_chat_now_is_replaced_when_away_or_unknown(reply):
    for st in (CLOSED, ("unknown", "")):
        with patch.object(ho, "team_state", return_value=st):
            out = ho.fix_availability({}, reply)
        assert out != reply and "now" not in out.lower().replace("know", "")


def test_chat_now_is_kept_when_the_team_is_open_and_normal_replies_untouched():
    with patch.object(ho, "team_state", return_value=OPEN):
        assert ho.fix_availability({}, "They can chat with you now.") == "They can chat with you now."
    with patch.object(ho, "team_state", return_value=CLOSED):
        for ok in ("We open at 8 am.", "Yes, we sell wigs.", "I know the price now is N5,000.".replace(" now", "")):
            assert ho.fix_availability({}, ok) == ok


def test_the_ai_answer_is_corrected_end_to_end():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=CLOSED), _plan_ok(), \
         _claude('{"reply": "Yes, I can pass you to the team and they can chat with you now.", "handoff": false, "offer_team": true}'):
        out = ai.answer(db, s, cfg, "is there someone I can speak to now?")
    assert out and "chat with you now" not in out["reply"] and "reply here" in out["reply"]


# ── the tap ─────────────────────────────────────────────────────────────────

def test_tap_when_away_invites_the_message_and_the_bubble_says_leave_a_message():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=CLOSED):
        r = flow.handle_message(db, s, cfg, kind="menu", menu_id=_human_menu_id(cfg))
    texts = [m["text"] for m in r["messages"]]
    assert texts[0] == "Leave a message"
    assert "Type your message here" in texts[1] and "saved" not in texts[1]
    assert s["state"].get("awaiting_message") is True


def test_tap_when_open_is_unchanged():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=OPEN):
        r = flow.handle_message(db, s, cfg, kind="menu", menu_id=_human_menu_id(cfg))
    assert r["messages"][0]["text"] == next(m["label"] for m in cfg["menu"] if m.get("action") == "human")
    assert "Type your message" not in r["messages"][1]["text"] and not s["state"].get("awaiting_message")


def test_tap_when_away_without_details_does_not_ask_for_a_message_before_the_name():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with patch.object(ho, "team_state", return_value=CLOSED):
        r = flow.handle_message(db, s, cfg, kind="menu", menu_id=_human_menu_id(cfg))
    texts = [m["text"] for m in r["messages"]]
    assert "Type your message" not in texts[1] and r.get("contact_step") == "name"


# ── after the tap ───────────────────────────────────────────────────────────

def _tapped(db, s, cfg):
    with patch.object(ho, "team_state", return_value=CLOSED):
        flow.handle_message(db, s, cfg, kind="menu", menu_id=_human_menu_id(cfg))


def test_first_typed_message_is_saved_and_confirmed_once():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    _tapped(db, s, cfg)
    with patch.object(ho, "team_state", return_value=CLOSED), _claude('{"reply": "AI", "handoff": false}') as cc:
        r = flow.handle_message(db, s, cfg, kind="text", text="I need a quote for 20 mattresses")
    assert not cc.called and r["messages"][-1]["text"].startswith("Got it. I have saved this for the team")
    assert "today at 8:00 am" in r["messages"][-1]["text"]
    assert not s["state"].get("awaiting_message")


def test_later_messages_are_answered_not_ignored_while_the_team_is_away():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    _tapped(db, s, cfg)
    with patch.object(ho, "team_state", return_value=CLOSED), _claude('{"reply": "AI", "handoff": false}'):
        flow.handle_message(db, s, cfg, kind="text", text="I need a quote")
    with patch.object(ho, "team_state", return_value=CLOSED), _plan_ok(), _claude('{"reply": "We sell mattresses and beds.", "handoff": false}') as cc:
        r = flow.handle_message(db, s, cfg, kind="text", text="what else can you help me with?")
    assert cc.called and any(m["text"] == "We sell mattresses and beds." for m in r["messages"])


def test_when_the_team_is_open_the_bot_stays_quiet_after_the_hand_over():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=OPEN):
        flow.handle_message(db, s, cfg, kind="menu", menu_id=_human_menu_id(cfg))
        with _claude('{"reply": "AI", "handoff": false}') as cc:
            r = flow.handle_message(db, s, cfg, kind="text", text="hello? anyone?")
    assert not cc.called and len(r["messages"]) == 1 and r["human"] is True


def test_a_real_reply_from_the_team_keeps_the_bot_quiet_even_after_hours():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    _tapped(db, s, cfg)
    wc.set_state(db, s, rep_last_at=wc._iso(wc._now()), awaiting_message=False)
    with patch.object(ho, "team_state", return_value=CLOSED), _claude('{"reply": "AI", "handoff": false}') as cc:
        r = flow.handle_message(db, s, cfg, kind="text", text="thank you, one more thing")
    assert not cc.called and len(r["messages"]) == 1


def test_the_team_is_still_notified_for_every_message_while_away():
    db = _db()
    s, cfg = _session(db), _cfg(db)
    _tapped(db, s, cfg)
    with patch.object(ho, "team_state", return_value=CLOSED), patch.object(flow, "_notify_human") as nh, _claude('{"reply": "AI", "handoff": false}'):
        flow.handle_message(db, s, cfg, kind="text", text="I need a quote")
    assert nh.called
