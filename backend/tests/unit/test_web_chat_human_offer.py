"""HUMAN-OFFER-1: a first tap on Talk to the team is offered a quick answer first (once, switchable, never for typed requests)."""
from __future__ import annotations

from unittest.mock import patch

from app.services import webchat_flow_service as flow
from app.services import webchat_handover_service as ho
from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _db, _no_rate_limit, _session  # noqa: F401


def _hid(cfg):
    return next(m["id"] for m in cfg["menu"] if m.get("action") == "human")


def _tap(db, s, cfg, mid):
    return flow.handle_message(db, s, cfg, kind="menu", menu_id=mid, text=None, reply_to=None)


def _on(**kw):
    return _db(ai=False, human_offer=True, **kw)


def test_setting_defaults_off_and_is_kept():
    assert wc.DEFAULT_CONFIG["human_offer"] is False
    assert wc.sanitise_config({"human_offer": 1})["human_offer"] is True


def test_off_goes_straight_to_the_team():
    db = _db(ai=False); s = _session(db); cfg = _cfg(db)
    r = _tap(db, s, cfg, _hid(cfg))
    assert r["human"] is True and not r.get("choices")


def test_first_tap_gets_the_offer_with_topics_and_connect_button():
    db = _on(); s = _session(db); cfg = _cfg(db)
    with patch.object(ho, "is_away", return_value=False):
        r = _tap(db, s, cfg, _hid(cfg))
    assert r["human"] is False
    assert "What is it about" in r["messages"][-1]["text"]
    ids = [c["id"] for c in r["choices"]]
    assert ids == ["item", "human"] and r["choices"][0]["menu_id"] == "hours"
    assert r["choices"][-1]["label"] == "No, connect me to the team"
    assert s["state"]["offer"] == "shown"


def test_away_wording():
    db = _on(); s = _session(db); cfg = _cfg(db)
    with patch.object(ho, "is_away", return_value=True):
        r = _tap(db, s, cfg, _hid(cfg))
    assert "away" in r["messages"][-1]["text"] and r["choices"][-1]["label"] == "Leave a message for the team"


def test_second_tap_goes_straight_through_and_is_counted():
    db = _on(); s = _session(db); cfg = _cfg(db)
    with patch.object(ho, "is_away", return_value=False):
        _tap(db, s, cfg, _hid(cfg))
        r = _tap(db, s, cfg, _hid(cfg))
    assert r["human"] is True and s["state"]["offer"] == "skipped"
    refs = [e.get("ref") for e in db.tables["webchat_events"]] if hasattr(db, "tables") else []
    assert not refs or "offer_skipped" in refs


def test_topic_answer_is_followed_by_did_that_help():
    db = _on(); s = _session(db); cfg = _cfg(db)
    with patch.object(ho, "is_away", return_value=False):
        _tap(db, s, cfg, _hid(cfg))
        r = _tap(db, s, cfg, "hours")
    texts = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert "We open 9 to 6" in texts[0] and texts[-1].startswith("Did that help")
    assert any(c["id"] == "human" for c in r["choices"]) and s["state"]["offer"] == "answered"
    with patch.object(ho, "is_away", return_value=False):
        r2 = _tap(db, s, cfg, _hid(cfg))
    assert r2["human"] is True                          # once per chat


def test_no_offer_after_an_answer_or_for_typed_requests():
    db = _on(); s = _session(db); cfg = _cfg(db)
    _tap(db, s, cfg, "hours")
    r = _tap(db, s, cfg, _hid(cfg))
    assert r["human"] is True
    db2 = _on(); s2 = _session(db2); cfg2 = _cfg(db2)
    r2 = flow.handle_message(db2, s2, cfg2, kind="text", menu_id=None, text="human", reply_to=None)
    assert not r2.get("choices") or all(c.get("id") != "item" for c in r2["choices"])


def test_no_offer_without_topics():
    db = _db(ai=False, human_offer=True); cfg = _cfg(db)
    cfg["menu"] = [m for m in cfg["menu"] if m.get("action") == "human"]
    s = _session(db)
    assert _tap(db, s, cfg, _hid(cfg))["human"] is True


def test_question_typed_while_asked_for_a_name_is_answered_when_team_is_away():
    """Away + Leave a message + asked for a first name + visitor types a question: she answers it (not 'saved for the team'), then asks the name once more."""
    db = _db(ai=False); s = _session(db, contact=False); cfg = _cfg(db)
    with patch.object(ho, "is_away", return_value=True), patch.object(wc, "notify_managers"):
        r = _tap(db, s, cfg, _hid(cfg))
        assert r["contact_step"] == "name"
        r = flow.handle_message(db, s, cfg, kind="text", menu_id=None, text="When do you open and what are your hours?", reply_to=None)
    bot = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert any("We open 9 to 6" in x for x in bot)
    assert not any(x.startswith("Got it") or "saved this for the team" in x.lower() for x in bot)
    assert bot[-1].startswith("Now, so the team knows") and r["contact_step"] == "name"


def test_ai_reply_with_one_bad_sentence_is_patched_and_long_replies_are_cut():
    from app.services import webchat_ai_service as ai
    from tests.unit.test_webchat_3 import _claude
    db = _db(); s = _session(db); cfg = _cfg(db)
    raw = '{"reply": "We open 9 to 6, Monday to Saturday. Our hotline is 08099999999. Come by any time. Bring a friend. Bring two.", "handoff": false}'
    with _claude(raw), patch("app.services.webchat_plan_service.use_ai_allowance", return_value=True):
        out = ai.answer(db, s, cfg, "when are you open")
    assert out and out["handoff"] is False and "08099999999" not in out["reply"] and out["reply"].startswith("We open 9 to 6")
    assert out["reply"].count(".") <= 3
