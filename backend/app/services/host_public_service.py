"""
services/host_public_service.py
HOST-2 - what the public /host page may show before anyone signs in: a domain availability check and the price breakdown.

Prices are NEVER invented here. Every figure comes from pricing_service.quote (the same engine the checkout uses, so the page
and the checkout always agree) for the Opsra organisation's Standard route. Only customer-facing lines are returned:
never costs, profit, gateway fees or the suggested client price.

Price lines (decided 21 Oct 2026): Domain, Hosting bundle, Setup fee (first year only), Total. The hosting bundle is one
price; `includes` lists what it contains (names from the Standard route's hosting_items in Settings, e.g. hosting, SSL
certificate, DNS manager, website protection).

Never raises for a lookup problem (S14); a bad domain or an unpriced ending returns a plain message the router turns into 422.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.services import account_entitlement_service, domain_check_service, pricing_service

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 300
_cache: dict = {}


class PublicHostError(Exception):
    def __init__(self, message: str, status_code: int = 422, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _org(db: Any) -> str:
    org = account_entitlement_service.platform_org_id(db)
    if not org:
        raise PublicHostError("Pricing is not available yet.", 503, "SERVICE_UNAVAILABLE")
    return org


def _lines(first: dict, renewal: dict) -> dict:
    fp, rp = first["price"], renewal["price"]
    # The setup fee shown is everything in the first-year total that is not the domain or the hosting bundle.
    setup = round(float(fp["total"]) - float(fp["domain"]) - float(fp["hosting"]), 2)
    renew_total = float(rp["total"])
    return {
        "first_year": {"domain": fp["domain"], "hosting": fp["hosting"], "setup": setup, "total": fp["total"]},
        "renewal": {"domain": rp["domain"], "hosting": rp["hosting"],
                    "adjustment": round(renew_total - float(rp["domain"]) - float(rp["hosting"]), 2), "total": rp["total"]},
    }


def quote_for(db: Any, domain: str, settings: Optional[dict] = None) -> dict:
    org = _org(db)
    settings = settings if settings is not None else pricing_service.get_settings(db, org)
    try:
        first = pricing_service.quote(db, org, domain, "standard", "initial", settings=settings)
        renewal = pricing_service.quote(db, org, domain, "standard", "renewal", settings=settings)
    except pricing_service.PricingError as exc:
        raise PublicHostError(str(exc))
    return {"domain": first["domain"], "tld": first["tld"], **_lines(first, renewal)}


def _includes(settings: dict) -> list:
    items = (((settings.get("pricing") or {}).get("routes") or {}).get("standard") or {}).get("hosting_items") or []
    return [str(i.get("name")) for i in items if i.get("name")]


def pricing_table(db: Any) -> dict:
    """One row per domain ending the Standard route sells, priced for a sample name, plus what the hosting includes."""
    cached = _cache.get("table")
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    org = _org(db)
    settings = pricing_service.get_settings(db, org)
    domains = ((((settings.get("pricing") or {}).get("routes") or {}).get("standard") or {}).get("domains")) or {}
    rows = []
    for tld in sorted(domains, key=lambda t: (len(t), t)):
        try:
            q = quote_for(db, f"yourname{tld}", settings)
        except PublicHostError:
            continue
        rows.append({"tld": tld, "first_year": q["first_year"], "renewal": q["renewal"]})
    own = None
    try:
        a = pricing_service.quote_own_domain(db, org, "yourname.com", "initial", settings=settings)
        b = pricing_service.quote_own_domain(db, org, "yourname.com", "renewal", settings=settings)
        own = {"first_year": a["price"]["total"], "renewal": b["price"]["total"]}
    except pricing_service.PricingError:
        own = None          # not priced yet: the page simply leaves the own-domain card out
    out = {"currency": "NGN", "endings": rows, "includes": _includes(settings), "own_domain": own,
           "setup_note": "The setup fee is charged once, in the first year." if any(r["first_year"]["setup"] > 0 for r in rows) else ""}
    _cache["table"] = (time.monotonic(), out)
    return out


def check(db: Any, domain: str, client_key: str) -> dict:
    """Availability, and the price for that exact domain when it is free (or unconfirmed-free)."""
    org = _org(db)
    try:
        result = domain_check_service.check_domain(db, org, f"public:{client_key}", domain)
    except domain_check_service.RateLimited as exc:
        raise PublicHostError(str(exc), 429, "RATE_LIMITED")
    except domain_check_service.DomainCheckError as exc:
        raise PublicHostError(str(exc))
    out = dict(result)
    if result.get("status") == "available":
        try:
            out["price"] = quote_for(db, result["domain"])
        except PublicHostError:
            out["price"] = None
    alts = []
    for a in result.get("alternatives") or []:
        alts.append({"domain": a.get("domain"), "status": a.get("status"), "available": a.get("available")})
    if "alternatives" in out:
        out["alternatives"] = alts
    return out
