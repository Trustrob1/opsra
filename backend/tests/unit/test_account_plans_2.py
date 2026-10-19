"""
ACCOUNT-PLANS AP-2: an organisation paying for its own plan (orders, Paystack on Opsra's key, webhook, worker).
"""
from __future__ import annotations

import pytest

from app.services import account_plan_billing_service as svc
from app.services import credit_order_service
from tests.unit.test_account_plans_1 import BIZ, OTHER, PLATFORM, WS, _db, _now, _plan

SECRET_ENV = "PAYSTACK_SECRET_KEY"


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _Client:
    """Stands in for httpx.Client; remembers what was sent to Paystack."""
    sent: list = []
    verify_data: dict = {}

    def __init__(self, *a, **k): ...
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, headers=None, json=None):
        _Client.sent.append(json)
        return _Resp({"status": True, "data": {"authorization_url": "https://paystack.test/pay/" + json["reference"]}})

    def get(self, url, headers=None):
        return _Resp({"status": True, "data": _Client.verify_data})


@pytest.fixture(autouse=True)
def _paystack(monkeypatch):
    monkeypatch.setenv(SECRET_ENV, "sk_test_x")
    monkeypatch.setattr(svc.httpx, "Client", _Client)
    monkeypatch.setattr(svc.sab, "_send_email", lambda *a, **k: True)
    _Client.sent = []
    _Client.verify_data = {}


def _full_db(**kw):
    db = _db(**kw)
    db.tables.setdefault("org_plan_orders", [])
    db.tables.setdefault("notifications", [])
    db.tables.setdefault("site_discount_codes", [])
    db.tables.setdefault("site_discount_redemptions", [])
    db.tables["users"] = [{"id": "u-owner", "org_id": BIZ, "roles": {"template": "owner"}}]
    return db


def _checkout(db, key="capture", **kw):
    return svc.checkout(db, BIZ, key=key, email="owner@biz.test", user_id=None, **kw)


def _order(db, i=-1):
    return db.rows("org_plan_orders")[i]


def _pay(db, ref=None, kobo=None, now=None):
    o = _order(db)
    return svc.mark_paid(db, ref or o["reference"], o["amount_kobo"] if kobo is None else kobo, now)


def _tier(db, org=BIZ):
    return next((r for r in db.rows("org_plans") if r["org_id"] == org and r["kind"] == "tier" and r["status"] != "cancelled"), None)


def _code(**kw):
    return {"id": "code-1", "org_id": PLATFORM, "code": "WELCOME", "active": True, "applies_to": "plans", "kind": "percent",
            "value": 10, "expires_at": None, "max_uses": None, "one_per_builder": False, **kw}


# -- the price comes from the server, with no set-up fee ------------------------

def test_new_plan_costs_the_monthly_price_only_and_the_amount_is_server_side():
    db = _full_db()
    res = _checkout(db)
    assert res["amount_kobo"] == 15000 * 100
    assert _Client.sent[0]["amount"] == 1500000 and _Client.sent[0]["reference"].startswith("ap_")
    o = _order(db)
    assert o["org_id"] == BIZ and o["status"] == "pending" and o["change_kind"] == "new"
    assert o["quote"]["price"] == 15000 and "setup_fee" not in o["quote"]


def test_unknown_or_unpriced_plan_is_refused():
    db = _full_db()
    with pytest.raises(svc.PlanBillingError):
        _checkout(db, key="grow")                 # price 0 = not for sale
    with pytest.raises(svc.PlanBillingError):
        _checkout(db, key="nonsense")
    assert db.rows("org_plan_orders") == []


def test_no_paystack_key_refuses_before_anything_is_stored(monkeypatch):
    monkeypatch.delenv(SECRET_ENV)
    db = _full_db()
    with pytest.raises(svc.PlanBillingError):
        _checkout(db)
    assert db.rows("org_plan_orders") == []


def test_same_choice_reuses_the_open_checkout_and_a_new_choice_expires_it():
    db = _full_db()
    first = _checkout(db)
    again = _checkout(db)
    assert again["reused"] and again["reference"] == first["reference"] and len(db.rows("org_plan_orders")) == 1
    other = _checkout(db, key="convert")
    assert not other["reused"]
    assert [o["status"] for o in db.rows("org_plan_orders")] == ["expired", "pending"]


def test_a_client_workspace_cannot_buy_an_account_plan():
    db = _full_db()
    with pytest.raises(svc.PlanBillingError):
        svc.checkout(db, WS, key="capture")
    assert db.rows("org_plan_orders") == []


# -- payment turns the plan on, once -------------------------------------------

def test_payment_creates_the_plan_for_30_days():
    db = _full_db()
    _checkout(db)
    now = _now()
    assert _pay(db, now=now) == {"applied": True, "reason": "ok"}
    t = _tier(db)
    assert t["key"] == "capture" and t["status"] == "active" and t["source"] == "paid" and t["price_ngn"] == 15000
    assert 29.9 < (svc.ent._parse(t["paid_until"]) - now).total_seconds() / 86400 <= 30.0
    assert _order(db)["status"] == "paid"
    assert any(n["org_id"] == BIZ for n in db.rows("notifications"))


def test_double_webhook_applies_once():
    db = _full_db()
    _checkout(db)
    _pay(db)
    until = _tier(db)["paid_until"]
    assert _pay(db)["reason"] == "already_applied"
    assert _tier(db)["paid_until"] == until and len(db.rows("org_plans")) == 1


def test_underpayment_does_not_turn_anything_on():
    db = _full_db()
    _checkout(db)
    assert _pay(db, kobo=1499999)["reason"] == "underpaid"
    assert _tier(db) is None and _order(db)["status"] == "pending"


def test_unknown_and_foreign_references_do_nothing():
    db = _full_db()
    assert svc.mark_paid(db, "ap_unknown", 5)["reason"] == "unknown_reference"
    assert svc.mark_paid(db, "cr_abc", 5)["reason"] == "not_a_plan_order"
    assert credit_order_service.mark_paid(db, "ap_x", 5)["reason"] == "not_a_credit_order"      # credits untouched


def test_early_renewal_keeps_the_unused_days():
    end = _now(10)
    db = _full_db(plans=[_plan(until=end, price_ngn=15000)])
    assert _checkout(db)["amount_kobo"] == 1500000 and _order(db)["change_kind"] == "renewal"
    _pay(db)
    assert abs((svc.ent._parse(_tier(db)["paid_until"]) - end).total_seconds() - 30 * 86400) < 5


def test_renewal_after_the_end_starts_now():
    db = _full_db(plans=[_plan(until=_now(-3), price_ngn=15000)])
    _checkout(db)
    now = _now()
    _pay(db, now=now)
    assert 29.9 < (svc.ent._parse(_tier(db)["paid_until"]) - now).total_seconds() / 86400 <= 30.0


def test_a_failed_apply_puts_the_order_back_so_a_retry_works(monkeypatch):
    db = _full_db()
    _checkout(db)
    real = svc._apply_paid
    monkeypatch.setattr(svc, "_apply_paid", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert _pay(db)["reason"] == "apply_failed" and _order(db)["status"] == "pending"
    monkeypatch.setattr(svc, "_apply_paid", real)
    assert _pay(db)["applied"] and _tier(db)["status"] == "active"


def test_a_payment_on_an_expired_order_still_applies():
    db = _full_db()
    _checkout(db)
    _checkout(db, key="convert")            # expires the first
    first = db.rows("org_plan_orders")[0]
    res = svc.mark_paid(db, first["reference"], first["amount_kobo"])
    assert res == {"applied": True, "reason": "late_payment"} and _tier(db)["key"] == "capture"


# -- upgrade, downgrade -----------------------------------------------------------

def test_upgrade_credits_unused_days_and_starts_now():
    db = _full_db(plans=[_plan(until=_now(15), price_ngn=15000)])
    res = _checkout(db, key="convert")
    o = _order(db)
    assert o["change_kind"] == "upgrade" and o["quote"]["credit"] > 0
    assert res["amount_kobo"] == (30000 - o["quote"]["credit"]) * 100 and res["amount_kobo"] < 3000000
    now = _now()
    _pay(db, now=now)
    t = _tier(db)
    assert t["key"] == "convert" and 29.9 < (svc.ent._parse(t["paid_until"]) - now).total_seconds() / 86400 <= 30.0


def test_downgrade_is_scheduled_then_applied_at_the_next_renewal():
    end = _now(10)
    db = _full_db(plans=[_plan(key="convert", until=end, price_ngn=30000)])
    res = _checkout(db, key="capture")
    assert res["scheduled"] and db.rows("org_plan_orders") == []
    assert _tier(db)["key"] == "convert" and _tier(db)["config"]["pending_key"] == "capture"
    res2 = _checkout(db, key="capture")               # now the renewal order at the LOWER price
    assert res2["amount_kobo"] == 1500000 and _order(db)["change_kind"] == "downgrade_renewal"
    _pay(db)
    t = _tier(db)
    assert t["key"] == "capture" and "pending_key" not in t["config"]
    assert abs((svc.ent._parse(t["paid_until"]) - end).total_seconds() - 30 * 86400) < 5


def test_paying_for_the_current_plan_cancels_a_scheduled_downgrade():
    db = _full_db(plans=[_plan(key="convert", until=_now(10), price_ngn=30000, config={"pending_key": "capture"})])
    _checkout(db, key="convert")
    _pay(db)
    assert _tier(db)["key"] == "convert" and "pending_key" not in _tier(db)["config"]


def test_clear_pending_change():
    db = _full_db(plans=[_plan(key="convert", until=_now(10), config={"pending_key": "capture"})])
    assert svc.clear_pending_change(db, BIZ)["cleared"] and "pending_key" not in _tier(db)["config"]
    with pytest.raises(svc.PlanBillingError):
        svc.clear_pending_change(db, BIZ)


def test_staff_granted_plan_switches_to_paid_with_no_credit():
    db = _full_db(plans=[_plan(source="staff", until="none")])
    res = _checkout(db, key="convert")
    assert res["amount_kobo"] == 3000000 and _order(db)["quote"]["credit"] == 0


# -- discount codes: first payment only ---------------------------------------------

def test_code_discounts_the_first_payment_and_counts_once():
    db = _full_db(site_discount_codes=[_code()])
    res = _checkout(db, code="welcome")
    assert res["amount_kobo"] == 1350000 and _order(db)["quote"]["discount"]["code_id"] == "code-1"
    _pay(db)
    _pay(db)
    reds = db.rows("site_discount_redemptions")
    assert len(reds) == 1 and reds[0]["org_id"] == PLATFORM and reds[0]["amount_ngn"] == 1500


def test_code_is_refused_on_a_renewal_or_after_a_first_payment():
    db = _full_db(plans=[_plan(until=_now(10))], site_discount_codes=[_code()])
    with pytest.raises(svc.PlanBillingError):
        _checkout(db, code="WELCOME")
    db2 = _full_db(site_discount_codes=[_code()])
    _checkout(db2)
    _pay(db2)
    db2.rows("org_plans")[0]["status"] = "cancelled"            # starts again from nothing, but it is not the first payment
    with pytest.raises(svc.PlanBillingError):
        _checkout(db2, code="WELCOME")


def test_bad_or_site_only_code_is_refused_with_the_same_message():
    db = _full_db(site_discount_codes=[_code(applies_to="websites")])
    with pytest.raises(svc.PlanBillingError, match="isn't valid"):
        _checkout(db, code="WELCOME")
    with pytest.raises(svc.PlanBillingError, match="isn't valid"):
        _checkout(db, code="NOPE")
    assert db.rows("org_plan_orders") == []


def test_preview_reports_a_bad_code_instead_of_raising():
    db = _full_db(site_discount_codes=[_code()])
    ok = svc.preview(db, BIZ, "capture", "WELCOME")
    assert ok["amount_due"] == 13500 and ok["discount"]["discount"] == 1500 and ok["discount_error"] is None
    bad = svc.preview(db, BIZ, "capture", "NOPE")
    assert bad["amount_due"] == 15000 and bad["discount_error"]


# -- the return page and org scoping ----------------------------------------------------

def test_verify_applies_a_paid_transaction_and_only_for_the_owner_org():
    db = _full_db()
    _checkout(db)
    ref = _order(db)["reference"]
    with pytest.raises(svc.PlanBillingError):
        svc.verify(db, OTHER, ref)
    _Client.verify_data = {"status": "success", "amount": 1500000}
    assert svc.verify(db, BIZ, ref) == {"status": "paid"} and _tier(db)["status"] == "active"
    assert svc.verify(db, BIZ, ref) == {"status": "paid"}
    with pytest.raises(svc.PlanBillingError):
        svc.verify(db, BIZ, "cr_nope")


def test_verify_pending_and_failed():
    db = _full_db()
    _checkout(db)
    ref = _order(db)["reference"]
    _Client.verify_data = {"status": "abandoned"}
    assert svc.verify(db, BIZ, ref) == {"status": "failed"} and _tier(db) is None


def test_summary_shows_only_the_callers_data():
    db = _full_db(plans=[_plan(until=_now(10)), _plan(org=OTHER, key="convert", until=_now(10))])
    s = svc.summary(db, BIZ)
    assert s["current"]["key"] == "capture" and s["current"]["days_left"] >= 9
    keys = {p["key"]: p for p in s["plans"]}
    assert set(keys) == {"capture", "convert"} and keys["capture"]["is_current"] and keys["convert"]["action"] == "upgrade"
    assert all(o["id"] for o in s["orders"]) and s["enforced"] is False


# -- the daily sweep ---------------------------------------------------------------------

def test_cycle_reminds_once_per_day_threshold():
    db = _full_db(plans=[_plan(until=_now(4.5), price_ngn=15000)])
    now = _now()
    r = svc.run_cycle(db, now)
    assert r["reminders"] == 1
    assert svc.run_cycle(db, now)["reminders"] == 0              # 5-day reminder already sent
    r2 = svc.run_cycle(db, now + svc.timedelta(days=3.6))        # inside the 1-day window
    assert r2["reminders"] == 1


def test_cycle_moves_to_grace_then_paused_and_pay_brings_it_back():
    db = _full_db(enforced=True, plans=[_plan(until=_now(-1), price_ngn=15000)])
    assert svc.run_cycle(db, _now())["to_grace"] == 1
    assert _tier(db)["status"] == "grace" and db.rows("organisations")[0]["subscription_status"] == "grace"
    later = _now(9)
    assert svc.run_cycle(db, later)["paused"] == 1
    assert _tier(db)["status"] == "paused" and db.rows("organisations")[0]["subscription_status"] == "read_only"
    _checkout(db)
    _pay(db, now=later)
    assert _tier(db)["status"] == "active" and db.rows("organisations")[0]["subscription_status"] == "active"


def test_a_business_not_switched_on_keeps_its_status_but_the_plan_still_moves():
    db = _full_db(enforced=False, plans=[_plan(until=_now(-10), price_ngn=15000)])
    svc.run_cycle(db, _now())
    assert _tier(db)["status"] == "paused" and db.rows("organisations")[0]["subscription_status"] == "active"


def test_suspended_business_is_never_touched_and_staff_plans_are_skipped():
    db = _full_db(enforced=True, plans=[_plan(until=_now(-10)), _plan(org=OTHER, source="staff", until=_now(-10))])
    db.rows("organisations")[0]["subscription_status"] = "suspended"
    r = svc.run_cycle(db, _now())
    assert r["paused"] == 0 and r["checked"] == 1
    assert db.rows("organisations")[0]["subscription_status"] == "suspended"
    assert _tier(db, OTHER)["status"] == "active"


def test_one_bad_row_does_not_stop_the_sweep(monkeypatch):
    db = _full_db(plans=[_plan(until=_now(-10)), _plan(org=OTHER, key="convert", until=_now(-10))])
    real = svc._process
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(svc, "_process", flaky)
    r = svc.run_cycle(db, _now())
    assert r["failed"] == 1 and r["checked"] == 2 and r["paused"] == 1
