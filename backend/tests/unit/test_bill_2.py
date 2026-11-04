"""BILL-2: the credit block the Billing header shows (balance, spend, this month's included credit)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import account_plan_billing_service as svc
from app.services import credit_order_service as cos
from app.services import site_entitlement_service as ent
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
CFG = ent.get_config({})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def _summary(monkeypatch, balance=1_000_000, spend=310_000, low=500_000, metering=True):
    monkeypatch.setattr(cos, "summary", lambda db, org: {
        "balance_kobo": balance, "month_spend_total_kobo": spend, "low_balance_kobo": low, "metering_enabled": metering})


def _db(lots):
    return FakeDB(credit_lots=lots)


def test_included_credit_shows_remaining_for_this_month(monkeypatch):
    _summary(monkeypatch)
    lot = {"org_id": BIZ, "ref": f"plangrant:{BIZ}:2026-11", "original_kobo": 750_000, "remaining_kobo": 520_000}
    b = svc.credit_block(_db([lot]), BIZ, CFG, "grow", NOW)
    assert b["balance_kobo"] == 1_000_000 and b["month_spend_kobo"] == 310_000 and b["low"] is False
    inc = b["included"]
    assert (inc["monthly_kobo"], inc["granted_kobo"], inc["remaining_kobo"], inc["used_kobo"]) == (750_000, 750_000, 520_000, 230_000)
    assert inc["granted"] is True and inc["resets_at"].startswith("2026-12-01")


def test_other_months_and_other_businesses_lots_are_ignored(monkeypatch):
    _summary(monkeypatch)
    lots = [{"org_id": BIZ, "ref": f"plangrant:{BIZ}:2026-10", "original_kobo": 750_000, "remaining_kobo": 750_000},
            {"org_id": "someone-else", "ref": f"plangrant:{BIZ}:2026-11", "original_kobo": 750_000, "remaining_kobo": 750_000}]
    inc = svc.credit_block(_db(lots), BIZ, CFG, "grow", NOW)["included"]
    assert inc["granted"] is False and inc["remaining_kobo"] == 0 and inc["monthly_kobo"] == 750_000


def test_plan_without_included_credit_has_no_included_part(monkeypatch):
    _summary(monkeypatch)
    assert svc.credit_block(_db([]), BIZ, CFG, "automate", NOW)["included"] is None
    assert svc.credit_block(_db([]), BIZ, CFG, None, NOW)["included"] is None


@pytest.mark.parametrize("balance,low", [(0, True), (400_000, True), (600_000, False)])
def test_low_flag(monkeypatch, balance, low):
    _summary(monkeypatch, balance=balance)
    assert svc.credit_block(_db([]), BIZ, CFG, "grow", NOW)["low"] is low


def test_not_metered_is_never_flagged_low(monkeypatch):
    _summary(monkeypatch, balance=0, metering=False)
    assert svc.credit_block(_db([]), BIZ, CFG, "grow", NOW)["low"] is False


def test_december_resets_in_january(monkeypatch):
    _summary(monkeypatch)
    dec = datetime(2026, 12, 20, 10, 0, tzinfo=timezone.utc)
    assert svc.credit_block(_db([]), BIZ, CFG, "grow", dec)["included"]["resets_at"].startswith("2027-01-01")


def test_never_raises(monkeypatch):
    monkeypatch.setattr(cos, "summary", lambda db, org: (_ for _ in ()).throw(RuntimeError("down")))
    assert svc.credit_block(_db([]), BIZ, CFG, "grow", NOW) is None
