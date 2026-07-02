"""
app/services/shopify_provider_service.py
INTEGRATIONS-1 — Shopify integration provider for owner query handler.

Reads live order and product data directly from the Shopify Admin REST API
using the per-org credentials already stored on the organisations table
(shopify_client_id, shopify_client_secret, shopify_shop_domain).

Token acquisition mirrors the existing bulk_sync_products() pattern in
shopify_service.py — calls _get_shopify_token() for a fresh 24-hour token
before every query. Tokens are short-lived; no caching.

Credentials required on organisations table (already present for Royal Rest):
  shopify_client_id     TEXT
  shopify_client_secret TEXT
  shopify_shop_domain   TEXT

No new schema changes required.

What the owner can ask:
  get_summary() — revenue, order count, AOV, top products, fulfilment rate
  search()      — recent or specific orders by status/product/customer

S14: all methods return error/empty shape on failure, never raise.
Pattern 29: load_dotenv() at module level.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from app.integrations.base import IntegrationProvider

load_dotenv()

logger = logging.getLogger(__name__)

_SHOPIFY_API_VERSION = "2026-01"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _get_shopify_credentials(db: Any, org_id: str) -> tuple[str, str, str]:
    """
    Read shopify_client_id, shopify_client_secret, shopify_shop_domain
    from the organisations table.
    Returns (client_id, client_secret, shop_domain) — all '' on failure.
    S14: never raises.
    """
    try:
        result = (
            db.table("organisations")
            .select("shopify_client_id, shopify_client_secret, shopify_shop_domain")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        data = data or {}
        return (
            (data.get("shopify_client_id")     or "").strip(),
            (data.get("shopify_client_secret")  or "").strip(),
            (data.get("shopify_shop_domain")    or "").strip(),
        )
    except Exception as exc:
        logger.warning("_get_shopify_credentials failed org=%s: %s", org_id, exc)
        return "", "", ""


def _get_fresh_token(
    shop_domain: str,
    client_id: str,
    client_secret: str,
) -> str:
    """
    Obtain a fresh Shopify access token using the existing
    _get_shopify_token() function from shopify_service.py.
    Returns '' on any failure. S14: never raises.
    """
    try:
        from app.services.shopify_service import _get_shopify_token, ShopifyAuthError
        return _get_shopify_token(shop_domain, client_id, client_secret)
    except Exception as exc:
        logger.warning(
            "_get_fresh_token failed shop=%s: %s", shop_domain, exc
        )
        return ""


def _shopify_headers(access_token: str) -> dict:
    return {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Shopify API calls
# ---------------------------------------------------------------------------

def _fetch_orders(
    shop_domain: str,
    access_token: str,
    date_from: str,
    date_to: str,
    status: str = "paid",
    limit: int = 250,
) -> list[dict]:
    """
    Fetch orders from Shopify for the given period.
    Paginates through all pages up to 1000 orders max.
    S14: returns [] on any failure.
    """
    orders: list[dict] = []
    try:
        base_url = (
            f"https://{shop_domain}/admin/api/{_SHOPIFY_API_VERSION}/orders.json"
            f"?financial_status={status}"
            f"&created_at_min={date_from}T00:00:00"
            f"&created_at_max={date_to}T23:59:59"
            f"&limit={limit}"
            f"&fields=id,name,total_price,financial_status,fulfillment_status,"
            f"created_at,line_items,customer"
        )
        url: Optional[str] = base_url
        page = 0
        max_pages = 4  # cap at 1000 orders (4 × 250)

        while url and page < max_pages:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=_shopify_headers(access_token))

            if resp.status_code != 200:
                logger.warning(
                    "_fetch_orders: HTTP %d shop=%s body=%s",
                    resp.status_code, shop_domain, resp.text[:200],
                )
                break

            data    = resp.json()
            batch   = data.get("orders") or []
            orders += batch
            page   += 1

            # Pagination via Link header cursor
            link = resp.headers.get("Link") or ""
            url  = _parse_next_link(link)

    except Exception as exc:
        logger.warning("_fetch_orders failed shop=%s: %s", shop_domain, exc)

    return orders


def _parse_next_link(link_header: str) -> Optional[str]:
    """
    Parse Shopify pagination Link header for the next page URL.
    Mirrors the pattern in shopify_service.py.
    Returns None if no next page.
    """
    try:
        if not link_header:
            return None
        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url
        return None
    except Exception:
        return None


def _fetch_order_count(
    shop_domain: str,
    access_token: str,
    date_from: str,
    date_to: str,
    status: str = "paid",
) -> int:
    """
    Fast order count without fetching full order objects.
    S14: returns 0 on any failure.
    """
    try:
        url = (
            f"https://{shop_domain}/admin/api/{_SHOPIFY_API_VERSION}/orders/count.json"
            f"?financial_status={status}"
            f"&created_at_min={date_from}T00:00:00"
            f"&created_at_max={date_to}T23:59:59"
        )
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=_shopify_headers(access_token))
        if resp.status_code != 200:
            return 0
        return int(resp.json().get("count") or 0)
    except Exception as exc:
        logger.warning("_fetch_order_count failed shop=%s: %s", shop_domain, exc)
        return 0


# ---------------------------------------------------------------------------
# Data aggregation helpers
# ---------------------------------------------------------------------------

def _aggregate_orders(orders: list[dict]) -> dict:
    """
    Aggregate a list of Shopify order dicts into a summary.
    Returns summary dict with revenue, counts, top products, etc.
    """
    total_revenue   = 0.0
    fulfilled       = 0
    unfulfilled     = 0
    product_revenue: dict[str, float] = {}
    product_units:   dict[str, int]   = {}

    for order in orders:
        price = float(order.get("total_price") or 0)
        total_revenue += price

        fs = (order.get("fulfillment_status") or "").lower()
        if fs == "fulfilled":
            fulfilled += 1
        else:
            unfulfilled += 1

        for item in (order.get("line_items") or []):
            title = item.get("title") or "Unknown"
            qty   = int(item.get("quantity") or 1)
            item_price = float(item.get("price") or 0) * qty
            product_revenue[title] = product_revenue.get(title, 0.0) + item_price
            product_units[title]   = product_units.get(title, 0) + qty

    total_orders = len(orders)
    aov = round(total_revenue / total_orders, 2) if total_orders > 0 else 0.0

    # Top 5 products by revenue
    top_products = sorted(
        [
            {
                "title":       title,
                "revenue_ngn": round(rev, 2),
                "units_sold":  product_units.get(title, 0),
            }
            for title, rev in product_revenue.items()
        ],
        key=lambda x: x["revenue_ngn"],
        reverse=True,
    )[:5]

    fulfilment_rate = (
        round(fulfilled / total_orders * 100, 1) if total_orders > 0 else 0.0
    )

    return {
        "total_revenue_ngn":   round(total_revenue, 2),
        "total_orders":        total_orders,
        "average_order_value_ngn": aov,
        "fulfilled_orders":    fulfilled,
        "unfulfilled_orders":  unfulfilled,
        "fulfilment_rate_pct": fulfilment_rate,
        "top_products":        top_products,
    }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class ShopifyProvider(IntegrationProvider):
    """
    Reads live order and product data from Shopify Admin REST API.
    Uses per-org credentials from organisations table.
    Falls back gracefully if credentials are missing.
    """

    name = "shopify"

    def capabilities(self) -> dict:
        return {
            "label": "Shopify Orders & Revenue",
            "emoji": "🛍️",
            "examples": [
                "What's my Shopify revenue this month?",
                "How many orders did we get this week?",
                "What are my top selling products this month?",
                "How many unfulfilled orders do we have?",
            ],
        }

    def get_summary(
        self,
        db: Any,
        org_id: str,
        date_from: date,
        date_to: date,
    ) -> dict:
        """
        Returns Shopify order summary for the given period.
        Calls live Shopify API using per-org credentials.
        S14: returns {'available': False, 'reason': ...} on any failure.
        """
        try:
            # ── Credentials ─────────────────────────────────────────────────
            client_id, client_secret, shop_domain = _get_shopify_credentials(
                db, org_id
            )
            if not client_id or not client_secret or not shop_domain:
                logger.warning(
                    "ShopifyProvider.get_summary: missing credentials org=%s", org_id
                )
                return {
                    "available": False,
                    "reason": "Shopify credentials not configured for this org.",
                }

            # ── Fresh token ──────────────────────────────────────────────────
            access_token = _get_fresh_token(shop_domain, client_id, client_secret)
            if not access_token:
                return {
                    "available": False,
                    "reason": "Could not authenticate with Shopify. Check credentials.",
                }

            from_iso = date_from.isoformat()
            to_iso   = date_to.isoformat()

            # ── Fetch paid orders ────────────────────────────────────────────
            paid_orders = _fetch_orders(
                shop_domain, access_token, from_iso, to_iso, status="paid"
            )

            # ── Fetch refunded count separately ──────────────────────────────
            refunded_count = _fetch_order_count(
                shop_domain, access_token, from_iso, to_iso, status="refunded"
            )

            summary = _aggregate_orders(paid_orders)

            return {
                "available":               True,
                "provider":                self.name,
                "data_source":             "live_shopify_api",
                "shop_domain":             shop_domain,
                "date_from":               str(date_from),
                "date_to":                 str(date_to),
                "total_revenue_ngn":       summary["total_revenue_ngn"],
                "total_orders":            summary["total_orders"],
                "average_order_value_ngn": summary["average_order_value_ngn"],
                "fulfilled_orders":        summary["fulfilled_orders"],
                "unfulfilled_orders":      summary["unfulfilled_orders"],
                "fulfilment_rate_pct":     summary["fulfilment_rate_pct"],
                "refunded_orders":         refunded_count,
                "top_products":            summary["top_products"],
            }

        except Exception as exc:
            logger.warning(
                "ShopifyProvider.get_summary failed org=%s: %s", org_id, exc
            )
            return {
                "available": False,
                "reason": "Could not retrieve Shopify data right now.",
            }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns recent Shopify orders, optionally filtered by query text.
        Matches against order name, product title, or financial status.
        S14: returns [] on any failure.
        """
        try:
            client_id, client_secret, shop_domain = _get_shopify_credentials(
                db, org_id
            )
            if not client_id or not client_secret or not shop_domain:
                return []

            access_token = _get_fresh_token(shop_domain, client_id, client_secret)
            if not access_token:
                return []

            # Fetch recent orders across all statuses for search
            from datetime import datetime, timedelta, timezone
            date_to   = datetime.now(timezone.utc).date()
            date_from = date_to - timedelta(days=90)

            orders = _fetch_orders(
                shop_domain, access_token,
                date_from.isoformat(), date_to.isoformat(),
                status="any", limit=250,
            )

            query_lower = query.lower()
            # Split into individual words for flexible matching
            query_words = [w for w in query_lower.split() if len(w) > 2]
            results = []

            # Detect explicit status filters from query
            filter_unfulfilled = any(
                w in query_lower for w in ["unfulfill", "pending", "not fulfilled"]
            )
            filter_fulfilled = (
                "fulfilled" in query_lower and not filter_unfulfilled
            )
            filter_paid = "paid" in query_lower
            filter_refund = any(
                w in query_lower for w in ["refund", "cancelled", "canceled"]
            )

            for order in orders:
                fin_status     = (order.get("financial_status") or "").lower()
                fulfill_status = (order.get("fulfillment_status") or "unfulfilled").lower()
                order_name     = (order.get("name") or "").lower()
                line_titles    = " ".join(
                    (item.get("title") or "").lower()
                    for item in (order.get("line_items") or [])
                )
                customer_name = " ".join(filter(None, [
                    (order.get("customer") or {}).get("first_name", ""),
                    (order.get("customer") or {}).get("last_name", ""),
                ])).lower()

                # Apply explicit status filters first
                if filter_unfulfilled and fulfill_status == "fulfilled":
                    continue
                if filter_fulfilled and fulfill_status != "fulfilled":
                    continue
                if filter_paid and fin_status != "paid":
                    continue
                if filter_refund and "refund" not in fin_status and "cancel" not in fin_status:
                    continue

                # For non-status queries, check word-level match across all fields
                if query_words and not filter_unfulfilled and not filter_fulfilled \
                        and not filter_paid and not filter_refund:
                    all_text = " ".join([
                        order_name, fin_status, fulfill_status,
                        line_titles, customer_name
                    ])
                    if not any(word in all_text for word in query_words):
                        continue

                customer     = order.get("customer") or {}
                customer_name = " ".join(filter(None, [
                    customer.get("first_name", ""),
                    customer.get("last_name", ""),
                ])).strip() or "—"
                results.append({
                    "order_name":         order.get("name") or "—",
                    "customer_name":      customer_name,
                    "customer_email":     customer.get("email") or "—",
                    "total_ngn":          float(order.get("total_price") or 0),
                    "financial_status":   order.get("financial_status") or "—",
                    "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
                    "created_at":         (order.get("created_at") or "")[:10],
                    "items":              [
                        {
                            "title": item.get("title") or "—",
                            "qty":   int(item.get("quantity") or 1),
                            "price": float(item.get("price") or 0),
                        }
                        for item in (order.get("line_items") or [])[:3]
                    ],
                })
                if len(results) >= limit:
                    break

            return results

        except Exception as exc:
            logger.warning(
                "ShopifyProvider.search failed org=%s: %s", org_id, exc
            )
            return []
