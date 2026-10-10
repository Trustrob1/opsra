"""
tests/unit/test_site_addon_billing.py
---------------------------------------
SITE-ADDONS A0-2 - the client's purchase of a tier / add-on: setting it up, the private pay link, the Paystack order,
the payment hook, upgrades / downgrades, the set-up fee, and the daily grace / pause / reminder sweep.
FakeDB stands in for Supabase; Paystack, e-mail / WhatsApp and manager alerts are patched at their own module.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.services import funnel_service, paystack_storefront_service
from app.services import site_addon_billing_service as billing
from app.services import site_entitlement_service as ent
from app.services import site_order_service as orders
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
SITE = "site-1"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)

PRICING = {"tiers": {
    "capture": {"monthly_ngn": 15000, "setup_fee_ngn": 5000},
    "convert": {"monthly_ngn": 40000, "setup_fee_ngn": 10000, "caps": {"ai_messages": 300}},
    "grow": {"monthly_ngn": 90000},
}, "addons": {"extra_rep": {"monthly_ngn": 5000}}}


def _db(pricing=None, site_extra=None, rows=None):
    site = {"id": SITE, "org_id": ORG, "builder_id": "b-1", "client_business_name": "Alfa Diva", "deleted_at": None,
            "legal_owner": {"full_name": "Ada Obi", "phone": "08030000001", "email": "ada@example.com"}}
    site.update(site_extra or {})
    return FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": copy.deepcopy(PRICING) if pricing is None else pricing}],
        sites=[site, {"id": "site-2", "org_id": ORG, "builder_id": "b-1", "client_business_name": "Other", "deleted_at": None,
                      "legal_owner": {}}],
        site_builders=[{"id": "b-1", "org_id": ORG, "full_name": "Chidi", "phone_number": "2348030000009",
                        "lead_id": "lead-1", "status": "active"}],
        site_addons=rows or [], site_usage_counters=[], site_events=[], site_orders=[], payment_links=[])


@pytest.fixture
def env(monkeypatch):
    log = {"links": 0, "payer": [], "builder": [], "managers": [], "emails": []}

    def link(db=None, org_id=None, lead_id=None, amount=None, **kw):
        log["links"] += 1
        n = log["links"]
        row = {"id": f"pl-{n}", "org_id": org_id, "checkout_url": f"https://checkout.paystack.com/{n}", "reference": f"ref-{n}"}
        db.table("payment_links").insert(row).execute()
        return {"payment_link_id": f"pl-{n}", "reference": f"ref-{n}", "checkout_url": f"https://checkout.paystack.com/{n}"}

    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", link)
    monkeypatch.setattr(funnel_service, "notify_managers", lambda db, org, t, b, ty, r: log["managers"].append((t, b)))
    monkeypatch.setattr(billing, "_notify_payer", lambda db, org, row, site, builder, text, url, params=None:
                        log["payer"].append((text, url)) or True)
    monkeypatch.setattr(billing, "_tell_builder", lambda db, org, site, order, text: log["builder"].append(text))
    monkeypatch.setattr(billing, "_send_email", lambda to, subject, text: log["emails"].append((to, subject)) or True)
    return log


def _buy(db, kind="tier", key="capture", **kw):
    return billing.start_purchase(db, ORG, SITE, "user:u1", kind, key, now=NOW, **kw)


def _row(db):
    return db.rows("site_addons")[0]


def _token(db):
    return _row(db)["config"]["pay_token"]


def _pay(db, env, now=NOW):
    """Open the link, pay it, and run the real payment hook."""
    out = billing.pay_checkout(db, _token(db), now)
    ref = db.rows("site_orders")[-1]["payment_reference"]
    assert orders.on_payment_confirmed(db, ORG, ref, now) is True
    return out


# -- starting a purchase ---------------------------------------------------------

def test_start_purchase_makes_a_pending_row_a_private_link_and_a_quote(env):
    db = _db()
    r = _buy(db)
    row = _row(db)
    assert (row["kind"], row["key"], row["status"], row["source"]) == ("tier", "capture", "pending", "paid")
    assert row["payer_name"] == "Ada Obi" and row["payer_email"] == "ada@example.com"      # defaults from the site's owner
    assert row["payer_token_hash"] and row["payer_token_hash"] != row["config"]["pay_token"]
    assert r["pay_url"].endswith("/site-pay/" + row["config"]["pay_token"])
    assert r["quote"]["price"] == 15000 and r["quote"]["setup_fee"] == 5000 and r["quote"]["total"] == 20000
    assert not ent.has_feature(db, ORG, SITE, "wa_menu", NOW)                              # nothing is on until it is paid
    assert db.rows("site_events")[-1]["event"] == "site_addon_purchase_started"


def test_a_second_start_reuses_the_row_and_keeps_the_link(env):
    db = _db()
    a = _buy(db)
    b = _buy(db, payer={"name": "Ada O.", "email": "new@example.com"})
    assert a["addon_id"] == b["addon_id"] and a["pay_url"] == b["pay_url"]
    assert len(db.rows("site_addons")) == 1 and _row(db)["payer_email"] == "new@example.com"


@pytest.mark.parametrize("kw,pricing,site_extra", [
    ({"key": "platinum"}, None, None),
    ({"key": "capture"}, {}, None),                                                       # price 0 = not for sale
    ({"key": "capture"}, None, {"legal_owner": {}}),                                      # nobody to send the link to
    ({"key": "capture"}, None, {"builder_id": None}),
    ({"key": "convert", "picks": ["wa_menu"]}, None, None),                               # not a choice for this tier
    ({"key": "capture", "billing_mode": "cash"}, None, None),
    ({"key": "capture", "kind": "plan"}, None, None),
])
def test_start_purchase_refuses_bad_requests(env, kw, pricing, site_extra):
    db = _db(pricing=pricing, site_extra=site_extra)
    with pytest.raises(ent.EntitlementError):
        _buy(db, **kw)
    assert db.rows("site_addons") == []


def test_site_must_belong_to_the_org(env):
    db = _db()
    db.rows("site_builder_settings").append({"org_id": "org-2", "enabled": True, "pricing": copy.deepcopy(PRICING)})
    with pytest.raises(ent.EntitlementNotFound):
        billing.start_purchase(db, "org-2", SITE, "user:u1", "tier", "capture", now=NOW)


# -- the pay page ---------------------------------------------------------------

def test_pay_view_shows_the_plan_the_price_and_nothing_else(env):
    db = _db()
    _buy(db, key="convert", picks=["selling_booking"])
    v = billing.pay_view(db, _token(db), NOW)
    assert v["state"] == "pay" and v["label"] == "Convert" and v["amount_due"] == 50000 and v["setup_fee"] == 10000
    assert "Booking with reminders" in v["includes"] and "Catalog with recommendations" not in v["includes"]
    assert "org_id" not in v and "id" not in v
    assert billing.pay_view(db, "wrong-token", NOW) is None
    assert billing.pay_view(db, "", NOW) is None


def test_pay_view_says_paid_up_until_the_renewal_window_then_shows_the_price(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    assert billing.pay_view(db, _token(db), NOW + 2 * DAY)["state"] == "paid_up"
    v = billing.pay_view(db, _token(db), NOW + 27 * DAY)                                   # 3 days left, window is 5
    assert v["state"] == "pay" and v["kind"] == "renewal" and v["amount_due"] == 15000 and v["setup_fee"] == 0


def test_a_cancelled_link_or_a_price_taken_off_sale_stops_working(env):
    db = _db()
    _buy(db)
    tok = _token(db)
    db.rows("site_builder_settings")[0]["pricing"] = {}
    assert billing.pay_view(db, tok, NOW)["state"] == "unavailable"
    with pytest.raises(ent.EntitlementError):
        billing.pay_checkout(db, tok, NOW)
    _row(db)["status"] = "cancelled"
    assert billing.pay_view(db, tok, NOW) is None and billing.pay_checkout(db, tok, NOW) is None


# -- the order and the Paystack link --------------------------------------------

def test_checkout_creates_a_site_addon_order_with_the_server_price(env):
    db = _db()
    _buy(db)
    out = billing.pay_checkout(db, _token(db), NOW)
    assert out["checkout_url"].startswith("https://checkout.paystack.com/") and out["amount"] == 20000
    o = db.rows("site_orders")[0]
    assert (o["kind"], o["status"], o["site_id"], o["builder_id"], o["lead_id"]) == ("site_addon", "pending_payment", SITE, "b-1", "lead-1")
    assert o["amount"] == 20000 and o["approval_required"] is False and o["route"] == "standard"
    assert o["quote"]["addon_id"] == _row(db)["id"] and o["quote"]["key"] == "capture" and o["quote"]["setup_fee"] == 5000


def test_the_same_open_link_is_reused(env):
    db = _db()
    _buy(db)
    a = billing.pay_checkout(db, _token(db), NOW)
    b = billing.pay_checkout(db, _token(db), NOW)
    assert b["reused"] is True and a["checkout_url"] == b["checkout_url"]
    assert env["links"] == 1 and len(db.rows("site_orders")) == 1


def test_a_price_change_expires_the_old_link_and_makes_a_new_one(env):
    db = _db()
    _buy(db)
    billing.pay_checkout(db, _token(db), NOW)
    db.rows("site_builder_settings")[0]["pricing"]["tiers"]["capture"]["monthly_ngn"] = 18000
    out = billing.pay_checkout(db, _token(db), NOW)
    assert out["amount"] == 23000 and out["reused"] is False
    assert [o["status"] for o in db.rows("site_orders")] == ["expired", "pending_payment"]


def test_paystack_failure_is_a_plain_error_and_leaves_no_order(env, monkeypatch):
    db = _db()
    _buy(db)

    def boom(**kw):
        raise paystack_storefront_service.PaystackLinkError("Paystack is not connected")
    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", boom)
    with pytest.raises(billing.AddonBillingError):
        billing.pay_checkout(db, _token(db), NOW)
    assert db.rows("site_orders") == []


# -- payment -> plan on ---------------------------------------------------------

def test_payment_switches_the_plan_on_for_30_days_and_tells_everyone(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    row = _row(db)
    assert (row["status"], row["source"], row["price_ngn"]) == ("active", "paid", 15000)
    assert ent._parse(row["paid_until"]) == NOW + 30 * DAY
    assert row["config"]["setup_paid"] is True
    assert ent.has_feature(db, ORG, SITE, "form_instant_reply", NOW) and not ent.has_feature(db, ORG, SITE, "ai_assistant", NOW)
    assert db.rows("site_orders")[0]["status"] == "live"
    assert any("active until" in t for t, _ in env["payer"]) and any("paid" in t for t in env["builder"])
    assert ("Plan paid", "₦20,000") in env["managers"]
    assert [e["event"] for e in db.rows("site_events")][-1] == "site_addon_paid"


def test_the_payment_hook_is_idempotent(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    ref = db.rows("site_orders")[0]["payment_reference"]
    until = _row(db)["paid_until"]
    assert orders.on_payment_confirmed(db, ORG, ref, NOW) is True                          # a second delivery of the webhook
    assert _row(db)["paid_until"] == until and len(env["payer"]) == 1


def test_a_payment_that_cannot_be_applied_alerts_managers_but_is_not_lost(env):
    db = _db()
    _buy(db)
    billing.pay_checkout(db, _token(db), NOW)
    db.rows("site_addons").clear()                                                         # the row vanished before payment
    ref = db.rows("site_orders")[0]["payment_reference"]
    assert orders.on_payment_confirmed(db, ORG, ref, NOW) is True
    assert db.rows("site_orders")[0]["status"] == "live"
    assert any(t == "Plan payment needs a hand" for t, _ in env["managers"])


def test_setup_fee_is_charged_once_only(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    later = NOW + 26 * DAY
    out = billing.pay_checkout(db, _token(db), later)
    assert out["amount"] == 15000
    ref = db.rows("site_orders")[-1]["payment_reference"]
    assert orders.on_payment_confirmed(db, ORG, ref, later) is True


def test_paying_early_keeps_the_unused_days(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    again = NOW + 20 * DAY                                                                 # 10 days still running
    _pay(db, env, again)
    assert ent._parse(_row(db)["paid_until"]) == NOW + 60 * DAY


def test_paying_after_it_lapsed_starts_from_the_payment_day(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    late = NOW + 45 * DAY
    _pay(db, env, late)
    assert ent._parse(_row(db)["paid_until"]) == late + 30 * DAY and _row(db)["status"] == "active"


def test_an_add_on_is_bought_the_same_way_and_extends_features(env):
    db = _db()
    _buy(db, kind="addon", key="extra_rep")
    _pay(db, env)
    row = _row(db)
    assert (row["kind"], row["key"], row["status"]) == ("addon", "extra_rep", "active")
    assert db.rows("site_orders")[0]["amount"] == 5000                                      # add-ons have no set-up fee
    assert "extra_rep" in ent.get_entitlements(db, ORG, SITE, NOW)["features"]


# -- upgrade / downgrade --------------------------------------------------------

def test_upgrade_credits_the_unused_days_and_starts_the_new_plan_now(env):
    db = _db()
    _buy(db)
    _pay(db, env)
    mid = NOW + 15 * DAY                                                                   # 15 of 30 days left
    r = billing.start_purchase(db, ORG, SITE, "user:u1", "tier", "convert", now=mid)
    q = r["quote"]
    assert q["kind"] == "upgrade" and q["credit"] == 7500 and q["total"] == 40000 - 7500   # set-up fee already paid once
    assert len(db.rows("site_addons")) == 1 and _row(db)["key"] == "capture"               # still Capture until it is paid
    billing.pay_checkout(db, _token(db), mid)
    ref = db.rows("site_orders")[-1]["payment_reference"]
    assert db.rows("site_orders")[-1]["amount"] == 32500
    assert orders.on_payment_confirmed(db, ORG, ref, mid) is True
    row = _row(db)
    assert row["key"] == "convert" and ent._parse(row["paid_until"]) == mid + 30 * DAY
    assert "change" not in row["config"]
    assert ent.has_feature(db, ORG, SITE, "qualification", mid)


def test_downgrade_is_scheduled_and_applies_when_the_next_renewal_is_paid(env):
    db = _db()
    _buy(db, key="convert")
    _pay(db, env)
    mid = NOW + 10 * DAY
    r = billing.start_purchase(db, ORG, SITE, "user:u1", "tier", "capture", now=mid)
    assert r["scheduled"] is True and _row(db)["key"] == "convert"
    assert ent.has_feature(db, ORG, SITE, "qualification", mid)                            # still Convert until the renewal
    assert db.rows("site_events")[-1]["event"] == "site_addon_downgrade_scheduled"
    near_end = NOW + 28 * DAY
    q = billing.quote_for(_row(db), ent.get_config(db.rows("site_builder_settings")[0]), near_end)
    assert q["key"] == "capture" and q["total"] == 15000 and q["change_kind"] == "downgrade"
    _pay(db, env, near_end)
    row = _row(db)
    assert row["key"] == "capture" and "pending_key" not in row["config"]
    assert ent._parse(row["paid_until"]) == NOW + 60 * DAY                                  # the paid-for days were kept
    assert not ent.has_feature(db, ORG, SITE, "qualification", near_end)


def test_switching_an_unpaid_or_staff_granted_plan_has_no_credit(env):
    db = _db()
    ent.grant(db, ORG, SITE, "user:u1", "tier", "capture", now=NOW)                        # staff-granted
    r = _buy(db, key="convert")
    assert r["quote"]["credit"] == 0 and r["quote"]["total"] == 50000
    _pay(db, env)
    row = _row(db)
    assert row["key"] == "convert" and row["source"] == "paid" and ent._parse(row["paid_until"]) == NOW + 30 * DAY


# -- the daily sweep ------------------------------------------------------------

def _paid_db(env, paid=NOW, billing_mode="link"):
    db = _db()
    _buy(db, billing_mode=billing_mode)
    _pay(db, env, paid)
    env["payer"].clear()
    env["builder"].clear()
    return db


ACTIVE = lambda org: True      # noqa: E731


def test_reminders_go_to_the_client_at_5_and_1_days_once_each(env):
    db = _paid_db(env)
    assert billing.run_cycle(db, NOW + 20 * DAY, ACTIVE)["reminders"] == 0                 # 10 days left
    r = billing.run_cycle(db, NOW + 25 * DAY + timedelta(hours=1), ACTIVE)                 # just under 5 days left
    assert r["reminders"] == 1 and len(env["payer"]) == 1
    assert "/site-pay/" in env["payer"][0][1]
    assert billing.run_cycle(db, NOW + 26 * DAY, ACTIVE)["reminders"] == 0                 # same day-5 reminder is not repeated
    assert billing.run_cycle(db, NOW + 29 * DAY + timedelta(hours=2), ACTIVE)["reminders"] == 1   # under 1 day left
    assert billing.run_cycle(db, NOW + 29 * DAY + timedelta(hours=3), ACTIVE)["reminders"] == 0
    assert len(env["payer"]) == 2


def test_a_failed_delivery_is_retried_next_run(env, monkeypatch):
    db = _paid_db(env)
    monkeypatch.setattr(billing, "_notify_payer", lambda *a, **k: False)
    assert billing.run_cycle(db, NOW + 26 * DAY, ACTIVE)["reminders"] == 0
    assert "reminded" not in _row(db)["config"]
    monkeypatch.setattr(billing, "_notify_payer", lambda db, org, row, site, builder, text, url, params=None:
                        env["payer"].append((text, url)) or True)
    assert billing.run_cycle(db, NOW + 27 * DAY, ACTIVE)["reminders"] == 1


def test_automatic_card_billing_rows_get_no_link_reminders(env):
    db = _paid_db(env, billing_mode="auto")
    assert billing.run_cycle(db, NOW + 27 * DAY, ACTIVE)["reminders"] == 0 and env["payer"] == []


def test_after_the_end_date_the_plan_goes_to_grace_then_pauses(env):
    db = _paid_db(env)
    r = billing.run_cycle(db, NOW + 31 * DAY, ACTIVE)
    assert r["to_grace"] == 1 and _row(db)["status"] == "grace"
    assert ent.has_feature(db, ORG, SITE, "wa_menu", NOW + 31 * DAY)                       # tools stay on in grace
    assert any("stay on until" in t for t, _ in env["payer"]) and any("has ended" in t for t in env["builder"])
    assert billing.run_cycle(db, NOW + 32 * DAY, ACTIVE)["to_grace"] == 0                  # not repeated
    r2 = billing.run_cycle(db, NOW + 38 * DAY + timedelta(hours=1), ACTIVE)                # 7 grace days are over
    assert r2["paused"] == 1 and _row(db)["status"] == "paused"
    assert not ent.has_feature(db, ORG, SITE, "wa_menu", NOW + 38 * DAY + timedelta(hours=1))
    assert any("paused" in t for t, _ in env["payer"]) and any(t == "Plan paused: Alfa Diva" for t, _ in env["managers"])
    assert billing.run_cycle(db, NOW + 39 * DAY, ACTIVE)["checked"] == 0                   # paused rows are left alone


def test_paying_in_grace_switches_it_straight_back_to_active(env):
    db = _paid_db(env)
    billing.run_cycle(db, NOW + 33 * DAY, ACTIVE)
    assert _row(db)["status"] == "grace"
    _pay(db, env, NOW + 34 * DAY)
    assert _row(db)["status"] == "active" and _row(db)["grace_until"] is None


def test_paying_after_the_pause_switches_it_back_on(env):
    db = _paid_db(env)
    billing.run_cycle(db, NOW + 40 * DAY, ACTIVE)
    assert _row(db)["status"] == "paused"
    _pay(db, env, NOW + 42 * DAY)
    assert _row(db)["status"] == "active" and ent.has_feature(db, ORG, SITE, "wa_menu", NOW + 42 * DAY)


def test_grace_days_come_from_settings(env):
    db = _paid_db(env)
    db.rows("site_builder_settings")[0]["pricing"]["tier_billing"] = {"grace_days": 2}
    billing.run_cycle(db, NOW + 31 * DAY, ACTIVE)
    billing.run_cycle(db, NOW + 33 * DAY, ACTIVE)
    assert _row(db)["status"] == "paused"


def test_inactive_orgs_and_staff_granted_rows_are_skipped_and_one_bad_row_does_not_stop_the_rest(env):
    db = _paid_db(env)
    assert billing.run_cycle(db, NOW + 40 * DAY, lambda org: False)["paused"] == 0
    ent.grant(db, ORG, "site-2", "user:u1", "tier", "capture", until=NOW + 100 * DAY, now=NOW)   # staff: not billed here
    db.rows("site_addons").append({"id": "bad", "org_id": ORG, "site_id": "gone", "kind": "tier", "key": "capture",
                                   "status": "active", "source": "paid", "paid_until": (NOW - 30 * DAY).isoformat(), "config": {}})
    r = billing.run_cycle(db, NOW + 40 * DAY, ACTIVE)
    assert r["paused"] == 1 and r["failed"] == 1
    assert db.rows("site_addons")[0]["status"] == "paused" and db.rows("site_addons")[1]["status"] == "active"


# -- sending the link -----------------------------------------------------------

def test_send_link_tells_the_client_the_amount_and_logs_it(env):
    db = _db()
    r = _buy(db)
    out = billing.send_link(db, ORG, SITE, r["addon_id"], "user:u1")
    assert out["sent"] is True and out["pay_url"] == r["pay_url"]
    assert "₦20,000" in env["payer"][-1][0] and db.rows("site_events")[-1]["event"] == "site_addon_link_sent"
    with pytest.raises(ent.EntitlementNotFound):
        billing.send_link(db, ORG, "site-2", r["addon_id"], "user:u1")                    # not this site's row
    with pytest.raises(ent.EntitlementNotFound):
        billing.send_link(db, "org-2", SITE, r["addon_id"], "user:u1")
