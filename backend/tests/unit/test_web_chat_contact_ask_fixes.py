"""Contact ask fixes: Talk to the team asks in the chat (no form), the name question wording, a robust name check, and a real question
typed during the required ask is answered first and the ask is repeated once."""
from unittest.mock import patch

from tests.unit.test_webchat_3 import _db, _session, _cfg, _claude, _no_rate_limit, ORG  # noqa: F401
from app.services import webchat_contact_service as c
from app.services import webchat_flow_service as f
from app.services import webchat_service as wc


import pytest


@pytest.mark.parametrize("text,expected", [
    ("Ada", "Ada"), ("ada", "Ada"), ("ADA", "Ada"), ("my name is Ada Obi", "Ada Obi"), ("Hi, I am Chinedu", "Chinedu"),
    ("hello my name is Ngozi", "Ngozi"), ("it's Tunde", "Tunde"), ("call me Bola", "Bola"), ("Ada here", "Ada"), ("Ada, thanks", "Ada"),
    ("Ọlá Adéyemi", "Ọlá Adéyemi"), ("O'Brien", "O'Brien"), ("Mary-Jane", "Mary-Jane"), ("Will Smith", "Will Smith"), ("Grace", "Grace"),
    ("McDonald", "McDonald"), ("Dr. Okafor", "Dr. Okafor"), ("Ng", "Ng"), ("  Ada   ", "Ada"), ("you can call me Seyi", "Seyi"),
])
def test_real_names_are_accepted(text, expected):
    assert c._clean_name(text) == expected


@pytest.mark.parametrize("text", [
    "I need a website", "do you sell phones", "what are your prices", "how much is it?", "hello", "hi", "hey there", "yes", "no", "ok", "thanks",
    "good morning", "I want to buy", "I am looking for a logo", "can you call me", "08031234567", "ada@example.com", "https://example.com",
    "www.example.com", "Ada123", "asdfasdf!!!", "aaaaaa", "😀", "???", "", "   ", "A", "not now", "nothing", "skip", "test", "price",
    "my name", "I", "the team", "please help me", "Ada Obi Okafor Nwosu Eze", "12345", "@@@", "tell me more", "what", "Chioma", "whatsapp",
])
def test_things_that_are_not_names_are_rejected(text):
    assert c._clean_name(text) is None


def test_a_name_is_not_taken_from_a_very_long_message():
    assert c._clean_name("Ada " * 30) is None


def test_the_name_question_wording():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    m = c.start(db, s, cfg, "")
    assert m["text"] == "So the team knows who they are replying to, may I have your first name?"
    m = c.start(db, s, cfg, "Happy to arrange a call back.")
    assert m["text"].startswith("Happy to arrange a call back. So the team knows")
    assert "What name should I use" not in m["text"] and "couple of details" not in m["text"]


def test_talk_to_the_team_asks_in_the_chat_not_with_the_form():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["menu"] = [{"id": "team", "label": "Talk to the team", "action": "human"}]
    with patch.object(wc, "notify_managers"):
        r = f.handle_message(db, s, cfg, kind="menu", menu_id="team")
    assert r["contact_step"] == "name" and r["ask_contact"] is False and r["human"] is True
    assert "first name" in r["messages"][-1]["text"]


def test_talk_to_the_team_falls_back_to_the_form_when_in_chat_details_are_off():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["menu"] = [{"id": "team", "label": "Talk to the team", "action": "human"}]
    cfg["contact_in_chat"] = False
    with patch.object(wc, "notify_managers"):
        r = f.handle_message(db, s, cfg, kind="menu", menu_id="team")
    assert r["ask_contact"] is True and not r.get("contact_step")


def test_the_name_typed_while_a_person_is_looking_after_the_chat_goes_to_the_script_not_the_team():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["menu"] = [{"id": "team", "label": "Talk to the team", "action": "human"}]
    with patch.object(wc, "notify_managers") as nm:
        f.handle_message(db, s, cfg, kind="menu", menu_id="team")
        r = f.handle_message(db, s, cfg, kind="text", text="Ada Obi")
    assert r["contact_step"] == "phone" and "Nice to meet you, Ada" in r["messages"][-1]["text"]
    assert r["human"] is True                                   # the hand-over stays on
    assert nm.call_count == 1                                   # the name was not forwarded to the team as a message


def test_a_real_question_during_the_required_ask_is_answered_then_the_ask_is_repeated_once():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["menu"] = [{"id": "hours", "label": "Opening hours", "answer": "We open 9 to 6.", "keywords": ["hours"]}]
    cfg["ai_enabled"] = False
    c.start(db, s, cfg, "Happy to arrange a call back.")          # required ask (not the gentle one)
    r = f.handle_message(db, s, cfg, kind="text", text="what are your opening hours?")
    texts = [m["text"] for m in r["messages"]]
    assert texts[0] == "what are your opening hours?" and "We open 9 to 6." in texts[1]       # answered first
    assert texts[-1].startswith("Now, so the team knows") and r["contact_step"] == "name"      # then asked again
    assert len([m for m in s["history"] if m["role"] == "visitor"]) == 1                        # the question was stored once
    # a second question is not deflected again: it counts as a failed try, then the form
    r = f.handle_message(db, s, cfg, kind="text", text="and where are you located?")
    assert "did not catch a first name" in r["messages"][-1]["text"]
    r = f.handle_message(db, s, cfg, kind="text", text="and what about prices?")
    assert r["ask_contact"] is True


def test_the_gentle_ask_is_still_dropped_quietly_and_never_repeated():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["ai_enabled"] = False
    c.start(db, s, cfg, "", optional=True)
    r = f.handle_message(db, s, cfg, kind="text", text="what are your prices?")
    assert s["state"].get("contact_step") is None and not r.get("contact_step")


def test_a_question_during_the_phone_step_is_answered_and_the_number_asked_again():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg["menu"] = [{"id": "hours", "label": "Opening hours", "answer": "We open 9 to 6.", "keywords": ["hours"]}]
    cfg["ai_enabled"] = False
    c.start(db, s, cfg, "")
    f.handle_message(db, s, cfg, kind="text", text="Ada")
    r = f.handle_message(db, s, cfg, kind="text", text="what are your opening hours?")
    assert r["contact_step"] == "phone" and "WhatsApp number" in r["messages"][-1]["text"] and "We open 9 to 6." in r["messages"][1]["text"]


def test_can_deflect_rules():
    db = _db()
    s, cfg = _session(db, contact=False), _cfg(db)
    c.start(db, s, cfg, "")
    assert c.can_deflect(s, "what are your prices?") is True
    assert c.can_deflect(s, "Ada") is False
    assert c.can_deflect(s, "hello") is False                    # a stray word is a failed try, not a question
    wc.set_state(db, s, contact_deflected=1)
    assert c.can_deflect(s, "what are your prices?") is False    # only once
