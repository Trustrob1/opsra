"""
ACCOUNT-PLANS AP-4: the plan decides what the web chat offers (page, AI, shop, follow-ups, insights).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import webchat as webchat_router
from app.services import ai_service, credit_service
from app.services import webchat_ai_service as ai
from app.services import webchat_followup_service as fu
from app.services import webchat_plan_service as plan
from app.services import webchat_redirect_service as redirect
from app.services import webchat_service as wc
from tests.unit.test_account_plans_1 import BIZ, FakeDB, OTHER, PLATFORM, _now, _plan

KEY = "wc_testkey12345"
CHAT_CFG = {"enabled": True, "ai_enabled": True, "shop_enabled": True, "email_followups": True, "wa_followups": True}


def _db(enforced=False, plans=None, other_enforced=False, other_plans=None):
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": ["webchat_basic", "webchat_insights"], "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": ["webchat_basic", "webchat_insights", "ai_assistant", "payment_links", "webchat_followups"],
                    "caps": {"ai_messages": 3}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "subscription_status": "active", "plans_enforced": enforced, "webchat_config": dict(CHAT_CFG)},
                       {"id": OTHER, "name": "Other", "subscription_status": "active", "plans_enforced": other_enforced, "webchat_config": dict(CHAT_CFG)}],
        org_plans=(plans or []) + (other_plans or []), org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[],
        webchat_keys=[{"key": KEY, "org_id": BIZ, "active": True}, {"key": "wc_otherkey12345", "org_id": OTHER, "active": True}],
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def _used(db):
    return sum(r["used"] for r in db.rows("org_usage_counters"))


# -- what visitors get ------------------------------------------------------------------

def test_a_business_not_switched_on_keeps_everything():
    found = wc.resolve_key(_db(enforced=False), KEY)
    assert found["config"]["ai_enabled"] and found["config"]["shop_enabled"] and found["config"]["email_followups"] and found["config"]["wa_followups"]


def test_switched_on_with_no_plan_means_no_web_chat():
    assert wc.resolve_key(_db(enforced=True), KEY) is None


def test_capture_gets_the_chat_but_not_ai_shop_or_followups():
    found = wc.resolve_key(_db(enforced=True, plans=[_plan(key="capture")]), KEY)
    c = found["config"]
    assert found and c["enabled"] and not c["ai_enabled"] and not c["shop_enabled"] and not c["email_followups"] and not c["wa_followups"]


def test_convert_gets_ai_shop_and_followups():
    c = wc.resolve_key(_db(enforced=True, plans=[_plan(key="convert")]), KEY)["config"]
    assert c["ai_enabled"] and c["shop_enabled"] and c["email_followups"] and c["wa_followups"]


def test_the_stored_settings_are_never_changed_by_the_plan():
    db = _db(enforced=True, plans=[_plan(key="capture")])
    wc.resolve_key(db, KEY)
    assert wc.get_config(db, BIZ)["ai_enabled"] is True            # the owner's own choice is kept for when they upgrade


def test_a_paused_or_lapsed_plan_turns_the_chat_off_and_paying_turns_it_back_on():
    lapsed = _plan(key="capture", status="paused")
    assert wc.resolve_key(_db(enforced=True, plans=[lapsed]), KEY) is None
    grace = _plan(key="capture", until=_now(-2))
    assert wc.resolve_key(_db(enforced=True, plans=[grace]), KEY) is not None        # inside the 7 grace days
    gone = _plan(key="capture", until=_now(-30))
    assert wc.resolve_key(_db(enforced=True, plans=[gone]), KEY) is None


def test_another_organisations_plan_never_counts():
    db = _db(enforced=True, other_enforced=True, other_plans=[_plan(org=OTHER, key="convert")])
    assert wc.resolve_key(db, KEY) is None
    assert wc.resolve_key(db, "wc_otherkey12345") is not None


def test_a_database_error_while_checking_an_enforced_plan_turns_it_off(monkeypatch):
    db = _db(enforced=True, plans=[_plan(key="convert")])
    monkeypatch.setattr(plan.acc, "_plan_has", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert plan.allowed(db, BIZ, "webchat_basic") is False


# -- AI answers use the plan's monthly allowance ---------------------------------------------

@pytest.fixture
def _ai(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_service, "call_claude", lambda **k: calls.append(1) or '{"reply": "Hello", "handoff": false}')
    monkeypatch.setattr(credit_service, "get_ai_level", lambda db, org_id: credit_service.LEVEL_FULL if hasattr(credit_service, "LEVEL_FULL") else "full")
    monkeypatch.setattr(wc, "rate_limited", lambda *a, **k: False)
    monkeypatch.setattr(wc, "set_state", lambda db, s, **kv: s)
    monkeypatch.setattr(ai, "_knowledge", lambda *a, **k: "x")
    return calls


def _session():
    return {"id": "s1", "org_id": BIZ, "lead_id": "l1", "state": {}}


def test_ai_stops_at_the_plan_allowance_and_falls_back_to_the_menu(_ai):
    db = _db(enforced=True, plans=[_plan(key="convert")])
    cfg = {"ai_enabled": True, "business_name": "Glow"}
    got = [ai.answer(db, _session(), cfg, "hello") for _ in range(5)]
    assert [g is not None for g in got] == [True, True, True, False, False] and len(_ai) == 3 and _used(db) == 3


def test_ai_is_not_counted_for_a_business_not_switched_on(_ai):
    db = _db(enforced=False)
    for _ in range(5):
        assert ai.answer(db, _session(), {"ai_enabled": True, "business_name": "Glow"}, "hello")
    assert len(_ai) == 5 and _used(db) == 0


def test_ai_off_when_the_plan_lacks_it_even_if_the_owner_switched_it_on(_ai):
    db = _db(enforced=True, plans=[_plan(key="capture")])
    assert ai.answer(db, _session(), {"ai_enabled": True, "business_name": "Glow"}, "hello") is None and _ai == []


def test_ai_allowance_is_per_organisation(_ai):
    db = _db(enforced=True, other_enforced=True, plans=[_plan(key="convert")], other_plans=[_plan(org=OTHER, key="convert")])
    for _ in range(3):
        ai.answer(db, _session(), {"ai_enabled": True, "business_name": "Glow"}, "hello")
    s2 = {"id": "s2", "org_id": OTHER, "lead_id": "l2", "state": {}}
    assert ai.answer(db, s2, {"ai_enabled": True, "business_name": "Other"}, "hello") is not None


# -- follow-ups ------------------------------------------------------------------------------

def test_followups_are_blocked_without_the_plan_and_work_with_it(monkeypatch):
    sent = []
    monkeypatch.setattr(fu.em, "can_email", lambda s, cfg: True)
    monkeypatch.setattr(fu.wa, "can_whatsapp", lambda s, cfg: False)
    monkeypatch.setattr(fu, "_gate", lambda s: True)
    monkeypatch.setattr(wc, "set_state", lambda db, s, **kv: s)
    monkeypatch.setattr(fu.em, "notify_rep_reply", lambda *a, **k: sent.append("reply") or True)
    monkeypatch.setattr(fu.em, "send_booking_confirmation", lambda *a, **k: sent.append("booking") or True)
    monkeypatch.setattr(fu.em, "send_order_link", lambda *a, **k: sent.append("order") or True)
    s = {"org_id": BIZ}
    off = _db(enforced=True, plans=[_plan(key="capture")])
    assert fu.notify_rep_reply(off, s, {}, "hi") is None
    fu.send_booking_confirmation(off, s, {}, "x")
    fu.send_order_link(off, s, {}, "x", "https://pay")
    assert sent == []
    on = _db(enforced=True, plans=[_plan(key="convert")])
    assert fu.notify_rep_reply(on, s, {}, "hi") == "email"
    fu.send_booking_confirmation(on, s, {}, "x")
    fu.send_order_link(on, s, {}, "x", "https://pay")
    assert sent == ["reply", "booking", "order"]
    assert fu.notify_rep_reply(_db(enforced=False), s, {}, "hi") == "email"            # not switched on = as before


# -- WhatsApp redirect and the staff pages -----------------------------------------------------

def test_redirect_sends_no_link_when_the_plan_has_no_chat(monkeypatch):
    from app.services import funnel_service, whatsapp_service
    sent, team = [], []
    monkeypatch.setattr(funnel_service, "_get_or_create_lead", lambda *a, **k: "lead-1")
    monkeypatch.setattr(whatsapp_service, "send_agent_text_message", lambda **k: sent.append(k))
    monkeypatch.setattr(redirect, "_notify_team", lambda *a, **k: team.append(1))
    monkeypatch.setattr(redirect, "_save_inbound", lambda *a, **k: None)
    monkeypatch.setattr(wc, "create_handoff", lambda *a, **k: "https://chat/link")
    monkeypatch.setattr(wc, "get_or_create_key", lambda *a, **k: KEY)
    monkeypatch.setattr(wc, "log_event", lambda *a, **k: None)
    num = {"org_id": BIZ, "phone_id": "p", "access_token": "t"}
    db = _db(enforced=True)
    db.tables["webchat_redirects"] = []
    redirect.handle_inbound(db, num, "2348012345678", "Ada", "text", "hi", "m1")
    assert sent == [] and team == [1]
    db2 = _db(enforced=True, plans=[_plan(key="capture")])
    db2.tables["webchat_redirects"] = []
    redirect.handle_inbound(db2, num, "2348012345678", "Ada", "text", "hi", "m2")
    assert len(sent) == 1


def test_insights_and_qr_need_the_plan_for_a_switched_on_business():
    org = {"org_id": BIZ, "id": "u1", "roles": {"template": "owner"}}
    with pytest.raises(HTTPException) as e:
        webchat_router.analytics(days=30, db=_db(enforced=True), org=org)
    assert e.value.status_code == 403 and "plan" in e.value.detail.lower()
    with pytest.raises(HTTPException):
        webchat_router.qr_svg(s="qr", download=False, db=_db(enforced=True), org=org)
    webchat_router._require_plan(_db(enforced=True, plans=[_plan(key="capture")]), org, "webchat_insights")      # allowed
    webchat_router._require_plan(_db(enforced=False), org, "webchat_insights")                                   # not switched on
