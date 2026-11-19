"""SMART-1: Chioma with the AI off: forgiving word matching, related buttons, built-in answers, guided form, starters, checklist, teach."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import knowledge_gap_service as kgap
from app.services import webchat_flow_service as flow
from app.services import webchat_handover_service as ho
from app.services import webchat_service as wc
from app.services import webchat_smart_service as smart
from tests.unit.test_webchat_3 import _cfg, _db, _no_rate_limit, _session  # noqa: F401

MENU = [
    {"id": "book", "label": "Book a call", "action": "booking", "keywords": ["book", "appointment"]},
    {"id": "websites", "label": "Websites and prices", "answer": "WEBSITES ANSWER", "keywords": ["website", "price", "cost", "how much"]},
    {"id": "learn", "label": "Learn: AI training", "answer": "LEARN ANSWER", "keywords": ["learn", "training", "course"]},
    {"id": "quote", "label": "Get a quote", "action": "guide", "keywords": ["quote"],
     "guide": {"steps": [{"q": "What do you need?", "options": ["Website", "Training"]}, {"q": "When do you need it?", "options": ["This week", "Later"]}], "done": "Sent to the team."}},
    {"id": "human", "label": "Talk to the team", "action": "human", "keywords": []},
]


def _ctx(**cfg_extra):
    db = _db(ai=False); s = _session(db); cfg = _cfg(db); cfg["menu"] = MENU; cfg.update(cfg_extra)
    return db, s, cfg


def _text(db, s, cfg, text):
    return flow.handle_message(db, s, cfg, kind="text", menu_id=None, text=text, reply_to=None)


def _bot(r):
    return [m["text"] for m in r["messages"] if m["role"] == "bot"]


# ── 1 matching ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("prices", "websites"), ("pricing please", "websites"), ("how much be website", "websites"), ("wetin be the prcies", "websites"),
    ("courses", "learn"), ("i wan learn", "learn"), ("my trainning", "learn"), ("bok an appointment", "book"),
])
def test_forgiving_matching(text, expected):
    cfg = {"menu": MENU}
    assert flow._match_item(cfg, text).get("id") == expected


def test_unrelated_words_do_not_match():
    cfg = {"menu": MENU}
    assert flow._match_item(cfg, "banana smoothie") is None and flow._match_item(cfg, "coat") is None


def test_two_equal_weak_matches_ask_which_one():
    menu = [{"id": "a", "label": "Hair", "answer": "A", "keywords": ["braids"]}, {"id": "b", "label": "Wigs", "answer": "B", "keywords": ["braids"]},
            {"id": "human", "label": "Talk", "action": "human", "keywords": []}]
    db = _db(ai=False); s = _session(db); cfg = _cfg(db); cfg["menu"] = menu
    r = _text(db, s, cfg, "braids")
    assert "Which of these" in _bot(r)[-1] and [c["menu_id"] for c in r["choices"]] == ["a", "b"]


# ── 3 related buttons ───────────────────────────────────────────────────────

def test_answer_is_followed_by_related_buttons_not_the_same_one():
    db, s, cfg = _ctx()
    r = _text(db, s, cfg, "prices")
    ids = [c.get("menu_id") or c["id"] for c in r["choices"]]
    assert "websites" not in ids and ids[0] in ("book", "quote") and ids[-1] == "human" and len(r["choices"]) <= 4


# ── 4 built-in answers ──────────────────────────────────────────────────────

def test_hours_phone_and_address_come_from_the_business_details():
    db, s, cfg = _ctx(address="12 Allen Avenue, Ikeja", call_enabled=True, call_number="08054313945")
    cfg["_call_org"] = {"business_hours": {"mon": {"open": "08:00", "close": "17:00"}}, "timezone": "Africa/Lagos", "fallback_number": ""}
    with patch("app.services.webchat_call_service.hours_text", return_value="Mon to Fri 8:00 am to 5:00 pm"), patch.object(ho, "team_state", return_value=("closed", "tomorrow at 8:00 am")):
        assert "Mon to Fri 8:00 am to 5:00 pm" in _bot(_text(db, s, cfg, "what time do you open?"))[-1]
        assert "away and back tomorrow at 8:00 am" in _bot(_text(db, s, cfg, "are you open"))[-1]
    assert "0805 431 3945" in _bot(_text(db, s, cfg, "what is your phone number"))[-1]
    assert "12 Allen Avenue" in _bot(_text(db, s, cfg, "where are you"))[-1]


def test_no_built_in_answer_when_the_detail_is_not_set():
    assert smart.info_answer({"menu": []}, "where are you") is None
    assert smart.info_answer({"menu": []}, "what is your phone number") is None


def test_a_long_enquiry_is_not_taken_for_a_hours_question():
    cfg = {"address": "X", "menu": []}
    assert smart.info_answer(cfg, "I want a website for my business and I would like to know about the location of the studio and the prices") is None


# ── 5 guided form ───────────────────────────────────────────────────────────

def test_guided_form_asks_each_question_then_hands_a_summary_to_the_team():
    db, s, cfg = _ctx()
    with patch.object(flow, "_notify_human") as notify, patch.object(ho, "is_away", return_value=False):
        r = flow.handle_message(db, s, cfg, kind="menu", menu_id="quote", text=None, reply_to=None)
        assert _bot(r)[-1] == "What do you need?" and [c["label"] for c in r["choices"]] == ["Website", "Training"] and all(c["id"] == "say" for c in r["choices"])
        r = _text(db, s, cfg, "Website")
        assert _bot(r)[-1] == "When do you need it?"
        r = _text(db, s, cfg, "This week")
    assert r["human"] is True and "Sent to the team." in _bot(r)[0]
    note = notify.call_args[0][3]
    assert "Get a quote" in note and "What do you need: Website" in note and "When do you need it: This week" in note
    assert not (s.get("state") or {}).get("guide")


def test_a_real_question_leaves_the_guide_and_is_answered():
    db, s, cfg = _ctx()
    flow.handle_message(db, s, cfg, kind="menu", menu_id="quote", text=None, reply_to=None)
    r = _text(db, s, cfg, "what are your prices?")
    assert any("WEBSITES ANSWER" in x for x in _bot(r)) and not (s.get("state") or {}).get("guide")


def test_tapping_another_button_drops_the_guide():
    db, s, cfg = _ctx()
    flow.handle_message(db, s, cfg, kind="menu", menu_id="quote", text=None, reply_to=None)
    flow.handle_message(db, s, cfg, kind="menu", menu_id="learn", text=None, reply_to=None)
    assert not (s.get("state") or {}).get("guide")


def test_guide_items_survive_sanitise_and_bad_ones_are_dropped():
    out = wc.sanitise_config({"menu": [{"id": "q", "label": "Quote", "action": "guide", "guide": {"steps": [{"q": "What?", "options": ["a", "b"]}]}},
                                       {"id": "bad", "label": "Bad", "action": "guide", "guide": {"steps": []}}]})
    assert [m["id"] for m in out["menu"]] == ["q"] and out["menu"][0]["guide"]["steps"][0]["options"] == ["a", "b"]


def test_parse_guide_text():
    g = smart.parse_guide_text("What do you need?: Website | Training\nWhen?: Soon|Later\nAnything else")
    assert [len(s["options"]) for s in g["steps"]] == [2, 2, 0] and g["steps"][1]["q"] == "When?"


# ── 6 away + 2 unanswered ───────────────────────────────────────────────────

def test_no_answer_while_away_offers_booking_first_and_notes_the_question():
    db, s, cfg = _ctx()
    with patch.object(ho, "is_away", return_value=True), patch.object(kgap, "record") as rec:
        r = _text(db, s, cfg, "banana smoothie recipe please")
    assert r["choices"][0] == {"id": "item", "menu_id": "book", "label": "Book a call"}
    rec.assert_called_once()
    assert rec.call_args[0][2] == "banana smoothie recipe please"


def test_emoji_is_not_noted_as_unanswered():
    db, s, cfg = _ctx()
    with patch.object(kgap, "record") as rec:
        _text(db, s, cfg, "???")
    rec.assert_not_called()


# ── 7 starters, checklist, teach ────────────────────────────────────────────

@pytest.mark.parametrize("key", list(smart.STARTERS))
def test_every_starter_menu_is_valid(key):
    menu = smart.STARTERS[key]["menu"]
    out = wc.sanitise_config({"menu": menu})["menu"]
    assert len(out) == len(menu) and any(m.get("action") == "human" for m in out) and len(out) <= wc.MENU_MAX


def test_checklist_reflects_what_is_set():
    cfg = {"menu": [{"id": "a", "label": "A", "answer": "[add]", "keywords": ["x"]}], "_call_org": {}}
    c = smart.checklist(cfg, 2)
    done = {i["id"]: i["done"] for i in c["items"]}
    assert done["menu"] is False and done["placeholders"] is False and done["hours"] is False and done["unanswered"] is False
    full = {"menu": [{"id": f"i{n}", "label": f"I{n}", "answer": f"Real answer {n}", "keywords": ["a", "b", "c"]} for n in range(3)]
            + [{"id": "bk", "label": "Book", "action": "booking"}, {"id": "h", "label": "Team", "action": "human"}],
            "address": "Here", "call_enabled": True, "call_number": "08054313945", "_call_org": {}}
    with patch("app.services.webchat_call_service.hours_text", return_value="Mon 8:00 am to 5:00 pm"):
        c2 = smart.checklist(full, 0)
    assert c2["done"] == c2["total"]


def test_suggest_keyword_takes_the_longest_content_word():
    assert smart.suggest_keyword("Do you do catering for weddings?") == "catering"
    assert smart.suggest_keyword("hi") == ""


def test_teach_adds_the_keyword_and_closes_the_question():
    db = _db(ai=False)
    cfg = wc.get_config(db, "org-1") if False else None
    from tests.unit.test_webchat_3 import ORG
    db.tables["knowledge_gaps"] = [{"id": "g1", "org_id": ORG, "question": "catering for weddings", "status": "open"}] if hasattr(db, "tables") else None
    with patch.object(wc, "get_config", return_value={"menu": [dict(m) for m in MENU]}), patch.object(wc, "save_config") as save:
        class _Q:
            def __init__(self): self.rows = [{"id": "g1"}]
            def select(self, *a): return self
            def update(self, *a): self.upd = a; return self
            def eq(self, *a): return self
            def limit(self, *a): return self
            def execute(self):
                class R: data = [{"id": "g1"}]
                return R()
        class _DB:
            def table(self, n): return _Q()
        res = smart.teach(_DB(), ORG, "g1", "websites", "Catering")
    assert res["keyword"] == "catering"
    saved = save.call_args[0][2]["menu"]
    assert "catering" in next(m for m in saved if m["id"] == "websites")["keywords"]
    with pytest.raises(ValueError):
        smart.teach(_DB(), ORG, "g1", "human", "x1")


# ── MENU-MORE: featured buttons lead ────────────────────────────────────────

def test_featured_flag_is_kept_and_sent_to_visitors():
    out = wc.sanitise_config({"menu": [{"id": "a", "label": "A", "answer": "x", "featured": True}, {"id": "b", "label": "B", "answer": "y"}]})
    assert out["menu"][0].get("featured") is True and "featured" not in out["menu"][1]
    cfg = dict(wc.DEFAULT_CONFIG); cfg.update(out); cfg["business_name"] = "X"
    pv = wc.public_view(cfg)["menu"]
    assert pv[0].get("featured") is True and "featured" not in pv[1]


def test_ask_bar_chips_lead_with_featured_buttons():
    cfg = {"ask_bar": True, "menu": [{"id": "a", "label": "A"}, {"id": "b", "label": "B", "featured": True}, {"id": "c", "label": "C"},
                                      {"id": "d", "label": "D"}, {"id": "t", "label": "Team", "action": "human", "featured": True}]}
    bar = wc.ask_bar_view(cfg)
    assert [c["id"] for c in bar["chips"]] == ["b"] and bar["more"] is True
    cfg["menu"][1].pop("featured")
    bar = wc.ask_bar_view(cfg)
    assert [c["id"] for c in bar["chips"]] == ["a", "b", "c"]


def test_related_and_overview_prefer_featured():
    cfg = {"menu": [{"id": "a", "label": "A", "answer": "x"}, {"id": "b", "label": "B", "answer": "y", "featured": True}, {"id": "c", "label": "C", "answer": "z"},
                    {"id": "h", "label": "Team", "action": "human"}]}
    assert smart.related(cfg, {"id": "c"})[0]["menu_id"] == "b"
    assert flow._overview(cfg)["choices"][0]["menu_id"] == "b"
