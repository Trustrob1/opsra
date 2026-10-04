"""SITE-PREMIUM P5: Premium fees, pay-first generation, go-live balance, retry, refund and paid redesign credits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import funnel_service, paystack_storefront_service as pay, pricing_service
from app.services import site_ops_service as ops
from app.services import site_order_service as orders
from app.services import site_premium_billing_service as bill
from app.services import site_premium_generation_service as gen
from app.services import site_premium_history as hist
from app.services import whatsapp_service
from app.services.site_ops_service import ValidationFailed
from tests.funnel_fake_db import FakeDB
from tests.unit.premium_gen_fixtures import ScriptedClaude, good_art_reply, good_build_reply
from tests.unit.test_site_premium_generation import CONTENT, ORG, _row

NOW = datetime.now(timezone.utc)
BUILDER = {"id": "b-1", "org_id": ORG, "lead_id": "lead-1", "phone_number": "2348030000001"}


def make_db(premium=True, pricing=None, **site_over):
    site = {"id": "site-1", "org_id": ORG, "builder_id": "b-1", "preset_id": "p1", "client_business_name": "Adaeze",
            "slug": "adaeze-1", "status": "preview_ready", "tier": "standard", "current_design_id": None,
            "deleted_at": None, "content": CONTENT, "brief": {}, "recipe": {}}
    settings = {"org_id": ORG, "enabled": True, "premium_enabled": premium}
    for key in [k for k in site_over if k.startswith("site_premium_")]:        # settings keys, not site columns
        settings[key] = site_over.pop(key)
    site.update(site_over)
    if pricing is not None:
        settings["pricing"] = pricing
    return FakeDB(
        site_builder_settings=[settings], sites=[site], site_presets=[{"id": "p1", "org_id": ORG, "key": "boutique"}],
        site_designs=[], site_events=[], site_assets=[], site_orders=[], payment_links=[], tasks=[],
        site_builders=[{"id": "b-1", "org_id": ORG, "phone_number": "2348030000001"}])


def site(db):
    return db.rows("sites")[0]


def order(db, kind=bill.KIND_DESIGN, status="live", amount=20000, **over):
    o = {"id": f"o{len(db.rows('site_orders')) + 1}", "org_id": ORG, "site_id": "site-1", "builder_id": "b-1", "lead_id": "lead-1",
         "kind": kind, "status": status, "amount": amount, "payment_reference": "ref-1",
         "created_at": (NOW - timedelta(minutes=30)).isoformat()}
    o.update(over)
    db.tables["site_orders"].append(o)
    return o


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_service, "send_agent_text_message", lambda **k: sent.append(k["message"]))
    monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: sent.append(("mgr", a[2])))
    monkeypatch.setattr(pay, "generate_payment_link", lambda **k: {
        "checkout_url": f"https://paystack.test/{k['amount']}", "reference": f"ref-{k['amount']}", "payment_link_id": "pl-1"})
    return sent


class TestConfig:
    def test_defaults_are_20000_30000_30000(self):
        assert bill.get_config({}) == {"design_fee_ngn": 20000, "total_fee_ngn": 30000, "redesign_fee_ngn": 30000}

    def test_prices_come_from_settings(self):
        cfg = bill.get_config({"pricing": {"premium": {"design_fee_ngn": 15000, "total_fee_ngn": "40000", "redesign_fee_ngn": 0}}})
        assert cfg == {"design_fee_ngn": 15000, "total_fee_ngn": 40000, "redesign_fee_ngn": 0}

    def test_bad_values_fall_back_and_the_total_is_never_below_the_first_part(self):
        cfg = bill.get_config({"pricing": {"premium": {"design_fee_ngn": 50000, "total_fee_ngn": "x", "redesign_fee_ngn": -5}}})
        assert cfg["design_fee_ngn"] == 50000 and cfg["total_fee_ngn"] == 50000 and cfg["redesign_fee_ngn"] == 30000


class TestOffer:
    def test_not_available_when_premium_is_off_or_free_priced(self):
        assert not bill.offer(make_db(premium=False), ORG, site(make_db(premium=False)))["available"]
        db = make_db(pricing={"premium": {"design_fee_ngn": 0}})
        assert not bill.offer(db, ORG, site(db))["available"]

    def test_premium_live_and_empty_sites_are_not_offered(self):
        db = make_db(tier="premium")
        assert bill.offer(db, ORG, site(db))["state"] == "premium"
        db = make_db(status="live")
        assert bill.offer(db, ORG, site(db))["state"] == "live"
        db = make_db(content={})
        assert bill.offer(db, ORG, site(db))["state"] == "no_content"

    def test_can_buy_shows_the_fee_the_total_and_the_go_live_balance(self):
        db = make_db()
        v = bill.offer(db, ORG, site(db))
        assert (v["available"], v["state"], v["design_fee"], v["total"], v["golive_balance"]) == (True, "can_buy", 20000, 30000, 10000)

    def test_an_open_payment_link_is_shown_again(self):
        db = make_db()
        db.tables["payment_links"].append({"id": "pl-9", "org_id": ORG, "checkout_url": "https://paystack.test/x"})
        order(db, status="pending_payment", payment_link_id="pl-9")
        v = bill.offer(db, ORG, site(db))
        assert v["state"] == "awaiting_payment" and v["checkout_url"] == "https://paystack.test/x"

    def test_paid_and_being_made(self):
        db = make_db()
        order(db)
        _row(db, id="d1", version=1, status="generating")
        assert bill.offer(db, ORG, site(db))["state"] == "designing"

    def test_paid_and_failed_shows_tries_left_and_the_refund_option(self):
        db = make_db()
        order(db)
        _row(db, id="d1", version=1, status="failed", checks={"stage": "build"})
        v = bill.offer(db, ORG, site(db))
        assert v["state"] == "failed" and v["attempts"] == 1 and v["retries_left"] == 2 and v["can_retry"] and v["can_refund"]
        assert v["refund_amount"] == 20000

    def test_a_refund_in_progress_is_shown(self):
        db = make_db()
        order(db, status="refund_pending", refund_amount=20000)
        assert bill.offer(db, ORG, site(db))["state"] == "refund_pending"


class TestCheckout:
    def test_the_design_fee_is_charged_from_settings(self):
        db = make_db(pricing={"premium": {"design_fee_ngn": 18000}})
        out = bill.create_checkout(db, ORG, BUILDER, "site-1", "design")
        assert out["amount"] == 18000 and out["kind"] == bill.KIND_DESIGN and not out["reused"]
        row = db.rows("site_orders")[0]
        assert row["status"] == "pending_payment" and row["amount"] == 18000 and row["site_id"] == "site-1"

    def test_an_open_link_for_the_same_price_is_reused(self):
        db = make_db()
        first = bill.create_checkout(db, ORG, BUILDER, "site-1", "design")
        db.tables["payment_links"].append({"id": "pl-1", "org_id": ORG, "checkout_url": first["checkout_url"]})
        again = bill.create_checkout(db, ORG, BUILDER, "site-1", "design")
        assert again["reused"] and len(db.rows("site_orders")) == 1

    def test_it_is_refused_after_go_live_for_premium_sites_and_when_already_paid(self):
        for over in ({"status": "live"}, {"tier": "premium"}):
            db = make_db(**over)
            with pytest.raises(bill.PremiumBillingBlocked):
                bill.create_checkout(db, ORG, BUILDER, "site-1", "design")
        db = make_db()
        order(db)
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.create_checkout(db, ORG, BUILDER, "site-1", "design")

    def test_another_builders_site_is_not_found(self):
        db = make_db()
        with pytest.raises(ops.NotFound):
            bill.create_checkout(db, ORG, {**BUILDER, "id": "b-2"}, "site-1", "design")

    def test_no_crm_lead_means_no_link(self):
        db = make_db()
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.create_checkout(db, ORG, {**BUILDER, "lead_id": None}, "site-1", "design")

    def test_unknown_purchase_is_refused(self):
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.create_checkout(make_db(), ORG, BUILDER, "site-1", "everything")

    def test_a_redesign_can_not_be_bought_while_a_free_one_remains(self):
        db = make_db(tier="premium", current_design_id="d1")
        _row(db, id="d1", version=1)
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.create_checkout(db, ORG, BUILDER, "site-1", "redesign")

    def test_after_go_live_a_redesign_costs_the_setting(self):
        db = make_db(tier="premium", current_design_id="d1", status="live", pricing={"premium": {"redesign_fee_ngn": 25000}})
        _row(db, id="d1", version=1)
        out = bill.create_checkout(db, ORG, BUILDER, "site-1", "redesign")
        assert out["amount"] == 25000 and out["kind"] == bill.KIND_REDESIGN

    def test_a_standard_site_cannot_buy_a_redesign(self):
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.create_checkout(make_db(), ORG, BUILDER, "site-1", "redesign")


class TestPaymentStartsTheDesign:
    def _pay(self, db, o):
        with patch("app.workers.site_premium_worker.run_premium_generation") as task:
            assert orders.on_payment_confirmed(db, ORG, o["payment_reference"], now=NOW) is True
        return task

    def test_payment_marks_the_order_paid_and_queues_a_design(self, quiet):
        db = make_db()
        o = order(db, status="pending_payment")
        task = self._pay(db, o)
        assert db.rows("site_orders")[0]["status"] == "live"
        d = db.rows("site_designs")[0]
        assert d["kind"] == "generate" and d["status"] == "generating" and d["created_by"] == "builder:b-1"
        task.apply_async.assert_called_once()
        assert any("being made now" in m for m in quiet if isinstance(m, str))

    def test_a_second_webhook_does_not_start_a_second_design(self):
        db = make_db()
        o = order(db, status="pending_payment")
        self._pay(db, o)
        self._pay(db, o)
        assert len(db.rows("site_designs")) == 1

    def test_a_design_that_cannot_start_tells_staff_and_keeps_the_payment(self, quiet):
        db = make_db(premium=False)
        o = order(db, status="pending_payment")
        self._pay(db, o)
        assert db.rows("site_orders")[0]["status"] == "live" and not db.rows("site_designs")
        assert ("mgr", "Premium design paid but not started") in quiet
        assert "premium_start_failed" in [e["event"] for e in db.rows("site_events")]

    def test_a_down_queue_marks_the_attempt_as_ours_not_the_builders(self):
        db = make_db()
        o = order(db, status="pending_payment")
        with patch("app.workers.site_premium_worker.run_premium_generation") as task:
            task.apply_async.side_effect = RuntimeError("redis down")
            orders.on_payment_confirmed(db, ORG, o["payment_reference"], now=NOW)
        d = db.rows("site_designs")[0]
        assert d["status"] == "failed" and d["checks"]["stage"] == "service"
        assert bill.failed_attempts(db, ORG, "site-1", None) == 0

    def test_a_paid_redesign_adds_a_credit_and_starts_nothing(self):
        db = make_db(tier="premium", current_design_id="d1", status="live")
        _row(db, id="d1", version=1)
        o = order(db, kind=bill.KIND_REDESIGN, status="pending_payment", amount=30000)
        self._pay(db, o)
        assert not [r for r in db.rows("site_designs") if r["id"] != "d1"]
        assert bill.redesign_credits(db, ORG, "site-1")["available"] == 1


class TestGoLiveBalance:
    def test_the_balance_is_the_total_minus_the_fee_already_paid(self):
        db = make_db()
        order(db)
        assert bill.go_live_balance(db, ORG, "site-1") == {"balance": 10000, "paid": 20000, "total": 30000}

    def test_no_prepaid_fee_means_no_balance(self):
        db = make_db(tier="premium")
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 0

    def test_a_refunded_fee_leaves_no_balance(self):
        db = make_db()
        order(db, status="refunded")
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 0

    def test_the_total_is_a_setting(self):
        db = make_db(pricing={"premium": {"total_fee_ngn": 45000}})
        order(db)
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 25000

    def test_the_go_live_order_includes_the_balance(self, monkeypatch):
        db = make_db(tier="premium")
        order(db)
        quote = {"route": "standard", "kind": "initial", "domain": "adaeza.com.ng", "tld": ".com.ng", "cost": {"total": 1000},
                 "price": {"domain": 1, "hosting": 1, "service_fee": 1, "total": 79500}, "profit": 5000, "gateway_fee": 10}
        monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: quote)
        monkeypatch.setattr(pricing_service, "get_settings", lambda db, org: {"approval_required": False})
        seen = {}
        monkeypatch.setattr(pay, "generate_payment_link", lambda **k: seen.update(k) or {"checkout_url": "u", "reference": "ref-go", "payment_link_id": "p"})
        from app.services import lead_service
        monkeypatch.setattr(lead_service, "move_stage", lambda **k: {})
        payload = SimpleNamespace(site_id="site-1", route="standard", domain="adaeza.com.ng", backup_domain="adaeza.ng", discount_code=None,
                                  legal_owner=SimpleNamespace(model_dump=lambda mode="json": {"full_name": "A"}))
        out = orders.create_checkout(db, ORG, BUILDER, payload)
        assert out["amount"] == 89500 and seen["amount"] == 89500
        row = [o for o in db.rows("site_orders") if o["kind"] == "initial"][0]
        assert row["amount"] == 89500 and row["quote"]["premium"]["balance"] == 10000

    def test_a_prepaid_premium_fee_is_not_their_first_site_order(self, monkeypatch):
        db = make_db(tier="premium")
        order(db)
        moved = []
        quote = {"route": "standard", "kind": "initial", "domain": "a.com.ng", "tld": ".com.ng", "cost": {"total": 1},
                 "price": {"total": 100}, "profit": 5}
        monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: quote)
        monkeypatch.setattr(pricing_service, "get_settings", lambda db, org: {})
        from app.services import lead_service
        monkeypatch.setattr(lead_service, "move_stage", lambda **k: moved.append(k) or {})
        payload = SimpleNamespace(site_id="site-1", route="standard", domain="a.com.ng", backup_domain="b.ng", discount_code=None,
                                  legal_owner=SimpleNamespace(model_dump=lambda mode="json": {}))
        orders.create_checkout(db, ORG, BUILDER, payload)
        assert moved and moved[0]["new_stage"] == "proposal_sent"


class TestRetryAndRefund:
    def _paid_failed(self, n=1, stage="build", **site_over):
        db = make_db(**site_over)
        order(db)
        for i in range(n):
            _row(db, id=f"d{i + 1}", version=i + 1, status="failed", checks={"stage": stage})
        return db

    def test_retry_is_free_and_starts_a_new_attempt(self):
        db = self._paid_failed(1)
        with patch("app.workers.site_premium_worker.run_premium_generation") as task:
            bill.retry(db, ORG, BUILDER, "site-1")
        assert db.rows("site_designs")[-1]["status"] == "generating" and task.apply_async.called
        assert len(db.rows("site_orders")) == 1                                   # no new charge

    def test_retry_stops_after_three_failed_attempts(self):
        db = self._paid_failed(3)
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.retry(db, ORG, BUILDER, "site-1")

    def test_failures_on_our_side_never_use_up_the_attempts(self):
        db = self._paid_failed(5, stage="service")
        assert bill.offer(db, ORG, site(db))["attempts"] == 0
        with patch("app.workers.site_premium_worker.run_premium_generation"):
            bill.retry(db, ORG, BUILDER, "site-1")

    def test_retry_needs_a_paid_fee(self):
        db = make_db()
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.retry(db, ORG, BUILDER, "site-1")

    def test_asking_for_the_money_back_opens_a_refund_task_for_staff(self, quiet):
        db = self._paid_failed(1)
        bill.request_refund(db, ORG, BUILDER, "site-1")
        o = db.rows("site_orders")[0]
        assert o["status"] == "refund_pending" and o["refund_amount"] == 20000
        t = db.rows("tasks")[0]
        assert t["task_type"] == "refund" and t["source_record_id"] == o["id"] and "ref-1" in t["description"]
        assert any("refund of ₦20,000" in m for m in quiet if isinstance(m, str))
        assert bill.offer(db, ORG, site(db))["state"] == "refund_pending"

    def test_staff_can_record_the_refund_with_the_existing_button(self):
        db = self._paid_failed(1)
        bill.request_refund(db, ORG, BUILDER, "site-1")
        out = ops.record_refund(db, ORG, db.rows("site_orders")[0]["id"], "u1")
        assert out["status"] == "refunded" and out["refund_amount"] == 20000

    def test_a_refund_is_refused_once_a_design_was_made(self):
        db = make_db()
        order(db)
        _row(db, id="d1", version=1, status="ready", staged=True)
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.request_refund(db, ORG, BUILDER, "site-1")

    def test_a_refund_is_refused_while_a_design_is_being_made_and_twice(self):
        db = make_db()
        order(db)
        _row(db, id="d1", version=1, status="generating")
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.request_refund(db, ORG, BUILDER, "site-1")
        db = self._paid_failed(1)
        bill.request_refund(db, ORG, BUILDER, "site-1")
        with pytest.raises(bill.PremiumBillingBlocked):
            bill.request_refund(db, ORG, BUILDER, "site-1")

    def test_the_third_failed_attempt_opens_the_refund_by_itself(self):
        db = make_db()
        order(db)
        for i in range(2):
            _row(db, id=f"d{i + 1}", version=i + 1, status="failed", checks={"stage": "build"})
        row = gen.start_generation(db, ORG, site(db), "builder:b-1")
        with patch("app.services.funnel_service._get_manager_ids", return_value=[]):
            gen.run_generation(db, row["id"], claude=ScriptedClaude("nope", "nope"))
        assert db.rows("site_orders")[0]["status"] == "refund_pending"
        assert db.rows("tasks")

    def test_the_first_failure_does_not_refund(self):
        db = make_db()
        order(db)
        row = gen.start_generation(db, ORG, site(db), "builder:b-1")
        gen.run_generation(db, row["id"], claude=ScriptedClaude("nope", "nope"))
        assert db.rows("site_orders")[0]["status"] == "live"

    def test_a_service_failure_never_refunds_by_itself(self):
        db = make_db()
        order(db)
        for i in range(4):
            _row(db, id=f"d{i + 1}", version=i + 1, status="failed", checks={"stage": "service"})
        bill.after_failure(db, ORG, {"kind": "generate", "site_id": "site-1", "checks": {"stage": "service"}})
        assert db.rows("site_orders")[0]["status"] == "live"


class TestPaidRedesignCredits:
    def live_premium(self, **settings):
        db = make_db(tier="premium", current_design_id="d1", status="live", **settings)
        _row(db, id="d1", version=1, kind="generate", art_direction={"fingerprint": {"accent_family": "blue"}})
        return db

    def test_after_go_live_a_redesign_is_blocked_and_buyable(self):
        db = self.live_premium()
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and s["can_buy"] and s["price"] == 30000 and "paid add-on" in s["blocked_reason"] and "30,000" in s["blocked_reason"]

    def test_a_paid_credit_allows_one_redesign_and_is_marked_when_used(self):
        db = self.live_premium()
        order(db, kind=bill.KIND_REDESIGN, amount=30000)
        assert hist.redesign_status(db, ORG, site(db))["allowed"]
        row = hist.start_redesign(db, ORG, site(db), "builder:b-1")
        with patch("app.routers.sites._render_and_store"):
            gen.run_generation(db, row["id"], claude=ScriptedClaude(good_art_reply(), good_build_reply()))
        used = [e for e in db.rows("site_events") if e["event"] == hist.USED_EVENT]
        assert used and used[0]["detail"]["paid_credit"] is True
        s = hist.redesign_status(db, ORG, site(db))
        assert bill.redesign_credits(db, ORG, "site-1")["available"] == 0
        db.tables["site_designs"] = [r for r in db.rows("site_designs") if r["id"] == "d1"]      # the held-back one is dealt with
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and s["can_buy"]

    def test_a_free_included_redesign_before_go_live_is_not_marked_paid(self):
        db = make_db(tier="premium", current_design_id="d1")
        _row(db, id="d1", version=1, art_direction={"fingerprint": {}})
        order(db, kind=bill.KIND_REDESIGN, amount=30000)           # a credit exists, but a free one is used first
        row = hist.start_redesign(db, ORG, site(db), "builder:b-1")
        with patch("app.routers.sites._render_and_store"):
            gen.run_generation(db, row["id"], claude=ScriptedClaude(good_art_reply(), good_build_reply()))
        used = [e for e in db.rows("site_events") if e["event"] == hist.USED_EVENT]
        assert used[0]["detail"]["paid_credit"] is False
        assert hist.redesign_status(db, ORG, site(db))["used"] == 1 and bill.redesign_credits(db, ORG, "site-1")["available"] == 1

    def test_once_the_free_ones_are_used_a_new_one_can_be_bought_before_go_live(self):
        db = make_db(tier="premium", current_design_id="d1", site_premium_redesigns_included=0)
        _row(db, id="d1", version=1)
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and s["can_buy"] and "buy another" in s["blocked_reason"]

    def test_a_zero_price_means_it_cannot_be_bought(self):
        db = self.live_premium(pricing={"premium": {"redesign_fee_ngn": 0}})
        s = hist.redesign_status(db, ORG, site(db))
        assert not s["allowed"] and not s["can_buy"]

    def test_the_staff_switch_still_allows_it_free(self):
        db = self.live_premium(site_premium_post_live_redesign=True)
        assert hist.redesign_status(db, ORG, site(db))["allowed"]


class TestChargeAtGoLive:
    """A Premium site made before payment existed is free by default; staff can switch the whole price on for it."""

    def test_off_by_default_so_an_old_premium_site_owes_nothing(self):
        db = make_db(tier="premium")
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 0

    def test_switched_on_the_whole_price_is_owed(self):
        db = make_db(tier="premium")
        out = bill.set_charge_at_golive(db, ORG, site(db), True, "user:u1")
        assert out == {"charge_at_golive": True, "balance": 30000, "paid": 0, "total": 30000}
        assert site(db)["premium_charge_at_golive"] is True
        assert "premium_charge_at_golive_on" in [e["event"] for e in db.rows("site_events")]

    def test_the_price_follows_the_setting(self):
        db = make_db(tier="premium", pricing={"premium": {"total_fee_ngn": 45000}})
        assert bill.set_charge_at_golive(db, ORG, site(db), True, "u")["balance"] == 45000

    def test_switching_it_off_again_charges_nothing(self):
        db = make_db(tier="premium")
        bill.set_charge_at_golive(db, ORG, site(db), True, "u")
        assert bill.set_charge_at_golive(db, ORG, site(db), False, "u")["balance"] == 0

    def test_a_standard_site_cannot_be_switched_on(self):
        db = make_db()
        with pytest.raises(ValidationFailed):
            bill.set_charge_at_golive(db, ORG, site(db), True, "u")

    def test_a_site_that_paid_the_fee_does_not_need_the_switch(self):
        db = make_db(tier="premium")
        order(db)
        with pytest.raises(ValidationFailed):
            bill.set_charge_at_golive(db, ORG, site(db), True, "u")
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 10000

    def test_a_site_sent_back_to_standard_is_not_charged(self):
        db = make_db(tier="premium")
        bill.set_charge_at_golive(db, ORG, site(db), True, "u")
        db.tables["sites"][0]["tier"] = "standard"
        assert bill.go_live_balance(db, ORG, "site-1")["balance"] == 0

    def test_the_go_live_order_carries_the_whole_price(self, monkeypatch):
        db = make_db(tier="premium")
        bill.set_charge_at_golive(db, ORG, site(db), True, "u")
        quote = {"route": "standard", "kind": "initial", "domain": "a.com.ng", "tld": ".com.ng", "cost": {"total": 1},
                 "price": {"total": 79500}, "profit": 5}
        monkeypatch.setattr(pricing_service, "quote", lambda *a, **k: quote)
        monkeypatch.setattr(pricing_service, "get_settings", lambda db, org: {})
        monkeypatch.setattr(pay, "generate_payment_link", lambda **k: {"checkout_url": "u", "reference": "r", "payment_link_id": "p"})
        from app.services import lead_service
        monkeypatch.setattr(lead_service, "move_stage", lambda **k: {})
        payload = SimpleNamespace(site_id="site-1", route="standard", domain="a.com.ng", backup_domain="b.ng", discount_code=None,
                                  legal_owner=SimpleNamespace(model_dump=lambda mode="json": {}))
        assert orders.create_checkout(db, ORG, BUILDER, payload)["amount"] == 109500
