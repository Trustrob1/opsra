"""
tests/unit/test_own_domain.py
HOST-3b - hosting for a domain the client already owns elsewhere: the hosting-only price, the checkout that skips the
backup domain and legal owner, the staff checklist that has no registration step, and renewal pricing.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.models.sites import CheckoutRequest
from app.services import site_order_service as svc
from app.services import pricing_service as ps
from app.services import paystack_storefront_service as pay_svc
from app.services import lead_service as lead_svc

ORG, SITE = "org-1", "site-1"
BUILDER = {"id": "b-1", "org_id": ORG, "lead_id": "lead-1"}
SETTINGS = {
    "pricing": {
        "gateway": {"pct": 1.5, "flat_ngn": 100, "flat_waived_below_ngn": 2500, "cap_ngn": 2000},
        "vat_pct": 7.5, "floors_after_fees": {"initial_ngn": 5000, "renewal_ngn": 5000},
        "ai_msg_cost_estimate_ngn": {"initial": 400, "renewal": 100},
        "routes": {"standard": {
            "hosting_items": [{"name": "Starter hosting", "yearly_ngn": 18500, "vat": True}],
            "domains": {".com.ng": {"first_ngn": 5500, "renew_ngn": 7000, "vat": True}},
            "own_domain_totals_ngn": {"initial": 25500, "renewal": 31500}}},
    }
}


def _chain(data=None):
    result = MagicMock()
    result.data = data if data is not None else []
    m = MagicMock()
    for method in ("select", "insert", "update", "delete", "eq", "neq", "is_", "order", "range", "limit",
                   "maybe_single", "filter", "in_", "not_"):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db(**tables):
    db = MagicMock()
    db.table.side_effect = lambda name: tables.get(name, _chain())
    return db


class _Owner:
    def model_dump(self, mode="json"):
        return {}


class _Payload:
    def __init__(self, route="standard", own_domain=True):
        self.site_id, self.route, self.domain = SITE, route, "Brand.ORG"
        self.own_domain, self.backup_domain, self.legal_owner = own_domain, None, None
        self.accepted_terms = True


# ----- pricing ---------------------------------------------------------------

@pytest.mark.parametrize("domain", ["brand.com", "brand.org", "brand.co.za", "x.com.ng"])
def test_one_hosting_only_price_for_any_ending(domain):
    a = ps.quote_own_domain(None, ORG, domain, "initial", settings=SETTINGS)
    b = ps.quote_own_domain(None, ORG, domain, "renewal", settings=SETTINGS)
    assert a["price"]["total"] == 25500 and b["price"]["total"] == 31500
    assert a["price"]["domain"] == 0 and a["price"]["hosting"] == 25500 and a["cost"]["domain"] == 0
    assert a["own_domain"] is True and a["price"]["service_fee"] == 0


def test_not_priced_yet_raises():
    s = {"pricing": {"routes": {"standard": {"hosting_items": []}}}}
    with pytest.raises(ps.PricingError):
        ps.quote_own_domain(None, ORG, "brand.com", "initial", settings=s)


def test_bad_domain_raises():
    with pytest.raises(ps.PricingError):
        ps.quote_own_domain(None, ORG, "not a domain", "initial", settings=SETTINGS)


def test_quote_both_routes_own_domain_returns_one_route():
    out = ps.quote_both_routes(None, ORG, "brand.com", "initial", settings=SETTINGS, own_domain=True)
    assert out["standard"]["price"]["total"] == 25500 and out["express"] is None


def test_quote_renewal_picks_the_right_quote():
    assert ps.quote_renewal(None, ORG, "brand.com", "standard", True, settings=SETTINGS)["price"]["total"] == 31500
    assert ps.quote_renewal(None, ORG, "brand.com.ng", "standard", False, settings=SETTINGS)["kind"] == "renewal"


# ----- request model -----------------------------------------------------------

def test_own_domain_checkout_needs_no_backup_or_legal_owner():
    r = CheckoutRequest(site_id="s", route="standard", domain="brand.com", own_domain=True, accepted_terms=True)
    assert r.backup_domain is None and r.legal_owner is None


def test_normal_checkout_still_needs_backup_and_legal_owner():
    with pytest.raises(ValidationError):
        CheckoutRequest(site_id="s", route="standard", domain="brand.com", accepted_terms=True)


# ----- checkout ----------------------------------------------------------------

def _wire(monkeypatch):
    monkeypatch.setattr(ps, "get_settings", lambda db, org: SETTINGS)
    monkeypatch.setattr(pay_svc, "generate_payment_link", lambda **k: {
        "checkout_url": "https://pay.test/x", "reference": "ref", "payment_link_id": "pl"})
    monkeypatch.setattr(lead_svc, "move_stage", lambda **k: {})


def test_checkout_creates_hosting_only_order(monkeypatch):
    _wire(monkeypatch)
    db = _db(sites=_chain([{"id": SITE, "org_id": ORG, "builder_id": "b-1"}]), site_orders=_chain([]), site_domains=_chain([]))
    out = svc.create_checkout(db, ORG, BUILDER, _Payload())
    assert out["amount"] == 25500
    row = db.table("site_orders").insert.call_args[0][0]
    assert row["domain"] == "brand.org" and row["backup_domain"] is None and row["legal_owner"] is None
    assert row["quote"]["own_domain"] is True and row["quote"]["price"]["domain"] == 0


def test_checkout_own_domain_must_use_standard_route(monkeypatch):
    _wire(monkeypatch)
    db = _db(sites=_chain([{"id": SITE, "org_id": ORG, "builder_id": "b-1"}]), site_orders=_chain([]))
    with pytest.raises(svc.CheckoutBlocked):
        svc.create_checkout(db, ORG, BUILDER, _Payload(route="express"))


def test_checkout_blocks_domain_hosted_on_another_site(monkeypatch):
    _wire(monkeypatch)
    db = _db(sites=_chain([{"id": SITE, "org_id": ORG, "builder_id": "b-1"}]), site_orders=_chain([]),
             site_domains=_chain([{"site_id": "other-site"}]))
    with pytest.raises(svc.CheckoutBlocked):
        svc.create_checkout(db, ORG, BUILDER, _Payload())


# ----- staff job ---------------------------------------------------------------

def _job_keys(order):
    db = _db(site_hosting_jobs=_chain([]), site_orders=_chain([]))
    svc.create_hosting_job(db, ORG, order)
    return [i["key"] for i in db.table("site_hosting_jobs").insert.call_args[0][0]["checklist"]]


def test_own_domain_job_has_no_registration_step():
    keys = _job_keys({"id": "o1", "site_id": SITE, "domain": "brand.com", "kind": "initial", "quote": {"own_domain": True}})
    assert "register_domain" not in keys and "recheck_domain" not in keys and "publish_site" in keys and "mark_live" in keys


def test_normal_job_keeps_registration_steps():
    keys = _job_keys({"id": "o2", "site_id": SITE, "domain": "brand.com.ng", "kind": "initial", "quote": {}})
    assert "register_domain" in keys


def test_own_domain_renewal_job_skips_domain_renewal():
    keys = _job_keys({"id": "o3", "site_id": SITE, "domain": "brand.com", "kind": "renewal", "quote": {"own_domain": True}})
    assert keys == ["renew_hosting", "confirm_site"]
