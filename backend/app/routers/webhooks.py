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
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.config import settings
from app.database import get_supabase
from app.models.common import ErrorCode
from app.models.leads import LeadSource, LeadCreate
from app.services import lead_service

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
# POST /webhooks/meta/whatsapp — stub (Phase 3A)
# ---------------------------------------------------------------------------

@router.post("/meta/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_message(request: Request):
    """
    WhatsApp inbound message handler stub.
    Full implementation in Phase 3A — Module 02 WhatsApp Backend.
    Returns 200 so Meta does not retry.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_meta_signature(raw_body, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )
    logger.debug("WhatsApp webhook received — Phase 3A handler pending")
    return {"status": "received"}