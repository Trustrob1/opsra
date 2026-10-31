"""YEARLY-1: a yearly plan pays 10 months for 365 days ("2 months free"); monthly behaviour is unchanged."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import account_plan_billing_service as bill
from app.services import site_addon_billing_service as sab
from app.services import site_entitlement_service as ent

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
CFG = ent.get_config({"pricing": {"tiers": {"capture": {"monthly_ngn": 50000}, "convert": {"monthly_ngn": 100000},
                                            "grow": {"monthly_ngn": 150000}}}})


def _quote(key="convert", row=None, interval="month", seats=(0, 5000, 0)):
    with patch.object(bill, "_tier_fits_org", return_value=True), patch.object(bill, "_paid_before", return_value=False), \
         patch("app.services.account_seat_service.renewal_seats", return_value=seats):
        return bill.quote_for(MagicMock(), "org", CFG, key, NOW, row, interval)


def test_defaults_are_ten_months_for_365_days():
    assert CFG["billing"]["annual_months"] == 10 and CFG["billing"]["annual_days"] == 365


def test_monthly_is_unchanged():
    q = _quote()
    assert (q["price"], q["days"], q["interval"], q["total"]) == (100000, 30, "month", 100000)


def test_yearly_new_plan_costs_ten_months_for_a_year():
    q = _quote(interval="year")
    assert (q["price"], q["days"], q["interval"], q["months"], q["total"]) == (1000000, 365, "year", 10, 1000000)


def test_yearly_can_be_switched_off():
    cfg = ent.get_config({"pricing": {"tier_billing": {"annual_months": 0}}})
    assert cfg["billing"]["annual_months"] == 0
    with pytest.raises(bill.PlanBillingError):
        bill.interval_of(cfg, "year")


def test_paid_extra_users_are_billed_for_the_year_too():
    row = {"id": "p", "key": "convert", "status": "active", "source": "paid", "paid_until": (NOW + timedelta(days=3)).isoformat(),
           "price_ngn": 100000, "config": {}}
    q = _quote(row=row, interval="year", seats=(2, 5000, 0))
    assert q["kind"] == "renewal" and q["seats_total"] == 2 * 5000 * 10 and q["total"] == 1000000 + 100000


def test_switching_a_monthly_plan_to_yearly_is_a_renewal_of_the_same_plan():
    row = {"id": "p", "key": "convert", "status": "active", "source": "paid", "paid_until": (NOW + timedelta(days=10)).isoformat(),
           "price_ngn": 100000, "config": {}}
    assert _quote(row=row, interval="year")["kind"] == "renewal"


def test_unused_days_of_a_yearly_plan_are_credited_against_a_year_not_a_month():
    row = {"id": "p", "kind": "tier", "key": "convert", "status": "active", "source": "paid", "price_ngn": 1000000,
           "paid_until": (NOW + timedelta(days=182.5)).isoformat(), "config": {"interval": "year", "period_days": 365}}
    credit = sab._credit_for_unused(row, CFG, NOW)
    assert 495000 <= credit <= 505000


def test_unused_days_of_a_monthly_plan_still_use_the_month():
    row = {"id": "p", "kind": "tier", "key": "convert", "status": "active", "source": "paid", "price_ngn": 100000,
           "paid_until": (NOW + timedelta(days=15)).isoformat(), "config": {}}
    assert 49000 <= sab._credit_for_unused(row, CFG, NOW) <= 51000


def test_pricing_settings_accept_the_yearly_setting():
    p = {"tier_billing": {"annual_months": 10}}
    ent.validate_pricing(p)
    with pytest.raises(ent.EntitlementError):
        ent.validate_pricing({"tier_billing": {"annual_months": 13}})
