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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from app.utils.phone import normalize_phone
from app.services.customer_inbound_service import (
    handle_lead_post_handoff_inbound,
)
from app.config import settings
from app.database import get_supabase
from app.models.common import ErrorCode
from app.models.leads import LeadSource, LeadCreate
from app.services import lead_service
from app.services import triage_service
from app.services import customer_inbound_service
from app.services.subscription_service import (
    process_paystack_webhook,
    process_flutterwave_webhook,
)
from app.services.whatsapp_service import send_qualification_question, send_qualification_handoff_message
from app.services.ai_service import generate_qualification_summary
from app.services import shopify_service
from app.utils.opt_out import handle_opt_keywords
from app.services.monitoring_service import log_system_error


load_dotenv()  # Pattern 29 — required for os.getenv() in service files

router = APIRouter()
logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ---------------------------------------------------------------------------
# SA-2A — webhook_request_log helper
# S14: never raises. DB write failure must not affect response code.
# ---------------------------------------------------------------------------
def _log_webhook(
    db,
    *,
    route: str,
    org_id: Optional[str] = None,
    topic: Optional[str] = None,
    response_status: int,
    processing_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Write one row to webhook_request_log. S14: never raises."""
    try:
        from datetime import datetime, timezone as _tz
        db.table("webhook_request_log").insert({
            "org_id": org_id or None,
            "route": route[:200],
            "method": "POST",
            "topic": (topic or "")[:200] or None,
            "response_status": response_status,
            "processing_ms": processing_ms,
            "error_message": (error_message or "")[:2000] or None,
            "received_at": datetime.now(_tz.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("_log_webhook: failed to write webhook_request_log — %s", exc)

# COMM-1: Valid commerce flow states on whatsapp_sessions.commerce_state
COMMERCE_STATES = {
    "commerce_browsing",
    "commerce_variant_select",
    "commerce_cart",
    "commerce_checkout",
}


# ---------------------------------------------------------------------------
# Signature verification — Section 6
# ---------------------------------------------------------------------------

def _verify_meta_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
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
    secret = os.getenv("FLUTTERWAVE_SECRET_HASH", "").strip()
    if not secret or not hash_header:
        return False
    return hmac.compare_digest(secret, hash_header)


# ---------------------------------------------------------------------------
# Graph API fetch — Section 6.1
# ---------------------------------------------------------------------------

async def _fetch_meta_lead(leadgen_id: str, access_token: str) -> dict:
    url = f"{GRAPH_API_BASE}/{leadgen_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            url,
            params={"fields": "field_data,created_time", "access_token": access_token},
        )
    resp.raise_for_status()
    return resp.json()


def _parse_field_data(field_data: list[dict]) -> dict:
    return {
        item.get("name", ""): (item.get("values") or [None])[0]
        for item in field_data
    }


def _map_meta_fields_to_lead(fields: dict, meta_payload: dict) -> dict:
    full_name = fields.get("full_name") or fields.get("name")
    if fields.get("first_name") and fields.get("last_name"):
        full_name = f"{fields['first_name']} {fields['last_name']}".strip()
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
        "utm_source": "instagram" if source == "instagram_ad" else "facebook",
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
    raw_body = await request.body()
    import time as _time
    _t0 = _time.monotonic()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw_body, signature):
        logger.warning("Meta lead-ads webhook: invalid signature — rejecting")
        _log_webhook(db, route="/webhooks/meta/lead-ads", response_status=403, error_message="Invalid signature")
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
        org_result = (
            db.table("organisations")
            .select("id, meta_page_id, whatsapp_phone_id")
            .eq("meta_page_id", page_id)
            .maybe_single()
            .execute()
        )
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None
        if not org_data:
            logger.info("No org found for page_id=%s — skipping", page_id)
            continue
        org_id = org_data["id"]
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
        access_token = (token_data or {}).get("access_token")
        if not access_token:
            logger.warning(
                "receive_meta_lead_ad: no Meta access token in integrations "
                "table for org %s — skipping leadgen fetch for this entry",
                org_id,
            )
            continue
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
                graph_resp = await _fetch_meta_lead(leadgen_id, access_token)
                field_data = graph_resp.get("field_data", [])
                fields = _parse_field_data(field_data)
                mapped = _map_meta_fields_to_lead(fields, meta_payload)
                utm_source_val  = mapped.pop("utm_source", None)
                campaign_id_val = mapped.pop("campaign_id", None)
                payload_obj = LeadCreate(
                    **{k: v for k, v in mapped.items() if v is not None}
                )
                lead_service.create_lead(
                    db=db,
                    org_id=org_id,
                    user_id="system",
                    payload=payload_obj,
                    utm_source=utm_source_val or "facebook",
                    campaign_id=campaign_id_val,
                    entry_path="meta_lead_ad",
                    utm_ad=meta_payload.get("ad_id"),
                )
                processed += 1
            except HTTPException as exc:
                code = (exc.detail or {}).get("code", "")
                if code == ErrorCode.DUPLICATE_DETECTED:
                    logger.info("Duplicate lead from Meta webhook: %s", leadgen_id)
                else:
                    logger.error("Lead creation error leadgen=%s: %s", leadgen_id, exc.detail)
                errors.append(f"{leadgen_id}: {code or str(exc.detail)}")
            except Exception as exc:
                logger.error("Meta webhook processing error: %s", exc)
                errors.append(str(exc))
    _log_webhook(
        db,
        route="/webhooks/meta/lead-ads",
        response_status=200,
        topic="lead_ad",
        processing_ms=int((_time.monotonic() - _t0) * 1000),
    )
    return {"status": "ok", "processed": processed, "errors": errors}


# ---------------------------------------------------------------------------
# POST /webhooks/meta/whatsapp
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _lookup_record_by_phone(db, phone: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    clean = phone.replace(" ", "").replace("-", "")
    variants = {clean}
    if clean.startswith("+"):
        variants.add(clean[1:])
    else:
        variants.add("+" + clean)
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
    try:
        cc_result = (
            db.table("customer_contacts")
            .select("org_id, customer_id, phone_number")
            .eq("status", "active")
            .execute()
        )
        for row in (cc_result.data or []):
            cc_ph = (row.get("phone_number") or "").replace(" ", "").replace("-", "")
            if cc_ph in variants:
                cust_r = (
                    db.table("customers")
                    .select("assigned_to")
                    .eq("id", row["customer_id"])
                    .maybe_single()
                    .execute()
                )
                cust_d = cust_r.data
                if isinstance(cust_d, list):
                    cust_d = cust_d[0] if cust_d else None
                return (
                    row["org_id"], row["customer_id"], None,
                    (cust_d or {}).get("assigned_to"),
                )
    except Exception as exc:
        logger.warning("Customer contacts phone lookup failed: %s", exc)
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


def _lookup_org_by_phone_number_id(db, phone_number_id: str) -> Optional[str]:
    if not phone_number_id:
        return None
    try:
        result = (
            db.table("organisations")
            .select("id, whatsapp_phone_id")
            .execute()
        )
        for row in (result.data or []):
            if (row.get("whatsapp_phone_id") or "").strip() == phone_number_id.strip():
                return row["id"]
    except Exception as exc:
        logger.warning("Org lookup by phone_number_id failed: %s", exc)
    return None


_OPT_OUT_KEYWORDS: frozenset = frozenset({
    "unsubscribe", "optout", "opt out", "opt-out",
    "quit", "remove me",
})
_OPT_IN_KEYWORDS: frozenset = frozenset({
    "start", "subscribe", "optin", "opt in",
})

_OPT_OUT_REPLY = (
    "You've been unsubscribed from our WhatsApp messages. "
    "Reply START at any time to opt back in. "
    "No further messages will be sent to you."
)
_OPT_IN_REPLY = (
    "Welcome back! You're now subscribed to receive messages from us again. "
    "Reply STOP at any time to unsubscribe."
)


def _handle_opt_keywords(
    db,
    content: str,
    sender_phone: str,
    org_id: str,
    customer_id: Optional[str],
    lead_id: Optional[str],
) -> bool:
    normalised = content.strip().lower()
    is_opt_out = normalised in _OPT_OUT_KEYWORDS
    is_opt_in  = normalised in _OPT_IN_KEYWORDS
    if not is_opt_out and not is_opt_in:
        return False
    try:
        opted_out_flag = is_opt_out
        reply_msg      = _OPT_OUT_REPLY if is_opt_out else _OPT_IN_REPLY
        if customer_id:
            db.table("customers").update(
                {"whatsapp_opted_out": opted_out_flag}
            ).eq("id", customer_id).eq("org_id", org_id).execute()
            logger.info("_handle_opt_keywords: customer %s whatsapp_opted_out=%s", customer_id, opted_out_flag)
        elif lead_id:
            db.table("leads").update(
                {"whatsapp_opted_out": opted_out_flag}
            ).eq("id", lead_id).eq("org_id", org_id).execute()
            logger.info("_handle_opt_keywords: lead %s whatsapp_opted_out=%s", lead_id, opted_out_flag)
        else:
            logger.info(
                "_handle_opt_keywords: opt-%s from unknown contact %s (no record found)",
                "out" if is_opt_out else "in", sender_phone,
            )
        try:
            from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send
            phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
            if phone_id and access_token:
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to":   sender_phone,
                    "type": "text",
                    "text": {"body": reply_msg},
                }, token=access_token)
        except Exception as send_exc:
            logger.warning("_handle_opt_keywords: failed to send reply to %s: %s", sender_phone, send_exc)
        return True
    except Exception as exc:
        logger.warning("_handle_opt_keywords: error processing keyword from %s: %s", sender_phone, exc)
        return False

def _is_lead_pre_qualified(db, org_id: str, lead_id: str) -> bool:
    """
    PRE-QUAL: Returns True if the lead already has qualification data populated.
    Reads the org's qualification_flow to find which lead fields it collects
    (via map_to_lead_field). If any of those fields are already populated on
    the lead, qualification bot is not needed.
    Returns True also if no flow is configured (nothing to collect).
    S14: returns False on any error — safe default is normal qualification.
    """
    try:
        org_r = (
            db.table("organisations")
            .select("qualification_flow")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None

        qualification_flow = (org_d or {}).get("qualification_flow")

        # No flow configured → skip qualification
        if not qualification_flow:
            logger.info("[PRE-QUAL] no qualification_flow for org %s — skipping bot", org_id)
            return True

        questions = qualification_flow.get("questions") or []
        mapped_fields = [
            q.get("map_to_lead_field")
            for q in questions
            if q.get("map_to_lead_field")
        ]

        # No mapped fields → nothing to collect → skip qualification
        if not mapped_fields:
            logger.info("[PRE-QUAL] no mapped fields in flow for org %s — skipping bot", org_id)
            return True

        # Check lead — if any mapped field is already populated, pre-qualified
        select_fields = ", ".join(set(mapped_fields))
        lead_r = (
            db.table("leads")
            .select(select_fields)
            .eq("id", lead_id)
            .maybe_single()
            .execute()
        )
        lead_d = lead_r.data
        if isinstance(lead_d, list):
            lead_d = lead_d[0] if lead_d else None
        lead_d = lead_d or {}

        for field in mapped_fields:
            value = lead_d.get(field)
            if value and str(value).strip():
                logger.info(
                    "[PRE-QUAL] lead %s pre-qualified — field '%s' already populated",
                    lead_id, field,
                )
                return True

        logger.info(
            "[PRE-QUAL] lead %s NOT pre-qualified — none of %s populated",
            lead_id, mapped_fields,
        )
        return False

    except Exception as exc:
        logger.warning("_is_lead_pre_qualified failed lead=%s: %s", lead_id, exc)
        return False

def _handle_pre_qualified_lead(
    db,
    org_id: str,
    lead_id: str,
    phone_number: str,
    contact_name: Optional[str],
    assigned_to: Optional[str],
    now_ts: str,
) -> None:
    """
    PRE-QUAL: Handle a lead that is already pre-qualified.
    1. Send a warm greeting
    2. Notify assigned rep (owner fallback)
    3. If whatsapp_sales_mode == 'bot' → go straight to product list
    4. Mark qualification as complete so this doesn't fire again on repeat messages
    S14: never raises.
    """
    try:
        from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send

        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()

        # Fetch wa_sales_mode and shopify status
        org_r = (
            db.table("organisations")
            .select("whatsapp_sales_mode, shopify_connected")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None
        org_d = org_d or {}

        wa_sales_mode = org_d.get("whatsapp_sales_mode", "human")
        shopify_connected = org_d.get("shopify_connected", False)

        # Get lead name for personalised greeting
        lead_name = contact_name
        if not lead_name:
            try:
                lead_r = (
                    db.table("leads")
                    .select("full_name")
                    .eq("id", lead_id)
                    .maybe_single()
                    .execute()
                )
                lead_d = lead_r.data
                if isinstance(lead_d, list):
                    lead_d = lead_d[0] if lead_d else None
                lead_name = (lead_d or {}).get("full_name") or phone_number
            except Exception:
                lead_name = phone_number

        first_name = (lead_name or "").split()[0] if lead_name else ""
        greeting = (
            f"Hi {first_name}! 👋 Thanks for reaching out. "
            "A member of our team will be in touch with you shortly."
            if first_name else
            "Hi there! 👋 Thanks for reaching out. "
            "A member of our team will be in touch with you shortly."
        )

        # 1 — Send warm greeting
        if phone_id:
            try:
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {"body": greeting},
                }, token=access_token)
            except Exception as send_exc:
                logger.warning("_handle_pre_qualified_lead: greeting send failed: %s", send_exc)

        # 2 — Notify assigned rep (owner fallback)
        notify_user_id = assigned_to
        if not notify_user_id:
            try:
                users_r = (
                    db.table("users")
                    .select("id, roles(template)")
                    .eq("org_id", org_id)
                    .execute()
                )
                for u in (users_r.data or []):
                    if (u.get("roles") or {}).get("template", "").lower() == "owner":
                        notify_user_id = u["id"]
                        break
            except Exception:
                pass

        if notify_user_id:
            try:
                db.table("notifications").insert({
                    "org_id":        org_id,
                    "user_id":       notify_user_id,
                    "type":          "new_lead",
                    "title":         f"Pre-qualified lead messaged: {lead_name}",
                    "body":          (
                        f"{lead_name} came in via a Lead Ad and has now messaged on WhatsApp. "
                        "Their details are already on file — no qualification needed."
                    ),
                    "resource_type": "lead",
                    "resource_id":   lead_id,
                    "is_read":       False,
                    "created_at":    now_ts,
                }).execute()
            except Exception as notif_exc:
                logger.warning("_handle_pre_qualified_lead: notification failed: %s", notif_exc)

        # 3 — If bot mode and Shopify connected → go straight to product list
        if wa_sales_mode == "bot" and shopify_connected and phone_id:
            try:
                from app.services.commerce_service import get_or_create_commerce_session
                from app.services.whatsapp_service import send_product_list

                session = triage_service.get_or_create_session(db, org_id, phone_number)
                if session:
                    get_or_create_commerce_session(db, org_id, phone_number, lead_id=lead_id)
                    products_r = (
                        db.table("products")
                        .select("*")
                        .eq("org_id", org_id)
                        .eq("is_active", True)
                        .order("title")
                        .execute()
                    )
                    products = products_r.data if isinstance(products_r.data, list) else []
                    if products:
                        send_product_list(db, org_id, phone_number, products)
                        db.table("whatsapp_sessions").update(
                            {"commerce_state": "commerce_browsing"}
                        ).eq("id", session["id"]).execute()
            except Exception as commerce_exc:
                logger.warning(
                    "_handle_pre_qualified_lead: commerce entry failed org=%s phone=%s: %s",
                    org_id, phone_number, commerce_exc,
                )

        # 4 — Mark qualification complete so this doesn't fire again on repeat messages
        try:
            db.table("lead_qualification_sessions").insert({
                "org_id":                 org_id,
                "lead_id":                lead_id,
                "ai_active":              False,
                "stage":                  "handed_off",
                "current_question_index": 0,
                "answers":                {"pre_qualified": True},
                "created_at":             now_ts,
                "last_message_at":        now_ts,
                "handed_off_at":          now_ts,
                "handoff_summary":        "Lead pre-qualified via Lead Ad form — qualification bot skipped.",
            }).execute()
        except Exception as sess_exc:
            logger.warning("_handle_pre_qualified_lead: session mark failed: %s", sess_exc)

        logger.info(
            "[PRE-QUAL] handled pre-qualified lead=%s org=%s wa_sales_mode=%s",
            lead_id, org_id, wa_sales_mode,
        )

    except Exception as exc:
        logger.warning("_handle_pre_qualified_lead failed lead=%s: %s", lead_id, exc)

def _handle_inbound_message(db, message: dict, contact_name: str, phone_number_id: str) -> None:
    from datetime import datetime, timezone, timedelta

    sender_phone = normalize_phone(message.get("from", ""))
    msg_id       = message.get("id", "")
    try:
        _dedup = (
            db.table("whatsapp_messages")
            .select("id")
            .eq("meta_message_id", msg_id)
            .limit(1)
            .execute()
        )
        if _dedup.data:
            logger.info("Duplicate message_id=%s — skipping", msg_id)
            return
    except Exception as _dedup_exc:
        logger.warning("Dedup check failed for msg_id=%s — proceeding: %s", msg_id, _dedup_exc)

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
    elif msg_type == "interactive":
        interactive_type = (message.get("interactive") or {}).get("type")
        if interactive_type == "list_reply":
            list_reply = (message.get("interactive") or {}).get("list_reply") or {}
            content = list_reply.get("title") or list_reply.get("id")
        elif interactive_type == "button_reply":
            button_reply = (message.get("interactive") or {}).get("button_reply") or {}
            content = button_reply.get("title") or button_reply.get("id")
        else:
            content = f"[interactive:{interactive_type}]"
    else:
        content = f"[{msg_type}]"

    interactive_payload = message.get("interactive") if msg_type == "interactive" else None
    logger.info("[WH] msg_type=%s content=%r from=%s", msg_type, content, sender_phone)

    org_id, customer_id, lead_id, assigned_to = _lookup_record_by_phone(db, sender_phone)
    logger.info("[WH] lookup result: org_id=%s customer_id=%s lead_id=%s", org_id, customer_id, lead_id)

    if org_id and msg_type == "text" and content:
        if _handle_opt_keywords(db, content, sender_phone, org_id, customer_id, lead_id):
            return

    if not org_id:
        org_id = _lookup_org_by_phone_number_id(db, phone_number_id)
        logger.info("[WH] unknown number — org_id from phone_number_id=%s", org_id)
        if not org_id:
            logger.info("[WH] no org found — dropping message")
            return

        active_session = triage_service.get_active_session(db, org_id, sender_phone)
        logger.info("[WH] active_session=%s", active_session)
        if active_session:
            if not active_session.get("commerce_state"):
                _restore_commerce_state_if_open(db, org_id, sender_phone, active_session)
            if (active_session.get("commerce_state") or "") in COMMERCE_STATES:
                logger.info("[WH] routing to commerce handler state=%s", active_session.get('commerce_state'))
                _handle_commerce_message(
                    db=db, org_id=org_id, phone_number=sender_phone,
                    message=message, session=active_session,
                    msg_type=msg_type, content=content,
                    interactive_payload=interactive_payload, contact_name=contact_name,
                )
                return
            logger.info("[WH] routing to session handler")
            triage_service.handle_session_message(
                db=db, org_id=org_id, phone_number=sender_phone,
                session=active_session, msg_type=msg_type, content=content,
                interactive_payload=interactive_payload, contact_name=contact_name,
                now_ts=_now_iso(),
            )
            return

        org_behavior_result = (
            db.table("organisations")
            .select("unknown_contact_behavior, whatsapp_triage_config, whatsapp_phone_id, sales_mode, whatsapp_sales_mode, shopify_connected")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_behavior = org_behavior_result.data
        if isinstance(org_behavior, list):
            org_behavior = org_behavior[0] if org_behavior else None
        behavior = (org_behavior or {}).get("unknown_contact_behavior", "triage_first")
        triage_config = (org_behavior or {}).get("whatsapp_triage_config")
        sales_mode = (org_behavior or {}).get("sales_mode", "consultative")
        wa_sales_mode = (org_behavior or {}).get("whatsapp_sales_mode", "human")
        logger.info("[WH] behavior=%s sales_mode=%s wa_sales_mode=%s", behavior, sales_mode, wa_sales_mode)

        if sales_mode == "transactional" or wa_sales_mode == "bot":
            _shopify_ok = (org_behavior or {}).get("shopify_connected", False)
            if _shopify_ok:
                logger.info("[WH] transactional mode — sending to commerce entry")
                session = triage_service.get_or_create_session(db, org_id, sender_phone)
                if not session:
                    session = triage_service.get_active_session(db, org_id, sender_phone)
                    logger.info("[WH] transactional: reused existing session=%s", session and session.get("id"))
                if session:
                    triage_service._action_transactional_entry(db, org_id, sender_phone, session["id"], contact_name)
                return

        elif sales_mode == "hybrid":
            logger.info("[WH] hybrid mode — sending hybrid gate")
            session = triage_service.get_or_create_session(db, org_id, sender_phone)
            if not session:
                session = triage_service.get_active_session(db, org_id, sender_phone)
                logger.info("[WH] hybrid: reused existing session=%s", session and session.get("id"))
            if not session:
                logger.info("[WH] hybrid: expired session blocking creation — clearing for %s", sender_phone)
                try:
                    db.table("whatsapp_sessions").delete().eq("org_id", org_id).eq("phone_number", sender_phone).execute()
                    session = triage_service.create_session(db=db, org_id=org_id, phone_number=sender_phone)
                    logger.info("[WH] hybrid: fresh session created=%s", session and session.get("id"))
                except Exception as exc:
                    logger.warning("[WH] hybrid: could not clear expired session for %s: %s", sender_phone, exc)
            if session:
                triage_service.send_hybrid_entry_choice(
                    db, org_id, sender_phone, contact_name=contact_name, msg_id=msg_id,
                )
            else:
                logger.warning("[WH] hybrid: could not get or create session for %s", sender_phone)
            return

        if behavior == "qualify_immediately":
            logger.info("[WH] qualify_immediately path")
            provisional_name = (contact_name or "").strip() or sender_phone
            try:
                _referral = message.get("referral") or {}
                _wa_utm_source = None
                _wa_campaign_id = None
                _wa_utm_ad = None
                if _referral:
                    _wa_utm_source = "facebook"
                    _wa_campaign_id = _referral.get("ctwa_clid") or _referral.get("ref")
                    _wa_utm_ad = _referral.get("headline") or None
                new_lead_payload = LeadCreate(
                    full_name=provisional_name, phone=sender_phone, whatsapp=sender_phone,
                    source=LeadSource.whatsapp_inbound.value,
                    problem_stated=content if msg_type == "text" else None,
                )
                new_lead = lead_service.create_lead(
                    db=db, org_id=org_id, user_id="system", payload=new_lead_payload,
                    utm_source=_wa_utm_source, campaign_id=_wa_campaign_id,
                    entry_path="whatsapp", utm_ad=_wa_utm_ad,
                )
                lead_id     = new_lead["id"]
                assigned_to = new_lead.get("assigned_to")
                logger.info("Auto-created lead %s for inbound WhatsApp from %s (org=%s)", lead_id, sender_phone, org_id)
            except Exception as exc:
                detail = getattr(exc, "detail", {}) or {}
                code   = detail.get("code", "") if isinstance(detail, dict) else str(detail)
                if code == ErrorCode.DUPLICATE_DETECTED:
                    logger.info("Duplicate on auto-create for %s — re-looking up", sender_phone)
                    org_id, customer_id, lead_id, assigned_to = _lookup_record_by_phone(db, sender_phone)
                    if not lead_id and not customer_id:
                        logger.warning("Re-lookup after duplicate also found nothing for %s", sender_phone)
                        return
                else:
                    logger.error("Failed to auto-create lead for %s: %s", sender_phone, exc)
                    return
        else:
            logger.info("[WH] triage_first path — sending menu")
            from app.services.whatsapp_service import send_triage_menu
            try:
                send_triage_menu(db=db, org_id=org_id, phone_number=sender_phone, section="unknown", contact_name=contact_name)
                logger.info("[WH] triage menu sent successfully")
                triage_service.create_session(db=db, org_id=org_id, phone_number=sender_phone)
                logger.info("[WH] session created")
            except Exception as exc:
                logger.warning("[WH] triage menu FAILED: %s", exc)
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

    reengaged_from_nurture = False
    if lead_id and not customer_id:
        try:
            nurture_check = (
                db.table("leads").select("nurture_track").eq("id", lead_id).maybe_single().execute()
            )
            nurture_data = nurture_check.data
            if isinstance(nurture_data, list):
                nurture_data = nurture_data[0] if nurture_data else None
            if (nurture_data or {}).get("nurture_track"):
                if msg_type == "text" and content:
                    from app.services.nurture_service import is_unsubscribe_signal, mark_lead_unsubscribed
                    if is_unsubscribe_signal(content):
                        mark_lead_unsubscribed(db=db, org_id=org_id, lead_id=lead_id, now_ts=now_ts)
                        logger.info("Lead %s opted out of nurture via unsubscribe signal", lead_id)
                        return
                from app.services.nurture_service import handle_re_engagement
                handle_re_engagement(db=db, org_id=org_id, lead_id=lead_id, assigned_to=assigned_to, now_ts=now_ts)
                reengaged_from_nurture = True
        except Exception as exc:
            logger.warning("Re-engagement check failed for lead %s — continuing: %s", lead_id, exc)

    if lead_id and not customer_id and not reengaged_from_nurture and msg_type == "text":
        try:
            _has_active_session = False
            try:
                _sess = (
                    db.table("lead_qualification_sessions")
                    .select("id").eq("lead_id", lead_id).eq("ai_active", True).execute()
                )
                _has_active_session = bool(_sess.data)
            except Exception:
                _has_active_session = True
            if not _has_active_session:
                from app.services.nurture_service import is_not_ready_signal, graduate_lead_self_identified
                if content and is_not_ready_signal(content):
                    lead_status = (
                        db.table("leads").select("nurture_track, stage").eq("id", lead_id).maybe_single().execute()
                    )
                    lead_status_data = lead_status.data or {}
                    if isinstance(lead_status_data, list):
                        lead_status_data = lead_status_data[0] if lead_status_data else {}
                    if not (lead_status_data or {}).get("nurture_track"):
                        graduate_lead_self_identified(
                            db=db, org_id=org_id, lead_id=lead_id, assigned_to=assigned_to, now_ts=now_ts,
                        )
                        logger.info("Lead %s self-identified as not ready — graduated to nurture", lead_id)
        except Exception as exc:
            logger.warning("Not-ready detection failed for lead %s — continuing: %s", lead_id, exc)

    ai_is_paused = False
    if lead_id or customer_id:
        try:
            _ai_table = "leads" if lead_id else "customers"
            _ai_id    = lead_id or customer_id
            _paused_r = (
                db.table(_ai_table).select("ai_paused")
                .eq("id", _ai_id).eq("org_id", org_id).maybe_single().execute()
            )
            _pd = _paused_r.data
            if isinstance(_pd, list):
                _pd = _pd[0] if _pd else None
            ai_is_paused = bool((_pd or {}).get("ai_paused", False))
            if ai_is_paused:
                logger.info("[WH] AI paused for %s=%s — routing to rep notification only", _ai_table.rstrip("s"), _ai_id)
        except Exception as _pause_exc:
            logger.warning("ai_paused check failed for %s — defaulting to AI active: %s", lead_id or customer_id, _pause_exc)
            ai_is_paused = False

    if lead_id and not customer_id and not ai_is_paused:
        # PRE-QUAL: Skip qualification bot if lead already has data from a Lead Ad form
        try:
            _any_qual = (
                db.table("lead_qualification_sessions")
                .select("id")
                .eq("lead_id", lead_id)
                .limit(1)
                .execute()
            )
            _has_any_qual_session = bool(_any_qual.data)
        except Exception:
            _has_any_qual_session = False

        if not _has_any_qual_session and _is_lead_pre_qualified(db, org_id, lead_id):
            _handle_pre_qualified_lead(
                db=db, org_id=org_id, lead_id=lead_id,
                phone_number=sender_phone, contact_name=contact_name,
                assigned_to=assigned_to, now_ts=now_ts,
            )
            return

        try:
            _handle_structured_qualification_turn(
                db=db, org_id=org_id, lead_id=lead_id,
                assigned_to=assigned_to, content=content or f"[{msg_type}]",
                interactive_payload=interactive_payload, now_ts=now_ts,
            )
            return
        except Exception as exc:
            logger.warning(
                "Qualification turn failed for lead %s — checking post-handoff path: %s",
                lead_id, exc,
            )
            # Commerce routing — if lead is currently in a commerce flow (e.g. was
            # sent a product list via the post-handoff path), route interactive
            # messages (product selections, Speak to Sales) to the commerce handler
            # before falling through to the text-only post-handoff handler.
            try:
                # Post-handoff leads may not have a whatsapp_session row.
                # Check for an open commerce_session directly — if one exists,
                # the lead is mid-commerce-flow and the message must go there.
                _ph_session = triage_service.get_active_session(db, org_id, sender_phone)
                _open_cs = (
                    db.table("commerce_sessions")
                    .select("id")
                    .eq("org_id", org_id)
                    .eq("phone_number", sender_phone)
                    .in_("status", ["open", "checkout_sent"])
                    .limit(1)
                    .execute()
                )
                _has_open_commerce = bool((_open_cs.data or []))
                if _has_open_commerce or (
                    _ph_session and (_ph_session.get("commerce_state") or "") in COMMERCE_STATES
                ):
                    if not _ph_session:
                        _ph_session = triage_service.get_or_create_session(db, org_id, sender_phone)
                    if _ph_session:
                        if not _ph_session.get("commerce_state") and _has_open_commerce:
                            _restore_commerce_state_if_open(db, org_id, sender_phone, _ph_session)
                        _handle_commerce_message(
                            db=db, org_id=org_id, phone_number=sender_phone,
                            message=message, session=_ph_session,
                            msg_type=msg_type, content=content,
                            interactive_payload=interactive_payload, contact_name=contact_name,
                        )
                        return
            except Exception as _ce:
                logger.warning("Commerce routing in post-handoff path failed lead=%s: %s", lead_id, _ce)
            if content:
                _lead_name = "Lead"
                try:
                    _ln = (
                        db.table("leads").select("full_name").eq("id", lead_id).maybe_single().execute()
                    )
                    _ld = _ln.data
                    if isinstance(_ld, list):
                        _ld = _ld[0] if _ld else None
                    _lead_name = (_ld or {}).get("full_name") or "Lead"
                except Exception:
                    pass
                handled = handle_lead_post_handoff_inbound(
                    db=db, org_id=org_id, lead_id=lead_id, lead_name=_lead_name,
                    content=content, msg_type=msg_type, assigned_to=assigned_to,
                    now_ts=now_ts, phone_number=sender_phone,
                )
                if handled:
                    return

    try:
        _known_wa_session = triage_service.get_active_session(db, org_id, sender_phone)
        if _known_wa_session:
            if not _known_wa_session.get("commerce_state"):
                _restore_commerce_state_if_open(db, org_id, sender_phone, _known_wa_session)
            if (_known_wa_session.get("commerce_state") or "") in COMMERCE_STATES:
                _handle_commerce_message(
                    db=db, org_id=org_id, phone_number=sender_phone,
                    message=message, session=_known_wa_session,
                    msg_type=msg_type, content=content,
                    interactive_payload=interactive_payload, contact_name=contact_name,
                )
                return
    except Exception as _comm_exc:
        logger.warning("Commerce routing (known contact) failed org=%s phone=%s: %s", org_id, sender_phone, _comm_exc)

    if customer_id and not lead_id:
        active_customer_session = triage_service.get_active_session(db, org_id, sender_phone)
        if active_customer_session:
            triage_service.handle_session_message(
                db=db, org_id=org_id, phone_number=sender_phone,
                session=active_customer_session, msg_type=msg_type, content=content,
                interactive_payload=interactive_payload, contact_name=contact_name,
                now_ts=now_ts, section="customer",
            )
            return
        try:
            org_triage_r = (
                db.table("organisations").select("whatsapp_triage_config")
                .eq("id", org_id).maybe_single().execute()
            )
            org_triage_d = org_triage_r.data
            if isinstance(org_triage_d, list):
                org_triage_d = org_triage_d[0] if org_triage_d else None
            triage_cfg = (org_triage_d or {}).get("whatsapp_triage_config") or {}
            customer_menu = triage_cfg.get("customer") or {}
            if customer_menu.get("items"):
                from app.services import whatsapp_service as _wa_svc
                _wa_svc.send_triage_menu(
                    db=db, org_id=org_id, phone_number=sender_phone,
                    section="customer", contact_name=contact_name,
                )
                triage_service.create_customer_session(
                    db=db, org_id=org_id, phone_number=sender_phone, customer_id=customer_id,
                )
                return
        except Exception as exc:
            logger.warning(
                "Customer triage menu check failed for %s — falling through to intent classifier: %s",
                sender_phone, exc,
            )
        if not ai_is_paused:
            handled = customer_inbound_service.handle_customer_inbound(
                db=db, org_id=org_id, customer_id=customer_id,
                content=content, msg_type=msg_type, assigned_to=assigned_to,
                now_ts=now_ts, phone_number=sender_phone,
            )
            if handled:
                return

    if lead_id and not customer_id and msg_type == "text" and content and not ai_is_paused:
        try:
            stage_check = (
                db.table("leads").select("stage").eq("id", lead_id).maybe_single().execute()
            )
            stage_data = stage_check.data
            if isinstance(stage_data, list):
                stage_data = stage_data[0] if stage_data else None
            lead_stage = (stage_data or {}).get("stage", "")
            if lead_stage in ("contacted", "meeting_done", "proposal_sent"):
                customer_inbound_service.handle_lead_stage_signal(
                    db=db, org_id=org_id, lead_id=lead_id, stage=lead_stage,
                    content=content, assigned_to=assigned_to, now_ts=now_ts,
                )
        except Exception as exc:
            logger.warning("Lead stage signal check failed for lead %s — continuing: %s", lead_id, exc)

    if not assigned_to:
        return
    try:
        resource_id   = customer_id or lead_id
        resource_type = "customer" if customer_id else "lead"
        display_name  = contact_name or sender_phone
        try:
            name_table  = "customers" if customer_id else "leads"
            name_id     = customer_id or lead_id
            name_result = (
                db.table(name_table).select("full_name").eq("id", name_id).maybe_single().execute()
            )
            name_data = name_result.data
            if isinstance(name_data, list):
                name_data = name_data[0] if name_data else None
            if name_data and name_data.get("full_name"):
                display_name = name_data["full_name"]
        except Exception:
            pass
        is_new_lead = (lead_id is not None and customer_id is None)
        notif_title = (
            f"New lead via WhatsApp: {display_name}" if is_new_lead
            else f"New WhatsApp reply from {display_name}"
        )
        notif_type = "whatsapp_new_lead" if is_new_lead else "whatsapp_reply"
        db.table("notifications").insert({
            "org_id":         org_id,
            "user_id":        assigned_to,
            "title":          notif_title,
            "body":           content or f"[{msg_type}]",
            "type":           notif_type,
            "resource_type":  resource_type,
            "resource_id":    resource_id,
            "is_read":        False,
            "created_at":     now_ts,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to insert reply notification for user %s: %s", assigned_to, exc)


def _handle_structured_qualification_turn(
    db,
    org_id: str,
    lead_id: str,
    assigned_to,
    content: str,
    interactive_payload,
    now_ts: str,
) -> None:
    session_result = (
        db.table("lead_qualification_sessions")
        .select("*").eq("lead_id", lead_id).eq("ai_active", True)
        .order("created_at", desc=True).limit(1).execute()
    )
    session_rows = session_result.data if isinstance(session_result.data, list) else []
    if not session_rows:
        raise ValueError(f"No active qualification session for lead {lead_id}")
    session = session_rows[0]
    session_id = session["id"]

    org_result = (
        db.table("organisations")
        .select("id, name, qualification_flow, whatsapp_phone_id")
        .eq("id", org_id).maybe_single().execute()
    )
    org_data = org_result.data
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else None
    if not org_data:
        raise ValueError(f"Org {org_id} not found")
    qualification_flow = (org_data or {}).get("qualification_flow")
    if not qualification_flow:
        raise ValueError(f"qualification_flow not configured for org {org_id}")
    questions = qualification_flow.get("questions") or []
    if not questions:
        raise ValueError(f"qualification_flow has no questions for org {org_id}")

    current_index = session.get("current_question_index") or 0
    if current_index >= len(questions):
        raise ValueError(f"qualification session {session_id} already past last question")
    current_question = questions[current_index]
    answer_key = current_question.get("answer_key", f"q{current_index}")
    q_type = current_question.get("type", "free_text")

    existing_answers = dict(session.get("answers") or {})
    if interactive_payload and q_type in ("multiple_choice", "yes_no", "list_select"):
        button_reply = interactive_payload.get("button_reply") or {}
        list_reply = interactive_payload.get("list_reply") or {}
        selected_id = button_reply.get("id") or list_reply.get("id") or content
        options = current_question.get("options") or []
        selected_label = selected_id
        for opt in options:
            if opt.get("id") == selected_id:
                selected_label = opt.get("label", selected_id)
                break
        answer_value = selected_label
    else:
        answer_value = content
    existing_answers[answer_key] = answer_value

    map_to = current_question.get("map_to_lead_field")
    _VALID_LEAD_FIELDS = {"business_name", "business_type", "location", "problem_stated", "branches"}
    if map_to and map_to in _VALID_LEAD_FIELDS:
        try:
            db.table("leads").update({map_to: answer_value}).eq("id", lead_id).execute()
        except Exception as exc:
            logger.warning(
                "_handle_structured_qualification_turn: failed to map field %s for lead %s: %s",
                map_to, lead_id, exc,
            )

    next_index = current_index + 1
    if next_index < len(questions):
        db.table("lead_qualification_sessions").update({
            "current_question_index": next_index,
            "answers": existing_answers,
            "last_message_at": now_ts,
        }).eq("id", session_id).execute()
        send_qualification_question(
            db=db, org_id=org_id,
            phone_number=_get_lead_phone(db, lead_id),
            question=questions[next_index],
            question_index=next_index,
            total=len(questions),
            opening_message=None,
        )
        return

    org_name = (org_data or {}).get("name", "")
    handoff_message = qualification_flow.get(
        "handoff_message",
        "Thanks so much! A member of our team will reach out to you shortly. 🙏",
    )
    lead_data = _get_lead_basic(db, lead_id)
    summary = generate_qualification_summary(answers=existing_answers, lead=lead_data, org_name=org_name)
    lead_phone = _get_lead_phone(db, lead_id)
    send_qualification_handoff_message(db=db, org_id=org_id, phone_number=lead_phone, handoff_message=handoff_message)
    db.table("lead_qualification_sessions").update({
        "ai_active": False, "stage": "handed_off", "answers": existing_answers,
        "handed_off_at": now_ts, "handoff_summary": summary, "last_message_at": now_ts,
    }).eq("id", session_id).execute()

    if assigned_to:
        try:
            db.table("notifications").insert({
                "org_id": org_id, "user_id": assigned_to,
                "title": "Lead ready for follow-up 🎯", "body": summary,
                "type": "qualification_complete", "resource_type": "lead",
                "resource_id": lead_id, "is_read": False, "created_at": now_ts,
            }).execute()
        except Exception as exc:
            logger.warning(
                "_handle_structured_qualification_turn: handoff notification failed for user %s: %s",
                assigned_to, exc,
            )

    try:
        from app.services import lead_service
        lead_service.score_lead(db=db, org_id=org_id, lead_id=lead_id, user_id=assigned_to)
        logger.info("AI scoring triggered at structured qualification handoff for lead %s", lead_id)
    except Exception as exc:
        logger.warning(
            "_handle_structured_qualification_turn: scoring failed for lead %s: %s", lead_id, exc,
        )

    try:
        _post_qual_session = triage_service.get_active_session(db, org_id, lead_phone)
        _prior_action = (_post_qual_session or {}).get("selected_action", "")
        if _prior_action == "transactional_entry":
            _post_qual_session_id = (_post_qual_session or {}).get("id") or ""
            triage_service._action_transactional_entry(db, org_id, lead_phone, _post_qual_session_id, None)
    except Exception as exc:
        logger.warning(
            "_handle_structured_qualification_turn: post-qual transactional entry failed lead=%s: %s",
            lead_id, exc,
        )


def _get_lead_phone(db, lead_id: str) -> str:
    try:
        r = (
            db.table("leads").select("phone, whatsapp").eq("id", lead_id).maybe_single().execute()
        )
        d = r.data
        if isinstance(d, list):
            d = d[0] if d else None
        return (d or {}).get("whatsapp") or (d or {}).get("phone") or ""
    except Exception as exc:
        logger.warning("_get_lead_phone failed for lead %s: %s", lead_id, exc)
        return ""


def _get_lead_basic(db, lead_id: str) -> dict:
    try:
        r = (
            db.table("leads").select("full_name, phone, whatsapp").eq("id", lead_id).maybe_single().execute()
        )
        d = r.data
        if isinstance(d, list):
            d = d[0] if d else None
        return d or {}
    except Exception as exc:
        logger.warning("_get_lead_basic failed for lead %s: %s", lead_id, exc)
        return {}


def _send_qualification_reply(db, org_id: str, lead_id: str, org_data: dict, reply: str, now_ts: str) -> None:
    from app.services.whatsapp_service import _call_meta_send, _now_iso, _get_org_wa_credentials
    from datetime import datetime, timezone, timedelta
    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
    phone_id = (phone_id or "").strip()
    window_expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    try:
        db.table("whatsapp_messages").insert({
            "org_id": org_id, "lead_id": lead_id, "direction": "outbound",
            "message_type": "text", "content": reply, "status": "sent",
            "window_open": True, "window_expires_at": window_expires,
            "sent_by": None, "created_at": now_ts,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to save qualification reply to DB: %s", exc)
    if not phone_id:
        logger.warning("No whatsapp_phone_id configured for org %s — reply saved but not sent", org_id)
        return
    try:
        lead_result = (
            db.table("leads").select("phone, whatsapp").eq("id", lead_id).maybe_single().execute()
        )
        lead_data = lead_result.data
        if isinstance(lead_data, list):
            lead_data = lead_data[0] if lead_data else None
        to_number = (lead_data or {}).get("whatsapp") or (lead_data or {}).get("phone")
        if not to_number:
            logger.warning("No phone/whatsapp on lead %s — cannot send reply", lead_id)
            return
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp", "to": to_number,
            "type": "text", "text": {"body": reply},
        }, token=access_token)
    except Exception as exc:
        logger.warning("Failed to send qualification reply via Meta API: %s", exc)


def _handle_status_update(db, status_update: dict) -> None:
    meta_msg_id = status_update.get("id")
    new_status  = status_update.get("status")
    if not meta_msg_id or not new_status:
        return
    updates: dict = {"status": new_status}
    now_ts = _now_iso()
    if new_status == "delivered":
        updates["delivered_at"] = now_ts
    elif new_status == "read":
        updates["read_at"] = now_ts
    try:
        db.table("whatsapp_messages").update(updates).eq("meta_message_id", meta_msg_id).execute()
    except Exception as exc:
        logger.warning("Status update failed for meta_message_id=%s: %s", meta_msg_id, exc)


def _handle_template_status_update(db, value: dict) -> None:
    try:
        meta_id  = str(value.get("message_template_id", ""))
        name     = value.get("message_template_name", "")
        event    = (value.get("event") or "").upper()
        new_cat  = (value.get("new_message_template_category") or "").lower()
        status_map = {
            "APPROVED": "approved", "REJECTED": "rejected", "DISABLED": "rejected",
            "PAUSED": "rejected", "FLAGGED": "rejected", "PENDING_DELETION": "rejected",
        }
        new_status = status_map.get(event)
        if not new_status:
            logger.info("_handle_template_status_update: unhandled event '%s' for template '%s' — ignoring", event, name)
            return
        updates: dict = {"meta_status": new_status}
        if new_cat and new_cat in ("marketing", "utility", "authentication"):
            updates["category"] = new_cat
        matched = False
        if meta_id:
            result = db.table("whatsapp_templates").update(updates).eq("meta_template_id", meta_id).execute()
            rows = result.data if isinstance(result.data, list) else []
            if rows:
                matched = True
                logger.info(
                    "_handle_template_status_update: template '%s' (meta_id=%s) updated to status=%s category=%s",
                    name, meta_id, new_status, new_cat or "unchanged",
                )
        if not matched and name:
            result = (
                db.table("whatsapp_templates").update(updates)
                .eq("name", name).eq("meta_status", "pending").execute()
            )
            rows = result.data if isinstance(result.data, list) else []
            if rows:
                logger.info(
                    "_handle_template_status_update: template '%s' matched by name — updated to status=%s category=%s",
                    name, new_status, new_cat or "unchanged",
                )
            else:
                logger.warning(
                    "_handle_template_status_update: no template found for name='%s' meta_id='%s' — update skipped",
                    name, meta_id,
                )
        if new_status == "rejected":
            _cancel_broadcasts_for_rejected_template(db, meta_id, name)
    except Exception as exc:
        logger.warning("_handle_template_status_update failed: %s", exc)


def _cancel_broadcasts_for_rejected_template(db, meta_template_id: str, template_name: str) -> None:
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        template_rows = []
        if meta_template_id:
            res = db.table("whatsapp_templates").select("id, org_id, name").eq("meta_template_id", meta_template_id).execute()
            template_rows = res.data if isinstance(res.data, list) else []
        if not template_rows and template_name:
            res = db.table("whatsapp_templates").select("id, org_id, name").eq("name", template_name).execute()
            template_rows = res.data if isinstance(res.data, list) else []
        if not template_rows:
            logger.info(
                "_cancel_broadcasts_for_rejected_template: no template rows found for meta_id=%s name=%s — nothing to cancel",
                meta_template_id, template_name,
            )
            return
        for tmpl in template_rows:
            tmpl_id   = tmpl.get("id")
            org_id    = tmpl.get("org_id")
            tmpl_name = tmpl.get("name", template_name)
            if not tmpl_id or not org_id:
                continue
            try:
                bc_res = (
                    db.table("broadcasts").select("id, name")
                    .eq("org_id", org_id).eq("template_id", tmpl_id)
                    .in_("status", ["scheduled", "sending"]).execute()
                )
                broadcasts = bc_res.data if isinstance(bc_res.data, list) else []
                if not broadcasts:
                    continue
                bc_ids = [b["id"] for b in broadcasts]
                db.table("broadcasts").update({"status": "cancelled", "updated_at": now}).eq("org_id", org_id).in_("id", bc_ids).execute()
                logger.info("G4: cancelled %d broadcast(s) for rejected template '%s' org=%s", len(bc_ids), tmpl_name, org_id)
                _notify_owner_template_rejected(db, org_id, tmpl_name, len(bc_ids), now)
            except Exception as inner_exc:
                logger.warning(
                    "_cancel_broadcasts_for_rejected_template: failed for template %s org=%s — %s",
                    tmpl_id, org_id, inner_exc,
                )
    except Exception as exc:
        logger.warning("_cancel_broadcasts_for_rejected_template failed: %s", exc)


def _notify_owner_template_rejected(db, org_id: str, template_name: str, cancelled_count: int, now: str) -> None:
    try:
        users_res = db.table("users").select("id, roles(template)").eq("org_id", org_id).execute()
        users = users_res.data if isinstance(users_res.data, list) else []
        for user in users:
            template = ((user.get("roles") or {}).get("template") or "").lower()
            if template != "owner":
                continue
            plural = "broadcasts" if cancelled_count > 1 else "broadcast"
            db.table("notifications").insert({
                "org_id": org_id, "user_id": user["id"],
                "type": "broadcast_cancelled",
                "title": "Broadcast Cancelled — Template Rejected",
                "body": (
                    f"Meta rejected your WhatsApp template '{template_name}'. "
                    f"{cancelled_count} {plural} using this template "
                    f"{'have' if cancelled_count > 1 else 'has'} been cancelled. "
                    "Please review your template and resubmit."
                ),
                "resource_type": "broadcast", "is_read": False, "created_at": now,
            }).execute()
    except Exception as exc:
        logger.warning("_notify_owner_template_rejected failed org=%s: %s", org_id, exc)


@router.post("/meta/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_message(request: Request, db=Depends(get_supabase)):
    import time as _time
    _t0 = _time.monotonic()
    raw_body  = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw_body, signature):
        _log_webhook(db, route="/webhooks/meta/whatsapp", response_status=403, error_message="Invalid signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")
    payload: dict = json.loads(raw_body)
    from app.workers.webhook_worker import process_inbound_webhook
    process_inbound_webhook.delay(payload)
    _log_webhook(
        db, route="/webhooks/meta/whatsapp", response_status=200,
        topic="whatsapp_inbound", processing_ms=int((_time.monotonic() - _t0) * 1000),
    )
    return Response(status_code=200)


@router.get("/meta/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        if hub_challenge and hub_challenge.isdigit():
            return int(hub_challenge)
        return hub_challenge
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed — token mismatch")


# ---------------------------------------------------------------------------
# POST /webhooks/payment/paystack
# ---------------------------------------------------------------------------

@router.post("/payment/paystack", status_code=status.HTTP_200_OK)
async def receive_paystack_webhook(request: Request, db=Depends(get_supabase)):
    raw_body = await request.body()
    import time as _time
    _t0 = _time.monotonic()
    sig = request.headers.get("X-Paystack-Signature")
    if not _verify_paystack_signature(raw_body, sig):
        logger.warning("Paystack webhook: invalid signature — rejecting")
        _log_webhook(db, route="/webhooks/payment/paystack", response_status=403, error_message="Invalid signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Paystack signature")
    payload: dict = json.loads(raw_body)
    _err = None
    try:
        process_paystack_webhook(db=db, payload=payload)
    except Exception as exc:
        logger.error("Paystack webhook processing error: %s", exc)
        _err = str(exc)[:500]
    _log_webhook(
        db, route="/webhooks/payment/paystack", response_status=200,
        topic=json.loads(raw_body).get("event") if not _err else None,
        processing_ms=int((_time.monotonic() - _t0) * 1000), error_message=_err,
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /webhooks/payment/flutterwave
# ---------------------------------------------------------------------------

@router.post("/payment/flutterwave", status_code=status.HTTP_200_OK)
async def receive_flutterwave_webhook(request: Request, db=Depends(get_supabase)):
    raw_body = await request.body()
    import time as _time
    _t0 = _time.monotonic()
    hash_header = request.headers.get("verif-hash")
    if not _verify_flutterwave_hash(hash_header):
        logger.warning("Flutterwave webhook: invalid hash — rejecting")
        _log_webhook(db, route="/webhooks/payment/flutterwave", response_status=403, error_message="Invalid hash")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Flutterwave hash")
    payload: dict = json.loads(raw_body)
    _err = None
    try:
        process_flutterwave_webhook(db=db, payload=payload)
    except Exception as exc:
        logger.error("Flutterwave webhook processing error: %s", exc)
        _err = str(exc)[:500]
    _log_webhook(
        db, route="/webhooks/payment/flutterwave", response_status=200,
        topic=payload.get("event", {}).get("type") if not _err else None,
        processing_ms=int((_time.monotonic() - _t0) * 1000), error_message=_err,
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /webhooks/shopify
# ---------------------------------------------------------------------------

@router.post("/shopify", status_code=status.HTTP_200_OK)
async def receive_shopify_webhook(request: Request, db=Depends(get_supabase)):
    raw_body = await request.body()
    import time as _time
    _t0 = _time.monotonic()
    topic = request.headers.get("X-Shopify-Topic") or ""
    shop_domain = request.headers.get("X-Shopify-Shop-Domain") or ""
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256") or ""
    logger.info("[SHOPIFY] topic=%s shop=%s", topic, shop_domain)
    if not shop_domain:
        logger.warning("[SHOPIFY] missing X-Shopify-Shop-Domain header — dropping")
        return {"status": "ok"}
    org_r = (
        db.table("organisations").select("id, shopify_webhook_secret, shopify_connected")
        .eq("shopify_shop_domain", shop_domain).maybe_single().execute()
    )
    org_d = org_r.data
    if isinstance(org_d, list):
        org_d = org_d[0] if org_d else None
    if not org_d:
        logger.warning("[SHOPIFY] no org found for shop_domain=%s — dropping", shop_domain)
        return {"status": "ok"}
    org_id = org_d["id"]
    webhook_secret = (org_d.get("shopify_webhook_secret") or "").strip()
    if webhook_secret:
        if not shopify_service.verify_webhook(raw_body, hmac_header, webhook_secret):
            logger.warning("[SHOPIFY] invalid HMAC for org=%s topic=%s", org_id, topic)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Shopify webhook signature")
    try:
        payload = json.loads(raw_body)
    except Exception as exc:
        logger.warning("[SHOPIFY] invalid JSON for org=%s: %s", org_id, exc)
        return {"status": "ok"}
    try:
        if topic in ("products/create", "products/update"):
            shopify_service.sync_product(db=db, org_id=org_id, shopify_product=payload)
        elif topic == "products/delete":
            shopify_service.handle_product_deleted(db=db, org_id=org_id, shopify_product_id=payload.get("id"))
        elif topic == "checkouts/update":
            shopify_service.handle_abandoned_cart(db=db, org_id=org_id, checkout=payload)
        elif topic == "orders/create":
            shopify_service.handle_order_created(db=db, org_id=org_id, order=payload)
        elif topic == "fulfillments/create":
            shopify_service.handle_fulfillment_created(db=db, org_id=org_id, fulfillment=payload)
        else:
            logger.info("[SHOPIFY] unhandled topic=%s org=%s — ignoring", topic, org_id)
    except Exception as exc:
        logger.error("[SHOPIFY] handler error org=%s topic=%s: %s", org_id, topic, exc)
        _log_webhook(
            db, route="/webhooks/shopify", org_id=org_id, topic=topic,
            response_status=200, processing_ms=int((_time.monotonic() - _t0) * 1000),
            error_message=str(exc)[:500],
        )
        return {"status": "ok"}
    _log_webhook(
        db, route="/webhooks/shopify", org_id=org_id, topic=topic,
        response_status=200, processing_ms=int((_time.monotonic() - _t0) * 1000),
    )
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# COMM-1 — Commerce Helper Functions
# ---------------------------------------------------------------------------

def _restore_commerce_state_if_open(db, org_id: str, phone_number: str, session: dict) -> None:
    try:
        open_cs = (
            db.table("commerce_sessions").select("*")
            .eq("org_id", org_id).eq("phone_number", phone_number)
            .in_("status", ["open", "checkout_sent"])
            .order("created_at", desc=True).limit(1).execute()
        )
        cs_rows = open_cs.data if isinstance(open_cs.data, list) else []
        if not cs_rows:
            return
        cs = cs_rows[0]
        if cs.get("status") == "checkout_sent":
            restored_state = "commerce_checkout"
        elif cs.get("cart") and len(cs["cart"]) > 0:
            restored_state = "commerce_cart"
        else:
            restored_state = "commerce_browsing"
        triage_service.update_session(db, session["id"], "active", selected_action="commerce_entry")
        db.table("whatsapp_sessions").update({"commerce_state": restored_state}).eq("id", session["id"]).execute()
        session["commerce_state"] = restored_state
    except Exception as exc:
        logger.warning("_restore_commerce_state_if_open failed org=%s phone=%s: %s", org_id, phone_number, exc)


def _extract_interactive_id(message: dict) -> Optional[str]:
    interactive = message.get("interactive") or {}
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return reply.get("id")


def _extract_list_selection(message: dict) -> Optional[str]:
    interactive = message.get("interactive") or {}
    reply = interactive.get("list_reply") or {}
    return reply.get("id") or None


def _is_cancel_intent(message: dict, content: Optional[str]) -> bool:
    text = (content or "").lower().strip()
    iid = (_extract_interactive_id(message) or "").lower()
    return any(k in text for k in ("cancel", "stop", "clear", "nevermind")) or iid == "cancel"


def _is_resend_intent(message: dict, content: Optional[str]) -> bool:
    text = (content or "").lower().strip()
    iid = (_extract_interactive_id(message) or "").lower()
    return any(k in text for k in ("resend", "send again", "checkout")) or iid == "resend"


def _is_checkout_intent(message: dict, content: Optional[str]) -> bool:
    text = (content or "").lower().strip()
    iid = (_extract_interactive_id(message) or "").lower()
    return iid == "checkout" or any(k in text for k in ("checkout", "pay", "buy now"))


def _is_add_more_intent(message: dict, content: Optional[str]) -> bool:
    text = (content or "").lower().strip()
    iid = (_extract_interactive_id(message) or "").lower()
    return iid == "add_more" or any(k in text for k in ("add more", "more", "continue"))


def _fetch_product(db, org_id: str, product_id: str) -> dict:
    try:
        r = (
            db.table("products").select("*")
            .eq("id", product_id).eq("org_id", org_id).eq("is_active", True)
            .maybe_single().execute()
        )
        d = r.data
        if isinstance(d, list):
            d = d[0] if d else None
        return d or {}
    except Exception as exc:
        logger.warning("_fetch_product failed org=%s product=%s: %s", org_id, product_id, exc)
        return {}


def _fetch_products(db, org_id: str) -> list:
    try:
        r = (
            db.table("products").select("*")
            .eq("org_id", org_id).eq("is_active", True).order("title").execute()
        )
        return r.data if isinstance(r.data, list) else []
    except Exception as exc:
        logger.warning("_fetch_products failed org=%s: %s", org_id, exc)
        return []


def _find_variant(product: dict, variant_id: str) -> dict:
    for v in (product.get("variants") or []):
        vid = str(v.get("id") or v.get("variant_id") or "")
        if vid and vid == str(variant_id):
            return v
    return {}


# ---------------------------------------------------------------------------
# COMM-1 — Core Commerce Message Handler
# ---------------------------------------------------------------------------

def _handle_commerce_message(
    db,
    org_id: str,
    phone_number: str,
    message: dict,
    session: dict,
    msg_type: str,
    content: Optional[str],
    interactive_payload: Optional[dict],
    contact_name: Optional[str] = None,
) -> None:
    from app.services.commerce_service import (
        get_or_create_commerce_session,
        add_to_cart,
        mark_cart_abandoned,
        generate_shopify_checkout,
    )
    from app.services.whatsapp_service import (
        send_product_list,
        send_variant_selection,
        send_cart_summary,
        send_checkout_link,
    )

    try:
        # ── Talk to Sales escape — fires before any state routing ────────────
        _btn_id = (interactive_payload or {}).get("button_reply", {}).get("id", "")
        _list_id = (interactive_payload or {}).get("list_reply", {}).get("id", "")
        if _btn_id == "talk_sales" or _list_id == "talk_sales":
            from app.services.whatsapp_service import _call_meta_send, _get_org_wa_credentials

            # 1. Leave the commerce_session open — do NOT abandon it.
            # If the user changes their mind and goes back to browse products,
            # _restore_commerce_state_if_open will find this session and
            # re-enter the commerce flow seamlessly. The session will be
            # abandoned naturally if the rep closes it or the user checks out.

            # 2. Clear commerce_state on whatsapp_session
            db.table("whatsapp_sessions").update(
                {"commerce_state": None}
            ).eq("id", session["id"]).execute()

            # 3. Find or create a lead for this phone number
            lead_id = (session.get("session_data") or {}).get("lead_id")
            assigned_to = None
            _lead_was_preexisting = False
            if not lead_id:
                try:
                    lead_r = (
                        db.table("leads").select("id, assigned_to")
                        .eq("org_id", org_id).eq("whatsapp", phone_number)
                        .is_("deleted_at", "null").limit(1).execute()
                    )
                    lead_rows = lead_r.data if isinstance(lead_r.data, list) else []
                    if lead_rows:
                        lead_id = lead_rows[0]["id"]
                        assigned_to = lead_rows[0].get("assigned_to")
                        _lead_was_preexisting = True
                except Exception:
                    pass

            if not lead_id:
                from app.models.leads import LeadCreate, LeadSource
                from app.services import lead_service
                new_lead = lead_service.create_lead(
                    db, org_id, None,
                    LeadCreate(
                        full_name=contact_name or phone_number,
                        phone=phone_number, whatsapp=phone_number,
                        source=LeadSource.whatsapp_inbound.value,
                        contact_type="sales_lead",
                    ),
                )
                if new_lead:
                    lead_id = new_lead["id"]
                    assigned_to = new_lead.get("assigned_to")

            # 4. Notify assigned rep
            if not assigned_to:
                try:
                    users_r = db.table("users").select("id, roles(template)").eq("org_id", org_id).execute()
                    for u in (users_r.data or []):
                        if (u.get("roles") or {}).get("template", "").lower() == "owner":
                            assigned_to = u["id"]
                            break
                except Exception:
                    pass

            if assigned_to and lead_id:
                display_name = contact_name or phone_number
                try:
                    db.table("notifications").insert({
                        "org_id": org_id, "user_id": assigned_to,
                        "type": "new_lead",
                        "title": "Contact switched from shopping to sales",
                        "body": f"{display_name} was browsing products and asked to speak with someone.",
                        "is_read": False, "channel": "inapp",
                    }).execute()
                except Exception as _notif_exc:
                    logger.warning("_handle_commerce_message talk_sales: notification failed: %s", _notif_exc)

            # 5. Confirm to the user — fetch credentials first so a missing
            # phone_id is surfaced as a warning, not a silent no-op.
            phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
            if not phone_id:
                logger.warning(
                    "_handle_commerce_message talk_sales: no whatsapp_phone_id "
                    "for org %s — confirmation not sent to %s", org_id, phone_number,
                )
            else:
                # If they already had an assigned rep, they're in the queue —
                # send reassurance rather than a generic handoff message.
                if _lead_was_preexisting and assigned_to:
                    reply_body = (
                        "You're already in our queue! 😊 A member of our team "
                        "will be with you shortly — no need to worry."
                    )
                else:
                    reply_body = (
                        "No problem! One of our team will be in touch with you shortly. 😊"
                    )
                _call_meta_send(phone_id, {
                    "messaging_product": "whatsapp",
                    "to": phone_number,
                    "type": "text",
                    "text": {"body": reply_body},
                }, token=access_token)

                # ── Backfill whatsapp_messages so the 24-hour window is recorded ──
                if lead_id:
                    try:
                        from datetime import datetime, timezone, timedelta
                        _window_expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
                        _now = _now_iso()
                        db.table("whatsapp_messages").insert({
                            "org_id": org_id, "lead_id": lead_id,
                            "direction": "inbound", "message_type": "text",
                            "content": "Speak to Sales", "status": "delivered",
                            "window_open": True, "window_expires_at": _window_expires,
                            "created_at": _now,
                        }).execute()
                        db.table("whatsapp_messages").insert({
                            "org_id": org_id, "lead_id": lead_id,
                            "direction": "outbound", "message_type": "text",
                            "content": reply_body, "status": "sent",
                            "window_open": True, "window_expires_at": _window_expires,
                            "sent_by": None, "created_at": _now,
                        }).execute()
                    except Exception as _wm_exc:
                        logger.warning(
                            "_handle_commerce_message talk_sales: whatsapp_messages "
                            "backfill failed for lead %s: %s", lead_id, _wm_exc,
                        )

            logger.info("[WH] talk_sales escape from commerce — org=%s phone=%s lead=%s", org_id, phone_number, lead_id)
            return
        # ── End Talk to Sales escape ─────────────────────────────────────────

        state = session.get("commerce_state", "")

        cs_result = (
            db.table("commerce_sessions").select("*")
            .eq("org_id", org_id).eq("phone_number", phone_number)
            .in_("status", ["open", "checkout_sent"])
            .order("created_at", desc=True).limit(1).execute()
        )
        cs_rows = cs_result.data if isinstance(cs_result.data, list) else []
        commerce_session = cs_rows[0] if cs_rows else {}

        org_cfg_r = (
            db.table("organisations").select("commerce_config")
            .eq("id", org_id).maybe_single().execute()
        )
        org_cfg_d = org_cfg_r.data
        if isinstance(org_cfg_d, list):
            org_cfg_d = org_cfg_d[0] if org_cfg_d else None
        commerce_config = (org_cfg_d or {}).get("commerce_config") or {}

        if state == "commerce_browsing":
            product_id = _extract_list_selection(message)
            if not product_id:
                # Check if user asked to see the full catalog
                _browse_text = (content or "").lower().strip()
                _full_catalog_keywords = (
                    "all products", "full catalog", "see all",
                    "more products", "all items", "everything",
                )
                if any(k in _browse_text for k in _full_catalog_keywords):
                    try:
                        from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send
                        _cat_phone_id, _cat_token, _ = _get_org_wa_credentials(db, org_id)
                        _shop_r = (
                            db.table("organisations").select("shopify_shop_domain")
                            .eq("id", org_id).maybe_single().execute()
                        )
                        _shop_d = _shop_r.data
                        if isinstance(_shop_d, list):
                            _shop_d = _shop_d[0] if _shop_d else None
                        _shop_domain = (_shop_d or {}).get("shopify_shop_domain") or None
                        if _cat_phone_id and _cat_token:
                            if _shop_domain:
                                _catalog_url = (
                                    f"https://{_shop_domain}"
                                    f"?utm_source=whatsapp&utm_medium=chat"
                                    f"&utm_campaign=product_browse"
                                )
                                _catalog_body = (
                                    f"Here's our full product catalog \U0001f6cd\ufe0f\n\n"
                                    f"{_catalog_url}\n\n"
                                    "Feel free to come back here to place your order on WhatsApp!"
                                )
                            else:
                                _catalog_body = (
                                    "Our product selection is shown in the list above. "
                                    "Tap any item to add it to your cart, or tap "
                                    "*Speak to Sales* and our team will help you find "
                                    "what you need."
                                )
                            _call_meta_send(_cat_phone_id, {
                                "messaging_product": "whatsapp",
                                "to": phone_number,
                                "type": "text",
                                "text": {"body": _catalog_body},
                            }, token=_cat_token)
                    except Exception as _cat_exc:
                        logger.warning(
                            "_handle_commerce_message: full catalog reply failed "
                            "org=%s phone=%s: %s", org_id, phone_number, _cat_exc,
                        )
                    return

                # No product selected and no catalog request — show product list
                products = _fetch_products(db, org_id)
                send_product_list(db, org_id, phone_number, products)
                return

            product = _fetch_product(db, org_id, product_id)
            if not product:
                logger.warning("_handle_commerce_message: product %s not found org=%s", product_id, org_id)
                products = _fetch_products(db, org_id)
                send_product_list(db, org_id, phone_number, products)
                return

            variants = product.get("variants") or []
            if len(variants) <= 1:
                variant = variants[0] if variants else {}
                variant_id = str(variant.get("id") or variant.get("variant_id") or "")
                if not commerce_session:
                    lead_id = session.get("session_data", {}).get("lead_id")
                    commerce_session = get_or_create_commerce_session(db, org_id, phone_number, lead_id=lead_id)
                commerce_session = add_to_cart(db, commerce_session, product, variant_id, quantity=1)
                db.table("whatsapp_sessions").update({"commerce_state": "commerce_cart"}).eq("id", session["id"]).execute()
                session["commerce_state"] = "commerce_cart"
                send_cart_summary(db, org_id, phone_number, commerce_session)
            else:
                db.table("whatsapp_sessions").update({
                    "commerce_state": "commerce_variant_select",
                    "pending_product_id": product_id,
                }).eq("id", session["id"]).execute()
                send_variant_selection(db, org_id, phone_number, product)

        elif state == "commerce_variant_select":
            raw_id = _extract_interactive_id(message) or ""
            variant_id = raw_id.removeprefix("variant_") if raw_id.startswith("variant_") else raw_id
            product_id = session.get("pending_product_id") or ""
            product = _fetch_product(db, org_id, product_id) if product_id else {}
            if not product or not variant_id:
                logger.warning(
                    "_handle_commerce_message: variant_select missing product or variant "
                    "org=%s phone=%s product=%s variant=%s",
                    org_id, phone_number, product_id, variant_id,
                )
                products = _fetch_products(db, org_id)
                send_product_list(db, org_id, phone_number, products)
                db.table("whatsapp_sessions").update(
                    {"commerce_state": "commerce_browsing", "pending_product_id": None}
                ).eq("id", session["id"]).execute()
                return
            if not commerce_session:
                lead_id = session.get("session_data", {}).get("lead_id")
                commerce_session = get_or_create_commerce_session(db, org_id, phone_number, lead_id=lead_id)
            commerce_session = add_to_cart(db, commerce_session, product, variant_id, quantity=1)
            db.table("whatsapp_sessions").update({
                "commerce_state": "commerce_cart", "pending_product_id": None,
            }).eq("id", session["id"]).execute()
            send_cart_summary(db, org_id, phone_number, commerce_session)

        elif state == "commerce_cart":
            if _is_checkout_intent(message, content):
                if not commerce_session:
                    lead_id = session.get("session_data", {}).get("lead_id")
                    commerce_session = get_or_create_commerce_session(db, org_id, phone_number, lead_id=lead_id)
                checkout_url = generate_shopify_checkout(db, org_id, commerce_session)
                db.table("whatsapp_sessions").update({"commerce_state": "commerce_checkout"}).eq("id", session["id"]).execute()
                send_checkout_link(db, org_id, phone_number, checkout_url, commerce_config)
            elif _is_add_more_intent(message, content):
                products = _fetch_products(db, org_id)
                db.table("whatsapp_sessions").update({"commerce_state": "commerce_browsing"}).eq("id", session["id"]).execute()
                # Build a context-aware message so the user knows they're adding
                # to an existing cart, not starting from scratch.
                _cart_items = (commerce_session or {}).get("cart") or []
                _item_count = len(_cart_items)
                _add_more_body = (
                    f"You have {_item_count} item{'s' if _item_count != 1 else ''} in your cart. "
                    f"What else would you like to add? \ud83d\uded2"
                )
                send_product_list(db, org_id, phone_number, products, add_more_context=_add_more_body)
            else:
                if commerce_session:
                    send_cart_summary(db, org_id, phone_number, commerce_session)

        elif state == "commerce_checkout":
            if _is_cancel_intent(message, content):
                if commerce_session:
                    mark_cart_abandoned(db, commerce_session["id"])
                db.table("whatsapp_sessions").update({"commerce_state": None}).eq("id", session["id"]).execute()
                from app.services.whatsapp_service import _get_org_wa_credentials, _call_meta_send
                try:
                    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
                    if phone_id:
                        _call_meta_send(phone_id, {
                            "messaging_product": "whatsapp", "to": phone_number,
                            "type": "text",
                            "text": {"body": "Your cart has been cleared. Feel free to browse again anytime."},
                        }, token=access_token)
                except Exception:
                    pass
            elif _is_resend_intent(message, content):
                if commerce_session:
                    checkout_url = generate_shopify_checkout(db, org_id, commerce_session)
                    send_checkout_link(db, org_id, phone_number, checkout_url, commerce_config)
            else:
                # Any other message — resend existing link as reminder
                existing_url = (commerce_session or {}).get("checkout_url") or ""
                if existing_url:
                    _reminder_config = {
                        **(commerce_config or {}),
                        "checkout_message": "You have a pending checkout! Complete your order here 👇",
                    }
                    send_checkout_link(db, org_id, phone_number, existing_url, _reminder_config)

    except Exception as exc:
        logger.warning(
            "_handle_commerce_message failed org=%s phone=%s state=%s: %s",
            org_id, phone_number, session.get("commerce_state"), exc,
        )
