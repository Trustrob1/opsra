"""
tests/unit/test_site_catalog_service.py
GIVEAWAY-2 - the bigger-catalog pack: limits, growth check, checkout, payment.
"""
from __future__ import annotations

import pytest

from app.services import site_catalog_service as svc
from app.services import site_order_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"


def _db(max_items=30, extra=0, items=0):
    db = FakeDB(site_presets=[{"id": "pr1", "org_id": ORG, "max_items": max_items}],
                sites=[{"id": "s1", "org_id": ORG, "builder_id": "b1", "preset_id": "pr1", "extra_items": extra,
                        "client_business_name": "Zed", "content": {"items": [{"name": str(i)} for i in range(items)]}}],
                site_builder_settings=[], site_orders=[], payment_links=[], site_builders=[])
    return db


def _site(db):
    return db.rows("sites")[0]


def _content(n):
    return {"items": [{"name": str(i)} for i in range(n)]}


class TestLimits:
    def test_config_defaults_and_live_override(self):
        assert svc.get_config({}) == {"price_ngn": 5000, "items": 30}
        assert svc.get_config({"pricing": {"catalog_pack": {"price_ngn": 7000, "items": 10}}}) == {"price_ngn": 7000, "items": 10}
        assert svc.get_config({"pricing": {"catalog_pack": {"price_ngn": "x", "items": -1}}}) == {"price_ngn": 5000, "items": 30}

    def test_base_plus_extra_never_past_the_hard_maximum(self):
        assert svc.limits(_db(30, 0), ORG, _site(_db(30, 0)))["limit"] == 30
        d = _db(30, 30)
        assert svc.limits(d, ORG, _site(d))["limit"] == 60
        d = _db(40, 60)
        assert svc.limits(d, ORG, _site(d))["limit"] == 60

    def test_unknown_template_only_hits_the_hard_maximum(self):
        d = _db()
        d.tables["site_presets"].clear()
        assert svc.limits(d, ORG, _site(d))["limit"] == 60


class TestGrowth:
    def test_within_the_limit_is_fine(self):
        d = _db(30, 0, items=10)
        svc.check_growth(d, ORG, _site(d), _content(30))

    def test_adding_past_the_limit_is_refused_with_the_offer(self):
        d = _db(30, 0, items=30)
        with pytest.raises(svc.CatalogLimitReached) as x:
            svc.check_growth(d, ORG, _site(d), _content(31))
        o = x.value.offer
        assert o["limit"] == 30 and o["pack_items"] == 30 and o["pack_price"] == 5000 and o["can_buy"] is True
        assert "5,000" in str(x.value)

    def test_not_growing_is_always_allowed_even_when_already_over(self):
        d = _db(30, 0, items=45)
        svc.check_growth(d, ORG, _site(d), _content(45))
        svc.check_growth(d, ORG, _site(d), _content(40))

    def test_at_the_hard_maximum_there_is_nothing_to_buy(self):
        d = _db(30, 30, items=60)
        d.tables["sites"][0]["content"] = _content(60)
        assert svc.offer_for(d, ORG, _site(d))["can_buy"] is False

    def test_a_bought_pack_lets_the_site_grow(self):
        d = _db(30, 30, items=30)
        svc.check_growth(d, ORG, _site(d), _content(55))


class TestCheckoutAndPayment:
    BUILDER = {"id": "b1", "lead_id": "lead-1"}

    def _pay(self, monkeypatch, calls):
        from app.services import paystack_storefront_service as pay
        monkeypatch.setattr(pay, "generate_payment_link", lambda **k: calls.append(k) or
                            {"checkout_url": "https://pay.test/p", "reference": f"ref{len(calls)}", "payment_link_id": f"pl{len(calls)}"})

    def test_checkout_creates_a_catalog_pack_order(self, monkeypatch):
        d, calls = _db(), []
        self._pay(monkeypatch, calls)
        r = svc.create_checkout(d, ORG, self.BUILDER, "s1")
        assert r["amount"] == 5000 and r["items"] == 30 and r["reused"] is False and calls[0]["amount"] == 5000
        o = d.rows("site_orders")[0]
        assert o["kind"] == "catalog_pack" and o["quote"]["items"] == 30 and o["status"] == "pending_payment"

    def test_an_open_link_is_reused(self, monkeypatch):
        d, calls = _db(), []
        self._pay(monkeypatch, calls)
        svc.create_checkout(d, ORG, self.BUILDER, "s1")
        d.table("payment_links").insert({"id": "pl1", "org_id": ORG, "checkout_url": "https://pay.test/p"}).execute()
        again = svc.create_checkout(d, ORG, self.BUILDER, "s1")
        assert again["reused"] is True and len(calls) == 1

    def test_refused_at_the_maximum_and_for_other_builders_sites(self, monkeypatch):
        calls = []
        self._pay(monkeypatch, calls)
        d = _db(30, 30)
        with pytest.raises(svc.CatalogBlocked):
            svc.create_checkout(d, ORG, self.BUILDER, "s1")
        with pytest.raises(svc.CatalogNotFound):
            svc.create_checkout(_db(), ORG, {"id": "someone-else", "lead_id": "l"}, "s1")
        assert calls == []

    def test_payment_adds_the_items_once(self, monkeypatch):
        d, calls = _db(), []
        self._pay(monkeypatch, calls)
        svc.create_checkout(d, ORG, self.BUILDER, "s1")
        msgs = []
        monkeypatch.setattr(site_order_service, "_message_builder", lambda db, org, order, text: msgs.append(text))
        from app.services import funnel_service
        monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: None)
        ref = d.rows("site_orders")[0]["payment_reference"]
        assert site_order_service.on_payment_confirmed(d, ORG, ref) is True
        assert site_order_service.on_payment_confirmed(d, ORG, ref) is True          # a second webhook changes nothing
        assert _site(d)["extra_items"] == 30 and d.rows("site_orders")[0]["status"] == "live"
        assert len(msgs) == 1 and "30 more items" in msgs[0]
