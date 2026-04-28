"""
app/services/shopify_service.py
---------------------------------
SHOP-1A: Shopify Integration — core service layer.

Public API:
  verify_webhook(raw_body, signature_header, secret) -> bool
  sync_product(db, org_id, shopify_product) -> dict
  handle_product_deleted(db, org_id, shopify_product_id) -> None
  bulk_sync_products(db, org_id, access_token, shop_domain) -> dict
  handle_abandoned_cart(db, org_id, checkout) -> None
  handle_order_created(db, org_id, order) -> None
  handle_fulfillment_created(db, org_id, fulfillment) -> None

All public functions follow S14 — wrapped in try/except, never raise.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def verify_webhook(
    raw_body: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """
    Verify Shopify X-Shopify-Hmac-Sha256 header.
    Shopify signs with HMAC-SHA256 and base64-encodes the result.
    Returns False if header is missing, secret is empty, or signature mismatches.
    S14: returns False on any exception.
    """
    try:
        import base64
        if not signature_header or not secret:
            return False
        computed = base64.b64encode(
            hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        ).decode("utf-8")
        return hmac.compare_digest(computed, signature_header)
    except Exception as exc:
        logger.warning("verify_webhook failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Product sync
# ---------------------------------------------------------------------------

def sync_product(db, org_id: str, shopify_product: dict) -> dict:
    """
    Upsert a Shopify product into the products table.
    Uses (org_id, shopify_id) as the conflict target.
    Returns the upserted product row.
    S14.
    """
    try:
        shopify_id = shopify_product.get("id")
        now = datetime.now(timezone.utc).isoformat()

        # Grab the first image URL if present
        images = shopify_product.get("images") or []
        image_url = images[0].get("src") if images else None

        # Variants — store full list as JSONB
        variants = shopify_product.get("variants") or []

        # Price from first variant
        price = None
        compare_at_price = None
        if variants:
            price = _safe_decimal(variants[0].get("price"))
            compare_at_price = _safe_decimal(variants[0].get("compare_at_price"))

        # Tags
        raw_tags = shopify_product.get("tags") or ""
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

        row = {
            "org_id":           org_id,
            "shopify_id":       shopify_id,
            "title":            (shopify_product.get("title") or "")[:500],
            "description":      shopify_product.get("body_html") or None,
            "price":            price,
            "compare_at_price": compare_at_price,
            "image_url":        image_url,
            "handle":           shopify_product.get("handle") or None,
            "status":           shopify_product.get("status") or "active",
            "is_active":        (shopify_product.get("status") or "active") != "archived",
            "variants":         variants,
            "tags":             tags,
            "updated_at":       now,
        }

        result = (
            db.table("products")
            .upsert(row, on_conflict="org_id,shopify_id")
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else row
        logger.info("sync_product: upserted shopify_id=%s for org=%s", shopify_id, org_id)
        return data or row

    except Exception as exc:
        logger.warning("sync_product failed org=%s shopify_id=%s: %s",
                       org_id, shopify_product.get("id"), exc)
        return {}


def handle_product_deleted(db, org_id: str, shopify_product_id: int) -> None:
    """
    Soft-delete a product when Shopify fires products/delete.
    Sets is_active=False rather than hard-deleting.
    S14.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.table("products").update({
            "is_active":  False,
            "status":     "archived",
            "updated_at": now,
        }).eq("org_id", org_id).eq("shopify_id", shopify_product_id).execute()
        logger.info("handle_product_deleted: shopify_id=%s org=%s", shopify_product_id, org_id)
    except Exception as exc:
        logger.warning("handle_product_deleted failed org=%s id=%s: %s",
                       org_id, shopify_product_id, exc)


def bulk_sync_products(
    db,
    org_id: str,
    access_token: str,
    shop_domain: str,
) -> dict:
    """
    Fetch all products from Shopify REST API and upsert into products table.
    Paginates using page_info cursor (250 per page).
    Returns { synced: int, failed: int }.
    S14: per-product failure never stops the loop.
    """
    synced = 0
    failed = 0
    try:
        url = f"https://{shop_domain}/admin/api/2024-01/products.json?limit=250"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        while url:
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                products = data.get("products") or []
                for p in products:
                    try:
                        sync_product(db, org_id, p)
                        synced += 1
                    except Exception as exc:
                        logger.warning("bulk_sync: product %s failed: %s", p.get("id"), exc)
                        failed += 1

                # Pagination — Link header cursor
                link_header = resp.headers.get("Link") or ""
                url = _parse_next_link(link_header)
            except Exception as exc:
                logger.warning("bulk_sync_products page fetch failed org=%s: %s", org_id, exc)
                break

        # Update last_sync_at
        try:
            db.table("organisations").update({
                "shopify_last_sync_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", org_id).execute()
        except Exception:
            pass

        logger.info("bulk_sync_products org=%s synced=%d failed=%d", org_id, synced, failed)
    except Exception as exc:
        logger.warning("bulk_sync_products failed org=%s: %s", org_id, exc)

    return {"synced": synced, "failed": failed}


# ---------------------------------------------------------------------------
# Order / fulfilment / cart handlers
# ---------------------------------------------------------------------------

def handle_abandoned_cart(db, org_id: str, checkout: dict) -> None:
    """
    Shopify checkouts/update webhook — fires when a checkout is created or updated.
    Matches the checkout phone to leads/customers.
    If no match is found but a phone exists, auto-creates a silent lead
    (no qualification bot, no triage menu — Shopify is the entry point).
    Creates or updates a commerce_session.
    Always sends a WhatsApp recovery message when a phone number is present.
    S14.
    """
    try:
        from app.services.whatsapp_service import send_abandoned_cart_message

        raw_phone = (checkout.get("phone") or "").strip()
        phone = _normalise_phone(raw_phone) if raw_phone else None

        now = datetime.now(timezone.utc).isoformat()

        if not phone:
            logger.info(
                "handle_abandoned_cart: no phone on checkout %s — skipping",
                checkout.get("id"),
            )
            return

        # COMM-1: Check for an existing WhatsApp commerce_session first.
        # If found, this is a Shopify-side abandonment of a WhatsApp-initiated
        # cart. Send WA recovery and return — do NOT create a lead.
        try:
            wa_cs_r = (
                db.table("commerce_sessions")
                .select("id, checkout_url")
                .eq("org_id", org_id)
                .eq("phone_number", phone)
                .in_("status", ["open", "checkout_sent"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            wa_cs_rows = wa_cs_r.data if isinstance(wa_cs_r.data, list) else []
            wa_cs = wa_cs_rows[0] if wa_cs_rows else None
        except Exception as _cs_exc:
            logger.warning(
                "handle_abandoned_cart: commerce_session lookup failed org=%s: %s",
                org_id, _cs_exc,
            )
            wa_cs = None

        if wa_cs:
            # WhatsApp-originated cart — update session + send recovery, skip lead creation
            recovery_url = (
                checkout.get("abandoned_checkout_url")
                or checkout.get("checkout_url")
                or wa_cs.get("checkout_url")
                or ""
            )
            try:
                db.table("commerce_sessions").update({
                    "status":       "checkout_sent",
                    "checkout_url": recovery_url,
                    "updated_at":   now,
                }).eq("id", wa_cs["id"]).execute()
            except Exception as _upd_exc:
                logger.warning(
                    "handle_abandoned_cart: session update failed cs=%s: %s",
                    wa_cs["id"], _upd_exc,
                )
            # Set commerce_state on whatsapp_session so next message routes correctly
            try:
                db.table("whatsapp_sessions").update({
                    "commerce_state": "commerce_checkout",
                }).eq("org_id", org_id).eq("phone_number", phone).execute()
            except Exception as _ws_exc:
                logger.warning(
                    "handle_abandoned_cart: whatsapp_session state update failed: %s",
                    _ws_exc,
                )
            # Send WhatsApp recovery message
            try:
                from app.services.whatsapp_service import send_checkout_link
                recovery_config = {
                    "checkout_message":
                        "Looks like you didn't complete your order. "
                        "Your cart is still saved — tap the link to finish your purchase."
                }
                send_checkout_link(
                    db=db,
                    org_id=org_id,
                    phone_number=phone,
                    checkout_url=recovery_url,
                    commerce_config=recovery_config,
                )
            except Exception as _send_exc:
                logger.warning(
                    "handle_abandoned_cart: recovery send failed org=%s phone=%s: %s",
                    org_id, phone, _send_exc,
                )
            return  # ← Do NOT create a lead

        # No WhatsApp commerce_session — existing lead-creation behaviour
        # Attempt to match phone to existing lead or customer
        lead_id, customer_id = _match_phone_to_record(db, org_id, phone)

        # No match — auto-create a silent lead (no qualification, no triage)
        if not lead_id and not customer_id:
            lead_id = _auto_create_lead_from_checkout(db, org_id, phone, checkout, now)

        # Upsert commerce_session
        existing = None
        shopify_checkout_id = checkout.get("id")
        if shopify_checkout_id:
            existing_r = (
                db.table("commerce_sessions")
                .select("id")
                .eq("org_id", org_id)
                .eq("shopify_order_id", shopify_checkout_id)
                .maybe_single()
                .execute()
            )
            existing_d = existing_r.data
            if isinstance(existing_d, list):
                existing_d = existing_d[0] if existing_d else None
            existing = existing_d

        cart_items = _build_cart_from_checkout(checkout)
        checkout_url = checkout.get("abandoned_checkout_url") or checkout.get("checkout_url")

        if existing:
            db.table("commerce_sessions").update({
                "cart":         cart_items,
                "checkout_url": checkout_url,
                "lead_id":      lead_id or existing.get("lead_id"),
                "status":       "open",
                "updated_at":   now,
            }).eq("id", existing["id"]).execute()
        else:
            db.table("commerce_sessions").insert({
                "org_id":           org_id,
                "phone_number":     phone,
                "lead_id":          lead_id,
                "customer_id":      customer_id,
                "status":           "open",
                "cart":             cart_items,
                "shopify_order_id": shopify_checkout_id,
                "checkout_url":     checkout_url,
                "created_at":       now,
                "updated_at":       now,
            }).execute()

        # Always send recovery message — phone is guaranteed to exist at this point
        send_abandoned_cart_message(
            db=db,
            org_id=org_id,
            phone_number=phone,
            checkout_url=checkout_url,
            cart_items=cart_items,
        )

    except Exception as exc:
        logger.warning("handle_abandoned_cart failed org=%s: %s", org_id, exc)


def _parse_utm_from_url(url: str) -> dict:
    """
    GPM-1D: Parse UTM parameters from a URL string.
    Returns dict with keys: utm_source, utm_campaign, utm_medium, utm_ad.
    All values are str or None.
    S14: returns all-None on any failure — never raises.
    """
    result = {"utm_source": None, "utm_campaign": None, "utm_medium": None, "utm_ad": None}
    try:
        if not url:
            return result
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        result["utm_source"]   = (qs.get("utm_source")   or [None])[0] or None
        result["utm_campaign"] = (qs.get("utm_campaign") or [None])[0] or None
        result["utm_medium"]   = (qs.get("utm_medium")   or [None])[0] or None
        result["utm_ad"]       = (qs.get("utm_ad") or qs.get("utm_content") or [None])[0] or None
    except Exception as exc:
        logger.warning("_parse_utm_from_url failed (url=%r): %s", url, exc)
    return result


def handle_order_created(db, org_id: str, order: dict) -> None:
    """
    Shopify orders/create webhook.
    Marks commerce_session as completed.
    Sends WhatsApp order confirmation.
    S14.
    """
    try:
        from app.services.whatsapp_service import send_order_confirmation_message

        raw_phone = _extract_order_phone(order)
        phone = _normalise_phone(raw_phone) if raw_phone else None
        shopify_order_id = order.get("id")
        order_name = order.get("name") or f"#{shopify_order_id}"
        now = datetime.now(timezone.utc).isoformat()

        # Close any open commerce_session for this phone
        if phone:
            db.table("commerce_sessions").update({
                "status":        "completed",
                "shopify_order_id": shopify_order_id,
                "completed_at":  now,
                "updated_at":    now,
            }).eq("org_id", org_id).eq("phone_number", phone).eq("status", "open").execute()

        # COMM-1: Post-order commerce session completion
        if phone:
            try:
                from app.services.commerce_service import (
                    mark_cart_completed,
                    convert_lead_on_purchase,
                )
                # Fetch the session we just closed to get lead_id / customer_id
                closed_cs_r = (
                    db.table("commerce_sessions")
                    .select("id, lead_id, customer_id")
                    .eq("org_id", org_id)
                    .eq("phone_number", phone)
                    .eq("shopify_order_id", shopify_order_id)
                    .maybe_single()
                    .execute()
                )
                closed_cs_d = closed_cs_r.data
                if isinstance(closed_cs_d, list):
                    closed_cs_d = closed_cs_d[0] if closed_cs_d else None

                if not closed_cs_d:
                    # Session wasn't matched by order_id yet — find by phone + status=completed
                    fallback_r = (
                        db.table("commerce_sessions")
                        .select("id, lead_id, customer_id")
                        .eq("org_id", org_id)
                        .eq("phone_number", phone)
                        .eq("status", "completed")
                        .order("updated_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    fb_rows = fallback_r.data if isinstance(fallback_r.data, list) else []
                    closed_cs_d = fb_rows[0] if fb_rows else None

                if closed_cs_d:
                    cs_id   = closed_cs_d["id"]
                    lead_id = closed_cs_d.get("lead_id")
                    cust_id = closed_cs_d.get("customer_id")

                    # Ensure shopify_order_id is stamped (idempotent)
                    mark_cart_completed(db, cs_id, shopify_order_id)

                    # Convert linked lead if present
                    if lead_id:
                        convert_lead_on_purchase(db, org_id, lead_id)

                    # Create customer record if not already linked
                    if not cust_id:
                        try:
                            first_name = (order.get("billing_address") or {}).get(
                                "first_name"
                            ) or (order.get("customer") or {}).get("first_name") or ""
                            last_name  = (order.get("billing_address") or {}).get(
                                "last_name"
                            ) or (order.get("customer") or {}).get("last_name") or ""
                            full_name  = f"{first_name} {last_name}".strip() or phone
                            email      = (
                                order.get("email")
                                or (order.get("customer") or {}).get("email")
                            )
                            new_cust_r = db.table("customers").insert({
                                "org_id":           org_id,
                                "full_name":        full_name,
                                "email":            email,
                                "whatsapp_number":  phone,
                                "phone":            phone,
                                "created_at":       now,
                                "updated_at":       now,
                            }).execute()
                            new_cust_rows = (
                                new_cust_r.data
                                if isinstance(new_cust_r.data, list)
                                else []
                            )
                            if new_cust_rows:
                                db.table("commerce_sessions").update({
                                    "customer_id": new_cust_rows[0]["id"],
                                    "updated_at":  now,
                                }).eq("id", cs_id).execute()
                        except Exception as _cust_exc:
                            logger.warning(
                                "handle_order_created: customer creation failed "
                                "org=%s phone=%s: %s",
                                org_id, phone, _cust_exc,
                            )

                    # Clear commerce_state on whatsapp_session
                    try:
                        db.table("whatsapp_sessions").update({
                            "commerce_state": None,
                        }).eq("org_id", org_id).eq("phone_number", phone).execute()
                    except Exception as _ws_exc:
                        logger.warning(
                            "handle_order_created: whatsapp_session clear failed: %s",
                            _ws_exc,
                        )

            except Exception as _comm_exc:
                logger.warning(
                    "handle_order_created: COMM-1 block failed org=%s: %s",
                    org_id, _comm_exc,
                )

        # GPM-1D: Extract UTM attribution from Shopify landing_site URL
        landing_site = (order.get("landing_site") or "").strip()
        utm_data = _parse_utm_from_url(landing_site)

        # Update commerce_session with UTM data if present
        if any(utm_data.values()) and phone:
            try:
                cs_r = (
                    db.table("commerce_sessions")
                    .select("id, lead_id")
                    .eq("org_id", org_id)
                    .eq("shopify_order_id", shopify_order_id)
                    .maybe_single()
                    .execute()
                )
                cs_d = cs_r.data
                if isinstance(cs_d, list):
                    cs_d = cs_d[0] if cs_d else None
                if cs_d:
                    utm_update = {k: v for k, v in utm_data.items() if v is not None}
                    if utm_update:
                        db.table("commerce_sessions").update({
                            **utm_update,
                            "updated_at": now,
                        }).eq("id", cs_d["id"]).execute()

                    # Write UTM to linked lead only if first_touch is unset (immutability rule)
                    lead_id = cs_d.get("lead_id")
                    if lead_id and utm_data.get("utm_source"):
                        try:
                            lead_r = (
                                db.table("leads")
                                .select("id, utm_source")
                                .eq("id", lead_id)
                                .eq("org_id", org_id)
                                .maybe_single()
                                .execute()
                            )
                            lead_d = lead_r.data
                            if isinstance(lead_d, list):
                                lead_d = lead_d[0] if lead_d else None
                            if lead_d and not lead_d.get("utm_source"):
                                lead_fields = {}
                                if utm_data.get("utm_source"):
                                    lead_fields["utm_source"]   = utm_data["utm_source"]
                                    lead_fields["first_touch_team"] = utm_data["utm_source"]
                                if utm_data.get("utm_campaign"):
                                    lead_fields["campaign_id"]  = utm_data["utm_campaign"]
                                if utm_data.get("utm_ad"):
                                    lead_fields["utm_ad"]       = utm_data["utm_ad"]
                                if lead_fields:
                                    db.table("leads").update(lead_fields).eq("id", lead_id).execute()
                        except Exception as exc:
                            logger.warning("handle_order_created: lead UTM update failed lead=%s: %s", lead_id, exc)
            except Exception as exc:
                logger.warning("handle_order_created: UTM session update failed org=%s: %s", org_id, exc)

        # Send confirmation
        if phone:
            total = order.get("total_price") or "0.00"
            send_order_confirmation_message(
                db=db,
                org_id=org_id,
                phone_number=phone,
                order_name=order_name,
                total=total,
            )

    except Exception as exc:
        logger.warning("handle_order_created failed org=%s: %s", org_id, exc)


def handle_fulfillment_created(db, org_id: str, fulfillment: dict) -> None:
    """
    Shopify fulfillments/create webhook.
    Sends WhatsApp dispatch notification with tracking link if present.
    S14.
    """
    try:
        from app.services.whatsapp_service import send_fulfillment_message

        # Fulfillment payload nests the order — extract phone from there
        order = fulfillment.get("order") or {}
        raw_phone = _extract_order_phone(order)
        if not raw_phone:
            # Some fulfillment payloads omit the nested order — skip silently
            logger.info("handle_fulfillment_created: no phone in fulfillment payload — skipping")
            return

        phone = _normalise_phone(raw_phone)
        tracking_url = None
        tracking_company = None

        tracking_info = fulfillment.get("tracking_info") or {}
        if isinstance(tracking_info, list) and tracking_info:
            tracking_info = tracking_info[0]
        if isinstance(tracking_info, dict):
            tracking_url = tracking_info.get("url")
            tracking_company = tracking_info.get("company")

        send_fulfillment_message(
            db=db,
            org_id=org_id,
            phone_number=phone,
            tracking_url=tracking_url,
            tracking_company=tracking_company,
        )

    except Exception as exc:
        logger.warning("handle_fulfillment_created failed org=%s: %s", org_id, exc)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_decimal(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalise_phone(phone: str) -> str:
    """Strip non-digits, ensure + prefix. Mirrors lead_service._normalise_phone."""
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return phone
    return f"+{digits}"


def _parse_next_link(link_header: str) -> Optional[str]:
    """
    Parse Shopify Link header for the next page URL.
    Format: <https://...>; rel="next", <https://...>; rel="previous"
    Returns URL string or None.
    """
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start + 1:end]
    return None


def _match_phone_to_record(db, org_id: str, phone: Optional[str]):
    """
    Resolution strategy (Technical Spec SHOP-1A):
      1. Match phone → customers table
      2. Match phone → leads table
      3. No match → (None, None)
    Returns (lead_id, customer_id).
    S14.
    """
    lead_id = None
    customer_id = None
    if not phone:
        return lead_id, customer_id
    try:
        # Customer match
        cust_r = (
            db.table("customers")
            .select("id")
            .eq("org_id", org_id)
            .eq("whatsapp_number", phone)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        cust_d = cust_r.data
        if isinstance(cust_d, list):
            cust_d = cust_d[0] if cust_d else None
        if cust_d:
            customer_id = cust_d["id"]
            return lead_id, customer_id

        # Lead match
        lead_r = (
            db.table("leads")
            .select("id")
            .eq("org_id", org_id)
            .eq("whatsapp_number", phone)
            .maybe_single()
            .execute()
        )
        lead_d = lead_r.data
        if isinstance(lead_d, list):
            lead_d = lead_d[0] if lead_d else None
        if lead_d:
            lead_id = lead_d["id"]
    except Exception as exc:
        logger.warning("_match_phone_to_record failed org=%s phone=%s: %s", org_id, phone, exc)
    return lead_id, customer_id


def _auto_create_lead_from_checkout(
    db,
    org_id: str,
    phone: str,
    checkout: dict,
    now: str,
) -> Optional[str]:
    """
    Silently create a lead from a Shopify checkout phone number.
    No qualification bot. No triage menu. No WhatsApp message at this point.
    The cart recovery message is sent by the caller immediately after.

    Name resolution (in order):
      1. billing_address.name
      2. billing_address.first_name + last_name
      3. shipping_address.name
      4. phone number (fallback)

    Returns the new lead_id or None on failure.
    S14.
    """
    try:
        from app.services.lead_service import create_lead
        from app.models.leads import LeadCreate, LeadSource

        # Resolve contact name from checkout addresses
        contact_name = None
        for addr_key in ("billing_address", "shipping_address"):
            addr = checkout.get(addr_key) or {}
            name = (addr.get("name") or "").strip()
            if not name:
                first = (addr.get("first_name") or "").strip()
                last = (addr.get("last_name") or "").strip()
                name = f"{first} {last}".strip()
            if name:
                contact_name = name
                break
        contact_name = contact_name or phone

        payload = LeadCreate(
            full_name  = contact_name,
            phone      = phone,
            whatsapp   = phone,
            source     = LeadSource.whatsapp_inbound.value,
        )
        new_lead = create_lead(
            db=db,
            org_id=org_id,
            user_id="system",
            payload=payload,
        )
        lead_id = new_lead["id"]
        logger.info(
            "_auto_create_lead_from_checkout: created lead %s for phone %s org=%s",
            lead_id, phone, org_id,
        )
        return lead_id

    except Exception as exc:
        # Duplicate phone — lead already exists, re-lookup
        from app.models.common import ErrorCode
        detail = getattr(exc, "detail", {}) or {}
        code = detail.get("code", "") if isinstance(detail, dict) else str(detail)
        if code == ErrorCode.DUPLICATE_DETECTED:
            try:
                lead_r = (
                    db.table("leads")
                    .select("id")
                    .eq("org_id", org_id)
                    .eq("whatsapp_number", phone)
                    .maybe_single()
                    .execute()
                )
                lead_d = lead_r.data
                if isinstance(lead_d, list):
                    lead_d = lead_d[0] if lead_d else None
                if lead_d:
                    logger.info(
                        "_auto_create_lead_from_checkout: duplicate — re-used lead %s",
                        lead_d["id"],
                    )
                    return lead_d["id"]
            except Exception as inner_exc:
                logger.warning(
                    "_auto_create_lead_from_checkout: re-lookup failed: %s", inner_exc
                )
        else:
            logger.warning(
                "_auto_create_lead_from_checkout failed org=%s phone=%s: %s",
                org_id, phone, exc,
            )
        return None


def _build_cart_from_checkout(checkout: dict) -> list:
    """Build a clean cart list from a Shopify checkout payload."""
    items = []
    try:
        for li in (checkout.get("line_items") or []):
            items.append({
                "shopify_variant_id": li.get("variant_id"),
                "title":              li.get("title") or "",
                "quantity":           li.get("quantity") or 1,
                "price":              _safe_decimal(li.get("price")),
            })
    except Exception:
        pass
    return items


def _extract_order_phone(order: dict) -> Optional[str]:
    """
    Extract phone from Shopify order payload.
    Checks: order.phone → billing_address.phone → shipping_address.phone
    """
    phone = (order.get("phone") or "").strip()
    if phone:
        return phone
    for addr_key in ("billing_address", "shipping_address"):
        addr = order.get(addr_key) or {}
        phone = (addr.get("phone") or "").strip()
        if phone:
            return phone
    return None