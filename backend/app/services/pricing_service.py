"""
app/services/pricing_service.py
--------------------------------
SITE-3 — the site-hosting pricing engine (spec §12).

Turns a domain + route (+ kind: initial/renewal) into a full price breakdown:
cost, customer price (with the profit-floor solved for directly, never by
trial-and-error), the Paystack gateway fee, expected profit, and the
suggested price to show the client. Settings live in
`site_builder_settings.pricing` (spec §12.1) — Trust can edit every value
there; nothing here is hard-coded except the §12.2 formula itself and the
fixed ₦5,000 rounding used only for the suggested client price.

S14: every public function either returns a value or raises PricingError —
callers (routers/builder_portal.py) decide how that becomes a 4xx response.
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal, Optional

Route = Literal["standard", "express"]
Kind = Literal["initial", "renewal"]

_TLD_RE = re.compile(r"^[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})+$")


class PricingError(Exception):
    """Base for pricing_service errors — caller maps to a 4xx response."""


class UnsupportedDomain(PricingError):
    """Domain format is invalid, or its TLD has no price configured for this route."""


class RouteUnavailable(PricingError):
    """The requested route isn't enabled for this org (e.g. Express, SITE-3B)."""


# ---------------------------------------------------------------------------
# Settings lookup
# ---------------------------------------------------------------------------

def get_settings(db: Any, org_id: str) -> dict:
    """Raw site_builder_settings row. Callers that need the 404-for-disabled-org
    behaviour use routers/sites.py::_require_enabled first — this just reads."""
    result = (
        db.table("site_builder_settings")
        .select("*")
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    return data or {}


# ---------------------------------------------------------------------------
# Small numeric helpers — the formula rounds UP to round_to_ngn everywhere
# except the suggested client price, which rounds to the NEAREST ₦5,000.
# ---------------------------------------------------------------------------

def _ceil_to(value: float, step: float) -> float:
    if not step or step <= 0:
        return round(value, 2)
    return math.ceil(round(value, 6) / step) * step


def _round_nearest(value: float, step: float) -> float:
    if not step or step <= 0:
        return round(value, 2)
    return round(value / step) * step


def _gateway_fee(price: float, gw: dict) -> float:
    pct = (gw.get("pct") or 0) / 100
    waive = gw.get("flat_waived_below_ngn") or 0
    flat = (gw.get("flat_ngn") or 0) if price >= waive else 0
    fee = price * pct + flat
    cap = gw.get("cap_ngn")
    if cap is not None:
        fee = min(fee, cap)
    return fee


def _solve_extra_for_floor(base_price: float, cost: float, floor: float, gw: dict, round_to: float) -> float:
    """
    Solves directly (no trial-and-error) for the extra amount (the initial
    service fee, or the renewal adjustment) that must be added on top of
    `base_price` so that profit = price - cost - gateway_fee(price) == floor,
    then rounds the result UP to round_to. Piecewise-linear in `price` with at
    most two breakpoints (the flat-fee waive threshold and the fee cap), so
    each branch has a closed-form solution; the branch is picked by checking
    which one is internally consistent, never by iterating/guessing.
    """
    pct = (gw.get("pct") or 0) / 100
    flat = gw.get("flat_ngn") or 0
    waive = gw.get("flat_waived_below_ngn") or 0
    cap = gw.get("cap_ngn")
    denom = 1 - pct
    if denom <= 0:
        # Pathological config (>=100% gateway pct) — fee formula breaks down.
        # Fall back to a safe, if approximate, answer rather than dividing by <=0.
        price = floor + cost + flat
    else:
        # Branch 1 (the common case): price ends up >= the waive threshold,
        # so the flat fee applies, and the fee stays under the cap.
        price1 = (floor + cost + flat) / denom
        fee1 = price1 * pct + (flat if price1 >= waive else 0)
        if price1 >= waive and (cap is None or fee1 <= cap):
            price = price1
        else:
            # Branch 2: price stays below the waive threshold, so no flat fee.
            price2 = (floor + cost) / denom
            fee2 = price2 * pct
            if price2 < waive and (cap is None or fee2 <= cap):
                price = price2
            else:
                # Branch 3: the fee is capped regardless of price.
                price = floor + cost + (cap or 0)

    extra = max(price - base_price, 0)
    return _ceil_to(extra, round_to)


# ---------------------------------------------------------------------------
# Domain/TLD helpers
# ---------------------------------------------------------------------------

def _normalise_domain(domain: str) -> str:
    d = (domain or "").strip().lower().rstrip(".")
    if not _TLD_RE.match(d):
        raise UnsupportedDomain(f"'{domain}' isn't a valid domain.")
    return d


def _extract_tld(domain: str, domains_cfg: dict) -> str:
    """Matches the LONGEST configured TLD suffix first, so '.com.ng' is picked
    over '.ng' for a domain like 'shop.com.ng'."""
    for tld in sorted(domains_cfg.keys(), key=len, reverse=True):
        if domain.endswith(tld):
            return tld
    # Fall back to the last label (e.g. '.xyz') so the error message is useful.
    parts = domain.split(".")
    return "." + parts[-1] if parts else domain


def _hosting_cost_ngn(hosting_items: list[dict], vat_pct: float) -> float:
    total = 0.0
    for item in hosting_items or []:
        v = float(item.get("yearly_ngn") or 0)
        if item.get("vat"):
            v *= 1 + vat_pct / 100
        total += v
    return total


def _domain_cost_ngn(tld_cfg: dict, kind: Kind, vat_pct: float) -> float:
    key = "first_ngn" if kind == "initial" else "renew_ngn"
    base = float(tld_cfg.get(key) or 0)
    if tld_cfg.get("vat"):
        base *= 1 + vat_pct / 100
    return base


def _domain_cost_usd_to_ngn(tld_cfg: dict, kind: Kind, fx: dict) -> float:
    key = "first_usd" if kind == "initial" else "renew_usd"
    base_usd = float(tld_cfg.get(key) or 0)
    usd_ngn = float(fx.get("usd_ngn") or 0)
    buffer_pct = float(fx.get("buffer_pct") or 0)
    return base_usd * usd_ngn * (1 + buffer_pct / 100)


# ---------------------------------------------------------------------------
# quote — the main entry point (spec §12.2)
# ---------------------------------------------------------------------------

def quote(
    db: Any,
    org_id: str,
    domain: str,
    route: Route,
    kind: Kind = "initial",
    settings: Optional[dict] = None,
) -> dict:
    """
    Returns the full breakdown for one route/kind:
      {
        "route", "kind", "domain", "tld",
        "cost": {"domain", "hosting", "ai_messages", "total"},
        "price": {"domain", "hosting", "service_fee", "renewal_adjustment", "total"},
        "gateway_fee", "profit", "suggested_client_price",
        "live_within_hours": int,
      }
    Raises UnsupportedDomain / RouteUnavailable — callers convert to 422/400.
    """
    if route not in ("standard", "express"):
        raise PricingError(f"Unknown route '{route}'")
    if kind not in ("initial", "renewal"):
        raise PricingError(f"Unknown kind '{kind}'")

    settings = settings if settings is not None else get_settings(db, org_id)
    pricing = settings.get("pricing") or {}
    if not pricing:
        raise PricingError("Pricing is not configured for this organisation yet.")

    if route == "express" and not settings.get("express_enabled"):
        raise RouteUnavailable("Express hosting isn't enabled for this organisation yet.")

    domain_norm = _normalise_domain(domain)
    route_cfg = (pricing.get("routes") or {}).get(route) or {}
    domains_cfg = route_cfg.get("domains") or {}
    tld = _extract_tld(domain_norm, domains_cfg)
    tld_cfg = domains_cfg.get(tld)
    if not tld_cfg:
        raise UnsupportedDomain(f"'{tld}' isn't supported on the {route} route.")

    vat_pct = float(pricing.get("vat_pct") or 0)
    round_to = float(pricing.get("round_to_ngn") or 500)
    gw = pricing.get("gateway") or {}
    markup = pricing.get("markup_pct") or {}
    floor = float((pricing.get("floors_after_fees") or {}).get(f"{kind}_ngn") or 0)
    ai_est = float((pricing.get("ai_msg_cost_estimate_ngn") or {}).get(kind) or 0)
    multiplier = float((pricing.get("suggested_client_multiplier") or {}).get(kind) or 1)

    if route == "standard":
        domain_cost = _domain_cost_ngn(tld_cfg, kind, vat_pct)
        domain_renewal_cost = _domain_cost_ngn(tld_cfg, "renewal", vat_pct)
        hosting_cost = _hosting_cost_ngn(route_cfg.get("hosting_items") or [], vat_pct)
    else:  # express
        fx = pricing.get("fx") or {}
        domain_cost = _domain_cost_usd_to_ngn(tld_cfg, kind, fx)
        domain_renewal_cost = _domain_cost_usd_to_ngn(tld_cfg, "renewal", fx)
        hosting_per_site_usd = route_cfg.get("hosting_per_site_usd")
        hosting_cost = (
            float(hosting_per_site_usd) * float(fx.get("usd_ngn") or 0) * (1 + float(fx.get("buffer_pct") or 0) / 100)
            if hosting_per_site_usd
            else 0.0
        )

    total_cost = domain_cost + hosting_cost + ai_est

    # Customer price: domain and hosting are priced off the RENEWAL cost with
    # markup applied, even in the first year (spec §12.2), each rounded UP.
    domain_price = _ceil_to(domain_renewal_cost * (1 + float(markup.get("domain") or 0) / 100), round_to)
    hosting_price = _ceil_to(hosting_cost * (1 + float(markup.get("hosting") or 0) / 100), round_to) if hosting_cost else 0.0
    base_price = domain_price + hosting_price

    service_fee_key = f"{route}_ngn"
    default_service_fee = float((pricing.get("service_fee") or {}).get(service_fee_key) or 0)

    service_fee = 0.0
    renewal_adjustment = 0.0

    if kind == "initial":
        price_at_default = base_price + default_service_fee
        profit_at_default = price_at_default - total_cost - _gateway_fee(price_at_default, gw)
        service_fee = (
            default_service_fee
            if profit_at_default >= floor
            else _solve_extra_for_floor(base_price, total_cost, floor, gw, round_to)
        )
    else:
        profit_at_base = base_price - total_cost - _gateway_fee(base_price, gw)
        if profit_at_base < floor:
            renewal_adjustment = _solve_extra_for_floor(base_price, total_cost, floor, gw, round_to)

    price = base_price + service_fee + renewal_adjustment
    gateway_fee = _gateway_fee(price, gw)
    profit = price - total_cost - gateway_fee
    suggested_client_price = _round_nearest(price * multiplier, 5000)

    return {
        "route": route,
        "kind": kind,
        "domain": domain_norm,
        "tld": tld,
        "cost": {
            "domain": round(domain_cost, 2),
            "hosting": round(hosting_cost, 2),
            "ai_messages": round(ai_est, 2),
            "total": round(total_cost, 2),
        },
        "price": {
            "domain": domain_price,
            "hosting": hosting_price,
            "service_fee": service_fee,
            "renewal_adjustment": renewal_adjustment,
            "total": round(price, 2),
        },
        "gateway_fee": round(gateway_fee, 2),
        "profit": round(profit, 2),
        "suggested_client_price": suggested_client_price,
        "live_within_hours": 24 if route == "standard" else (24 if settings.get("approval_required") else 0),
    }


def quote_both_routes(
    db: Any, org_id: str, domain: str, kind: Kind = "initial", settings: Optional[dict] = None
) -> dict:
    """
    Spec §11.2 — "the builder sees both routes side by side". Returns
    {"standard": {...} | {"error": str}, "express": {...} | None | {"error": str}}.
    Express is omitted (None) rather than erroring when it's simply not enabled,
    so the frontend can hide it instead of showing a scary error.
    """
    settings = settings if settings is not None else get_settings(db, org_id)
    out: dict = {"standard": None, "express": None}
    try:
        out["standard"] = quote(db, org_id, domain, "standard", kind, settings=settings)
    except PricingError as exc:
        out["standard"] = {"error": str(exc)}

    if settings.get("express_enabled"):
        try:
            out["express"] = quote(db, org_id, domain, "express", kind, settings=settings)
        except PricingError as exc:
            out["express"] = {"error": str(exc)}

    return out
