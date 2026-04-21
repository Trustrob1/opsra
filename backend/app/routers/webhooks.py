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
from app.services import triage_service
from app.services import customer_inbound_service
from app.services.subscription_service import (
    process_paystack_webhook,
    process_flutterwave_webhook,
)
from app.services.whatsapp_service import send_qualification_question, send_qualification_handoff_message
from app.services.ai_service import generate_qualification_summary

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

    # Search customer_contacts — B2B employees linked to a customer account (WH-0)
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


def _lookup_org_by_phone_number_id(db, phone_number_id: str) -> Optional[str]:
    """
    Look up org_id by matching phone_number_id against organisations.whatsapp_phone_id.
    Used when an inbound WhatsApp message arrives from an unknown number — we still
    need to know which org owns the receiving WhatsApp number to create the lead.
    Returns org_id string or None if not found.
    S14: failures swallowed — returns None.
    """
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


def _handle_inbound_message(db, message: dict, contact_name: str, phone_number_id: str) -> None:
    """
    Process one inbound WhatsApp text message.

    Flow:
      1. Look up customer/lead by sender phone number
      2a. If found → save message, notify assigned rep
      2b. If NOT found → look up org by phone_number_id, auto-create new lead (M01-1),
          save message against the new lead, notify via new-lead notification

    S14 — all failures after message save are swallowed.
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
    elif msg_type == "interactive":
        interactive_type = (message.get("interactive") or {}).get("type")
        if interactive_type == "list_reply":
            content = (message.get("interactive", {})
                       .get("list_reply", {}).get("id"))
        elif interactive_type == "button_reply":
            content = (message.get("interactive", {})
                       .get("button_reply", {}).get("id"))
        else:
            content = f"[interactive:{interactive_type}]"
    else:
        content = f"[{msg_type}]"

    # WH-0: capture full interactive dict for triage session handler
    interactive_payload = message.get("interactive") if msg_type == "interactive" else None
    print(f"[WH] msg_type={msg_type} content={content!r} from={sender_phone}", flush=True)

    org_id, customer_id, lead_id, assigned_to = _lookup_record_by_phone(db, sender_phone)
    print(f"[WH] lookup result: org_id={org_id} customer_id={customer_id} lead_id={lead_id}", flush=True)

    if not org_id:
        # Derive org from the receiving WhatsApp phone_number_id.
        org_id = _lookup_org_by_phone_number_id(db, phone_number_id)
        print(f"[WH] unknown number — org_id from phone_number_id={org_id}", flush=True)
        if not org_id: 
            print(f"[WH] no org found — dropping message", flush=True)
            return

        # WH-0: Check for an active triage session before taking any pipeline action.
        active_session = triage_service.get_active_session(db, org_id, sender_phone)
        print(f"[WH] active_session={active_session}", flush=True)
        if active_session:
            print(f"[WH] routing to session handler", flush=True)
            triage_service.handle_session_message(
                db=db,
                org_id=org_id,
                phone_number=sender_phone,
                session=active_session,
                msg_type=msg_type,
                content=content,
                interactive_payload=interactive_payload,
                contact_name=contact_name,
                now_ts=_now_iso(),
            )
            return

        # No active session — check org behavior setting.
        org_behavior_result = (
            db.table("organisations")
            .select("unknown_contact_behavior, whatsapp_triage_config, whatsapp_phone_id")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_behavior = org_behavior_result.data
        if isinstance(org_behavior, list):
            org_behavior = org_behavior[0] if org_behavior else None
        behavior = (org_behavior or {}).get("unknown_contact_behavior", "triage_first")
        triage_config = (org_behavior or {}).get("whatsapp_triage_config")
        print(f"[WH] behavior={behavior} triage_config={triage_config}", flush=True)

        if behavior == "qualify_immediately":
            print(f"[WH] qualify_immediately path", flush=True)
            # Preserved legacy path — auto-create lead + fire qualification bot.
            # Duplicate-race handler lives in this branch only.
            provisional_name = (contact_name or "").strip() or sender_phone
            try:
                new_lead_payload = LeadCreate(
                    full_name      = provisional_name,
                    phone          = sender_phone,
                    whatsapp       = sender_phone,
                    source         = LeadSource.whatsapp_inbound.value,
                    problem_stated = content if msg_type == "text" else None,
                )
                new_lead = lead_service.create_lead(
                    db      = db,
                    org_id  = org_id,
                    user_id = "system",
                    payload = new_lead_payload,
                )
                lead_id     = new_lead["id"]
                assigned_to = new_lead.get("assigned_to")
                logger.info(
                    "Auto-created lead %s for inbound WhatsApp from %s (org=%s)",
                    lead_id, sender_phone, org_id,
                )
            except Exception as exc:
                detail = getattr(exc, "detail", {}) or {}
                code   = detail.get("code", "") if isinstance(detail, dict) else str(detail)
                if code == ErrorCode.DUPLICATE_DETECTED:
                    logger.info(
                        "Duplicate on auto-create for %s — re-looking up", sender_phone
                    )
                    org_id, customer_id, lead_id, assigned_to = _lookup_record_by_phone(
                        db, sender_phone
                    )
                    if not lead_id and not customer_id:
                        logger.warning(
                            "Re-lookup after duplicate also found nothing for %s",
                            sender_phone,
                        )
                        return
                else:
                    logger.error("Failed to auto-create lead for %s: %s", sender_phone, exc)
                    return

        else:
            # triage_first (default) — send interactive menu and create session.
            # Do NOT create a lead or fire the qualification bot.
            print(f"[WH] triage_first path — sending menu", flush=True)
            from app.services.whatsapp_service import send_triage_menu
            try:
                send_triage_menu(
                    db=db, org_id=org_id,
                    phone_number=sender_phone, section="unknown",
                )
                print(f"[WH] triage menu sent successfully", flush=True)
                triage_service.create_session(
                    db=db, org_id=org_id, phone_number=sender_phone,
                )
                print(f"[WH] session created", flush=True)
            except Exception as exc:
                print(f"[WH] triage menu FAILED: {exc}", flush=True)
            return  # No lead/customer yet — nothing further to save

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

    # M01-10a: Nurture track handling — GAP-4 unsubscribe check fires first,
    # then re-engagement. Only one branch executes per message.
    # S14 — all failures are swallowed; flow continues to qualification check.
    reengaged_from_nurture = False
    if lead_id and not customer_id:
        try:
            nurture_check = (
                db.table("leads")
                .select("nurture_track")
                .eq("id", lead_id)
                .maybe_single()
                .execute()
            )
            nurture_data = nurture_check.data
            if isinstance(nurture_data, list):
                nurture_data = nurture_data[0] if nurture_data else None
            if (nurture_data or {}).get("nurture_track"):
                # GAP-4: Unsubscribe takes highest priority — check before re-engagement.
                # If lead opts out, mark permanently and stop all further processing.
                if msg_type == "text" and content:
                    from app.services.nurture_service import (
                        is_unsubscribe_signal,
                        mark_lead_unsubscribed,
                    )
                    if is_unsubscribe_signal(content):
                        mark_lead_unsubscribed(
                            db=db,
                            org_id=org_id,
                            lead_id=lead_id,
                            now_ts=now_ts,
                        )
                        logger.info(
                            "Lead %s opted out of nurture via unsubscribe signal — "
                            "no re-engagement or rep notification",
                            lead_id,
                        )
                        return  # Do NOT re-engage, do NOT notify rep

                # Normal reply on nurture track — re-engage lead to active pipeline
                from app.services.nurture_service import handle_re_engagement
                handle_re_engagement(
                    db=db,
                    org_id=org_id,
                    lead_id=lead_id,
                    assigned_to=assigned_to,
                    now_ts=now_ts,
                )
                reengaged_from_nurture = True
        except Exception as exc:  # S14
            logger.warning(
                "Re-engagement check failed for lead %s — continuing: %s",
                lead_id, exc,
            )

    # M01-10a (gap fix): Self-identified not-ready detection.
    # GAP-2: Skipped if lead has an active qualification session — the bot handles it.
    # Only runs for active (non-nurture) leads on text messages.
    # Skips if the lead just re-engaged from nurture (handled above).
    # S14 — failures are swallowed; flow continues to qualification/rep notification.
    if lead_id and not customer_id and not reengaged_from_nurture and msg_type == "text":
        try:
            # GAP-2: Check for active qualification session before running not-ready
            # detection. If the bot is mid-session, skip graduation — the bot manages
            # the conversation. Fail-safe: treat as active session on any DB error.
            _has_active_session = False
            try:
                _sess = (
                    db.table("lead_qualification_sessions")
                    .select("id")
                    .eq("lead_id", lead_id)
                    .eq("ai_active", True)
                    .execute()
                )
                _has_active_session = bool(_sess.data)
            except Exception:
                _has_active_session = True  # fail-safe: skip detection if unsure

            if not _has_active_session:
                from app.services.nurture_service import is_not_ready_signal, graduate_lead_self_identified
                if content and is_not_ready_signal(content):
                    # Verify lead is not already on nurture track before graduating
                    lead_status = (
                        db.table("leads")
                        .select("nurture_track, stage")
                        .eq("id", lead_id)
                        .maybe_single()
                        .execute()
                    )
                    lead_status_data = lead_status.data or {}
                    if isinstance(lead_status_data, list):
                        lead_status_data = lead_status_data[0] if lead_status_data else {}
                    if not (lead_status_data or {}).get("nurture_track"):
                        graduate_lead_self_identified(
                            db=db,
                            org_id=org_id,
                            lead_id=lead_id,
                            assigned_to=assigned_to,
                            now_ts=now_ts,
                        )
                        logger.info(
                            "Lead %s self-identified as not ready — graduated to nurture",
                            lead_id,
                        )
        except Exception as exc:  # S14
            logger.warning(
                "Not-ready detection failed for lead %s — continuing: %s",
                lead_id, exc,
            )

    # M01-3: Check if this lead has an active qualification session.
    # If yes and ai_active=true, route to the AI qualification bot instead of
    # notifying the rep directly. S14 — all failures fall back to rep notification.
    if lead_id and not customer_id:
        try:
            _handle_structured_qualification_turn(
                db=db, org_id=org_id, lead_id=lead_id,
                assigned_to=assigned_to, content=content or f"[{msg_type}]",
                interactive_payload=interactive_payload,
                now_ts=now_ts,
            )
            return  # qualification handler manages its own notifications
        except Exception as exc:
            logger.warning(
                "Qualification turn failed for lead %s — falling back to rep notification: %s",
                lead_id, exc,
            )
            # Fall through to standard rep notification below

    # WH-1: Customer intent classifier — KB-first routing for known customers.
    # Returns True if fully handled (no rep notification needed).
    # Returns False for 'general' intent or non-text — rep notification fires below.
    # S14 — all failures swallowed inside handle_customer_inbound; returns False.
    if customer_id and not lead_id:
        # WH-2: Check for an active customer triage session first.
        # If one exists, route to the customer triage dispatcher instead of
        # the intent classifier.
        active_customer_session = triage_service.get_active_session(
            db, org_id, sender_phone
        )
        if active_customer_session:
            triage_service.handle_session_message(
                db=db,
                org_id=org_id,
                phone_number=sender_phone,
                session=active_customer_session,
                msg_type=msg_type,
                content=content,
                interactive_payload=interactive_payload,
                contact_name=contact_name,
                now_ts=now_ts,
                section="customer",
            )
            return

        # WH-2: No active session — check if org has a customer triage menu
        # configured. If yes, send the menu and create a session.
        # Falls through to handle_customer_inbound if not configured.
        try:
            org_triage_r = (
                db.table("organisations")
                .select("whatsapp_triage_config")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_triage_d = org_triage_r.data
            if isinstance(org_triage_d, list):
                org_triage_d = org_triage_d[0] if org_triage_d else None
            triage_cfg = (org_triage_d or {}).get("whatsapp_triage_config") or {}
            customer_menu = triage_cfg.get("customer") or {}
            if customer_menu.get("items"):
                from app.services import whatsapp_service as _wa_svc
                _wa_svc.send_triage_menu(
                    db=db, org_id=org_id,
                    phone_number=sender_phone, section="customer",
                )
                triage_service.create_customer_session(
                    db=db, org_id=org_id,
                    phone_number=sender_phone, customer_id=customer_id,
                )
                return
        except Exception as exc:
            logger.warning(
                "Customer triage menu check failed for %s — falling through to "
                "intent classifier: %s", sender_phone, exc
            )

        handled = customer_inbound_service.handle_customer_inbound(
            db=db,
            org_id=org_id,
            customer_id=customer_id,
            content=content,
            msg_type=msg_type,
            assigned_to=assigned_to,
            now_ts=now_ts,
        )
        if handled:
            return  # KB or context handler took care of it — skip rep notification

    # WH-1: Mid-pipeline lead stage signal detection (GAP-C7).
    # Only for leads in contacted | demo_done | proposal_sent stages.
    # S14 — all failures swallowed inside handle_lead_stage_signal.
    if lead_id and not customer_id and msg_type == "text" and content:
        try:
            stage_check = (
                db.table("leads")
                .select("stage")
                .eq("id", lead_id)
                .maybe_single()
                .execute()
            )
            stage_data = stage_check.data
            if isinstance(stage_data, list):
                stage_data = stage_data[0] if stage_data else None
            lead_stage = (stage_data or {}).get("stage", "")
            if lead_stage in ("contacted", "demo_done", "proposal_sent"):
                customer_inbound_service.handle_lead_stage_signal(
                    db=db,
                    org_id=org_id,
                    lead_id=lead_id,
                    stage=lead_stage,
                    content=content,
                    assigned_to=assigned_to,
                    now_ts=now_ts,
                )
        except Exception as exc:
            logger.warning(
                "Lead stage signal check failed for lead %s — continuing: %s",
                lead_id, exc,
            )

    # Standard rep notification (for customers, or leads without active sessions,
    # or when the qualification handler fails)
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
            pass

        is_new_lead = (lead_id is not None and customer_id is None)
        notif_title = (
            f"New lead via WhatsApp: {display_name}"
            if is_new_lead
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
    """
    WH-1b: Handle one turn of the structured WhatsApp qualification flow.
 
    Replaces the old AI-per-turn _handle_qualification_turn().
 
    Flow:
      1. Fetch active qualification session (ai_active=True). Raises if none.
      2. Fetch org qualification_flow. Raises if null.
      3. Read current_question_index. Get current question from flow["questions"].
      4. Record answer:
         - button_reply / list_reply: extract selected option id; resolve label.
         - free_text: content as-is.
         - Store as answers[question["answer_key"]] = answer_value.
      5. If map_to_lead_field is set: update leads table column with answer_value.
      6. Advance: next_index = current_question_index + 1.
      7. If more questions remain: send next question, update session index.
      8. If all questions answered:
         a. Generate Haiku summary.
         b. Send handoff_message to lead.
         c. Update session: ai_active=False, stage='handed_off', handoff_summary=summary.
         d. Notify rep with summary.
         e. Trigger lead scoring.
 
    S14: entire function wrapped in try/except — raises ValueError on unrecoverable
    error so caller (_handle_inbound_message) falls back to rep notification.
    """

 
    # 1 — Fetch active qualification session
    session_result = (
        db.table("lead_qualification_sessions")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("ai_active", True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    session_rows = session_result.data if isinstance(session_result.data, list) else []
    if not session_rows:
        raise ValueError(f"No active qualification session for lead {lead_id}")
 
    session = session_rows[0]
    session_id = session["id"]
 
    # 2 — Fetch org qualification_flow
    org_result = (
        db.table("organisations")
        .select("id, name, qualification_flow, whatsapp_phone_id")
        .eq("id", org_id)
        .maybe_single()
        .execute()
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
 
    # 3 — Read current question
    current_index = session.get("current_question_index") or 0
    if current_index >= len(questions):
        # Already completed — should not happen, but raise so caller falls back
        raise ValueError(
            f"qualification session {session_id} already past last question"
        )
 
    current_question = questions[current_index]
    answer_key = current_question.get("answer_key", f"q{current_index}")
    q_type = current_question.get("type", "free_text")
 
    # 4 — Record answer
    existing_answers = dict(session.get("answers") or {})
 
    if interactive_payload and q_type in ("multiple_choice", "yes_no", "list_select"):
        # Extract option id from interactive payload
        button_reply = interactive_payload.get("button_reply") or {}
        list_reply = interactive_payload.get("list_reply") or {}
        selected_id = button_reply.get("id") or list_reply.get("id") or content
 
        # Resolve human-readable label from flow config
        options = current_question.get("options") or []
        selected_label = selected_id  # fallback to id if label not found
        for opt in options:
            if opt.get("id") == selected_id:
                selected_label = opt.get("label", selected_id)
                break
        answer_value = selected_label
    else:
        # free_text or fallback
        answer_value = content
 
    existing_answers[answer_key] = answer_value
 
    # 5 — map_to_lead_field: write answer to leads table column
    map_to = current_question.get("map_to_lead_field")
    _VALID_LEAD_FIELDS = {
        "business_name", "business_type", "location", "problem_stated", "branches"
    }
    if map_to and map_to in _VALID_LEAD_FIELDS:
        try:
            db.table("leads").update(
                {map_to: answer_value}
            ).eq("id", lead_id).execute()
        except Exception as exc:
            logger.warning(
                "_handle_structured_qualification_turn: failed to map field %s "
                "for lead %s: %s", map_to, lead_id, exc
            )
 
    # 6 — Advance index
    next_index = current_index + 1
 
    # 7 — More questions remain
    if next_index < len(questions):
        # Update session: advance index + merge answers
        db.table("lead_qualification_sessions").update({
            "current_question_index": next_index,
            "answers": existing_answers,
            "last_message_at": now_ts,
        }).eq("id", session_id).execute()
 
        # Send next question (no opening_message after Q1)
        send_qualification_question(
            db=db,
            org_id=org_id,
            phone_number=_get_lead_phone(db, lead_id),
            question=questions[next_index],
            question_index=next_index,
            total=len(questions),
            opening_message=None,
        )
        return  # Caller returns True — rep notification suppressed
 
    # 8 — All questions answered — handoff
    org_name = (org_data or {}).get("name", "")
    handoff_message = qualification_flow.get(
        "handoff_message",
        "Thanks so much! A member of our team will reach out to you shortly. 🙏",
    )
 
    # 8a — Generate Haiku summary
    lead_data = _get_lead_basic(db, lead_id)
    summary = generate_qualification_summary(
        answers=existing_answers,
        lead=lead_data,
        org_name=org_name,
    )
 
    # 8b — Send handoff message to lead
    lead_phone = _get_lead_phone(db, lead_id)
    send_qualification_handoff_message(
        db=db,
        org_id=org_id,
        phone_number=lead_phone,
        handoff_message=handoff_message,
    )
 
    # 8c — Close session
    db.table("lead_qualification_sessions").update({
        "ai_active": False,
        "stage": "handed_off",
        "answers": existing_answers,
        "handed_off_at": now_ts,
        "handoff_summary": summary,
        "last_message_at": now_ts,
    }).eq("id", session_id).execute()
 
    # 8d — Notify rep with summary
    if assigned_to:
        try:
            db.table("notifications").insert({
                "org_id":        org_id,
                "user_id":       assigned_to,
                "title":         "Lead ready for follow-up 🎯",
                "body":          summary,
                "type":          "qualification_complete",
                "resource_type": "lead",
                "resource_id":   lead_id,
                "is_read":       False,
                "created_at":    now_ts,
            }).execute()
        except Exception as exc:
            logger.warning(
                "_handle_structured_qualification_turn: handoff notification "
                "failed for user %s: %s", assigned_to, exc
            )
 
    # 8e — Trigger lead scoring (S14 — never disrupts handoff flow)
    try:
        from app.services import lead_service
        lead_service.score_lead(
            db=db,
            org_id=org_id,
            lead_id=lead_id,
            user_id=assigned_to or org_id,
        )
        logger.info(
            "AI scoring triggered at structured qualification handoff for lead %s",
            lead_id,
        )
    except Exception as exc:
        logger.warning(
            "_handle_structured_qualification_turn: scoring failed for lead %s: %s",
            lead_id, exc,
        )

def _get_lead_phone(db, lead_id: str) -> str:
    """
    Helper: fetch whatsapp or phone from leads table for a given lead_id.
    Returns empty string on any failure (S14).
    """
    try:
        r = (
            db.table("leads")
            .select("phone, whatsapp")
            .eq("id", lead_id)
            .maybe_single()
            .execute()
        )
        d = r.data
        if isinstance(d, list):
            d = d[0] if d else None
        return (d or {}).get("whatsapp") or (d or {}).get("phone") or ""
    except Exception as exc:
        logger.warning("_get_lead_phone failed for lead %s: %s", lead_id, exc)
        return ""
 
 
def _get_lead_basic(db, lead_id: str) -> dict:
    """
    Helper: fetch full_name + phone from leads table.
    Returns empty dict on any failure (S14).
    """
    try:
        r = (
            db.table("leads")
            .select("full_name, phone, whatsapp")
            .eq("id", lead_id)
            .maybe_single()
            .execute()
        )
        d = r.data
        if isinstance(d, list):
            d = d[0] if d else None
        return d or {}
    except Exception as exc:
        logger.warning("_get_lead_basic failed for lead %s: %s", lead_id, exc)
        return {}

def _send_qualification_reply(
    db, org_id: str, lead_id: str, org_data: dict, reply: str, now_ts: str
) -> None:
    """
    Save the AI's reply to whatsapp_messages and send via Meta Cloud API.
    S14 — swallows failures silently.
    """
    from app.services.whatsapp_service import _call_meta_send, _now_iso
    from datetime import datetime, timezone, timedelta

    phone_id = (org_data.get("whatsapp_phone_id") or "").strip()

    # Save the outbound message to whatsapp_messages first
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()
    try:
        db.table("whatsapp_messages").insert({
            "org_id":          org_id,
            "lead_id":         lead_id,
            "direction":       "outbound",
            "message_type":    "text",
            "content":         reply,
            "status":          "sent",
            "window_open":     True,
            "window_expires_at": window_expires,
            "sent_by":         None,  # system / AI
            "created_at":      now_ts,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to save qualification reply to DB: %s", exc)

    # Send via Meta API if phone_id is configured
    if not phone_id:
        logger.warning("No whatsapp_phone_id configured for org %s — reply saved but not sent", org_id)
        return

    # We need the lead's phone number to send to
    try:
        lead_result = (
            db.table("leads")
            .select("phone, whatsapp")
            .eq("id", lead_id)
            .maybe_single()
            .execute()
        )
        lead_data = lead_result.data
        if isinstance(lead_data, list):
            lead_data = lead_data[0] if lead_data else None
        to_number = (lead_data or {}).get("whatsapp") or (lead_data or {}).get("phone")
        if not to_number:
            logger.warning("No phone/whatsapp on lead %s — cannot send reply", lead_id)
            return

        meta_payload = {
            "messaging_product": "whatsapp",
            "to":   to_number,
            "type": "text",
            "text": {"body": reply},
        }
        _call_meta_send(phone_id, meta_payload)
    except Exception as exc:
        logger.warning("Failed to send qualification reply via Meta API: %s", exc)


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
                    print(f"Processing inbound message from {message.get('from')}", flush=True)
                    _handle_inbound_message(db, message, contact_name, phone_number_id)
                    print("Inbound message processed successfully", flush=True)
                except Exception as exc:
                    print(f"Inbound message processing error: {exc}", flush=True)

            # Process delivery/read status updates
            for status_upd in value.get("statuses", []):
                try:
                    _handle_status_update(db, status_upd)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Status update processing error: %s", exc)

    return {"status": "ok"}

@router.get("/meta/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification challenge for WhatsApp endpoint."""
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        if hub_challenge and hub_challenge.isdigit():
            return int(hub_challenge)
        return hub_challenge
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook verification failed — token mismatch",
    )

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