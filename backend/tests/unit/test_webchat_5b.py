"""
tests/unit/test_webchat_5b.py
----------------------------
WEBCHAT-5b: what counts as a win (goals), order / paid / tap tracking, revenue, start counting from now.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import webchat_analytics_service as an
from app.services import webchat_service as wc
from tests.unit.test_webchat_3b import FakeDB, ORG, _cfg, _session, _shop_db  # reuse the shop fixtures

OTHER = "00000000-0000-0000-0000-0000000000bb"


def _now(d=0):
    return (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()


def _ev(kind, src="qr", org=ORG, d=0, value=None, ref=None):
    r = {"org_id": org, "kind": kind, "source": src, "created_at": _now(d), "session_id": "s"}
    if value is not None:
        r["value_kobo"] = value
    if ref:
        r["ref"] = ref
    return r


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch.object(wc, "rate_limited", return_value=False):
        yield


def _shop_cfg_db(**cfg):
    return FakeDB(organisations=[{"id": ORG, "name": "Shop", "webchat_config": {"enabled": True, **cfg}}], **{})


# ── goals ───────────────────────────────────────────────────────────────────

def test_auto_goals_follow_the_shop_switch():
    assert an.goals_for({}) == ["booking"]
    assert an.goals_for({"shop_enabled": True}) == ["booking", "order", "paid"]


def test_chosen_goals_win_over_auto_and_unknown_are_ignored():
    assert an.goals_for({"goals": ["paid", "nonsense", "tap"], "shop_enabled": True}) == ["paid", "tap"]


def test_sanitise_goals_keeps_known_keys_in_order_and_empty_means_auto():
    assert wc.sanitise_config({"goals": ["tap", "booking", "x"]})["goals"] == ["booking", "tap"]
    assert wc.sanitise_config({"goals": []})["goals"] is None
    assert wc.sanitise_config({"goals": "booking"})["goals"] is None


def test_stats_from_now_and_clear_and_bad_value():
    assert wc.sanitise_config({"stats_from": "now"})["stats_from"]
    assert wc.sanitise_config({"stats_from": ""})["stats_from"] is None
    assert wc.sanitise_config({"stats_from": "garbage"})["stats_from"] is None


# ── funnel follows goals ────────────────────────────────────────────────────

def _funnel_db(**cfg):
    return FakeDB(
        organisations=[{"id": ORG, "name": "Shop", "webchat_config": cfg}],
        webchat_events=[_ev("visit"), _ev("visit"), _ev("visit", "instagram"), _ev("started"), _ev("started", "instagram"),
                        _ev("contact"), _ev("order"), _ev("order", "instagram"), _ev("paid", value=1100000),
                        _ev("tap", "instagram"), _ev("redirect_sent"), _ev("visit", org=OTHER), _ev("paid", org=OTHER, value=5)],
    )


def test_shop_funnel_shows_orders_and_paid_not_booking():
    f = an.analytics(_funnel_db(shop_enabled=True), ORG, 30)["funnel"]
    keys = [s["key"] for s in f["steps"]]
    assert keys == ["visit", "started", "contact", "booking", "order", "paid"]
    by = {s["key"]: s for s in f["steps"]}
    assert by["order"]["count"] == 2 and by["paid"]["count"] == 1 and by["paid"]["rate"] == 50.0
    assert f["revenue_kobo"] == 1100000


def test_chosen_goals_drive_the_steps_and_source_revenue():
    f = an.analytics(_funnel_db(goals=["whatsapp", "tap", "paid"]), ORG, 30)["funnel"]
    assert [s["key"] for s in f["steps"]][3:] == ["paid", "whatsapp", "tap"]
    by = {s["key"]: s["count"] for s in f["steps"]}
    assert by["whatsapp"] == 1 and by["tap"] == 1
    qr = next(s for s in f["sources"] if s["source"] == "qr")
    assert qr["revenue_kobo"] == 1100000 and qr["paid"] == 1


def test_default_service_business_unchanged():
    out = an.analytics(_funnel_db(), ORG, 30)
    assert out["goals"] == ["booking"] and out["goals_auto"] is True
    assert out["funnel"]["rates"]["started_of_visit"] == 66.7


def test_start_counting_from_now_hides_older_events():
    db = FakeDB(organisations=[{"id": ORG, "name": "S", "webchat_config": {"stats_from": _now(1)}}],
                webchat_events=[_ev("visit", d=5), _ev("visit", d=3), _ev("visit", d=0)])
    out = an.analytics(db, ORG, 30)
    assert out["funnel"]["totals"]["visit"] == 1 and out["counting_from"]


def test_funnel_still_works_before_the_migration_adds_value_kobo():
    class Old(FakeDB):
        def table(self, name):
            q = super().table(name)
            if name == "webchat_events":
                orig = q.select
                q.select = lambda cols="*", *a, **k: (_ for _ in ()).throw(RuntimeError("no column")) if "value_kobo" in cols else orig(cols)
            return q
    db = Old(organisations=[{"id": ORG, "name": "S", "webchat_config": {}}], webchat_events=[_ev("visit"), _ev("started")])
    assert an.analytics(db, ORG, 30)["funnel"]["totals"]["started"] == 1


# ── paid tracking ───────────────────────────────────────────────────────────

def _paid_db():
    return FakeDB(webchat_events=[_ev("order", "instagram", ref="opsra_x")],
                  payment_links=[{"org_id": ORG, "reference": "opsra_x", "amount": 11000}])


def test_payment_confirmed_records_paid_once_with_source_and_amount():
    db = _paid_db()
    assert wc.on_payment_confirmed(db, ORG, "opsra_x") is True
    paid = [r for r in db.rows("webchat_events") if r["kind"] == "paid"]
    assert len(paid) == 1 and paid[0]["source"] == "instagram" and paid[0]["value_kobo"] == 1100000
    assert wc.on_payment_confirmed(db, ORG, "opsra_x") is False          # webhook retry
    assert len([r for r in db.rows("webchat_events") if r["kind"] == "paid"]) == 1


def test_payment_for_something_else_is_ignored_and_other_org_cannot_match():
    db = _paid_db()
    assert wc.on_payment_confirmed(db, ORG, "opsra_other") is False
    assert wc.on_payment_confirmed(db, OTHER, "opsra_x") is False
    assert wc.on_payment_confirmed(db, ORG, "") is False
    assert not [r for r in db.rows("webchat_events") if r["kind"] == "paid"]


def test_payment_hook_never_raises():
    class Boom(FakeDB):
        def table(self, name): raise RuntimeError("down")
    assert wc.on_payment_confirmed(Boom(), ORG, "x") is False


# ── checkout logs the order with the payment reference ──────────────────────

def test_checkout_logs_order_with_reference():
    from app.services import webchat_shop_service as shop
    db = _shop_db(); s = _session(db)
    shop.add(db, s, "p1", None)
    with patch("app.services.paystack_storefront_service.generate_payment_link",
               return_value={"checkout_url": "https://p.test/x", "reference": "opsra_abc", "payment_link_id": "pl"}), \
         patch("app.services.lead_service.write_timeline_event"), patch("app.services.webchat_service.notify_managers"):
        shop.checkout(db, s, _cfg(db))
    ev = [r for r in db.rows("webchat_events") if r["kind"] == "order"]
    assert len(ev) == 1 and ev[0]["ref"] == "opsra_abc" and s["state"]["last_checkout"]["reference"] == "opsra_abc"


def test_checkout_without_paystack_still_counts_as_an_order():
    from app.services import webchat_shop_service as shop
    db = _shop_db(); s = _session(db)
    shop.add(db, s, "p1", None)
    with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=RuntimeError("no keys")), \
         patch("app.services.webchat_service.notify_managers"), patch("app.services.lead_service.write_timeline_event"):
        shop.checkout(db, s, _cfg(db))
    assert len([r for r in db.rows("webchat_events") if r["kind"] == "order"]) == 1


# ── link tap ────────────────────────────────────────────────────────────────

def test_tap_counts_once_per_chat():
    from app.routers import public_webchat as pw
    db = _shop_db(); s = _session(db)
    with patch.object(pw, "_chat", return_value={"org_id": ORG, "config": {}}), patch.object(pw, "_session", return_value=s):
        from fastapi import Response
        first = pw.tap("k", Response(), None, db)
        second = pw.tap("k", Response(), None, db)
    assert first.data["counted"] is True and second.data["counted"] is False
    assert len([r for r in db.rows("webchat_events") if r["kind"] == "tap"]) == 1


def test_log_event_only_sends_new_columns_when_used():
    db = FakeDB()
    wc.log_event(db, ORG, "s", "visit", "qr")
    wc.log_event(db, ORG, "s", "paid", "qr", ref="r1", value_kobo=500)
    a, b = db.rows("webchat_events")
    assert "ref" not in a and "value_kobo" not in a and b["ref"] == "r1" and b["value_kobo"] == 500
