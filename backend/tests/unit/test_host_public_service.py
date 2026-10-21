"""
tests/unit/test_host_public_service.py
HOST-2 - the public price table and domain check on /host. Numbers come from the pricing engine; costs and profit never leave.
"""
from __future__ import annotations

import pytest

from app.services import domain_check_service as dcs
from app.services import host_public_service as svc
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
PRICING = {
    "gateway": {"pct": 1.5, "flat_ngn": 100, "flat_waived_below_ngn": 2500, "cap_ngn": 2000}, "vat_pct": 7.5,
    "fx": {"usd_ngn": 0, "buffer_pct": 10}, "floors_after_fees": {"initial_ngn": 35000, "renewal_ngn": 20000},
    "service_fee": {"standard_ngn": 15000, "express_ngn": 25000}, "markup_pct": {"domain": 40, "hosting": 35}, "round_to_ngn": 500,
    "ai_msg_cost_estimate_ngn": {"initial": 400, "renewal": 100},
    "routes": {"standard": {"hosting_items": [
        {"name": "Starter hosting", "yearly_ngn": 18500, "vat": True}, {"name": "Advanced DNS Manager", "yearly_ngn": 500, "vat": True},
        {"name": "Website protection (AWPS)", "yearly_ngn": 1000, "vat": True}, {"name": "PositiveSSL", "yearly_ngn": 14200, "vat": True}],
        "domains": {".com.ng": {"first_ngn": 5500, "renew_ngn": 7000, "vat": True}, ".ng": {"first_ngn": 13500, "renew_ngn": 15000, "vat": True},
                    ".com": {"first_ngn": 12000, "renew_ngn": 20000, "vat": True}}}},
    "suggested_client_multiplier": {"initial": 1.9, "renewal": 1.3},
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    svc._cache.clear()
    dcs._rate_hits.clear()
    dcs._cache.clear()
    monkeypatch.delenv("PLATFORM_ORG_ID", raising=False)


def db(pricing=PRICING):
    return FakeDB(site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": pricing, "created_at": "2026-01-01"}])


class TestPricingTable:
    def test_matches_the_worked_example(self):
        t = svc.pricing_table(db())
        row = {r["tld"]: r for r in t["endings"]}[".com.ng"]
        assert row["first_year"] == {"domain": 11000.0, "hosting": 50000.0, "setup": 18500.0, "total": 79500.0}
        assert row["renewal"]["total"] == 65500.0 and row["renewal"]["domain"] == 11000.0
        assert [r["tld"] for r in t["endings"]] == [".ng", ".com", ".com.ng"]

    def test_includes_list_and_no_internal_figures(self):
        t = svc.pricing_table(db())
        assert t["includes"] == ["Starter hosting", "Advanced DNS Manager", "Website protection (AWPS)", "PositiveSSL"]
        text = repr(t).lower()
        assert "profit" not in text and "gateway" not in text and "cost" not in text and "suggested" not in text

    def test_first_year_lines_add_up(self):
        for r in svc.pricing_table(db())["endings"]:
            f = r["first_year"]
            assert f["domain"] + f["hosting"] + f["setup"] == pytest.approx(f["total"])

    def test_no_pricing_configured_gives_no_rows(self):
        t = svc.pricing_table(db({}))
        assert t["endings"] == []

    def test_no_organisation(self):
        with pytest.raises(svc.PublicHostError) as e:
            svc.pricing_table(FakeDB())
        assert e.value.status_code == 503


class TestDomainCheck:
    def test_free_domain_comes_with_its_price(self, monkeypatch):
        monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: True)
        out = svc.check(db(), "adaezestyles.com.ng", "1.2.3.4")
        assert out["status"] == "available" and out["confirmed"] is False
        assert out["price"]["first_year"]["total"] == 79500.0 and out["price"]["domain"] == "adaezestyles.com.ng"

    def test_taken_domain_gets_alternatives_and_no_price(self, monkeypatch):
        monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: d != "adaezestyles.ng")
        out = svc.check(db(), "adaezestyles.ng", "1.2.3.4")
        assert out["status"] == "taken" and "price" not in out
        assert out["alternatives"] and set(out["alternatives"][0]) == {"domain", "status", "available"}

    def test_lookup_trouble_is_unknown_not_an_error(self, monkeypatch):
        monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: None)
        out = svc.check(db(), "shop.com", "1.2.3.4")
        assert out["status"] == "unknown" and "price" not in out

    @pytest.mark.parametrize("bad", ["no-ending", "bad_name.com", "-x.com", "shop.xyz"])
    def test_bad_domains_are_422(self, bad):
        with pytest.raises(svc.PublicHostError) as e:
            svc.check(db(), bad, "1.2.3.4")
        assert e.value.status_code == 422

    def test_rate_limit_is_per_visitor(self, monkeypatch):
        monkeypatch.setattr(dcs, "_lookup_availability", lambda d, t: True)
        for i in range(20):
            svc.check(db(), f"name{i}.com", "9.9.9.9")
        with pytest.raises(svc.PublicHostError) as e:
            svc.check(db(), "another.com", "9.9.9.9")
        assert e.value.status_code == 429
        assert svc.check(db(), "another.com", "8.8.8.8")["status"] == "available"
