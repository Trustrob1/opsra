"""
ACCOUNT-PLANS AP-5b (part 1): ai_assistant on WhatsApp AI-agent numbers, payment_links for reps and the AI agent.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import leads as leads_router
from app.routers import webhooks as wh
from app.services import paystack_storefront_service as pay
from app.services import plan_gate_service as gate
from app.services import site_feature_registry as reg
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _Q, _plan

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

PHONE = "2348012345678"
CONVERT = ["wa_leads", "wa_menu", "ai_assistant", "payment_links"]


def _db(enforced=False, plans=None, features=None, ai_cap=2):
    feats = features if features is not None else CONVERT
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": ["wa_leads", "wa_menu"], "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": feats, "caps": {"ai_messages": ai_cap}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "slug": "glow", "subscription_status": "active", "plans_enforced": enforced,
                        "unknown_contact_behavior": "triage_first", "whatsapp_triage_config": {}, "payment_link_config": {},
                        "sales_mode": "consultative", "whatsapp_sales_mode": "human"}],
        org_plans=plans or [], org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[],
        notifications=[], whatsapp_messages=[], whatsapp_sessions=[], users=[{"id": "u1", "org_id": BIZ, "roles": {"template": "owner"}}],
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def test_registry_marks_both_built():
    assert reg.FEATURES["ai_assistant"]["built"] and reg.FEATURES["payment_links"]["built"]


# -- the door ---------------------------------------------------------------------------------

def test_gate_not_switched_on_allows_and_counts_nothing():
    db = _db(enforced=False)
    assert gate.allowed(db, BIZ, "payment_links") and gate.use(db, BIZ, "ai_assistant", 5)
    assert db.rows("org_usage_counters") == []


def test_gate_switched_on_without_a_plan_blocks():
    db = _db(enforced=True)
    assert not gate.allowed(db, BIZ, "payment_links") and not gate.use(db, BIZ, "ai_assistant")


def test_gate_allowance_runs_out():
    db = _db(enforced=True, plans=[_plan(key="convert")], ai_cap=2)
    assert gate.use(db, BIZ, "ai_assistant") and gate.use(db, BIZ, "ai_assistant")
    assert not gate.use(db, BIZ, "ai_assistant")


def test_gate_never_drops_live_work_when_the_check_breaks(monkeypatch):
    monkeypatch.setattr(gate.acc, "has_feature", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(gate.acc, "consume", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert gate.allowed(_db(), BIZ, "payment_links") is True and gate.use(_db(), BIZ, "ai_assistant") is True


def test_http_error_is_a_403_with_a_code():
    e = gate.http_error()
    assert e.status_code == 403 and e.detail["code"] == "PLAN_REQUIRED"


# -- WhatsApp AI agent number --------------------------------------------------------------------

@pytest.fixture
def agent(monkeypatch):
    s = {"agent": 0, "leads": 0}
    monkeypatch.setattr(wh, "_lookup_whatsapp_number", lambda db, pid: {"org_id": BIZ, "wa_sales_mode": "ai_agent", "phone_id": "p", "access_token": "t"})
    monkeypatch.setattr(wh, "_lookup_org_by_phone_number_id", lambda db, pid: BIZ)
    monkeypatch.setattr(wh, "_lookup_record_by_phone", lambda db, phone, org_id=None: (None, None, None, None))
    monkeypatch.setattr(wh, "_is_org_owner", lambda *a, **k: False)
    monkeypatch.setattr(wh, "_handle_opt_keywords", lambda *a, **k: False)
    monkeypatch.setattr(wh.triage_service, "get_active_session", lambda *a, **k: None)
    monkeypatch.setattr(wh, "_route_to_ai_agent", lambda **k: s.__setitem__("agent", s["agent"] + 1))
    monkeypatch.setattr(wh.lead_service, "create_lead", lambda **k: (s.__setitem__("leads", s["leads"] + 1), {"id": "L", "assigned_to": None})[1])
    from app.services import whatsapp_service
    monkeypatch.setattr(whatsapp_service, "send_triage_menu", lambda **k: None)
    monkeypatch.setattr(wh.triage_service, "get_or_create_session", lambda *a, **k: {"id": "s"})
    return s


def _inbound(db, n=1):
    for i in range(n):
        wh._handle_inbound_message(db, {"from": PHONE, "id": f"wamid.{i}", "type": "text", "text": {"body": "hi"}}, "Ada", "pid")


def test_agent_number_not_switched_on_uses_the_agent(agent):
    _inbound(_db(enforced=False))
    assert agent["agent"] == 1


def test_agent_number_without_the_feature_acts_like_a_normal_number(agent):
    db = _db(enforced=True, plans=[_plan(key="capture")], features=["wa_leads", "wa_menu"])
    _inbound(db)
    assert agent["agent"] == 0 and agent["leads"] == 1          # normal flow: lead captured by the Capture feature


def test_agent_number_stops_when_the_monthly_allowance_is_used(agent):
    db = _db(enforced=True, plans=[_plan(key="convert")], ai_cap=2)
    _inbound(db, 3)
    assert agent["agent"] == 2 and agent["leads"] == 1          # third message handled by the team flow


# -- payment links ---------------------------------------------------------------------------------

def _send(db, monkeypatch):
    monkeypatch.setattr(leads_router, "has_permission", lambda *a, **k: True)
    monkeypatch.setattr(leads_router, "_org_id", lambda org: BIZ)
    monkeypatch.setattr(leads_router, "_user_id", lambda org: "u1")
    calls = []

    def fake(**kw):
        calls.append(kw)
        raise pay.PaystackLinkError("stop here")
    monkeypatch.setattr(leads_router.paystack_storefront_service, "generate_payment_link", fake)
    payload = SimpleNamespace(amount=5000, payment_type="full", currency="NGN")
    try:
        asyncio.run(leads_router.send_payment_link("lead-1", payload, {}, db))
    except HTTPException as e:
        return e, calls
    return None, calls


def test_rep_payment_link_blocked_without_the_feature(monkeypatch):
    e, calls = _send(_db(enforced=True), monkeypatch)
    assert e.status_code == 403 and e.detail["code"] == "PLAN_REQUIRED" and calls == []


def test_rep_payment_link_allowed_with_the_feature_or_not_switched_on(monkeypatch):
    for db in (_db(enforced=False), _db(enforced=True, plans=[_plan(key="convert")])):
        e, calls = _send(db, monkeypatch)
        assert e.status_code == 400 and e.detail["code"] == "PAYSTACK_LINK_FAILED" and len(calls) == 1


def test_opsras_own_billing_links_are_never_gated(monkeypatch):
    # generate_payment_link itself has no plan check, so Opsra's own site and plan billing can never be blocked by a plan
    import inspect
    assert "plan_gate" not in inspect.getsource(pay.generate_payment_link)
