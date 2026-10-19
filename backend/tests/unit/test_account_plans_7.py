"""ACCOUNT-PLANS AP-7: extra users (seats) - buy, prorate, renew, lapse."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import account_plan_billing_service as bill
from app.services import account_seat_service as seats
from app.services import plan_gate_service as gate
from tests.unit.test_account_plans_1 import BIZ, _Q, _db, _now, _plan
from tests.unit.test_account_plans_2 import _Client, _full_db, _paystack, _order  # noqa: F401  (autouse fixture)

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

PRICE = 5000


def _sdb(users=2, tier_days=15, seat_rows=None, enforced=True, price=PRICE):
    db = _full_db(enforced=enforced, plans=[_plan(key="convert", until=_now(tier_days))] + (seat_rows or []))
    db.tables["site_builder_settings"][0]["pricing"]["addons"] = {"extra_rep": {"monthly_ngn": price, "sellable": True}}
    db.tables["users"] = [{"id": f"u{i}", "org_id": BIZ, "is_active": True, "email": f"u{i}@x.com"} for i in range(users)]
    return db


def _seat(db):
    return next((r for r in db.rows("org_plans") if r["key"] == "extra_rep" and r["status"] != "cancelled"), None)


def _pay_last(db):
    o = _order(db)
    return bill.mark_paid(db, o["reference"], o["amount_kobo"], None)


def test_quote_is_prorated_to_the_days_left():
    q = seats.quote_seats(_sdb(tier_days=15), BIZ, 2)
    assert q["total"] == 5000  # 2 x 5000 x 15/30
    assert seats.quote_seats(_sdb(tier_days=30), BIZ, 1)["total"] == 5000


def test_quote_refuses_bad_input_no_plan_or_no_price():
    with pytest.raises(bill.PlanBillingError):
        seats.quote_seats(_sdb(), BIZ, 0)
    with pytest.raises(bill.PlanBillingError):
        seats.quote_seats(_sdb(price=0), BIZ, 1)
    nodb = _sdb()
    nodb.tables["org_plans"] = []
    with pytest.raises(bill.PlanBillingError):
        seats.quote_seats(nodb, BIZ, 1)


def test_a_plan_given_by_staff_can_buy_seats_too():
    db = _sdb(users=2, tier_days=15)
    next(r for r in db.rows("org_plans") if r["key"] == "convert")["source"] = "staff"
    assert seats.team(db, BIZ)["can_buy"] is True
    seats.checkout_seats(db, BIZ, add=1)
    _pay_last(db)
    assert _seat(db)["config"]["quantity"] == 1
    gate.check_can_add_user(db, BIZ)
    nodate = _sdb(users=2)
    t = next(r for r in nodate.rows("org_plans") if r["key"] == "convert")
    t["source"], t["paid_until"] = "staff", None
    assert seats.team(nodate, BIZ)["can_buy"] is False


def test_pay_adds_seats_until_plan_end_and_allows_more_users():
    db = _sdb(users=2)
    with pytest.raises(HTTPException):
        gate.check_can_add_user(db, BIZ)
    seats.checkout_seats(db, BIZ, add=2, email="o@x.com")
    assert _order(db)["change_kind"] == "seats"
    _pay_last(db)
    row = _seat(db)
    assert row["config"]["quantity"] == 2 and row["paid_until"] == next(r for r in db.rows("org_plans") if r["key"] == "convert")["paid_until"]
    gate.check_can_add_user(db, BIZ)
    assert seats.team(db, BIZ)["allowed"] == 4


def test_paying_twice_is_idempotent_and_second_purchase_adds():
    db = _sdb()
    seats.checkout_seats(db, BIZ, add=1)
    _pay_last(db)
    _pay_last(db)
    assert _seat(db)["config"]["quantity"] == 1
    seats.checkout_seats(db, BIZ, add=2)
    _pay_last(db)
    assert _seat(db)["config"]["quantity"] == 3


def test_same_open_order_is_reused():
    db = _sdb()
    a = seats.checkout_seats(db, BIZ, add=1)
    b = seats.checkout_seats(db, BIZ, add=1)
    assert b["reused"] and a["reference"] == b["reference"]


def test_renewal_adds_seats_and_next_quantity_lowers_them():
    db = _sdb(users=2, tier_days=2)
    seats.checkout_seats(db, BIZ, add=3)
    _pay_last(db)
    qt = bill.quote_for(db, BIZ, bill.acc.plan_config(db), "convert", _now(), bill._tier_row(db, BIZ))
    assert qt["seats"] == 3 and qt["seats_total"] == 15000 and qt["total"] == 30000 + 15000
    seats.set_next_seats(db, BIZ, 1)
    qt = bill.quote_for(db, BIZ, bill.acc.plan_config(db), "convert", _now(), bill._tier_row(db, BIZ))
    assert qt["seats"] == 1 and qt["total"] == 35000
    bill.checkout(db, BIZ, key="convert", email="o@x.com")
    _pay_last(db)
    assert _seat(db)["config"] == {"quantity": 1}
    assert _seat(db)["paid_until"] == next(r for r in db.rows("org_plans") if r["key"] == "convert")["paid_until"]


def test_renewing_with_zero_next_seats_ends_them():
    db = _sdb(tier_days=2)
    seats.checkout_seats(db, BIZ, add=1)
    _pay_last(db)
    seats.set_next_seats(db, BIZ, 0)
    bill.checkout(db, BIZ, key="convert", email="o@x.com")
    _pay_last(db)
    assert _seat(db) is None


def test_next_seats_cannot_go_up_and_needs_paid_seats():
    db = _sdb()
    with pytest.raises(bill.PlanBillingError):
        seats.set_next_seats(db, BIZ, 1)
    seats.checkout_seats(db, BIZ, add=1)
    _pay_last(db)
    with pytest.raises(bill.PlanBillingError):
        seats.set_next_seats(db, BIZ, 2)


def test_lapsed_plan_blocks_new_users_but_removes_nobody():
    db = _sdb(users=4, tier_days=-40)
    db.tables["org_plans"].append(_plan(key="extra_rep", kind="addon", until=_now(-40), config={"quantity": 2}))
    t = seats.team(db, BIZ)
    assert t["seats"] == 0 and t["allowed"] == 2 and t["used"] == 4 and t["over_by"] == 2 and t["seats_lapsed"]
    with pytest.raises(HTTPException):
        gate.check_can_add_user(db, BIZ)
    assert all(u["is_active"] for u in db.rows("users"))


def test_not_enforced_is_unlimited_and_staff_seats_are_free():
    gate.check_can_add_user(_sdb(users=9, enforced=False), BIZ)
    db = _sdb(users=3, seat_rows=[_plan(key="extra_rep", kind="addon", source="staff", until="none", config={"quantity": 2})])
    gate.check_can_add_user(db, BIZ)
    qt = bill.quote_for(db, BIZ, bill.acc.plan_config(db), "convert", _now(), bill._tier_row(db, BIZ))
    assert qt["seats"] == 0 and qt["total"] == 30000


def test_upgrade_credits_unused_seat_days():
    db = _sdb(tier_days=15)
    db.tables["site_builder_settings"][0]["pricing"]["tiers"]["grow"] = {"monthly_ngn": 60000, "features": [], "caps": {}}
    seats.checkout_seats(db, BIZ, add=2)
    _pay_last(db)
    qt = bill.quote_for(db, BIZ, bill.acc.plan_config(db), "grow", _now(), bill._tier_row(db, BIZ))
    assert qt["kind"] == "upgrade" and qt["seats"] == 2 and qt["seats_total"] == 10000
