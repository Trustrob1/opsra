"""
tests/unit/test_site_access_service.py
---------------------------------------
SITE-ACCESS-1 - the free-site cap (3 by default), the NGN 5,000 / 30-day builder subscription, the Paystack
order for it, the payment hook, and the WhatsApp bot gate. FakeDB stands in for Supabase; Paystack, WhatsApp and
manager alerts are patched at their own module.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import funnel_service, paystack_storefront_service
from app.services import site_access_service as access
from app.services import site_chat_service as chat
from app.services import site_order_service as orders
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def _builder(**kw):
    base = {"id": "b-1", "org_id": ORG, "full_name": "Chidi Obi", "phone_number": "2348030000001",
            "email": "chidi@example.com", "lead_id": "lead-1", "status": "active",
            "max_active_sites": None, "access_paid_until": None}
    base.update(kw)
    return base


def _site(i, status="preview_ready", deleted=None, builder="b-1"):
    return {"id": f"s-{i}", "org_id": ORG, "builder_id": builder, "status": status, "deleted_at": deleted}


def _db(sites=None, builder=None, settings=None):
    return FakeDB(
        sites=sites if sites is not None else [], site_orders=[], site_events=[], payment_links=[],
        site_builders=[builder or _builder()],
        site_builder_settings=[settings or {"org_id": ORG, "pricing": {}}],
    )


@pytest.fixture
def env(monkeypatch):
    log = {"links": 0, "notify": [], "msgs": [], "leads": []}

    def link(**kw):
        log["links"] += 1
        return {"payment_link_id": f"pl-{log['links']}", "reference": f"ref-{log['links']}",
                "checkout_url": f"https://pay.test/{log['links']}"}

    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", link)
    monkeypatch.setattr(funnel_service, "notify_managers", lambda db, org, t, b, ty, r: log["notify"].append((t, b, ty)))
    monkeypatch.setattr(orders, "_message_builder", lambda db, org, order, text: log["msgs"].append(text))
    return log


# -- config -----------------------------------------------------------------

def test_config_defaults_and_overrides():
    assert access.get_config({}) == {"free_sites": 3, "price_ngn": 5000, "days": 30}
    cfg = access.get_config({"pricing": {"builder_access": {"free_sites": "5", "price_ngn": 7500, "days": "bad"}}})
    assert cfg == {"free_sites": 5, "price_ngn": 7500, "days": 30}
    assert access.get_config({"pricing": {"builder_access": "oops"}})["free_sites"] == 3


# -- counting and the cap ------------------------------------------------------

def test_under_the_cap_can_create():
    db = _db([_site(1), _site(2)])
    v = access.view(db, ORG, _builder(), NOW)
    assert v["used"] == 2 and v["free_sites"] == 3 and v["free_left"] == 1 and v["can_create"] is True


def test_third_site_uses_the_last_free_slot_and_fourth_is_blocked():
    db = _db([_site(1), _site(2), _site(3)])
    v = access.view(db, ORG, _builder(), NOW)
    assert v["can_create"] is False and v["free_left"] == 0
    with pytest.raises(access.AccessBlocked) as exc:
        access.check_can_create(db, ORG, _builder(), NOW)
    assert "3 free sites" in str(exc.value) and "₦5,000" in str(exc.value)
    assert exc.value.view["used"] == 3


def test_deleted_cancelled_and_other_builders_sites_do_not_count():
    sites = [_site(1), _site(2, deleted="2026-10-01T00:00:00+00:00"), _site(3, status="cancelled"),
             _site(4, builder="b-2"), _site(5, builder="b-2"), _site(6, builder="b-2")]
    db = _db(sites)
    assert access.count_sites(db, ORG, "b-1") == 1
    assert access.view(db, ORG, _builder(), NOW)["can_create"] is True


def test_live_and_draft_sites_both_count():
    db = _db([_site(1, "live"), _site(2, "brief_in_progress"), _site(3, "renewal_due")])
    assert access.view(db, ORG, _builder(), NOW)["can_create"] is False


def test_staff_override_replaces_the_free_count_for_one_builder():
    db = _db([_site(i) for i in range(1, 8)])
    assert access.view(db, ORG, _builder(max_active_sites=20), NOW)["can_create"] is True
    assert access.view(db, ORG, _builder(max_active_sites=7), NOW)["can_create"] is False
    assert access.view(db, ORG, _builder(max_active_sites=0), NOW)["free_left"] == 0


def test_org_setting_changes_the_free_count():
    db = _db([_site(1), _site(2), _site(3)], settings={"org_id": ORG, "pricing": {"builder_access": {"free_sites": 5}}})
    assert access.view(db, ORG, _builder(), NOW)["can_create"] is True


def test_active_subscription_lifts_the_cap_and_expired_one_does_not():
    db = _db([_site(i) for i in range(1, 6)])
    live = _builder(access_paid_until=(NOW + timedelta(days=3)).isoformat())
    v = access.view(db, ORG, live, NOW)
    assert v["subscribed"] is True and v["can_create"] is True
    lapsed = _builder(access_paid_until=(NOW - timedelta(days=1)).isoformat())
    v = access.view(db, ORG, lapsed, NOW)
    assert v["subscribed"] is False and v["can_create"] is False


def test_a_broken_counter_never_blocks_a_builder():
    class Boom:
        def table(self, _):
            raise RuntimeError("db down")
    assert access.check_can_create(Boom(), ORG, _builder(), NOW)["can_create"] is True


# -- checkout --------------------------------------------------------------------

def test_checkout_makes_a_site_less_order(env):
    db = _db()
    out = access.create_checkout(db, ORG, _builder())
    assert out == {"checkout_url": "https://pay.test/1", "amount": 5000, "days": 30, "reused": False}
    order = db.rows("site_orders")[0]
    assert order["kind"] == "builder_access" and order["site_id"] is None and order["route"] == "standard"
    assert order["status"] == "pending_payment" and order["approval_required"] is False
    assert order["payment_reference"] == "ref-1" and order["builder_id"] == "b-1"


def test_checkout_reuses_the_open_link(env):
    db = _db()
    first = access.create_checkout(db, ORG, _builder())
    db.tables["payment_links"].append({"id": "pl-1", "org_id": ORG, "checkout_url": first["checkout_url"]})
    again = access.create_checkout(db, ORG, _builder())
    assert again["reused"] is True and again["checkout_url"] == first["checkout_url"]
    assert env["links"] == 1 and len(db.rows("site_orders")) == 1


def test_checkout_uses_the_price_setting(env):
    db = _db(settings={"org_id": ORG, "pricing": {"builder_access": {"price_ngn": 8000, "days": 60}}})
    out = access.create_checkout(db, ORG, _builder())
    assert out["amount"] == 8000 and out["days"] == 60
    assert db.rows("site_orders")[0]["quote"]["days"] == 60


def test_checkout_switched_off_when_price_is_zero(env):
    db = _db(settings={"org_id": ORG, "pricing": {"builder_access": {"price_ngn": 0}}})
    with pytest.raises(access.AccessError):
        access.create_checkout(db, ORG, _builder())


def test_checkout_creates_the_missing_lead(env, monkeypatch):
    from app.services import lead_service
    seen = {}

    def fake_create_lead(**kw):
        seen.update(kw)
        return {"id": "lead-new"}
    monkeypatch.setattr(lead_service, "create_lead", fake_create_lead)
    b = _builder(lead_id=None)
    db = _db(builder=b)
    access.create_checkout(db, ORG, b)
    assert seen["payload"].full_name == "Chidi Obi" and seen["entry_path"] == "site_builder"
    assert db.rows("site_builders")[0]["lead_id"] == "lead-new"
    assert db.rows("site_orders")[0]["lead_id"] == "lead-new"


def test_checkout_without_a_lead_is_a_plain_error(env, monkeypatch):
    from app.services import lead_service

    def boom(**kw):
        raise RuntimeError("no")
    monkeypatch.setattr(lead_service, "create_lead", boom)
    b = _builder(lead_id=None)
    with pytest.raises(access.AccessError):
        access.create_checkout(_db(builder=b), ORG, b)


# -- payment hook --------------------------------------------------------------------

def _paid(env, builder=None, now=NOW):
    b = builder or _builder()
    db = _db(builder=b)
    access.create_checkout(db, ORG, b)
    assert orders.on_payment_confirmed(db, ORG, "ref-1", now) is True
    return db


def test_payment_starts_a_period(env):
    db = _paid(env)
    end = datetime.fromisoformat(db.rows("site_builders")[0]["access_paid_until"])
    assert end == NOW + timedelta(days=30)
    assert db.rows("site_orders")[0]["status"] == "live"
    assert db.rows("site_events")[0]["event"] == "builder_access_paid"
    assert env["msgs"] and "subscription is active" in env["msgs"][0]
    assert env["notify"][0][0] == "Builder subscription paid"


def test_paying_early_adds_to_the_running_period(env):
    running = (NOW + timedelta(days=10)).isoformat()
    db = _paid(env, _builder(access_paid_until=running))
    end = datetime.fromisoformat(db.rows("site_builders")[0]["access_paid_until"])
    assert end == NOW + timedelta(days=40)


def test_paying_after_lapse_starts_from_now(env):
    db = _paid(env, _builder(access_paid_until=(NOW - timedelta(days=9)).isoformat()))
    end = datetime.fromisoformat(db.rows("site_builders")[0]["access_paid_until"])
    assert end == NOW + timedelta(days=30)


def test_a_repeated_webhook_does_not_extend_twice(env):
    db = _paid(env)
    first = db.rows("site_builders")[0]["access_paid_until"]
    assert orders.on_payment_confirmed(db, ORG, "ref-1", NOW + timedelta(minutes=5)) is True
    assert db.rows("site_builders")[0]["access_paid_until"] == first


def test_a_failure_applying_the_payment_alerts_managers_and_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db")
    monkeypatch.setattr(access, "on_paid", boom)
    b = _builder()
    db = _db(builder=b)
    access.create_checkout(db, ORG, b)
    assert orders.on_payment_confirmed(db, ORG, "ref-1", NOW) is True
    assert any("needs a hand" in n[0] for n in env["notify"])
    assert db.rows("site_orders")[0]["status"] == "live"


# -- the WhatsApp bot gate ---------------------------------------------------------------

@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(chat, "_send_text", lambda db, org, number, phone, text, lead_id=None: out.append(text))
    return out


def test_bot_is_not_blocked_under_the_cap(env, sent):
    db = _db([_site(1)])
    assert chat._blocked_by_access(db, ORG, {}, "2348030000001", _builder()) is False
    assert sent == []


def test_bot_blocks_with_a_payment_link(env, sent):
    db = _db([_site(1), _site(2), _site(3)])
    assert chat._blocked_by_access(db, ORG, {}, "2348030000001", _builder()) is True
    assert "3 free sites" in sent[0] and "https://pay.test/1" in sent[0] and "reply NEW" in sent[0]


def test_bot_still_explains_when_the_link_cannot_be_made(env, sent, monkeypatch):
    def boom(**kw):
        raise paystack_storefront_service.PaystackLinkError("no key")
    monkeypatch.setattr(paystack_storefront_service, "generate_payment_link", boom)
    db = _db([_site(1), _site(2), _site(3)])
    assert chat._blocked_by_access(db, ORG, {}, "2348030000001", _builder()) is True
    assert "HUMAN" in sent[0]


def test_send_form_link_stops_when_blocked(env, sent):
    db = _db([_site(1), _site(2), _site(3)])
    db.tables["site_brief_forms"] = []
    chat._send_form_link(db, ORG, {}, "2348030000001", _builder(), {}, "builder")
    assert db.rows("site_brief_forms") == []
    assert "free sites" in sent[0]


def test_send_form_link_works_for_a_subscriber(env, sent):
    db = _db([_site(i) for i in range(1, 6)])
    db.tables["site_brief_forms"] = []
    b = _builder(access_paid_until=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())
    chat._send_form_link(db, ORG, {}, "2348030000001", b, {}, "builder")
    assert len(db.rows("site_brief_forms")) == 1
    assert "/f/" in sent[0]
