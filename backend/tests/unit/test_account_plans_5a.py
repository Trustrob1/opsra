"""
ACCOUNT-PLANS AP-5a: the plan decides whether a first WhatsApp message becomes a lead (wa_leads) and whether the
WhatsApp menu goes out (wa_menu). Messages are never lost.
"""
from __future__ import annotations

import pytest

from app.routers import webhooks as wh
from app.services import site_feature_registry as reg
from app.services import wa_plan_service as plan
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _plan, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self      # the live code reads one row; the stand-in returns a list, which it handles

PHONE = "2348012345678"
PNID = "phone-id-1"


def _db(enforced=False, plans=None, behavior="triage_first", tier_features=None):
    feats = tier_features if tier_features is not None else ["wa_leads", "wa_menu"]
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": feats, "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": feats, "caps": {}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "slug": "glow", "subscription_status": "active", "plans_enforced": enforced,
                        "unknown_contact_behavior": behavior, "whatsapp_triage_config": {"customer": {"items": [1]}},
                        "sales_mode": "consultative", "whatsapp_sales_mode": "human"}],
        org_plans=plans or [], org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[],
        notifications=[], whatsapp_messages=[], whatsapp_sessions=[],
        users=[{"id": "u-owner", "org_id": BIZ, "roles": {"template": "owner"}}],
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


# -- registry -----------------------------------------------------------------------------

def test_the_two_features_are_marked_built():
    assert reg.FEATURES["wa_leads"]["built"] and reg.FEATURES["wa_menu"]["built"]


# -- the checks -----------------------------------------------------------------------------

def test_not_switched_on_keeps_both():
    db = _db(enforced=False)
    assert plan.leads_on(db, BIZ) and plan.menu_on(db, BIZ)


def test_switched_on_without_a_plan_loses_both():
    db = _db(enforced=True)
    assert not plan.leads_on(db, BIZ) and not plan.menu_on(db, BIZ)


def test_switched_on_with_a_plan_that_includes_them():
    db = _db(enforced=True, plans=[_plan(key="capture")])
    assert plan.leads_on(db, BIZ) and plan.menu_on(db, BIZ)


def test_a_plan_that_has_leads_but_not_the_menu():
    db = _db(enforced=True, plans=[_plan(key="capture")], tier_features=["wa_leads"])
    assert plan.leads_on(db, BIZ) and not plan.menu_on(db, BIZ)


def test_a_broken_check_never_drops_a_live_message(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(plan.acc, "has_feature", boom)
    assert plan.leads_on(_db(), BIZ) is True


# -- the team note ---------------------------------------------------------------------------

def test_team_note_is_sent_once_per_half_hour():
    db = _db(enforced=True)
    plan.tell_team(db, BIZ, PHONE, "Ada", "hello")
    plan.tell_team(db, BIZ, PHONE, "Ada", "hello again")
    notes = db.rows("notifications")
    assert len(notes) == 1 and notes[0]["type"] == "wa_plan_off" and notes[0]["user_id"] == "u-owner"
    plan.tell_team(db, BIZ, PHONE, "Bola", "hi")
    assert len(db.rows("notifications")) == 2


# -- the live WhatsApp path --------------------------------------------------------------------

@pytest.fixture
def spy(monkeypatch):
    s = {"leads": 0, "menus": []}
    monkeypatch.setattr(wh, "_lookup_whatsapp_number", lambda db, pid: {"org_id": BIZ, "wa_sales_mode": "human"})
    monkeypatch.setattr(wh, "_lookup_org_by_phone_number_id", lambda db, pid: BIZ)
    monkeypatch.setattr(wh, "_lookup_record_by_phone", lambda db, phone, org_id=None: (None, None, None, None))
    monkeypatch.setattr(wh, "_is_org_owner", lambda *a, **k: False)
    monkeypatch.setattr(wh.triage_service, "get_active_session", lambda *a, **k: None)
    monkeypatch.setattr(wh.triage_service, "get_or_create_session", lambda *a, **k: {"id": "s1"})

    def create_lead(**kw):
        s["leads"] += 1
        return {"id": "lead-1", "assigned_to": None}
    monkeypatch.setattr(wh.lead_service, "create_lead", create_lead)
    from app.services import whatsapp_service
    monkeypatch.setattr(whatsapp_service, "send_triage_menu", lambda **kw: s["menus"].append(kw.get("section")))
    return s


def _inbound(db):
    wh._handle_inbound_message(db, {"from": PHONE, "id": "wamid.1", "type": "text", "text": {"body": "hello"}}, "Ada", PNID)


def test_a_business_not_switched_on_still_gets_the_lead_and_the_menu(spy):
    db = _db(enforced=False)
    _inbound(db)
    assert spy["leads"] == 1 and spy["menus"] == ["unknown"]
    assert db.rows("notifications") == []


@pytest.mark.parametrize("behavior", ["triage_first", "qualify_immediately"])
def test_no_plan_means_no_lead_no_menu_but_the_message_is_kept_and_the_team_told(spy, behavior):
    db = _db(enforced=True, behavior=behavior)
    _inbound(db)
    assert spy["leads"] == 0 and spy["menus"] == []
    assert len(db.rows("whatsapp_messages")) == 1 and db.rows("whatsapp_messages")[0]["content"] == "hello"
    assert [n["type"] for n in db.rows("notifications")] == ["wa_plan_off"]


def test_lead_capture_without_the_menu_creates_the_lead_and_skips_the_menu(spy):
    db = _db(enforced=True, plans=[_plan(key="capture")], tier_features=["wa_leads"])
    _inbound(db)
    assert spy["leads"] == 1 and spy["menus"] == []


def test_a_full_capture_plan_behaves_as_before(spy):
    db = _db(enforced=True, plans=[_plan(key="capture")])
    _inbound(db)
    assert spy["leads"] == 1 and spy["menus"] == ["unknown"]
