"""
app/services/site_catalog_service.py
--------------------------------------
GIVEAWAY-2 — the bigger-catalog upgrade. A template lists at most `max_items` products/services (the preset's own limit,
e.g. 30). A site that outgrows it buys a one-time pack (default +30 items for ₦5,000) that raises THAT site's limit.
Packs stack, up to the hard limit of 60 items every site can hold (the content model's own maximum).

  limits()        base (template) + extra (bought) = the site's limit
  check_growth()  called by the content save: a save that would ADD items past the limit is refused with an offer.
                  A save that does not grow the list is always allowed, so sites already over the limit are not locked out.
  create_checkout()  a Paystack link for one pack (reuses an open link), recorded as a site_orders row of kind 'catalog_pack'
  on_paid()       called from site_order_service.on_payment_confirmed: raises sites.extra_items
Price and size are live settings: site_builder_settings.pricing.catalog_pack = {"price_ngn": 5000, "items": 30}.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULTS = {"price_ngn": 5000, "items": 30}
HARD_MAX = 60


class CatalogError(Exception):
    pass


class CatalogNotFound(CatalogError):
    pass


class CatalogBlocked(CatalogError):
    pass


class CatalogLimitReached(Exception):
    def __init__(self, message: str, offer: dict):
        super().__init__(message)
        self.offer = offer


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def get_config(settings: Optional[dict]) -> dict:
    raw = (((settings or {}).get("pricing") or {}).get("catalog_pack")) or {}
    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        try:
            if raw.get(key) is not None and float(raw[key]) > 0:
                cfg[key] = int(float(raw[key]))
        except (TypeError, ValueError):
            pass
    return cfg


def _settings(db: Any, org_id: str) -> dict:
    from app.services import pricing_service
    return pricing_service.get_settings(db, org_id)


def limits(db: Any, org_id: str, site: dict) -> dict:
    """{"base", "extra", "limit"}. A site whose template can't be found is only held to the hard maximum."""
    base = HARD_MAX
    try:
        preset = _one((db.table("site_presets").select("max_items").eq("id", site.get("preset_id")).eq("org_id", org_id)
                       .limit(1).execute()).data)
        if preset and preset.get("max_items"):
            base = int(preset["max_items"])
    except Exception:  # S14
        logger.warning("[GIVEAWAY-2] preset limit lookup failed site=%s", site.get("id"))
    try:
        extra = max(0, int(site.get("extra_items") or 0))
    except (TypeError, ValueError):
        extra = 0
    return {"base": base, "extra": extra, "limit": min(HARD_MAX, base + extra)}


def offer_for(db: Any, org_id: str, site: dict) -> dict:
    lim = limits(db, org_id, site)
    cfg = get_config(_settings(db, org_id))
    return {"limit": lim["limit"], "base": lim["base"], "extra": lim["extra"], "hard_max": HARD_MAX,
            "pack_items": cfg["items"], "pack_price": cfg["price_ngn"], "can_buy": lim["limit"] < HARD_MAX}


def check_growth(db: Any, org_id: str, site: dict, new_content: Optional[dict]) -> None:
    new_n = len((new_content or {}).get("items") or [])
    old_n = len(((site.get("content") or {}).get("items")) or [])
    if new_n <= old_n:
        return
    lim = limits(db, org_id, site)
    if new_n <= lim["limit"]:
        return
    offer = offer_for(db, org_id, site)
    if offer["can_buy"]:
        msg = (f"This site can list {lim['limit']} items. To add more, buy {offer['pack_items']} more items "
               f"for ₦{offer['pack_price']:,}.")
    else:
        msg = f"This site is at the maximum of {HARD_MAX} items."
    raise CatalogLimitReached(msg, offer)


def _load_site(db: Any, org_id: str, site_id: str, builder_id: Optional[str]) -> dict:
    q = db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).is_("deleted_at", "null")
    if builder_id:
        q = q.eq("builder_id", builder_id)
    site = _one(q.limit(1).execute().data)
    if not site:
        raise CatalogNotFound("Site not found")
    return site


def create_checkout(db: Any, org_id: str, builder: dict, site_id: str) -> dict:
    """Returns {"checkout_url", "amount", "items", "reused"}."""
    from app.services import paystack_storefront_service as paystack
    site = _load_site(db, org_id, site_id, builder.get("id"))
    if not builder.get("lead_id"):
        raise CatalogBlocked("A payment link can't be created yet. Please try again shortly.")
    offer = offer_for(db, org_id, site)
    if not offer["can_buy"]:
        raise CatalogBlocked(f"This site is already at the maximum of {HARD_MAX} items.")
    amount, items = offer["pack_price"], offer["pack_items"]

    open_orders = [o for o in ((db.table("site_orders").select("*").eq("org_id", org_id).eq("site_id", site["id"])
                                .eq("kind", "catalog_pack").eq("status", "pending_payment").execute()).data or [])
                   if o.get("payment_link_id") and float(o.get("amount") or 0) == float(amount)]
    open_orders.sort(key=lambda o: str(o.get("created_at") or ""), reverse=True)
    for order in open_orders:
        link = _one((db.table("payment_links").select("checkout_url").eq("id", order["payment_link_id"])
                     .eq("org_id", org_id).limit(1).execute()).data)
        if link and link.get("checkout_url"):
            return {"checkout_url": link["checkout_url"], "amount": amount, "items": items, "reused": True}

    try:
        link = paystack.generate_payment_link(
            db=db, org_id=org_id, lead_id=builder["lead_id"], amount=amount, payment_type="full", currency="NGN",
            trigger_stage=None, target_stage_on_paid=None, created_by=None)
    except paystack.PaystackLinkError as exc:
        raise CatalogBlocked(str(exc))
    try:
        from app.services import pricing_service
        gw = (_settings(db, org_id).get("pricing") or {}).get("gateway") or {}
        profit = round(amount - float(pricing_service._gateway_fee(amount, gw)), 2)
    except Exception:
        profit = amount
    now = _iso()
    row = {
        "org_id": org_id, "site_id": site["id"], "builder_id": builder["id"], "lead_id": builder["lead_id"],
        "kind": "catalog_pack", "route": "standard", "domain": None, "backup_domain": None,
        "quote": {"kind": "catalog_pack", "items": items, "price": amount}, "amount": amount, "cost_snapshot": {},
        "expected_profit": profit, "payment_link_id": link.get("payment_link_id"), "payment_reference": link["reference"],
        "status": "pending_payment", "approval_required": False, "created_at": now, "updated_at": now,
    }
    db.table("site_orders").insert(row).execute()
    return {"checkout_url": link["checkout_url"], "amount": amount, "items": items, "reused": False}


def on_paid(db: Any, org_id: str, order: dict, now: Optional[datetime] = None) -> None:
    now = now or _now()
    site = _one((db.table("sites").select("id,extra_items,client_business_name").eq("id", order["site_id"])
                 .eq("org_id", org_id).limit(1).execute()).data) or {}
    items = int(((order.get("quote") or {}).get("items")) or DEFAULTS["items"])
    new_extra = int(site.get("extra_items") or 0) + items
    db.table("sites").update({"extra_items": new_extra, "updated_at": _iso(now)}).eq("id", order["site_id"]) \
        .eq("org_id", org_id).execute()
    try:
        from app.services import site_order_service
        site_order_service._message_builder(
            db, org_id, order,
            f"{items} more items added to {site.get('client_business_name') or 'your site'}. "
            "You can now list more products or services.")
    except Exception as exc:  # S14
        logger.warning("[GIVEAWAY-2] catalog message failed order=%s: %s", order.get("id"), exc)
