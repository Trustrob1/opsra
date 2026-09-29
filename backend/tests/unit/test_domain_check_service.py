"""
tests/unit/test_domain_check_service.py
-----------------------------------------
SITE-3 — domain_check_service.check_domain(). Registry lookups
(_lookup_availability) are mocked in every test — no real RDAP/DNS calls.

Spec §19: "Domain checks: format, the RDAP parser, and the suggestions."
"""
from __future__ import annotations

import pytest

from app.services import domain_check_service as dcs


@pytest.fixture(autouse=True)
def reset_state():
    """The rate limiter and cache are in-process module state — clear them
    between tests so one test's hits/cache never leak into the next."""
    dcs._rate_hits.clear()
    dcs._cache.clear()
    yield
    dcs._rate_hits.clear()
    dcs._cache.clear()


@pytest.fixture
def settings_patch(monkeypatch):
    def _get_settings(db, org_id):
        return {
            "express_enabled": False,
            "pricing": {"routes": {
                "standard": {"domains": {".com.ng": {}, ".ng": {}, ".com": {}}},
                "express": {"domains": {}},
            }},
        }
    monkeypatch.setattr(dcs.pricing_service, "get_settings", _get_settings)


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def test_invalid_label_raises(settings_patch):
    with pytest.raises(dcs.InvalidDomain):
        dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="-badlabel.com")


def test_unsupported_tld_raises(settings_patch):
    with pytest.raises(dcs.InvalidDomain):
        dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="shop.xyz")


def test_longest_tld_match(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: True)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="shop.com.ng")
    assert r["domain"] == "shop.com.ng"
    assert r["status"] == "available"


# ---------------------------------------------------------------------------
# Availability + alternatives
# ---------------------------------------------------------------------------

def test_available_domain_has_no_alternatives(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: True)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="freshlabel.com")
    assert r["status"] == "available"
    assert "alternatives" not in r


def test_taken_domain_suggests_up_to_five_checked_alternatives(monkeypatch, settings_patch):
    taken = {"adaezastyles.com"}

    def fake_lookup(domain, tld):
        return domain not in taken

    monkeypatch.setattr(dcs, "_lookup_availability", fake_lookup)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="adaezastyles.com")
    assert r["status"] == "taken"
    assert 0 < len(r["alternatives"]) <= dcs._MAX_SUGGESTIONS
    for alt in r["alternatives"]:
        assert alt["available"] is True
        assert alt["domain"] != "adaezastyles.com"


def test_all_alternatives_also_taken_returns_empty_list(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: False)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="popularname.com")
    assert r["status"] == "taken"
    assert r["alternatives"] == []


def test_unknown_registry_result_does_not_raise(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: None)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="mystery.com")
    assert r["status"] == "unknown"
    assert r["available"] is None


# ---------------------------------------------------------------------------
# Cache (10 minutes) + rate limit (20/hour/builder)
# ---------------------------------------------------------------------------

def test_cache_hit_skips_registry_lookup(monkeypatch, settings_patch):
    calls = {"n": 0}

    def counting_lookup(domain, tld):
        calls["n"] += 1
        return True

    monkeypatch.setattr(dcs, "_lookup_availability", counting_lookup)
    dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="cached.com")
    dcs.check_domain(db=None, org_id="org1", builder_id="b2", domain="cached.com")
    assert calls["n"] == 1


def test_cache_expires_after_ttl(monkeypatch, settings_patch):
    calls = {"n": 0}

    def counting_lookup(domain, tld):
        calls["n"] += 1
        return True

    monkeypatch.setattr(dcs, "_lookup_availability", counting_lookup)
    t = {"now": 1_000_000.0}
    monkeypatch.setattr(dcs, "_now", lambda: t["now"])
    dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="expiring.com")
    t["now"] += dcs._CACHE_TTL_S + 1
    dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="expiring.com")
    assert calls["n"] == 2


def test_rate_limit_20_per_hour_per_builder(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: True)
    for i in range(dcs._RATE_LIMIT_PER_HOUR):
        dcs.check_domain(db=None, org_id="org1", builder_id="heavy", domain=f"unique{i}.com")
    with pytest.raises(dcs.RateLimited):
        dcs.check_domain(db=None, org_id="org1", builder_id="heavy", domain="onemore.com")


def test_rate_limit_is_per_builder(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: True)
    for i in range(dcs._RATE_LIMIT_PER_HOUR):
        dcs.check_domain(db=None, org_id="org1", builder_id="builder-a", domain=f"a{i}.com")
    # A different builder isn't affected by builder-a's limit.
    r = dcs.check_domain(db=None, org_id="org1", builder_id="builder-b", domain="freshone.com")
    assert r["status"] == "available"


# ---------------------------------------------------------------------------
# .ng / .com.ng — DNS-over-HTTPS fallback (port-43 WHOIS times out from Render)
# ---------------------------------------------------------------------------

def _doh(monkeypatch, answers):
    """answers: {resolver_url: (rcode, has_ns) | None}. Records the resolvers tried."""
    tried = []

    def fake(resolver, domain):
        tried.append(resolver)
        return answers[resolver]

    monkeypatch.setattr(dcs, "_doh_ns_query", fake)
    return tried


def test_ng_with_nameservers_is_taken(monkeypatch):
    _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: (0, True), dcs._DOH_RESOLVERS[1]: (0, True)})
    assert dcs._check_dns_ng("adaezastyles.com.ng") is False


def test_ng_nxdomain_is_available(monkeypatch):
    _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: (3, False), dcs._DOH_RESOLVERS[1]: (3, False)})
    assert dcs._check_dns_ng("freshname.com.ng") is True


def test_ng_noerror_without_ns_is_unknown(monkeypatch):
    _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: (0, False), dcs._DOH_RESOLVERS[1]: (0, False)})
    assert dcs._check_dns_ng("odd.com.ng") is None


def test_ng_servfail_is_unknown(monkeypatch):
    _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: (2, False), dcs._DOH_RESOLVERS[1]: (2, False)})
    assert dcs._check_dns_ng("broken.com.ng") is None


def test_ng_falls_back_to_second_resolver(monkeypatch):
    tried = _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: None, dcs._DOH_RESOLVERS[1]: (3, False)})
    assert dcs._check_dns_ng("freshname.ng") is True
    assert tried == list(dcs._DOH_RESOLVERS)


def test_ng_both_resolvers_down_is_unknown(monkeypatch):
    _doh(monkeypatch, {dcs._DOH_RESOLVERS[0]: None, dcs._DOH_RESOLVERS[1]: None})
    assert dcs._check_dns_ng("freshname.ng") is None


def test_ng_uses_dns_and_gtld_uses_rdap(monkeypatch):
    monkeypatch.setattr(dcs, "_check_dns_ng", lambda d: "dns")
    monkeypatch.setattr(dcs, "_check_rdap_gtld", lambda d: "rdap")
    assert dcs._lookup_availability("a.com.ng", ".com.ng") == "dns"
    assert dcs._lookup_availability("a.ng", ".ng") == "dns"
    assert dcs._lookup_availability("a.com", ".com") == "rdap"


def test_ng_available_is_flagged_unconfirmed(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_check_dns_ng", lambda d: True)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="freshname.com.ng")
    assert r["status"] == "available"
    assert r["confirmed"] is False


def test_ng_taken_is_confirmed(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_check_dns_ng", lambda d: False)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="adaezastyles.com.ng")
    assert r["status"] == "taken"
    assert r["confirmed"] is True


def test_gtld_available_is_confirmed(monkeypatch, settings_patch):
    monkeypatch.setattr(dcs, "_lookup_availability", lambda domain, tld: True)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="freshlabel.com")
    assert r["confirmed"] is True


def test_unknown_skips_alternatives_search(monkeypatch, settings_patch):
    calls = []

    def counting(domain, tld):
        calls.append(domain)
        return None

    monkeypatch.setattr(dcs, "_lookup_availability", counting)
    r = dcs.check_domain(db=None, org_id="org1", builder_id="b1", domain="mystery.com")
    assert r["status"] == "unknown"
    assert "alternatives" not in r
    assert calls == ["mystery.com"]          # no per-candidate lookups


def test_is_unconfirmed_tld():
    assert dcs.is_unconfirmed_tld("shop.com.ng")
    assert dcs.is_unconfirmed_tld("shop.ng")
    assert not dcs.is_unconfirmed_tld("shop.com")
