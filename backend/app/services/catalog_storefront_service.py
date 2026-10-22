"""
app/services/catalog_storefront_service.py
------------------------------------------
STORE-1 - the "Storefront" look for the public catalog (backend only; no screen changes in this phase).

  resolve_template(db, org_id, catalog_config)   "storefront" or "classic" - what the public page should draw
  public_style(catalog_config)                   owner-typed Storefront text/colour/logo, cleaned for the browser
  shop_info(db, org_id)                          {"key": "wc_..."} when the cart can be used, else None
  discount_percent(price, compare_at)            whole-number "% off", or None when there is no real discount

Rules
  * Classic is the default. Storefront shows only when the owner picked it AND the plan includes catalog_storefront.
    A plan that lacks it always gets Classic (the saved choice is kept, never erased).
  * The cart is the web chat shop (webchat_shop_service). It is offered only when web chat is on, its shop switch is
    on, the plan includes it, Paystack (paystack_storefront) is connected and the business already has a chat key.
    Reading never writes: no key is created from a public page.
  * Nothing secret is returned - only the chat key, which is already public in every /c/ chat link.
  * S14: every public helper fails safe (Classic / no shop) and never raises into the router.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

FEATURE_KEY = "catalog_storefront"
TEMPLATES = ("classic", "storefront")
DEFAULT_TEMPLATE = "classic"

ANNOUNCEMENT_MAX = 120
TRUST_POINTS_MAX = 3
TRUST_POINT_CHARS = 40
LOGO_URL_MAX = 300
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _text(v, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def clean_https_url(v) -> Optional[str]:
    u = str(v or "").strip()
    return u[:LOGO_URL_MAX] if u.lower().startswith("https://") and len(u) <= LOGO_URL_MAX and " " not in u else None


def public_style(catalog_config: Optional[dict]) -> dict:
    """The owner's optional Storefront text, accent colour and logo, cleaned again on the way out."""
    cfg = catalog_config if isinstance(catalog_config, dict) else {}
    points = cfg.get("trust_points")
    points = [_text(p, TRUST_POINT_CHARS) for p in points[:TRUST_POINTS_MAX]] if isinstance(points, list) else []
    accent = cfg.get("accent")
    return {
        "announcement": _text(cfg.get("announcement"), ANNOUNCEMENT_MAX) or None,
        "trust_points": [p for p in points if p],
        "accent": accent if isinstance(accent, str) and _HEX.match(accent) else None,
        "logo_url": clean_https_url(cfg.get("logo_url")),
        # STORE-1b: show the category menu / buttons (default on; the owner can turn it off)
        "show_categories": cfg.get("show_categories") is not False,
    }


def storefront_allowed(db, org_id: str) -> bool:
    """Does the business's plan include the Storefront look? (A business not switched onto plans is allowed.)"""
    from app.services import plan_gate_service as gate
    return bool(gate.allowed(db, org_id, FEATURE_KEY))


def resolve_template(db, org_id: str, catalog_config: Optional[dict]) -> str:
    try:
        cfg = catalog_config if isinstance(catalog_config, dict) else {}
        if cfg.get("template") != "storefront":
            return DEFAULT_TEMPLATE
        return "storefront" if storefront_allowed(db, org_id) else DEFAULT_TEMPLATE
    except Exception as exc:
        logger.warning("storefront resolve_template failed org=%s: %s", org_id, exc)
        return DEFAULT_TEMPLATE


def shop_info(db, org_id: str) -> Optional[dict]:
    """{'key': 'wc_...'} when a visitor can add to cart and pay on the Storefront; otherwise None."""
    try:
        from app.services import paystack_storefront_service as paystack
        from app.services import webchat_plan_service as plan
        from app.services import webchat_service as wc

        cfg = plan.apply(db, org_id, wc.get_config(db, org_id))
        if not cfg or not cfg.get("enabled") or not cfg.get("shop_enabled"):
            return None
        if not (paystack._get_storefront_credentials(db, org_id).get("secret_key") or "").strip():
            return None
        rows = (db.table("webchat_keys").select("key").eq("org_id", org_id).eq("active", True).limit(1).execute().data) or []
        key = rows[0].get("key") if rows else None
        return {"key": key} if key else None
    except Exception as exc:
        logger.warning("storefront shop_info failed org=%s: %s", org_id, exc)
        return None


def discount_percent(price, compare_at) -> Optional[int]:
    """Whole-number '% off' only when compare_at is really higher than price. Otherwise None (show nothing)."""
    try:
        p, c = float(price), float(compare_at)
    except (TypeError, ValueError):
        return None
    if p <= 0 or c <= p:
        return None
    pct = int(round((1 - p / c) * 100))
    return pct if pct >= 1 else None


def public_extras(db, org_id: str, catalog_config: Optional[dict]) -> dict:
    """The three public fields added to every public catalog response: template, shop and the owner's style."""
    template = resolve_template(db, org_id, catalog_config)
    storefront = template == "storefront"
    return {
        "template": template,
        "shop": shop_info(db, org_id) if storefront else None,
        "style": public_style(catalog_config) if storefront else None,
    }
