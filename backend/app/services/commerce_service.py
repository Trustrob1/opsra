"""
COMM-1 — Commerce Service
Handles cart state, session lifecycle, and Shopify checkout generation.
All functions S14 — never raises.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_shopify_credentials(db, org_id: str) -> tuple:
    """
    Returns (shop_domain, access_token).
    Raises ValueError if not connected or credentials incomplete.
    """
    result = (
        db.table("organisations")
        .select("shopify_shop_domain, shopify_access_token, shopify_connected")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    data = data or {}
    if not data.get("shopify_connected"):
        raise ValueError(f"Shopify not connected for org {org_id}")
    domain = (data.get("shopify_shop_domain") or "").strip()
    token = (data.get("shopify_access_token") or "").strip()
    if not domain or not token:
        raise ValueError(f"Shopify credentials incomplete for org {org_id}")
    return domain, token


def _find_variant_by_id(product: dict, variant_id: str) -> dict:
    """Find a variant dict by its id in product.variants. Returns {} if not found."""
    for v in (product.get("variants") or []):
        vid = str(v.get("id", "") or v.get("variant_id", "") or "")
        if vid and vid == str(variant_id):
            return v
    return {}


def _build_item_name(product: dict, variant: dict) -> str:
    """Build display name combining product title and variant title."""
    title = (product.get("title") or product.get("name") or "Product").strip()
    variant_title = (variant.get("title") or "").strip()
    if variant_title and variant_title.lower() not in ("default title", "default", ""):
        return f"{title} — {variant_title}"
    return title


def _default_variant(product: dict) -> dict:
    """Return a minimal variant dict for single/no-variant products."""
    return {
        "id": None,
        "variant_id": None,
        "price": product.get("price") or 0,
        "title": "Default",
    }


def _recalc_subtotal(cart: list) -> float:
    """Recalculate cart subtotal from items."""
    return round(
        sum(float(item.get("price", 0)) * int(item.get("quantity", 0))
            for item in cart),
        2,
    )


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

def get_or_create_commerce_session(
    db,
    org_id: str,
    phone_number: str,
    lead_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> dict:
    """
    C4 — Atomically fetch active (open or checkout_sent) commerce session or
    create a new one.

    The unique index idx_cs_open_session on (org_id, phone_number)
    WHERE status IN ('open', 'checkout_sent') ensures only one active session
    exists per org+phone. On a concurrent duplicate INSERT, the DB raises a
    unique violation (23505) and we fall back to fetching the winner.

    If creating new:
      - lead_id provided → set session.lead_id.
      - customer_id provided → set session.customer_id.

    S14 — never raises. Returns {} on unrecoverable error.
    """
    try:
        # Fast path: existing active session
        existing = (
            db.table("commerce_sessions")
            .select("*")
            .eq("org_id", org_id)
            .eq("phone_number", phone_number)
            .in_("status", ["open", "checkout_sent"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = existing.data if isinstance(existing.data, list) else []
        if rows:
            return rows[0]

        new_session: dict = {
            "org_id": org_id,
            "phone_number": phone_number,
            "status": "open",
            "cart": [],
            "subtotal": 0,
        }
        if lead_id:
            new_session["lead_id"] = lead_id
        if customer_id:
            new_session["customer_id"] = customer_id

        try:
            result = db.table("commerce_sessions").insert(new_session).execute()
            created = result.data if isinstance(result.data, list) else []
            if created:
                return created[0]
            # Supabase returned empty without raising — fetch the winner
            fallback = (
                db.table("commerce_sessions")
                .select("*")
                .eq("org_id", org_id)
                .eq("phone_number", phone_number)
                .in_("status", ["open", "checkout_sent"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            fb_rows = fallback.data if isinstance(fallback.data, list) else []
            return fb_rows[0] if fb_rows else new_session

        except Exception as insert_exc:
            err_str = str(insert_exc).lower()
            if (
                "23505" in err_str
                or "duplicate" in err_str
                or "unique" in err_str
            ):
                # Concurrent INSERT — another handler won the race, fetch it
                logger.debug(
                    "get_or_create_commerce_session: duplicate INSERT org=%s "
                    "phone=%s — returning winner",
                    org_id, phone_number,
                )
                fallback = (
                    db.table("commerce_sessions")
                    .select("*")
                    .eq("org_id", org_id)
                    .eq("phone_number", phone_number)
                    .in_("status", ["open", "checkout_sent"])
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                fb_rows = fallback.data if isinstance(fallback.data, list) else []
                return fb_rows[0] if fb_rows else new_session
            raise  # unexpected DB error — propagate to outer S14 handler

    except Exception as exc:
        logger.warning(
            "get_or_create_commerce_session failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )
        return {}


# ---------------------------------------------------------------------------
# Cart Operations
# ---------------------------------------------------------------------------

def add_to_cart(
    db,
    session: dict,
    product: dict,
    variant_id: str,
    quantity: int = 1,
) -> dict:
    """
    Append item to session.cart JSONB array (or increment quantity if exists).
    Item shape: { id, shopify_id, variant_id, name, price, quantity, image_url }
    Recalculates session.subtotal.
    S14 — never raises. Returns (possibly unchanged) session dict.
    """
    try:
        cart = list(session.get("cart") or [])
        variant_data = _find_variant_by_id(product, variant_id)
        price = float(variant_data.get("price") or product.get("price") or 0)

        # Increment if already in cart
        found = False
        for item in cart:
            if str(item.get("variant_id", "")) == str(variant_id):
                item["quantity"] += quantity
                found = True
                break

        if not found:
            cart.append({
                "id": product.get("id"),
                "shopify_id": product.get("shopify_id"),
                "variant_id": variant_id,
                "name": _build_item_name(product, variant_data),
                "price": price,
                "quantity": quantity,
                "image_url": product.get("image_url"),
            })

        subtotal = _recalc_subtotal(cart)

        db.table("commerce_sessions").update({
            "cart": cart,
            "subtotal": subtotal,
            "updated_at": "now()",
        }).eq("id", session["id"]).execute()

        # Update in-memory session so caller has fresh state
        session = dict(session)
        session["cart"] = cart
        session["subtotal"] = subtotal
        return session

    except Exception as exc:
        logger.warning(
            "add_to_cart failed session=%s: %s",
            session.get("id"), exc,
        )
        return session


def remove_from_cart(db, session_id: str, product_id: str) -> dict:
    """
    Remove item by product id from cart. Recalculates subtotal.
    S14 — never raises. Returns updated session dict (or {} on failure).
    """
    try:
        result = (
            db.table("commerce_sessions")
            .select("*")
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        session = result.data
        if isinstance(session, list):
            session = session[0] if session else {}
        session = dict(session or {})

        cart = list(session.get("cart") or [])
        new_cart = [item for item in cart if item.get("id") != product_id]
        subtotal = _recalc_subtotal(new_cart)

        db.table("commerce_sessions").update({
            "cart": new_cart,
            "subtotal": subtotal,
            "updated_at": "now()",
        }).eq("id", session_id).execute()

        session["cart"] = new_cart
        session["subtotal"] = subtotal
        return session

    except Exception as exc:
        logger.warning("remove_from_cart failed session=%s: %s", session_id, exc)
        return {}


def get_cart_summary(session: dict) -> str:
    """
    Returns a WhatsApp-formatted cart summary string.
    e.g. "🛒 Your cart:\n• Product A x1 — ₦5,000\n• Product B x2 — ₦10,000\n\nTotal: ₦15,000"
    """
    cart = session.get("cart") or []
    if not cart:
        return "🛒 Your cart is empty."

    lines = ["🛒 Your cart:"]
    for item in cart:
        qty = int(item.get("quantity", 1))
        price = float(item.get("price", 0))
        lines.append(f"• {item.get('name', 'Product')} x{qty} — ₦{price * qty:,.0f}")

    subtotal = _recalc_subtotal(cart)
    lines.append(f"\nTotal: ₦{subtotal:,.0f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def generate_shopify_checkout(db, org_id: str, session: dict) -> str:
    """
    Creates a Shopify Draft Order and returns the invoice_url.
    Pre-populates phone on the draft order so Shopify includes it in
    abandoned_checkouts webhook payload — enables reliable session matching.
    Updates session: checkout_url = invoice_url, status = checkout_sent.
    S14 — never raises. Returns existing checkout_url on any failure.
    """
    try:
        shop_domain, access_token = _get_shopify_credentials(db, org_id)

        cart = session.get("cart") or []
        if not cart:
            logger.warning(
                "generate_shopify_checkout: empty cart session=%s", session.get("id")
            )
            return session.get("checkout_url") or ""

        line_items = []
        for item in cart:
            entry: dict = {
                "quantity": int(item.get("quantity", 1)),
                "price": str(item.get("price", "0")),
                "title": item.get("name", "Product"),
            }
            if item.get("variant_id"):
                entry["variant_id"] = item["variant_id"]
            line_items.append(entry)

        phone = (session.get("phone_number") or "").strip()
        draft_payload: dict = {
            "draft_order": {
                "line_items": line_items,
                "use_customer_default_address": False,
            }
        }
        if phone:
            draft_payload["draft_order"]["customer"] = {"phone": phone}

        url = f"https://{shop_domain}/admin/api/2024-01/draft_orders.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=draft_payload, headers=headers)
            resp.raise_for_status()

        invoice_url = resp.json().get("draft_order", {}).get("invoice_url") or ""

        db.table("commerce_sessions").update({
            "checkout_url": invoice_url,
            "status": "checkout_sent",
            "updated_at": "now()",
        }).eq("id", session["id"]).execute()

        return invoice_url

    except Exception as exc:
        logger.warning(
            "generate_shopify_checkout failed org=%s session=%s: %s",
            org_id, session.get("id"), exc,
        )
        return session.get("checkout_url") or ""


def mark_cart_completed(db, session_id: str, shopify_order_id) -> None:
    """
    Updates: status=completed, shopify_order_id, completed_at=now().
    S14 — never raises.
    """
    try:
        db.table("commerce_sessions").update({
            "status": "completed",
            "shopify_order_id": shopify_order_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": "now()",
        }).eq("id", session_id).execute()
    except Exception as exc:
        logger.warning("mark_cart_completed failed session=%s: %s", session_id, exc)


def mark_cart_abandoned(db, session_id: str) -> None:
    """
    Updates: status=abandoned, abandoned_at=now().
    S14 — never raises.
    """
    try:
        db.table("commerce_sessions").update({
            "status": "abandoned",
            "abandoned_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": "now()",
        }).eq("id", session_id).execute()
    except Exception as exc:
        logger.warning("mark_cart_abandoned failed session=%s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Lead Attribution
# ---------------------------------------------------------------------------

def convert_lead_on_purchase(db, org_id: str, lead_id: str) -> None:
    """
    Called when order.created fires and commerce_session.lead_id is set.
    Updates lead: stage=converted, converted_at=now().
    Writes audit log: action="lead.converted_via_commerce".
    S14 — never raises.
    """
    try:
        now_ts = datetime.now(timezone.utc).isoformat()

        # Fetch old stage for audit log (best-effort)
        old_stage = None
        try:
            stage_r = (
                db.table("leads")
                .select("stage")
                .eq("id", lead_id)
                .eq("org_id", org_id)
                .maybe_single()
                .execute()
            )
            stage_d = stage_r.data
            if isinstance(stage_d, list):
                stage_d = stage_d[0] if stage_d else None
            old_stage = (stage_d or {}).get("stage")
        except Exception:
            pass

        db.table("leads").update({
            "stage": "converted",
            "converted_at": now_ts,
            "updated_at": now_ts,
        }).eq("id", lead_id).eq("org_id", org_id).execute()

        db.table("audit_logs").insert({
            "org_id": org_id,
            "action": "lead.converted_via_commerce",
            "resource_type": "lead",
            "resource_id": lead_id,
            "old_value": {"stage": old_stage},
            "new_value": {"stage": "converted"},
        }).execute()

    except Exception as exc:
        logger.warning(
            "convert_lead_on_purchase failed org=%s lead=%s: %s",
            org_id, lead_id, exc,
        )
