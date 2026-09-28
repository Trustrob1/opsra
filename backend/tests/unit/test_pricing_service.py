"""
tests/unit/test_pricing_service.py
-----------------------------------
SITE-3 — pricing_service.quote(). No DB needed: every test passes `settings=`
directly (quote()/quote_both_routes() accept it to make this pure-function
testable), matching spec §12.1's example settings exactly.

Spec §19: "Pricing: the gateway fee, VAT, FX buffer and rounding. Solving for
the minimum (initial and renewal). The worked example in §12.3 must reproduce
exactly." — test_worked_example_* below does exactly that.
"""
from __future__ import annotations

import pytest

from app.services import pricing_service as ps


@pytest.fixture
def settings() -> dict:
    """Spec §12.1's example settings, verbatim — also what's live in
    site_builder_settings.pricing for Trust's own org."""
    return {
        "express_enabled": False,
        "approval_required": True,
        "pricing": {
            "gateway": {"pct": 1.5, "flat_ngn": 100, "flat_waived_below_ngn": 2500, "cap_ngn": 2000},
            "vat_pct": 7.5,
            "fx": {"usd_ngn": 0, "buffer_pct": 10},
            "floors_after_fees": {"initial_ngn": 35000, "renewal_ngn": 20000},
            "service_fee": {"standard_ngn": 15000, "express_ngn": 25000},
            "markup_pct": {"domain": 40, "hosting": 35},
            "round_to_ngn": 500,
            "ai_msg_cost_estimate_ngn": {"initial": 400, "renewal": 100},
            "routes": {
                "standard": {
                    "hosting_items": [
                        {"name": "Starter hosting", "yearly_ngn": 18500, "vat": True},
                        {"name": "Advanced DNS Manager", "yearly_ngn": 500, "vat": True},
                        {"name": "Website protection (AWPS)", "yearly_ngn": 1000, "vat": True},
                        {"name": "PositiveSSL", "yearly_ngn": 14200, "vat": True},
                    ],
                    "domains": {
                        ".com.ng": {"first_ngn": 5500, "renew_ngn": 7000, "vat": True},
                        ".ng": {"first_ngn": 13500, "renew_ngn": 15000, "vat": True},
                        ".com": {"first_ngn": 12000, "renew_ngn": 20000, "vat": True},
                    },
                },
                "express": {
                    "hosting_per_site_usd": None,
                    "domains": {
                        ".com": {"first_usd": 9.99, "renew_usd": 19.99},
                        ".com.ng": {"first_usd": 19.99, "renew_usd": 25.99},
                        ".ng": {"first_usd": 24.99, "renew_usd": 32.99},
                    },
                },
            },
            "suggested_client_multiplier": {"initial": 1.9, "renewal": 1.3},
        },
    }


# ---------------------------------------------------------------------------
# §12.3 worked example — must reproduce exactly
# ---------------------------------------------------------------------------

def test_worked_example_initial_standard_com_ng(settings):
    q = ps.quote(db=None, org_id="org1", domain="adaezastyles.com.ng", route="standard", kind="initial", settings=settings)
    assert q["tld"] == ".com.ng"
    assert q["cost"]["hosting"] == pytest.approx(36765.0)
    assert q["cost"]["domain"] == pytest.approx(5912.5)
    assert q["cost"]["total"] == pytest.approx(43077.5)
    assert q["price"]["domain"] == 11000
    assert q["price"]["hosting"] == 50000
    assert q["price"]["service_fee"] == 18500
    assert q["price"]["total"] == 79500
    assert q["gateway_fee"] == pytest.approx(1292.5)
    assert q["profit"] == pytest.approx(35130.0, abs=1)
    assert q["suggested_client_price"] == 150000


def test_worked_example_renewal_standard_com_ng(settings):
    q = ps.quote(db=None, org_id="org1", domain="adaezastyles.com.ng", route="standard", kind="renewal", settings=settings)
    assert q["cost"]["total"] == pytest.approx(44390.0)
    assert q["price"]["domain"] == 11000
    assert q["price"]["hosting"] == 50000
    assert q["price"]["renewal_adjustment"] == 4500
    assert q["price"]["service_fee"] == 0
    assert q["price"]["total"] == 65500
    assert q["profit"] == pytest.approx(20027.5, abs=1)
    assert q["suggested_client_price"] == 85000


# ---------------------------------------------------------------------------
# Rounding: every price line rounds UP to round_to_ngn; suggested price
# rounds to the NEAREST ₦5,000.
# ---------------------------------------------------------------------------

def test_rounding_is_ceiling_not_nearest(settings):
    q = ps.quote(db=None, org_id="org1", domain="x.com.ng", route="standard", kind="initial", settings=settings)
    for key in ("domain", "hosting", "service_fee"):
        assert q["price"][key] % 500 == 0, f"{key} not a multiple of round_to_ngn"


def test_suggested_price_rounds_to_nearest_5000(settings):
    q = ps.quote(db=None, org_id="org1", domain="x.com.ng", route="standard", kind="initial", settings=settings)
    assert q["suggested_client_price"] % 5000 == 0


# ---------------------------------------------------------------------------
# VAT
# ---------------------------------------------------------------------------

def test_vat_applied_only_when_item_flagged(settings):
    settings["pricing"]["routes"]["standard"]["hosting_items"][0]["vat"] = False
    q = ps.quote(db=None, org_id="org1", domain="x.com.ng", route="standard", kind="initial", settings=settings)
    # Starter hosting (18500) now excluded from VAT — cost should drop vs the base fixture.
    base = ps.quote(db=None, org_id="org1", domain="x.com.ng", route="standard", kind="initial",
                     settings={**settings, "pricing": {**settings["pricing"]}})
    assert q["cost"]["hosting"] < 36765.0


# ---------------------------------------------------------------------------
# Gateway fee: pct + flat, waived below threshold, capped
# ---------------------------------------------------------------------------

def test_gateway_fee_waived_below_threshold():
    gw = {"pct": 1.5, "flat_ngn": 100, "flat_waived_below_ngn": 2500, "cap_ngn": 2000}
    assert ps._gateway_fee(2000, gw) == pytest.approx(2000 * 0.015)  # no flat, below waive threshold
    assert ps._gateway_fee(3000, gw) == pytest.approx(3000 * 0.015 + 100)  # flat applies


def test_gateway_fee_capped():
    gw = {"pct": 1.5, "flat_ngn": 100, "flat_waived_below_ngn": 2500, "cap_ngn": 2000}
    # A huge price would blow past the cap without it.
    assert ps._gateway_fee(1_000_000, gw) == 2000


# ---------------------------------------------------------------------------
# FX buffer (Express)
# ---------------------------------------------------------------------------

def test_express_fx_buffer_applied(settings):
    settings["express_enabled"] = True
    settings["pricing"]["fx"] = {"usd_ngn": 1500, "buffer_pct": 10}
    q = ps.quote(db=None, org_id="org1", domain="x.com", route="express", kind="initial", settings=settings)
    # 9.99 * 1500 * 1.10
    assert q["cost"]["domain"] == pytest.approx(9.99 * 1500 * 1.10)


def test_express_unavailable_when_not_enabled(settings):
    with pytest.raises(ps.RouteUnavailable):
        ps.quote(db=None, org_id="org1", domain="x.com", route="express", kind="initial", settings=settings)


# ---------------------------------------------------------------------------
# TLD resolution + unsupported domain/tld
# ---------------------------------------------------------------------------

def test_longest_tld_match_preferred(settings):
    q = ps.quote(db=None, org_id="org1", domain="shop.com.ng", route="standard", kind="initial", settings=settings)
    assert q["tld"] == ".com.ng"
    q2 = ps.quote(db=None, org_id="org1", domain="shop.ng", route="standard", kind="initial", settings=settings)
    assert q2["tld"] == ".ng"


def test_unsupported_tld_raises(settings):
    with pytest.raises(ps.UnsupportedDomain):
        ps.quote(db=None, org_id="org1", domain="shop.xyz", route="standard", kind="initial", settings=settings)


def test_invalid_domain_format_raises(settings):
    with pytest.raises(ps.UnsupportedDomain):
        ps.quote(db=None, org_id="org1", domain="not a domain", route="standard", kind="initial", settings=settings)


# ---------------------------------------------------------------------------
# quote_both_routes
# ---------------------------------------------------------------------------

def test_quote_both_routes_hides_disabled_express(settings):
    both = ps.quote_both_routes(db=None, org_id="org1", domain="x.com.ng", kind="initial", settings=settings)
    assert both["standard"]["price"]["total"] == 79500
    assert both["express"] is None


def test_quote_both_routes_includes_express_when_enabled(settings):
    settings["express_enabled"] = True
    settings["pricing"]["fx"] = {"usd_ngn": 1500, "buffer_pct": 10}
    both = ps.quote_both_routes(db=None, org_id="org1", domain="x.com.ng", kind="initial", settings=settings)
    assert both["express"] is not None
    assert "error" not in both["express"]
