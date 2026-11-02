"""PLANS-3: the credit a plan includes each month (one expiring lot per business per month)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import credit_service as cs
from app.services import site_entitlement_service as ent
from app.workers import plan_credit_worker as w
from tests.unit.test_account_plans_1 import BIZ, FakeDB, OTHER, PLATFORM, _Q, _plan

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


def _db(plans, enforced=True, settings=None):
    return FakeDB(
        site_builder_settings=[{"org_id": PLATFORM, "pricing": settings or {}}],
        organisations=[{"id": BIZ, "name": "Glow", "subscription_status": "active", "plans_enforced": enforced}],
        org_plans=plans, org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


@pytest.fixture
def wallet(monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"org_id": org, "metering_enabled": True})
    monkeypatch.setattr(cs, "add_credit", lambda db, org, kobo, kind, ref, meta=None, expires_at=None:
                        calls.append(dict(org=org, kobo=kobo, kind=kind, ref=ref, meta=meta, expires_at=expires_at)) or {"applied": True})
    return calls


def _plan_at(key, **kw):
    return _plan(org=BIZ, key=key, until=NOW + timedelta(days=20), **kw)


def test_defaults_per_plan():
    t = ent.get_config({})["tiers"]
    assert [t[k]["included_credit_ngn"] for k in ("capture", "automate", "convert", "grow", "scale")] == [0, 0, 2000, 7500, 15000]


def test_settings_can_override_and_are_validated():
    cfg = ent.get_config({"pricing": {"tiers": {"convert": {"included_credit_ngn": 3000}}}})
    assert cfg["tiers"]["convert"]["included_credit_ngn"] == 3000
    ent.validate_pricing({"tiers": {"grow": {"included_credit_ngn": 5000}}})
    with pytest.raises(ent.EntitlementError):
        ent.validate_pricing({"tiers": {"grow": {"included_credit_ngn": -1}}})


@pytest.mark.parametrize("key,ngn", [("convert", 2000), ("grow", 7500), ("scale", 15000)])
def test_each_paid_plan_gets_its_amount_expiring_at_month_end(wallet, key, ngn):
    db = _db([_plan_at(key)])
    out = w.run_plan_credit_grants(db, NOW)
    assert out["granted"] == 1
    c = wallet[0]
    assert c["org"] == BIZ and c["kobo"] == ngn * 100 and c["kind"] == "adjust"
    assert c["ref"] == f"plangrant:{BIZ}:2026-11" and c["meta"]["reason"] == "plan_credit"
    assert datetime.fromisoformat(c["expires_at"]) == datetime(2026, 12, 1, tzinfo=ent.LAGOS)


def test_chat_basic_and_capture_get_nothing(wallet):
    for key in ("automate", "capture"):
        assert w.run_plan_credit_grants(_db([_plan_at(key)]), NOW)["granted"] == 0
    assert wallet == []


def test_not_switched_on_gets_nothing(wallet):
    assert w.run_plan_credit_grants(_db([_plan_at("grow")], enforced=False), NOW)["granted"] == 0 and wallet == []


def test_paused_or_lapsed_plan_gets_nothing(wallet):
    db = _db([_plan(org=BIZ, key="grow", until=NOW - timedelta(days=30))])
    assert w.run_plan_credit_grants(db, NOW)["granted"] == 0 and wallet == []


def test_no_wallet_metering_means_no_grant(monkeypatch, wallet):
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"org_id": org, "metering_enabled": False})
    assert w.run_plan_credit_grants(_db([_plan_at("grow")]), NOW)["granted"] == 0 and wallet == []


def test_second_run_in_the_same_month_adds_nothing(monkeypatch):
    seen, refs = [], set()

    def add(db, org, kobo, kind, ref, meta=None, expires_at=None):
        if ref in refs:
            return {"applied": False}
        refs.add(ref); seen.append(kobo)
        return {"applied": True}
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"metering_enabled": True})
    monkeypatch.setattr(cs, "add_credit", add)
    db = _db([_plan(org=BIZ, key="grow", until=NOW + timedelta(days=90))])
    assert w.run_plan_credit_grants(db, NOW)["granted"] == 1
    assert w.run_plan_credit_grants(db, NOW + timedelta(days=1))["granted"] == 0 and seen == [750000]
    assert w.run_plan_credit_grants(db, NOW + timedelta(days=30))["granted"] == 1      # next month: new ref


def test_dry_run_writes_nothing(wallet):
    assert w.run_plan_credit_grants(_db([_plan_at("grow")]), NOW, dry_run=True)["granted"] == 1 and wallet == []


def test_month_end_wraps_the_year():
    assert w.month_end_lagos(datetime(2026, 12, 20, tzinfo=timezone.utc)) == datetime(2027, 1, 1, tzinfo=ent.LAGOS)


def test_grant_for_org_itself_never_raises(monkeypatch):
    monkeypatch.setattr(w.acc, "_compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert w.grant_for_org(object(), BIZ, NOW) is None


def test_new_signup_wallets_let_opsra_pay_meta():
    from app.services import wa_signup_service as su
    seen = []

    class _T:
        def upsert(self, row, **k): seen.append(row); return self
        def execute(self): return self

    class _D:
        def table(self, name): return _T()
    su._open_wallet(_D(), BIZ, 0)
    assert seen == [{"org_id": BIZ, "metering_enabled": True, "meta_billing": "opsra_credit_line"}]
