"""
ACCOUNT-PLANS AP-5b/5c: the plan decides Convert, Grow and add-on features across screens, jobs and webhooks.
Not switched on = everything works as before. Switched on = only what the plan includes.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import admin as admin_router
from app.routers import catalog, funnel_tools, funnels, leads as leads_router, tasks, tickets
from app.routers import webhooks as wh
from app.routers import whatsapp as wa_router
from app.services import plan_gate_service as gate
from app.services import site_feature_registry as reg
from app.workers import lead_nurture_worker as nurture
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _Q, _plan

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

ALL = [k for k, v in reg.FEATURES.items() if v["scope"] != "site"]


def _db(enforced=False, plans=None, features=None, caps=None, users=None):
    feats = ALL if features is None else features
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": [], "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": feats, "caps": caps or {}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "subscription_status": "active", "plans_enforced": enforced,
                        "nurture_track_enabled": True, "nurture_interval_days": 7, "nurture_sequence": [{"message": "hi"}],
                        "qualification_flow": {"questions": [{"q": 1}]}}],
        org_plans=plans or [], org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[],
        users=users if users is not None else [], notifications=[], leads=[], whatsapp_numbers=[],
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def test_every_wired_feature_is_marked_built():
    wired = ["qualification", "followups", "fb_ig_leads", "own_wa_number", "selling_catalog", "selling_booking", "bulk_messaging",
             "welcome_series", "surveys", "weekly_report", "monday_summary", "multi_rep_inbox", "team_tasks", "support_tickets",
             "renewals_winback", "event_funnel", "extra_wa_number", "speed_alerts", "wa_leads", "wa_menu", "ai_assistant", "payment_links"]
    assert all(reg.FEATURES[k]["built"] for k in wired)


# -- whole-screen gates -------------------------------------------------------------------------

SCREENS = [(tasks, "team_tasks"), (tickets, "support_tickets"), (catalog, "selling_catalog"),
           (funnels, "event_funnel"), (funnel_tools, "event_funnel")]


@pytest.mark.parametrize("mod,key", SCREENS)
def test_screens_carry_the_gate(mod, key):
    assert len(mod.router.dependencies) == 1


def _run_dep(key, db):
    dep = gate.require(key)
    return asyncio.run(dep(org={"org_id": BIZ}, db=db))


@pytest.mark.parametrize("mod,key", SCREENS)
def test_screens_open_when_not_switched_on(mod, key):
    assert _run_dep(key, _db(enforced=False)) is None


@pytest.mark.parametrize("mod,key", SCREENS)
def test_screens_closed_without_the_feature_open_with_it(mod, key):
    with pytest.raises(HTTPException) as e:
        _run_dep(key, _db(enforced=True))
    assert e.value.status_code == 403 and e.value.detail["code"] == "PLAN_REQUIRED"
    assert _run_dep(key, _db(enforced=True, plans=[_plan(key="convert")])) is None


# -- users --------------------------------------------------------------------------------------

def _u(n, system=0):
    return [{"id": f"u{i}", "org_id": BIZ, "is_active": True, "email": f"u{i}@x.com"} for i in range(n)] + \
           [{"id": f"s{i}", "org_id": BIZ, "is_active": True, "email": f"ai-agent+{BIZ}@system.opsra.internal"} for i in range(system)]


def test_user_limit_not_switched_on_is_unlimited():
    gate.check_can_add_user(_db(enforced=False, users=_u(9)), BIZ)


def test_user_limit_without_multi_rep_means_one_user():
    db = _db(enforced=True, plans=[_plan(key="convert")], features=["wa_leads"], users=_u(1))
    with pytest.raises(HTTPException) as e:
        gate.check_can_add_user(db, BIZ)
    assert e.value.detail["code"] == "PLAN_REQUIRED"
    gate.check_can_add_user(_db(enforced=True, plans=[_plan(key="convert")], features=["wa_leads"], users=[]), BIZ)


def test_user_limit_follows_the_reps_allowance_and_ignores_the_ai_agent_user():
    mk = lambda n, s=0: _db(enforced=True, plans=[_plan(key="convert")], features=["multi_rep_inbox"], caps={"reps": 3}, users=_u(n, s))
    gate.check_can_add_user(mk(2, 1), BIZ)             # 2 people + the AI agent user: room for one more
    with pytest.raises(HTTPException):
        gate.check_can_add_user(mk(3, 1), BIZ)


def test_user_limit_with_the_feature_and_no_allowance_is_unlimited():
    gate.check_can_add_user(_db(enforced=True, plans=[_plan(key="convert")], features=["multi_rep_inbox"], users=_u(20)), BIZ)


# -- rep screens ------------------------------------------------------------------------------------

def _patch_leads(monkeypatch):
    monkeypatch.setattr(leads_router, "_org_id", lambda org: BIZ)
    monkeypatch.setattr(leads_router, "_user_id", lambda org: "u1")
    monkeypatch.setattr(leads_router.lead_service, "score_lead", lambda **k: {"id": "L", "score": "hot"})
    monkeypatch.setattr(leads_router.demo_service, "create_demo_request", lambda **k: {"id": "D"})


def test_scoring_and_demo_booking_follow_the_plan(monkeypatch):
    _patch_leads(monkeypatch)
    for key, call in (("qualification", lambda db: asyncio.run(leads_router.score_lead("L", {}, db))),
                      ("selling_booking", lambda db: asyncio.run(leads_router.create_demo_request(
                          "L", SimpleNamespace(lead_preferred_time=None, medium="call", notes=None), {}, db)))):
        assert call(_db(enforced=False))
        assert call(_db(enforced=True, plans=[_plan(key="convert")]))
        with pytest.raises(HTTPException) as e:
            call(_db(enforced=True))
        assert e.value.detail["code"] == "PLAN_REQUIRED", key


# -- WhatsApp numbers, broadcasts, qualification ------------------------------------------------------

OWNER = {"org_id": BIZ, "id": "u1", "roles": {"template": "owner"}}


def test_connecting_a_whatsapp_number_needs_the_feature():
    with pytest.raises(HTTPException) as e:
        asyncio.run(admin_router.connect_whatsapp(SimpleNamespace(), OWNER, _db(enforced=True)))
    assert e.value.detail["code"] == "PLAN_REQUIRED"


def test_adding_a_second_number_needs_the_extra_number_add_on():
    pl = [_plan(key="convert")]
    db = _db(enforced=True, plans=pl, features=["own_wa_number"])
    db.tables["whatsapp_numbers"] = [{"id": "n1", "org_id": BIZ}]
    payload = SimpleNamespace(wa_sales_mode="human", phone_id="p", access_token="t", waba_id="w", label="x")
    with pytest.raises(HTTPException) as e:
        admin_router.create_whatsapp_number(payload, OWNER, db)
    assert e.value.detail["code"] == "PLAN_REQUIRED"


def test_creating_a_broadcast_needs_bulk_messaging(monkeypatch):
    monkeypatch.setattr(wa_router, "require_not_affiliate", lambda *a, **k: None)
    monkeypatch.setattr(wa_router.whatsapp_service, "create_broadcast", lambda **k: {"id": "B"})
    assert wa_router.create_broadcast(SimpleNamespace(), _db(enforced=False), OWNER)
    with pytest.raises(HTTPException):
        wa_router.create_broadcast(SimpleNamespace(), _db(enforced=True), OWNER)


def test_prequalification_bot_is_skipped_without_the_feature():
    assert wh._is_lead_pre_qualified(_db(enforced=True), BIZ, "L") is True
    # with the feature the plan check lets the normal rules decide (it is never the reason for the answer)
    from app.services import plan_gate_service as g
    asked = []
    orig = g.allowed
    g.allowed = lambda db, org_id, key: (asked.append(key), True)[1]
    try:
        wh._is_lead_pre_qualified(_db(enforced=True, plans=[_plan(key="convert")]), BIZ, "L")
    finally:
        g.allowed = orig
    assert asked == ["qualification"]


# -- background jobs ----------------------------------------------------------------------------------

def test_follow_up_sequences_stop_without_the_feature(monkeypatch):
    for enforced, has_plan, expect_skipped in ((True, False, True), (True, True, False), (False, False, False)):
        db = _db(enforced=enforced, plans=[_plan(key="convert")] if has_plan else [])
        monkeypatch.setattr(nurture, "get_supabase", lambda db=db: db)
        seen = []
        orig = db.table

        def spy(name, orig=orig, seen=seen):
            seen.append(name)
            return orig(name)
        db.table = spy
        nurture.run_lead_nurture_send()
        assert ("leads" in seen) is (not expect_skipped), (enforced, has_plan)
