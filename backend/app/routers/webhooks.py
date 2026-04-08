"""
app/routers/webhooks.py
Webhook handlers — Technical Spec Section 5.8 and 6.1.

Routes:
  GET  /webhooks/meta/verify         — Meta hub.challenge verification
  POST /webhooks/meta/lead-ads       — Meta Lead Ads handler (Section 6.1)
  POST /webhooks/meta/whatsapp       — WhatsApp inbound stub (Phase 3A)

Security:
  - X-Hub-Signature-256 verified on every incoming POST — Section 6
  - org_id derived from page_id → organisations.meta_page_id (never from body)
  - Graph API fetch uses the org's own access token
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.config import settings
from app.database import get_supabase
from app.models.common import ErrorCode
from app.models.leads import LeadSource, LeadCreate
from app.services import lead_service
from app.services.subscription_service import (
    process_paystack_webhook,
    process_flutterwave_webhook,
)

load_dotenv()  # Pattern 29 — required for os.getenv() in service files

router = APIRouter()
logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ---------------------------------------------------------------------------
# Signature verification — Section 6
# ---------------------------------------------------------------------------

def _verify_meta_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify X-Hub-Signature-256 header against META_APP_SECRET.
    Returns False if header is missing or signature does not match.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = (
        "sha256="
        + hmac.new(
            settings.META_APP_SECRET.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def _verify_paystack_signature(payload_bytes: bytes, sig_header: Optional[str]) -> bool:
    """
    Verify X-Paystack-Signature header using HMAC-SHA512 with PAYSTACK_SECRET_KEY.
    Technical Spec §6 — payment webhooks verified using provider-specific headers.
    Returns False if header is missing, key is not configured, or signature mismatches.
    """
    secret = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    if not secret or not sig_header:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def _verify_flutterwave_hash(hash_header: Optional[str]) -> bool:
    """
    Verify verif-hash header by direct comparison with FLUTTERWAVE_SECRET_HASH.
    Flutterwave sends the secret hash value verbatim — no HMAC computation needed.
    Technical Spec §6 — payment webhooks verified using provider-specific headers.
    Returns False if header is missing or key is not configured.
    """
    secret = os.getenv("FLUTTERWAVE_SECRET_HASH", "").strip()
    if not secret or not hash_header:
        return False
    return hmac.compare_digest(secret, hash_header)


# ---------------------------------------------------------------------------
# Graph API fetch — Section 6.1
# ---------------------------------------------------------------------------

async def _fetch_meta_lead(leadgen_id: str, access_token: str) -> dict:
    """
    GET https://graph.facebook.com/v18.0/{leadgen_id}?fields=field_data
    Returns the full response dict including field_data.
    """
    url = f"{GRAPH_API_BASE}/{leadgen_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            url,
            params={"fields": "field_data,created_time", "access_token": access_token},
        )
    resp.raise_for_status()
    return resp.json()


def _parse_field_data(field_data: list[dict]) -> dict:
    """
    Convert Meta field_data list into a flat dict keyed by field name.
    [{"name": "full_name", "values": ["Emeka Obi"]}, ...] → {"full_name": "Emeka Obi"}
    """
    return {
        item.get("name", ""): (item.get("values") or [None])[0]
        for item in field_data
    }


def _map_meta_fields_to_lead(fields: dict, meta_payload: dict) -> dict:
    """Map Graph API field_data to LeadCreate field names."""
    full_name = fields.get("full_name") or fields.get("name")
    if fields.get("first_name") and fields.get("last_name"):
        full_name = f"{fields['first_name']} {fields['last_name']}".strip()

    # Default to facebook_ad; distinguish Instagram by ad_name if available
    source = LeadSource.facebook_ad.value
    if "instagram" in (fields.get("ad_name") or "").lower():
        source = LeadSource.instagram_ad.value

    return {
        "full_name": full_name or "Unknown",
        "phone": fields.get("phone_number") or fields.get("phone"),
        "email": fields.get("email"),
        "business_name": fields.get("business_name") or fields.get("company_name"),
        "business_type": fields.get("business_type"),
        "problem_stated": fields.get("problem_stated") or fields.get("message"),
        "location": fields.get("city") or fields.get("location"),
        "source": source,
        "campaign_id": meta_payload.get("campaign_id"),
        "ad_id": meta_payload.get("ad_id"),
    }


# ---------------------------------------------------------------------------
# GET /webhooks/meta/verify
# ---------------------------------------------------------------------------

@router.get("/meta/verify")
async def verify_meta_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification challenge — returns hub.challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Meta webhook verified successfully")
        if hub_challenge and hub_challenge.isdigit():
            return int(hub_challenge)
        return hub_challenge
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook verification failed — token mismatch",
    )


# ---------------------------------------------------------------------------
# POST /webhooks/meta/lead-ads
# ---------------------------------------------------------------------------

@router.post("/meta/lead-ads", status_code=status.HTTP_200_OK)
async def receive_meta_lead_ad(
    request: Request,
    db=Depends(get_supabase),
):
    """
    Receives Facebook/Instagram Lead Ad form submissions — Section 6.1.

    Flow:
      1. Verify X-Hub-Signature-256 (reject 403 on failure)
      2. Parse leadgen_id + page_id from payload
      3. Look up org by meta_page_id
      4. Fetch full lead from Graph API
      5. Create lead (duplicate check applies)
      6. Return 200 always (Meta requires 200)
    """
    raw_body = await request.body()

    # Step 1 — signature verification
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw_body, signature):
        logger.warning("Meta lead-ads webhook: invalid signature — rejecting")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    payload: dict = json.loads(raw_body)

    if payload.get("object") != "page":
        return {"status": "ignored", "reason": "not a page event"}

    processed = 0
    errors: list[str] = []

    for entry in payload.get("entry", []):
        page_id = entry.get("id", "")

        # Step 3 — look up org by meta_page_id
        org_result = (
            db.table("organisations")
            .select("id, meta_page_id, whatsapp_phone_id")
            .eq("meta_page_id", page_id)
            .maybe_single()
            .execute()
        )
        # Normalise: real supabase returns dict, mocks return list
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None
        if not org_data:
            logger.info("No org found for page_id=%s — skipping", page_id)
            continue

        org_id = org_data["id"]

        # Get org's Meta access token
        token_result = (
            db.table("integrations")
            .select("access_token")
            .eq("org_id", org_id)
            .eq("provider", "meta")
            .maybe_single()
            .execute()
        )
        token_data = token_result.data
        if isinstance(token_data, list):
            token_data = token_data[0] if token_data else None
        access_token = (
            (token_data or {}).get("access_token")
            or settings.META_WHATSAPP_TOKEN
        )

        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value", {})
            leadgen_id = value.get("leadgen_id")
            if not leadgen_id:
                continue

            meta_payload = {
                "ad_id":       value.get("ad_id"),
                "campaign_id": value.get("campaign_id"),
                "form_id":     value.get("form_id"),
            }

            try:
                # Step 4 — fetch from Graph API
                graph_resp = await _fetch_meta_lead(leadgen_id, access_token)
                field_data = graph_resp.get("field_data", [])
                fields = _parse_field_data(field_data)
                mapped = _map_meta_fields_to_lead(fields, meta_payload)

                # Step 5 — create lead
                payload_obj = LeadCreate(
                    **{k: v for k, v in mapped.items() if v is not None}
                )
                lead_service.create_lead(
                    db=db,
                    org_id=org_id,
                    user_id="system",
                    payload=payload_obj,
                )
                processed += 1

            except HTTPException as exc:
                code = (exc.detail or {}).get("code", "")
                if code == ErrorCode.DUPLICATE_DETECTED:
                    logger.info("Duplicate lead from Meta webhook: %s", leadgen_id)
                else:
                    logger.error("Lead creation error leadgen=%s: %s", leadgen_id, exc.detail)
                errors.append(f"{leadgen_id}: {code or str(exc.detail)}")
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Meta webhook processing error: %s", exc)
                errors.append(str(exc))

    return {"status": "ok", "processed": processed, "errors": errors}


# ---------------------------------------------------------------------------
# POST /webhooks/meta/whatsapp
# Inbound WhatsApp messages and delivery status updates — Technical Spec §6.2
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _lookup_record_by_phone(db, phone: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Find a customer or lead matching the given WhatsApp phone number.
    Searches ALL orgs — returns (org_id, customer_id, lead_id, assigned_to).
    Customers take priority over leads.
    Uses Python-side filtering (Pattern 33 — no ILIKE).
    Returns (None, None, None, None) if no match found.
    """
    # Normalise phone — strip spaces, dashes, leading zeros; try with/without +
    clean = phone.replace(" ", "").replace("-", "")
    variants = {clean}
    if clean.startswith("+"):
        variants.add(clean[1:])
    else:
        variants.add("+" + clean)

    # Search customers first
    try:
        cust_result = (
            db.table("customers")
            .select("id, org_id, whatsapp, phone, assigned_to")
            .is_("deleted_at", "null")
            .execute()
        )
        for row in (cust_result.data or []):
            wa = (row.get("whatsapp") or "").replace(" ", "").replace("-", "")
            ph = (row.get("phone") or "").replace(" ", "").replace("-", "")
            if wa in variants or ph in variants:
                return row["org_id"], row["id"], None, row.get("assigned_to")
    except Exception as exc:
        logger.warning("Customer phone lookup failed: %s", exc)

    # Fall back to leads
    try:
        lead_result = (
            db.table("leads")
            .select("id, org_id, whatsapp, phone, assigned_to")
            .is_("deleted_at", "null")
            .execute()
        )
        for row in (lead_result.data or []):
            wa = (row.get("whatsapp") or "").replace(" ", "").replace("-", "")
            ph = (row.get("phone") or "").replace(" ", "").replace("-", "")
            if wa in variants or ph in variants:
                return row["org_id"], None, row["id"], row.get("assigned_to")
    except Exception as exc:
        logger.warning("Lead phone lookup failed: %s", exc)

    return None, None, None, None


def _handle_inbound_message(db, message: dict, contact_name: str, phone_number_id: str) -> None:
    """
    Process one inbound WhatsApp text message.
    - Looks up customer/lead by sender phone number
    - Saves row to whatsapp_messages
    - Inserts in-app notification for assigned rep (S14 — failures swallowed)
    """
    from datetime import datetime, timezone, timedelta

    sender_phone = message.get("from", "")
    msg_id       = message.get("id", "")
    msg_type     = message.get("type", "text")
    content: Optional[str] = None

    if msg_type == "text":
        content = (message.get("text") or {}).get("body")
    elif msg_type == "image":
        content = "[Image]"
    elif msg_type == "video":
        content = "[Video]"
    elif msg_type == "audio":
        content = "[Audio]"
    elif msg_type == "document":
        content = "[Document]"
    else:
        content = f"[{msg_type}]"

    org_id, customer_id, lead_id, assigned_to = _lookup_record_by_phone(db, sender_phone)

    if not org_id:
        logger.info("Inbound WhatsApp from unknown number %s — no matching record", sender_phone)
        return

    now_ts = _now_iso()
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()

    row: dict = {
        "org_id":          org_id,
        "direction":       "inbound",
        "message_type":    msg_type,
        "content":         content,
        "status":          "delivered",
        "meta_message_id": msg_id,
        "window_open":     True,
        "window_expires_at": window_expires,
        "sent_by":         None,
        "created_at":      now_ts,
    }
    if customer_id:
        row["customer_id"] = customer_id
    if lead_id:
        row["lead_id"] = lead_id

    try:
        db.table("whatsapp_messages").insert(row).execute()
    except Exception as exc:
        logger.error("Failed to save inbound WhatsApp message: %s", exc)
        return

    # Notify assigned rep in-app (S14 — failure must never affect message save)
    if not assigned_to:
        return
    try:
        resource_id   = customer_id or lead_id
        resource_type = "customer" if customer_id else "lead"
        # Fetch actual full_name from matched record — more reliable than
        # the WhatsApp contact profile name which may differ or be absent.
        display_name = contact_name or sender_phone
        try:
            name_table  = "customers" if customer_id else "leads"
            name_id     = customer_id or lead_id
            name_result = (
                db.table(name_table)
                .select("full_name")
                .eq("id", name_id)
                .maybe_single()
                .execute()
            )
            name_data = name_result.data
            if isinstance(name_data, list):
                name_data = name_data[0] if name_data else None
            if name_data and name_data.get("full_name"):
                display_name = name_data["full_name"]
        except Exception:
            pass  # fall back to contact_name / sender_phone

        db.table("notifications").insert({
            "org_id":         org_id,
            "user_id":        assigned_to,
            "title":          f"New WhatsApp reply from {display_name}",
            "body":           content or f"[{msg_type}]",
            "type":           "whatsapp_reply",
            "resource_type":  resource_type,
            "resource_id":    resource_id,
            "is_read":        False,
            "created_at":     now_ts,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to insert reply notification for user %s: %s", assigned_to, exc)


def _handle_status_update(db, status_update: dict) -> None:
    """
    Process a delivery/read status update from Meta.
    Updates the whatsapp_messages row matched by meta_message_id.
    S14 — failures are logged and swallowed.
    """
    meta_msg_id = status_update.get("id")
    new_status  = status_update.get("status")  # sent | delivered | read | failed

    if not meta_msg_id or not new_status:
        return

    updates: dict = {"status": new_status}
    now_ts = _now_iso()

    if new_status == "delivered":
        updates["delivered_at"] = now_ts
    elif new_status == "read":
        updates["read_at"] = now_ts

    try:
        db.table("whatsapp_messages") \
            .update(updates) \
            .eq("meta_message_id", meta_msg_id) \
            .execute()
    except Exception as exc:
        logger.warning("Status update failed for meta_message_id=%s: %s", meta_msg_id, exc)


@router.post("/meta/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_message(
    request: Request,
    db=Depends(get_supabase),
):
    """
    WhatsApp inbound message and status update handler — Technical Spec §6.2.

    Handles two event types:
      1. Inbound messages — saves to whatsapp_messages, notifies assigned rep
      2. Status updates (sent/delivered/read/failed) — updates message row

    Security: X-Hub-Signature-256 verified before any processing.
    S14: all processing errors after signature check are swallowed — always returns 200.
    """
    raw_body  = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not _verify_meta_signature(raw_body, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    payload: dict = json.loads(raw_body)

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored", "reason": "not a whatsapp_business_account event"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id", "")
            contacts        = value.get("contacts", [])
            contact_name    = (contacts[0].get("profile") or {}).get("name", "") if contacts else ""

            # Process inbound messages
            for message in value.get("messages", []):
                try:
                    _handle_inbound_message(db, message, contact_name, phone_number_id)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Inbound message processing error: %s", exc)

            # Process delivery/read status updates
            for status_upd in value.get("statuses", []):
                try:
                    _handle_status_update(db, status_upd)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Status update processing error: %s", exc)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /webhooks/payment/paystack  — Technical Spec §6.3
# ---------------------------------------------------------------------------

@router.post("/payment/paystack", status_code=status.HTTP_200_OK)
async def receive_paystack_webhook(
    request: Request,
    db=Depends(get_supabase),
):
    """
    Paystack charge.success webhook handler.
    Technical Spec §6.3.  Route: POST /webhooks/payment/paystack.

    Security: HMAC-SHA512 of raw body verified against PAYSTACK_SECRET_KEY
    using X-Paystack-Signature header before any processing.

    Always returns 200 after signature check — Paystack retries on non-200.
    S14: processing errors are logged and swallowed; never return 5xx.
    """
    raw_body = await request.body()
    sig = request.headers.get("X-Paystack-Signature")
    if not _verify_paystack_signature(raw_body, sig):
        logger.warning("Paystack webhook: invalid signature — rejecting")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Paystack signature",
        )

    payload: dict = json.loads(raw_body)
    try:
        process_paystack_webhook(db=db, payload=payload)
    except Exception as exc:  # pylint: disable=broad-except
        # S14 — never return 5xx to Paystack; log and acknowledge
        logger.error("Paystack webhook processing error: %s", exc)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /webhooks/payment/flutterwave  — Technical Spec §6
# ---------------------------------------------------------------------------

@router.post("/payment/flutterwave", status_code=status.HTTP_200_OK)
async def receive_flutterwave_webhook(
    request: Request,
    db=Depends(get_supabase),
):
    """
    Flutterwave charge.completed webhook handler.
    Route: POST /webhooks/payment/flutterwave.

    Security: verif-hash header compared directly against FLUTTERWAVE_SECRET_HASH
    env var (Flutterwave sends the secret verbatim — no HMAC computation).

    Always returns 200 after hash check — Flutterwave retries on non-200.
    S14: processing errors are logged and swallowed; never return 5xx.
    """
    raw_body = await request.body()
    hash_header = request.headers.get("verif-hash")
    if not _verify_flutterwave_hash(hash_header):
        logger.warning("Flutterwave webhook: invalid hash — rejecting")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Flutterwave hash",
        )

    payload: dict = json.loads(raw_body)
    try:
        process_flutterwave_webhook(db=db, payload=payload)
    except Exception as exc:  # pylint: disable=broad-except
        # S14 — never return 5xx to Flutterwave; log and acknowledge
        logger.error("Flutterwave webhook processing error: %s", exc)

    return {"status": "ok"}