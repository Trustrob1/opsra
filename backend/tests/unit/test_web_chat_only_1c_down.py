"""ONLY-1c-DOWN: when Chioma has no answer the visitor gets a way forward that fits the clock: menu, leave a message / talk to the team,
call or call back. The owner is emailed. A failed AI call does not use up the plan's AI allowance."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import account_entitlement_service as acc
from app.services import chat_signup_service as signup
from app.services import webchat_ai_service as ai
from app.services import webchat_flow_service as flow
from app.services import webchat_handover_service as ho
from app.services import webchat_service as wc
from tests.unit.test_account_plans_1 import BIZ, _db as _plans_db, _env, _plan  # noqa: F401
from tests.unit.test_webchat_3 import ORG, _cfg, _claude, _db, _no_rate_limit, _session  # noqa: F401

STOCK_FALLBACK = wc.DEFAULT_CONFIG["fallback"]
STOCK_HUMAN = wc.DEFAULT_CONFIG["human_reply"]
MENU = [{"id": "prices", "label": "See prices", "answer": "x", "keywords": []}, {"id": "human", "label": "Talk to the team", "action": "human"}]


def _cfg_for(open_state="open", reopens="Monday at 8:00 am", call=True, menu=None, fallback=None, human_reply=None):
    cfg = {"menu": MENU if menu is None else menu, "fallback": fallback or STOCK_FALLBACK, "human_reply": human_reply or STOCK_HUMAN}
    return cfg, {"open": open_state, "reopens": reopens, "call": call}


def _na(open_state="open", reopens="Monday at 8:00 am", call=True, **kw):
    cfg, st = _cfg_for(open_state, reopens, call, **kw)
    with patch.object(ho, "team_state", return_value=(st["open"], st["reopens"] if st["open"] == "closed" else "")), \
         patch.object(ho, "_call_on", return_value=st["call"]):
        return ho.no_answer(cfg)


def _labels(r):
    return [c["label"] for c in r["choices"]]


# ── the reply and the buttons ───────────────────────────────────────────────

def test_inside_hours_with_call_offers_menu_team_and_call():
    r = _na("open", call=True)
    assert "Talk to the team" in r["text"] and "Call us" in r["text"] and "unable to answer" in r["text"]
    assert _labels(r) == ["Open menu", "Talk to the team", "Call us"]
    assert [c["id"] for c in r["choices"]] == ["menu", "human", "call"]


def test_inside_hours_without_call_has_no_call_button_or_words():
    r = _na("open", call=False)
    assert "Call us" not in r["text"] and _labels(r) == ["Open menu", "Talk to the team"]


def test_after_hours_says_when_the_team_is_back_and_offers_leave_a_message_and_call_back():
    r = _na("closed", "Monday at 8:00 am", call=True)
    assert "away until Monday at 8:00 am" in r["text"] and "Leave a message" in r["text"] and "Request a call back" in r["text"]
    assert _labels(r) == ["Open menu", "Leave a message", "Request a call back"]


def test_after_hours_without_call_has_no_call_back():
    r = _na("closed", call=False)
    assert "call back" not in r["text"].lower() and _labels(r) == ["Open menu", "Leave a message"]


def test_no_hours_set_never_claims_the_team_is_away():
    r = _na("unknown", call=False)
    assert "away" not in r["text"] and "as soon as they can" in r["text"] and "Leave a message" in _labels(r)


def test_the_old_did_not_catch_that_wording_never_appears():
    for st in ("open", "closed", "unknown"):
        assert "did not catch" not in _na(st)["text"]


def test_a_business_that_wrote_its_own_fallback_keeps_it_and_still_gets_buttons():
    r = _na("open", fallback="Sorry, ask our team.")
    assert r["text"] == "Sorry, ask our team." and "Open menu" in _labels(r)


def test_buttons_only_when_they_can_work():
    r = _na("open", menu=[{"id": "prices", "label": "See prices", "answer": "x"}], call=False)    # menu but no human item
    assert _labels(r) == ["Open menu"]
    assert _na("open", menu=[], call=False)["choices"] == []


# ── the hand-over confirmation ──────────────────────────────────────────────

def test_human_reply_after_hours_says_when_back():
    cfg, _ = _cfg_for()
    with patch.object(ho, "team_state", return_value=("closed", "Monday at 8:00 am")):
        t = ho.human_reply(cfg)
    assert "away until Monday at 8:00 am" in t and "saved" in t


def test_human_reply_inside_hours_or_unknown_is_the_stock_line_and_custom_is_kept():
    cfg, _ = _cfg_for()
    for st in (("open", ""), ("unknown", ""), ("closed", "")):
        with patch.object(ho, "team_state", return_value=st):
            assert ho.human_reply(cfg) == STOCK_HUMAN
    custom, _ = _cfg_for(human_reply="We will be in touch.")
    with patch.object(ho, "team_state", return_value=("closed", "Monday at 8:00 am")):
        assert ho.human_reply(custom) == "We will be in touch."


def test_team_state_reads_the_real_hours():
    sat_only = {"sat": {"start": "09:00", "end": "13:00"}}
    cfg = {"_call_org": {"business_hours": sat_only, "timezone": "Africa/Lagos"}}
    assert ho.team_state({"_call_org": {}})[0] == "unknown"
    assert ho.team_state({})[0] == "unknown"
    st, reopens = ho.team_state(cfg)
    assert st in ("open", "closed") and (st == "open" or "Saturday" in reopens or "tomorrow" in reopens or "today" in reopens)


# ── the email to the owner ──────────────────────────────────────────────────

def test_owner_is_emailed_with_the_message_and_how_to_reach_the_visitor():
    s = {"org_id": ORG, "contact_name": "Ada Obi", "contact_phone": "2348012345678", "contact_email": None}
    with patch("app.services.chat_pause_service._owner_emails", return_value=["o@x.test", "p@x.test"]), \
         patch("app.services.site_addon_billing_service._send_email", return_value=True) as send, \
         patch.object(ho, "team_state", return_value=("closed", "Monday at 8:00 am")):
        n = ho.email_owner(None, s, {}, "Do you do logos?")
    assert n == 2 and send.call_count == 2
    to, subject, body = send.call_args_list[0].args
    assert to == "o@x.test" and "Ada Obi" in subject and "Do you do logos?" in body and "2348012345678" in body and "Monday at 8:00 am" in body


def test_email_failure_never_breaks_the_chat():
    with patch("app.services.chat_pause_service._owner_emails", side_effect=RuntimeError("db down")):
        assert ho.email_owner(None, {"org_id": ORG}, {}, "hi") == 0
    with patch("app.services.chat_pause_service._owner_emails", return_value=["o@x.test"]), \
         patch("app.services.site_addon_billing_service._send_email", return_value=False):
        assert ho.email_owner(None, {"org_id": ORG}, {}, "hi") == 0


# ── the chat flow ───────────────────────────────────────────────────────────

def test_ai_down_gives_the_hours_aware_reply_and_choices():
    db = _db(ai=True)
    s, cfg = _session(db), _cfg(db)
    with _claude(None), patch.object(ho, "team_state", return_value=("closed", "Monday at 8:00 am")), patch.object(ho, "_call_on", return_value=False):
        r = flow.handle_message(db, s, cfg, kind="text", text="do you do logos for restaurants")
    bot = [m["text"] for m in r["messages"] if m["role"] == "bot"]
    assert len(bot) == 1 and "away until Monday at 8:00 am" in bot[0]
    assert r["choices"] and r["choices"][0]["id"] == "menu" and any(c["label"] == "Leave a message" for c in r["choices"])
    assert r["cards"] == []


def test_normal_answers_carry_no_choices():
    db = _db(ai=True)
    s, cfg = _session(db), _cfg(db)
    with _claude('{"reply": "We open 9 to 6.", "handoff": false}'):
        r = flow.handle_message(db, s, cfg, kind="text", text="when do you open")
    assert "choices" not in r


def test_leave_a_message_button_hands_over_with_an_hours_aware_note_and_emails_once_per_ten_minutes():
    db = _db(ai=True)
    s, cfg = _session(db), _cfg(db)
    with patch.object(ho, "team_state", return_value=("closed", "Monday at 8:00 am")), \
         patch("app.services.chat_pause_service._owner_emails", return_value=["o@x.test"]), \
         patch("app.services.site_addon_billing_service._send_email", return_value=True) as send:
        r = flow.handle_message(db, s, cfg, kind="menu", menu_id="team")
        assert r["human"] is True
        assert any("away until Monday at 8:00 am" in m["text"] for m in r["messages"] if m["role"] == "bot")
        flow.handle_message(db, s, cfg, kind="text", text="also, my budget is 50k")         # still within 10 minutes
    assert send.call_count == 1


# ── a failed AI call does not use the allowance ─────────────────────────────

def _ai_run(reply):
    db = _db(ai=True)
    s, cfg = _session(db), _cfg(db)
    plan = MagicMock()
    plan.use_ai_allowance.return_value = True
    with patch("app.services.webchat_plan_service.use_ai_allowance", plan.use_ai_allowance), \
         patch("app.services.webchat_plan_service.give_back_ai_allowance", plan.give_back_ai_allowance), _claude(reply):
        out = ai.answer(db, s, cfg, "do you do logos")
    return out, plan


def test_failed_call_gives_the_allowance_back():
    out, plan = _ai_run(None)
    assert out is None and plan.give_back_ai_allowance.call_count == 1


def test_an_empty_reply_gives_the_allowance_back():
    out, plan = _ai_run("")
    assert out is None and plan.give_back_ai_allowance.call_count == 1


def test_a_real_answer_keeps_the_allowance_used():
    out, plan = _ai_run('{"reply": "Yes we do.", "handoff": false}')
    assert out and out["reply"] == "Yes we do." and plan.give_back_ai_allowance.call_count == 0


def test_a_crash_inside_the_call_gives_it_back_too():
    db = _db(ai=True)
    s, cfg = _session(db), _cfg(db)
    give = MagicMock()
    with patch("app.services.webchat_plan_service.use_ai_allowance", return_value=True), \
         patch("app.services.webchat_plan_service.give_back_ai_allowance", give), \
         patch("app.services.ai_service.call_claude", side_effect=RuntimeError("boom")):
        assert ai.answer(db, s, cfg, "do you do logos") is None
    assert give.call_count == 1


def test_refund_returns_exactly_what_was_taken_and_never_below_zero():
    db = _plans_db(True, [_plan(key="convert", source="staff", until="none")])
    assert acc.consume(db, "ai_assistant", org_id=BIZ, n=2) is True
    assert acc.refund(db, "ai_assistant", org_id=BIZ, n=1) is True
    assert acc.get_entitlements(db, BIZ)["usage"]["ai_messages"] == {"used": 1, "cap": 3}
    assert acc.refund(db, "ai_assistant", org_id=BIZ, n=5) is True
    assert acc.get_entitlements(db, BIZ)["usage"]["ai_messages"] == {"used": 0, "cap": 3}


def test_refund_is_a_no_op_when_plans_are_not_enforced_or_input_is_bad():
    db = _plans_db(False)
    assert acc.consume(db, "ai_assistant", org_id=BIZ) is True and db.rows("org_usage_counters") == []
    assert acc.refund(db, "ai_assistant", org_id=BIZ) is True and db.rows("org_usage_counters") == []
    assert acc.refund(db, "not_a_feature", org_id=BIZ) is False and acc.refund(db, "ai_assistant", org_id=BIZ, n=0) is False


# ── sign-up sets up the call button on the owner's number ──────────────────

def _signup_cfg(existing=None, phone="08012345678"):
    from tests.unit.test_account_plans_1 import FakeDB
    db = FakeDB(organisations=[{"id": ORG, "webchat_config": existing}])
    signup._turn_on_ai(db, ORG, phone)
    return db.tables["organisations"][0]["webchat_config"]


def test_signup_turns_on_calls_with_the_owners_own_number():
    cfg = _signup_cfg()
    assert cfg["call_enabled"] is True and cfg["call_number"] == "2348012345678"


def test_signup_without_a_usable_number_leaves_calls_off():
    for bad in (None, "", "abc", "123"):
        cfg = _signup_cfg(phone=bad)
        assert "call_enabled" not in cfg and "call_number" not in cfg


def test_signup_never_overwrites_a_number_or_setting_already_chosen():
    cfg = _signup_cfg({"call_enabled": False, "call_number": "2349011111111"})
    assert cfg["call_enabled"] is False and cfg["call_number"] == "2349011111111"


def test_verify_passes_the_phone_on():
    src = open(signup.__file__, encoding="utf-8").read()
    assert 'req.get("phone_number"))' in src.split("def verify")[1].split("def _start_free_plan")[0].split("_turn_on_ai(")[1]
