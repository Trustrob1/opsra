"""
tests/unit/test_site_addon_discount.py
SITE-ADDONS - discount codes on the first payment of a plan / add-on: scope (websites / plans / both), the pay page,
the Paystack amount, redemption counting, and the cases where a code must not work (renewal, expired, used up).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import public_site_pay
from app.services import site_addon_billing_service as billing
from app.services import site_discount_service as dsc
from app.services import site_entitlement_service as ent
from app.services import site_order_service as orders
from tests.unit.test_site_addon_billing import (ACTIVE, DAY, NOW, ORG, SITE, _buy, _db as _billing_db, _paid_db, _pay,  # noqa: F401
                                                 _row, _token, env)


def _code(db, code="WELCOME", kind="percent", value=10, applies_to="plans", **kw):
    row = {"id": f"c-{code}", "org_id": ORG, "code": code, "kind": kind, "value": value, "active": True, "applies_to": applies_to,
           "expires_at": None, "max_uses": None, "one_per_builder": False}
    row.update(kw)
    db.tables.setdefault("site_discount_codes", []).append(row)
    db.tables.setdefault("site_discount_redemptions", [])
    return row


def _world(env, **code_kw):
    db = _billing_db()
    db.tables.setdefault("site_discount_codes", [])
    db.tables.setdefault("site_discount_redemptions", [])
    if code_kw is not None:
        _code(db, **code_kw)
    return db


# -- the code itself ----------------------------------------------------------------------

def test_a_plans_code_works_on_plans_and_not_on_website_orders(env):
    db = _world(env)
    assert dsc.validate(db, ORG, "b-1", "welcome", 20000, scope="plans")["discount"] == 2000
    with pytest.raises(dsc.DiscountError, match="isn't valid"):
        dsc.validate(db, ORG, "b-1", "WELCOME", 20000)                               # a website order: default scope


def test_a_websites_code_still_works_on_websites_and_not_on_plans(env):
    db = _world(env, code="SITE10", applies_to="websites")
    assert dsc.validate(db, ORG, "b-1", "SITE10", 50000)["discount"] == 5000
    with pytest.raises(dsc.DiscountError):
        dsc.validate(db, ORG, "b-1", "SITE10", 20000, scope="plans")


def test_a_code_for_both_works_on_both(env):
    db = _world(env, code="ALL", applies_to="both")
    assert dsc.validate(db, ORG, "b-1", "ALL", 1000)["discount"] == 100
    assert dsc.validate(db, ORG, "b-1", "ALL", 1000, scope="plans")["discount"] == 100


def test_a_code_row_without_the_column_is_a_websites_code(env):
    db = _world(env, code="OLD")
    del db.rows("site_discount_codes")[0]["applies_to"]
    assert dsc.validate(db, ORG, "b-1", "OLD", 1000)["discount"] == 100
    with pytest.raises(dsc.DiscountError):
        dsc.validate(db, ORG, "b-1", "OLD", 1000, scope="plans")


def test_applies_to_is_cleaned_and_defaults_to_websites():
    assert dsc._clean_payload({"code": "ABC", "kind": "percent", "value": 5}, True)["applies_to"] == "websites"
    assert dsc._clean_payload({"code": "ABC", "kind": "percent", "value": 5, "applies_to": "both"}, True)["applies_to"] == "both"
    assert "applies_to" not in dsc._clean_payload({"note": "x"}, False)
    with pytest.raises(dsc.DiscountError):
        dsc._clean_payload({"code": "ABC", "kind": "percent", "value": 5, "applies_to": "cars"}, True)


# -- the client's pay page ------------------------------------------------------------------

def test_the_pay_view_shows_a_typed_code_and_the_reduced_total(env):
    db = _world(env)
    _buy(db)
    plain = billing.pay_view(db, _token(db), NOW)
    typed = billing.pay_view(db, _token(db), NOW, code="welcome")
    assert plain["amount_due"] == 20000 and plain["discount"] is None
    assert typed["amount_due"] == 18000 and typed["discount"] == {"code": "WELCOME", "discount": 2000.0}


def test_a_bad_typed_code_is_explained_and_the_price_is_unchanged(env):
    db = _world(env)
    _buy(db)
    v = billing.pay_view(db, _token(db), NOW, code="NOPE")
    assert v["amount_due"] == 20000 and v["discount_error"] == "That code isn't valid."


def test_a_code_attached_when_the_link_was_sent_is_applied_automatically(env):
    db = _world(env)
    out = _buy(db, discount_code="welcome")
    assert out["discount"] == {"code": "WELCOME", "discount": 2000.0, "amount_due": 18000.0}
    assert billing.pay_view(db, _token(db), NOW)["amount_due"] == 18000
    assert billing.pay_view(db, _token(db), NOW, code="OTHER")["amount_due"] == 20000     # a different typed code replaces it (and fails)


def test_attaching_an_unusable_code_is_refused_with_a_plain_message(env):
    db = _world(env, applies_to="websites")
    with pytest.raises(ent.EntitlementError, match="isn't valid"):
        _buy(db, discount_code="WELCOME")


def test_an_expired_attached_code_is_dropped_quietly_at_pay_time(env):
    db = _world(env)
    _buy(db, discount_code="WELCOME")
    db.rows("site_discount_codes")[0]["expires_at"] = (NOW - DAY).isoformat()
    v = billing.pay_view(db, _token(db), NOW)
    assert v["amount_due"] == 20000 and v["discount_error"] is None


# -- the order, the payment and the use count ------------------------------------------------

def test_the_paystack_order_uses_the_server_side_discount(env):
    db = _world(env)
    _buy(db)
    out = billing.pay_checkout(db, _token(db), NOW, code="WELCOME")
    order = db.rows("site_orders")[-1]
    assert out["amount"] == 18000 and order["amount"] == 18000
    assert order["quote"]["discount"]["code"] == "WELCOME" and order["quote"]["total_before_discount"] == 20000
    assert order["quote"]["setup_fee"] == 5000 and order["quote"]["price"] == 15000


def test_a_fixed_code_never_takes_the_payment_below_the_floor(env):
    db = _world(env, code="BIG", kind="fixed", value=999999)
    _buy(db)
    out = billing.pay_checkout(db, _token(db), NOW, code="BIG")
    assert out["amount"] == dsc.MIN_PAYABLE_NGN


def test_a_changed_code_makes_a_new_link_and_the_same_code_reuses_it(env):
    db = _world(env)
    _buy(db)
    a = billing.pay_checkout(db, _token(db), NOW, code="WELCOME")
    b = billing.pay_checkout(db, _token(db), NOW, code="WELCOME")
    c = billing.pay_checkout(db, _token(db), NOW)
    assert b["reused"] is True and b["checkout_url"] == a["checkout_url"]
    assert c["amount"] == 20000 and c["checkout_url"] != a["checkout_url"]
    assert [o["status"] for o in db.rows("site_orders")].count("expired") == 1


def test_payment_counts_one_use_and_the_webhook_cannot_count_twice(env):
    db = _world(env)
    _buy(db)
    billing.pay_checkout(db, _token(db), NOW, code="WELCOME")
    ref = db.rows("site_orders")[-1]["payment_reference"]
    assert orders.on_payment_confirmed(db, ORG, ref, NOW) is True
    orders.on_payment_confirmed(db, ORG, ref, NOW)
    reds = db.rows("site_discount_redemptions")
    assert len(reds) == 1 and reds[0]["amount_ngn"] == 2000 and reds[0]["builder_id"] == "b-1"
    assert "discount_code" not in (_row(db)["config"] or {}) and _row(db)["status"] == "active"


def test_a_max_uses_code_stops_working_when_used_up(env):
    db = _world(env, max_uses=1)
    _buy(db)
    billing.pay_checkout(db, _token(db), NOW, code="WELCOME")
    orders.on_payment_confirmed(db, ORG, db.rows("site_orders")[-1]["payment_reference"], NOW)
    db2 = db
    db2.rows("site_addons").clear()
    _buy(db2)                                                                   # a second site-plan purchase
    assert billing.pay_view(db2, _token(db2), NOW, code="WELCOME")["discount_error"] == "That code has been used up."


def test_a_code_does_not_work_on_a_renewal_or_an_upgrade(env):
    db = _paid_db(env)
    _code(db)
    out_view = billing.pay_view(db, _token(db), NOW + 27 * DAY, code="WELCOME")      # inside the renewal window
    assert out_view["kind"] == "renewal" and out_view["discount"] is None and out_view["amount_due"] == 15000
    assert out_view["discount_error"] == "Codes only work on the first payment of a plan."
    with pytest.raises(ent.EntitlementError):
        billing.pay_checkout(db, _token(db), NOW + 27 * DAY, code="WELCOME")
    assert db.rows("site_orders")[-1]["amount"] == 20000                                # the first payment, untouched


def test_an_add_on_first_payment_can_be_discounted_too(env):
    db = _world(env)
    out = _buy(db, kind="addon", key="extra_rep", discount_code="WELCOME")
    assert out["quote"]["total"] == 5000 and out["discount"]["amount_due"] == 4500


# -- the pay page in a browser-like call ----------------------------------------------------

@pytest.fixture
def page(env):
    db = _world(env)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    public_site_pay._rate_store.clear()
    yield db, TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def test_the_pay_page_has_a_code_box_and_shows_the_discount(page):
    db, c = page
    _buy(db)
    tok = _token(db)
    plain = c.get(f"/site-pay/{tok}")
    assert plain.status_code == 200 and "Have a discount code?" in plain.text and "/go\"" in plain.text
    applied = c.get(f"/site-pay/{tok}?code=welcome")
    assert "Code WELCOME" in applied.text and "−₦2,000" in applied.text and "Pay ₦18,000 securely" in applied.text
    assert f"/site-pay/{tok}/go?code=WELCOME" in applied.text
    assert "<script" not in applied.text.lower()


def test_the_pay_page_reports_a_bad_code_and_escapes_it(page):
    db, c = page
    _buy(db)
    r = c.get(f"/site-pay/{_token(db)}", params={"code": "\"><b>x</b>"})
    assert r.status_code == 200 and "isn&#x27;t valid" in r.text or "isn't valid" in r.text
    assert "<b>x</b>" not in r.text


def test_going_to_paystack_with_a_code_charges_the_reduced_amount(page):
    db, c = page
    _buy(db)
    r = c.get(f"/site-pay/{_token(db)}/go?code=WELCOME")
    assert r.status_code == 302 and r.headers["location"].startswith("https://checkout.paystack.com/")
    assert db.rows("site_orders")[-1]["amount"] == 18000


def test_going_to_paystack_with_a_bad_code_is_a_friendly_page_and_makes_no_order(page):
    db, c = page
    _buy(db)
    r = c.get(f"/site-pay/{_token(db)}/go?code=NOPE")
    assert r.status_code == 422 and "isn&#x27;t valid" in r.text or "isn't valid" in r.text
    assert db.rows("site_orders") == []


def test_a_renewal_page_has_no_code_box(env):
    db = _paid_db(env)
    _code(db)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    public_site_pay._rate_store.clear()
    try:
        # inside the renewal window the page shows the renewal price and no code box
        db.rows("site_addons")[0]["paid_until"] = (ent._parse(_row(db)["paid_until"]) - 27 * DAY).isoformat()
        r = TestClient(app, raise_server_exceptions=False).get(f"/site-pay/{_token(db)}?code=WELCOME")
        assert r.status_code == 200 and "Have a discount code?" not in r.text and "Code WELCOME" not in r.text
        assert "Renew" in r.text
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
