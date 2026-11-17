"""WEB-ONLY-1c-GREET: greetings, thanks and goodbyes (English, Pidgin, Yoruba, Igbo, Hausa, salaam) and answer-first."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import webchat_greeting_service as g
from tests.unit.test_webchat_3 import _cfg, _claude, _db, _session, _no_rate_limit  # noqa: F401

BIZ = "Tech with Trust Robert"

GREETINGS = [
    "Hi", "hello", "Heyyy", "HELLO!!!", "good morning", "Good Morning o", "gm", "Good afternoon Chioma", "good evening", "good day",
    "sup", "what's up", "Hi there", "hey chioma", "Hiii Chioma", "hello please", "Hello Tech with Trust Robert", "Hello!! \U0001F60A",
    "Hi, how are you?", "hello how are you doing", "How are you today", "nice to meet you",
    # Pidgin
    "how far", "How far na", "how you dey", "wetin dey", "Wetin dey happen o", "how body", "how market", "oya how far", "i dey greet you",
    # Yoruba, Igbo, Hausa
    "e kaaro", "Ẹ káàárọ̀", "Bawo ni", "kedu", "Ndewo", "Kedu ka i mere", "Sannu", "ina kwana", "Barka da rana",
    # salaam
    "Assalamu alaikum", "salam", "assalamualaikum", "peace be upon you",
]
QUESTIONS = ["hi how much is a website", "hello do you sell wigs", "good morning I want to book", "how much is it", "what are your opening hours",
             "I want to buy", "how are you able to help me with orders", "ok", "okay", "yes", "no", "my name is Hi",
             "how far is your office from Lekki", "ok hi", "great hello", "see prices"]
THANKS = ["thanks", "Thank you", "thank you so much", "thx", "ok thanks", "Thanks a lot!", "oshe", "nagode", "God bless you", "you try",
          "I appreciate it", "great thanks"]
BYES = ["bye", "Goodbye", "good night", "goodnight", "gn", "see you later", "ok bye", "thanks bye", "thank you bye bye", "take care",
        "i dey go", "make i go", "I go come back", "talk later", "have a good day", "ka chi bo", "sai an jima", "cheers"]


@pytest.mark.parametrize("text", GREETINGS)
def test_greetings_are_recognised(text):
    r = g.classify(text, BIZ)
    assert r and r["kind"] == "greeting", text


@pytest.mark.parametrize("text", QUESTIONS)
def test_questions_are_not_greetings(text):
    assert g.classify(text, BIZ) is None, text


@pytest.mark.parametrize("text", THANKS)
def test_thanks_are_recognised(text):
    assert g.classify(text)["kind"] == "thanks", text


@pytest.mark.parametrize("text", BYES)
def test_goodbyes_are_recognised(text):
    assert g.classify(text)["kind"] == "bye", text


NOON = datetime(2026, 11, 17, 11, 0, tzinfo=timezone.utc)      # 12:00 in Lagos


def test_greeting_reply_is_warm_names_the_business_and_asks_how_to_help():
    for text in GREETINGS:
        out = g.reply(g.classify(text, BIZ), BIZ, NOON)
        assert BIZ in out and out.endswith(("How can I help you today?", "How I fit help you today?")), (text, out)


def test_time_of_day_follows_the_visitor_or_the_clock():
    assert g.reply(g.classify("good morning"), BIZ, NOON).startswith("Good morning!")
    assert g.reply(g.classify("good evening"), BIZ, NOON).startswith("Good evening!")
    assert "good afternoon" in g.reply(g.classify("hello"), BIZ, NOON)                       # 12:00 Lagos
    assert "good morning" in g.reply(g.classify("hello"), BIZ, datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc))


def test_pidgin_and_salaam_and_local_replies():
    assert "I dey fine" in g.reply(g.classify("how far"), BIZ, NOON) and "How I fit help you today?" in g.reply(g.classify("wetin dey"), BIZ, NOON)
    assert g.reply(g.classify("Assalamu alaikum"), BIZ, NOON).startswith("Wa alaikum assalam!")
    assert g.reply(g.classify("e kaaro"), BIZ, NOON).startswith("E kaabo!")
    assert g.reply(g.classify("Sannu"), BIZ, NOON).startswith("Sannu")
    assert g.reply(g.classify("hi, how are you"), BIZ, NOON).count("doing very well") == 1


def test_thanks_and_goodbye_replies():
    assert g.reply(g.classify("thanks"), BIZ).startswith("You are most welcome!")
    assert "Goodbye" in g.reply(g.classify("bye"), BIZ) and BIZ in g.reply(g.classify("bye"), BIZ)
    assert g.reply(g.classify("good night"), BIZ).startswith("Good night")
    assert "Safe journey" in g.reply(g.classify("i dey go"), BIZ)


def test_no_business_name_still_reads_well():
    assert g.reply(g.classify("hello"), "", NOON).startswith("Hello, and good afternoon! Welcome. How can I help")


# -- the chat flow ----------------------------------------------------------------------------------------------------
def _answer_first_db(**kw):
    return _db(answer_first=True, **kw)


def test_greeting_in_the_flow_makes_no_ai_call_and_does_not_ask_for_details():
    from app.services import webchat_flow_service as f
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "AI", "handoff": false}') as cc:
        r = f.handle_message(db, s, cfg, kind="text", text="How far")
    assert not cc.called and "contact_step" not in r and r["ask_contact"] is False
    assert "I dey fine" in r["messages"][-1]["text"] and "Glow Salon" in r["messages"][-1]["text"]


def test_greeting_then_question_is_answered_without_details_first():
    from app.services import webchat_flow_service as f
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "Yes we do braids.", "handoff": false}') as cc:
        r = f.handle_message(db, s, cfg, kind="text", text="do you do braids?")
    texts = [m["text"] for m in r["messages"]]
    assert cc.called and texts[0] == "do you do braids?" and texts[1] == "Yes we do braids."      # the answer comes first
    assert r.get("contact_step") == "name"                    # details are asked AFTER the first answer
    assert any("couple of details" in m["text"] for m in r["messages"])


def test_without_answer_first_the_old_order_is_kept():
    from app.services import webchat_flow_service as f
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "x", "handoff": false}') as cc:
        r = f.handle_message(db, s, cfg, kind="text", text="do you do braids?")
    assert not cc.called and r["contact_step"] == "name" and s["state"]["pending_question"] == "do you do braids?"


def test_handoff_before_details_asks_for_them():
    from app.services import webchat_flow_service as f, webchat_service as wc
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    with _claude('{"reply": "A team member will reply.", "handoff": true}'), patch.object(wc, "notify_managers"):
        r = f.handle_message(db, s, cfg, kind="text", text="can I get a discount on 10 wigs?")
    assert r["human"] is True and r.get("contact_step") == "name"
    assert "reply to you" in r["messages"][-1]["text"]


def test_known_contact_greeting_still_gets_a_greeting_not_ai():
    from app.services import webchat_flow_service as f
    db = _db()
    s, cfg = _session(db), _cfg(db)
    with _claude('{"reply": "AI", "handoff": false}') as cc:
        r = f.handle_message(db, s, cfg, kind="text", text="Good morning")
    assert not cc.called and r["messages"][-1]["text"].startswith("Good morning!")


def test_a_human_takeover_is_not_interrupted_by_a_greeting():
    from app.services import webchat_flow_service as f, webchat_service as wc
    db = _db()
    s, cfg = _session(db), _cfg(db)
    wc.set_human(db, s)
    with patch.object(wc, "notify_managers"):
        r = f.handle_message(db, s, cfg, kind="text", text="hello?")
    assert r["human"] is True and len(r["messages"]) == 1       # only the visitor's own message is stored; the team will answer


def test_ai_allowed_before_contact_only_when_answer_first():
    from app.services import webchat_ai_service as ai
    db = _db()
    s = _session(db, contact=False)
    assert ai.can_use_ai(db, s, _cfg(db))[1] == "no_contact"
    db2 = _answer_first_db()
    assert ai.can_use_ai(db2, _session(db2, contact=False), _cfg(db2))[0] is True


def test_answer_first_is_a_known_setting_and_not_shown_to_visitors():
    from app.services import webchat_service as wc
    assert wc.sanitise_config({"answer_first": 1}) == {"answer_first": True}
    assert _cfg(_db())["answer_first"] is False
    assert "answer_first" not in wc.public_view(_cfg(_answer_first_db()))


def test_the_ai_is_told_to_greet_back():
    from app.services import webchat_ai_service as ai
    db = _answer_first_db()
    s, cfg = _session(db, contact=False), _cfg(db)
    prompt = ai.build_system_prompt(db, s, cfg, "hello")
    assert "greets you" in prompt and "Pidgin" in prompt and "goodbye" in prompt
