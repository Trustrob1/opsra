"""
PLANS-2: the plan decides Reports, Performance Hub, Business Activities and the contacts download.
Not switched on = everything works as before. Switched on = only what the plan includes.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app import main
from app.routers import whatsapp as wa_router
from app.services import plan_gate_service as gate
from app.services import site_feature_registry as reg
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _Q, _plan

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

def _db(enforced, plan_key=None, features=None):
    tiers = {"capture": {"monthly_ngn": 15000, "features": features if features is not None else [], "caps": {}},
             "convert": {"monthly_ngn": 30000, "features": ["reports", "performance_hub", "leads_download"], "caps": {}},
             "grow": {"monthly_ngn": 50000, "features": ["reports", "performance_hub", "business_activities", "leads_download"], "caps": {}}}
    return FakeDB(
        site_builder_settings=[{"org_id": PLATFORM, "pricing": {"tiers": tiers}}],
        organisations=[{"id": BIZ, "name": "Glow", "subscription_status": "active", "plans_enforced": enforced}],
        org_plans=[_plan(key=plan_key)] if plan_key else [], org_usage_counters=[], org_plan_events=[], site_addons=[],
        site_usage_counters=[], sites=[], users=[], notifications=[], leads=[], whatsapp_numbers=[])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def _run(key, db):
    return asyncio.run(gate.require(key)(org={"org_id": BIZ}, db=db))


def test_new_keys_are_marked_built():
    assert all(reg.FEATURES[k]["built"] for k in ("performance_hub", "reports", "business_activities", "leads_download"))


@pytest.mark.parametrize("key", ["performance_hub", "reports", "business_activities"])
def test_open_when_not_switched_on(key):
    assert _run(key, _db(False)) is None


@pytest.mark.parametrize("key", ["performance_hub", "reports", "business_activities"])
def test_closed_for_an_enforced_business_whose_plan_lacks_it(key):
    with pytest.raises(HTTPException) as e:
        _run(key, _db(True, "capture"))
    assert e.value.status_code == 403 and e.value.detail["code"] == "PLAN_REQUIRED"


def test_growth_plan_has_reports_and_hub_but_not_business_activities():
    db = _db(True, "convert")
    assert _run("reports", db) is None and _run("performance_hub", db) is None
    with pytest.raises(HTTPException):
        _run("business_activities", db)
    assert _run("business_activities", _db(True, "grow")) is None


def test_the_three_routers_carry_the_gate_in_main():
    import pathlib
    src = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    for router, key in (("report_analytics_router", "reports"), ("performance_hub_router", "performance_hub"),
                        ("business_activities_report_router", "business_activities")):
        line = next(l for l in src.splitlines() if l.startswith(f"app.include_router({router}.router"))
        assert f'_plan_gate.require("{key}")' in line and "crm_only" in line


def test_contacts_download_follows_the_plan():
    owner = {"org_id": BIZ, "id": "u1", "roles": {"template": "owner"}}
    with pytest.raises(HTTPException) as e:
        wa_router.export_contacts(db=_db(True, "capture"), org=owner)
    assert e.value.status_code == 403 and e.value.detail["code"] == "PLAN_REQUIRED"
