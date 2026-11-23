"""OPEN-OFFER-1: a booking offer made in an answer is not lost when the details ask comes in between, and a typed yes/no settles it."""
from unittest.mock import patch

import pytest

from tests.unit.test_webchat_3 import _db, _session, _cfg, _no_rate_limit, ORG  # noqa: F401
from app.services import webchat_contact_service as c
from app.services import webchat_flow_service as f
from app.services import webchat_service as wc

MENU = [
    {"id": "book", "label": "Book an appointment", "action": "booking", "keywords": ["book", "appointment"]},
    {"id": "whitening", "label": "Cosmetic dentistry", "answer": "Teeth whitening starts from N45,000 and takes about 45 minutes. Want to book a time?",
     "keywords": ["teeth whitening"]},
    {"id": "hours", "label": "Opening hours", "answer": "We open 9 to 6.", "keywords": ["hours"]},
    {"id": "team", "label": "Talk to the team", "action": "human", "keywords": []},
]


def _setup(contact=False):
    db = _db(ai=False, menu=MENU)
    return db, _session(db, contact=contact), None


def _texts(r):
    return [m["text"] for m in r["messages"] if m.get("role") != "visitor"]


@pytest.mark.parametrize("text", ["yes", "Yes", "yeah", "yeah sure", "ok please", "Yes please!", "sure", "y", "yes I would", "go ahead"])
def test_yes_variants(text):
    assert c.is_yes(text)


@pytest.mark.parametrize("text", ["no", "not now", "no thanks", "what is the price?", "sure what does it cost?", "yes no maybe so what now", "", "nothing"])
def test_not_yes(text):
    assert not c.is_yes(text) or text == ""


def test_details_then_the_booking_offer_comes_back_with_the_button():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=False), _cfg(db)
    r = f.handle_message(db, s, cfg, kind="menu", menu_id="whitening")
    assert not r.get("contact_step")                       # NAME-AT-ACTION-1: no name question after a plain answer
    c.start(db, s, cfg, "Happy to help.", optional=True)        # the visitor took an action that needs details
    for typed in ("Sandra", "08031234567", "yeah sure"):
        with patch.object(wc, "notify_managers"):
            r = f.handle_message(db, s, cfg, kind="text", text=typed)
    last = _texts(r)[-1]
    assert "book a time" in last.lower() and "What would you like to know" not in last
    assert any(ch.get("menu_id") == "book" for ch in r.get("choices", []))


def test_a_typed_yes_after_the_offer_starts_the_booking():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=True), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="whitening")
    assert s["state"].get("open_offer") == "book"
    r = f.handle_message(db, s, cfg, kind="text", text="Yes")
    joined = " ".join(_texts(r)).lower()
    assert "unable to answer" not in joined and ("booking" in joined or r.get("form") == "booking")
    assert not s["state"].get("open_offer")


def test_a_typed_no_closes_the_offer_politely():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=True), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="whitening")
    r = f.handle_message(db, s, cfg, kind="text", text="no thanks")
    assert "No problem" in _texts(r)[-1] and r.get("choices")
    assert not s["state"].get("open_offer")


def test_other_action_settles_the_offer():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=True), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="whitening")
    f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    assert not s["state"].get("open_offer")
    r = f.handle_message(db, s, cfg, kind="text", text="yes")
    assert "booking" not in " ".join(_texts(r)).lower()


def test_an_answer_with_no_booking_question_opens_no_offer():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=True), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    assert not s["state"].get("open_offer")


def test_the_consent_step_accepts_yeah_sure():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=False), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    c.start(db, s, cfg, "Happy to help.", optional=True)        # the visitor took an action that needs details
    for typed in ("Ada", "08031234567", "yeah sure"):
        with patch.object(wc, "notify_managers"):
            r = f.handle_message(db, s, cfg, kind="text", text=typed)
    assert any("Thank you" in t for t in _texts(r)) and not r.get("contact_step")


def test_consent_comes_with_yes_and_no_buttons_and_no_instruction_to_type():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=False), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    c.start(db, s, cfg, "Happy to help.", optional=True)        # the visitor took an action that needs details
    f.handle_message(db, s, cfg, kind="text", text="Ada")
    r = f.handle_message(db, s, cfg, kind="text", text="08031234567")
    assert [ch["label"] for ch in r["choices"]] == ["Yes", "No"] and all(ch["id"] == "say" for ch in r["choices"])
    assert "Reply Yes or No" not in _texts(r)[-1]


def test_bot_mode_wording_does_not_invite_free_questions():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=False), _cfg(db)
    f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    for typed in ("Ada", "08031234567", "yes"):
        r = f.handle_message(db, s, cfg, kind="text", text=typed)
    assert "type your question" not in _texts(r)[-1] and r.get("choices")
    # saying no to consent
    s2 = _session(db, contact=False)
    f.handle_message(db, s2, cfg, kind="menu", menu_id="hours")
    for typed in ("Ada", "08031234567", "no"):
        r = f.handle_message(db, s2, cfg, kind="text", text=typed)
    assert "ask me anything" not in _texts(r)[-1]


def test_typed_product_words_show_the_product_card_without_ai():
    db = _db(ai=False, menu=MENU, shop_enabled=True)
    db.tables["products"] = [
        {"id": "P1", "org_id": ORG, "title": "Water Flosser", "price": 32000, "variants": [], "catalog_images": [], "description": "Cordless", "available": True},
        {"id": "P2", "org_id": ORG, "title": "Gentle Foaming Cleanser", "price": 11500, "variants": [], "catalog_images": [], "description": "", "available": True},
    ] if hasattr(db, "tables") else None
    s, cfg = _session(db, contact=True), _cfg(db)
    r = f.handle_message(db, s, cfg, kind="text", text="do you have a water flosser?")
    assert [c["id"] for c in r["cards"]] == ["P1"] and "Water Flosser" in _texts(r)[-1] and "unable to answer" not in _texts(r)[-1]
    r = f.handle_message(db, s, cfg, kind="text", text="blah blah nothing")
    assert not r.get("cards")


def test_the_first_details_ask_has_a_friendly_lead_in():
    db = _db(ai=False, menu=MENU)
    s, cfg = _session(db, contact=False), _cfg(db)
    r = f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
    assert not r.get("contact_step") and not any("first name" in t for t in _texts(r))
    last = c.start(db, s, cfg, "Happy to help.", optional=True)["text"]
    assert last.startswith("Happy to help. So the team knows") and "first name" in last
