"""
whatsapp_service.py — Module 02 business logic.

Covers:
  - Customer CRUD
  - WhatsApp message dispatch via Meta Cloud API
  - 24-hour conversation window enforcement
  - Template management
  - Broadcast lifecycle
  - Drip sequence configuration

Follows all CRITICAL PATTERNS from Build Status:
  - Pattern 1  : lazy get_supabase factory — never module-level singleton
  - Pattern 5  : write_audit_log always receives db explicitly
  - Pattern 9  : normalise list vs dict from every .maybe_single() result
  - Pattern 17 : phone normalisation via lead_service._normalise_phone
"""
from __future__ import annotations

import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import HTTPException

from app.config import settings
from app.models.common import ErrorCode
from app.models.customers import CustomerUpdate
from app.models.whatsapp import (
    BroadcastCreate,
    DripMessageConfig,
    SendMessageRequest,
    TEMPLATE_CATEGORIES,
    TemplateCreate,
    TemplateUpdate,
)
from app.services.lead_service import write_audit_log
import logging
logger = logging.getLogger(__name__)

class IntegrationError(Exception):
    """Raised when an org has no WhatsApp credentials configured in the DB.
    I0: replaces the silent env-var fallback that could send via the wrong org.
    """
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_name(full_name):
    """
    Return the first word of full_name, title-cased.
    Falls back to 'there' so messages read naturally as 'Hi there'.
    Examples:
      "Adebayo Okonkwo" -> "Adebayo"
      "adebayo"         -> "Adebayo"
      None / ""         -> "there"
    """
    if not full_name or not full_name.strip():
        return "there"
    return full_name.strip().split()[0].title()


def _personalise_greeting(raw_greeting: str, contact_name: Optional[str] = None) -> str:
    """
    Replace {{name}} placeholder with contact's first name if available.
    Strips {{name}} cleanly if no name is available.
    S14 — never raises.
    """
    try:
        if "{{name}}" not in raw_greeting:
            return raw_greeting
        first_name = (
            (contact_name or "").strip().split()[0].title()
            if contact_name and contact_name.strip()
            else None
        )
        if first_name:
            return raw_greeting.replace("{{name}}", first_name)
        # No name — strip the placeholder cleanly
        return (
            raw_greeting
            .replace("{{name}}! ", "")
            .replace("{{name}}, ", "")
            .replace("{{name}} ", "")
            .replace("{{name}}", "")
            .strip()
        )
    except Exception:
        return raw_greeting

def _get_last_inbound_msg_id(db, org_id: str, phone_number: str) -> Optional[str]:
    """
    Fetch the meta_message_id of the most recent inbound WhatsApp message
    from this phone number. Used to fire the typing indicator.
    S14 — returns None on any failure.
    """
    try:
        r = (
            db.table("whatsapp_messages")
            .select("meta_message_id")
            .eq("org_id", org_id)
            .eq("direction", "inbound")
            .eq("status", "delivered")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = r.data if isinstance(r.data, list) else []
        if rows:
            return rows[0].get("meta_message_id")
    except Exception as exc:
        logger.warning(
            "_get_last_inbound_msg_id failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )
    return None


def _fire_typing_indicator(phone_id: str, msg_id: str, token: str) -> None:
    """
    Show the WhatsApp typing indicator (wiggling dots) to the contact.
    Also marks the incoming message as read (blue double ticks).
    Dismissed automatically when next message is sent or after 25 seconds.
    S14 — never raises.
    """
    try:
        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": msg_id,
            "typing_indicator": {"type": "text"},
        }, token=token)
    except Exception as exc:
        logger.warning(
            "_fire_typing_indicator failed phone_id=%s: %s", phone_id, exc
        )

def _build_template_components(variables, recipient_name=None):
    """
    Build the Meta Cloud API components array for a template send.

    recipient_name is always prepended as {{1}} when provided, shifting any
    caller-supplied variables to {{2}}, {{3}}, etc.

    Returns a components list or None if there are no variables to inject.
    """
    params = []
    if recipient_name is not None:
        params.append({"type": "text", "text": _first_name(recipient_name)})
    for v in (variables or []):
        params.append({"type": "text", "text": str(v)})
    if not params:
        return None
    return [{"type": "body", "parameters": params}]


def _normalise_data(result_data):
    """
    Pattern 9 — normalise list vs dict from .maybe_single().
    Real Supabase returns a dict; test mocks may return a list.
    """
    data = result_data
    if isinstance(data, list):
        data = data[0] if data else None
    return data


def _customer_or_404(db, org_id: str, customer_id: str) -> dict:
    """Fetch a non-deleted customer scoped to the org, raise 404 if absent."""
    result = (
        db.table("customers")
        .select("*")
        .eq("id", customer_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    data = _normalise_data(result.data)
    if not data:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return data


def _broadcast_or_404(db, org_id: str, broadcast_id: str) -> dict:
    """Fetch a broadcast scoped to the org, raise 404 if absent."""
    result = (
        db.table("broadcasts")
        .select("*")
        .eq("id", broadcast_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    data = _normalise_data(result.data)
    if not data:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return data


# ---------------------------------------------------------------------------
# Meta Cloud API
# ---------------------------------------------------------------------------

def _get_org_wa_credentials(db, org_id: str) -> tuple:
    """
    MULTI-ORG-WA-1: Return (phone_id, access_token, waba_id) for the given org.

    Reads whatsapp_phone_id, whatsapp_access_token, and whatsapp_waba_id from
    the organisations table.  Falls back to settings values if DB columns are
    null — preserves backwards compatibility for any org not yet migrated via
    the admin UI.

    S14: never raises.  Returns (None, None, None) on any exception.
    """
    try:
        result = (
            db.table("organisations")
            .select(
                "whatsapp_phone_id, whatsapp_access_token, "
                "whatsapp_waba_id"
            )
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        row = data or {}
 
        # I0: Never fall back to the META_WHATSAPP_TOKEN env var.
        # Each org must have its own token in the DB.
        phone_id     = row.get("whatsapp_phone_id") or None
        access_token = row.get("whatsapp_access_token") or None
        waba_id      = row.get("whatsapp_waba_id") or None
 
        if not access_token:
            logger.warning(
                "_get_org_wa_credentials: org %s has no whatsapp_access_token — "
                "integration is broken. Admin must set the token in Admin → Integrations.",
                org_id,
            )
            return None, None, None
 
        return phone_id, access_token, waba_id
    except Exception as exc:
        logger.warning("_get_org_wa_credentials failed for org %s: %s", org_id, exc)
        return None, None, None
 


def _call_meta_send(phone_id: str, meta_payload: dict, token: str | None = None) -> dict:
    """
    Send a WhatsApp message via Meta Cloud API.
    Returns the Meta API response dict.
    Raises HTTPException(503) on network error or non-2xx response.
    This function is kept thin so it can be patched in tests.
    """
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    # I0: token must always come from _get_org_wa_credentials — never from env.
    if not token:
        logger.warning(
            "_call_meta_send: called with no token for phone_id=%s — refusing send",
            phone_id,
        )
        raise HTTPException(
            status_code=503,
            detail=f"{ErrorCode.INTEGRATION_ERROR} — no WhatsApp access token provided",
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=meta_payload, headers=headers)
        if response.status_code not in (200, 201):
            if response.status_code in (401, 403):
                logger.error(
                    "WHATSAPP TOKEN EXPIRED or INVALID — phone_id=%s HTTP %s. "
                    "Go to Meta Business Manager → System Users → regenerate token. "
                    "Then update organisations.whatsapp_access_token in the DB. "
                    "Body: %s",
                    phone_id, response.status_code, response.text,
                )
            else:
                logger.warning(
                    "_call_meta_send: Meta returned %s for phone_id=%s — body: %s",
                    response.status_code, phone_id, response.text,
                )
            raise HTTPException(
                status_code=503,
                detail=f"{ErrorCode.INTEGRATION_ERROR} — Meta {response.status_code}: {response.text}",
            )
        return response.json()
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        logger.warning("_call_meta_send: network error for phone_id=%s — %s", phone_id, exc)
        raise HTTPException(
            status_code=503,
            detail=ErrorCode.INTEGRATION_ERROR,
        )

# ---------------------------------------------------------------------------
# 9E-A: Meta token validity check
# Callable from meta_token_worker and testable in isolation.
# ---------------------------------------------------------------------------
 
def check_meta_token_validity(db, org_id: str) -> bool:
    """
    Validate the org's WhatsApp access token against the Meta Graph API.
 
    Calls GET https://graph.facebook.com/v17.0/me?access_token={token}
 
    Returns:
        True  — token is valid (HTTP 200) or no token configured (N/A)
        False — token invalid (HTTP 401/403) or any network/exception
 
    S14: never raises.
    PII: only the last 4 chars of the token are logged — never the full value.
    """
    try:
        _, access_token, _ = _get_org_wa_credentials(db, org_id)
        if not access_token:
            # No token configured — not applicable, not invalid.
            return True
 
        url = f"https://graph.facebook.com/v17.0/me?access_token={access_token}"
 
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
 
        if response.status_code == 200:
            return True
 
        # 401 / 403 → token revoked or expired
        logger.warning(
            "check_meta_token_validity: invalid token for org=%s — HTTP %s (token ...%s)",
            org_id,
            response.status_code,
            access_token[-4:],
        )
        return False
 
    except Exception as exc:
        logger.warning(
            "check_meta_token_validity: exception for org=%s — %s", org_id, exc
        )
        return False
 


def send_triage_menu(
    db,
    org_id: str,
    phone_number: str,
    section: str = "unknown",
    contact_name: Optional[str] = None,
) -> None:
    """
    WH-0: Send an Interactive List Message to an unknown contact.
    Fetches the org's triage config and builds the WhatsApp interactive payload.

    Guards:
      - No whatsapp_phone_id → log warning, return (cannot send).
      - No triage_config or section key absent → log warning, return.
        Caller is responsible for fallback — we do NOT fall back to qualification.
      - WhatsApp API hard limits enforced: label[:24], description[:72], items[:10].

    S14: entire function body wrapped in try/except — never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        if not phone_id:
            logger.warning(
                "send_triage_menu: no whatsapp_phone_id for org %s — skipping", org_id
            )
            return

        # Fetch triage config separately (not in _get_org_wa_credentials to keep it lean)
        triage_result = (
            db.table("organisations")
            .select("whatsapp_triage_config")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        triage_data = triage_result.data
        if isinstance(triage_data, list):
            triage_data = triage_data[0] if triage_data else None
        triage_config = (triage_data or {}).get("whatsapp_triage_config")
        if not triage_config or section not in triage_config:
            logger.warning(
                "send_triage_menu: no triage_config[%s] for org %s — skipping",
                section, org_id,
            )
            return

        config = triage_config[section]

        rows = [
            {
                "id":          item["id"],
                "title":       item["label"][:24],
                "description": item.get("description", "")[:72],
            }
            for item in (config.get("items") or [])[:10]
        ]

        meta_payload = {
            "messaging_product": "whatsapp",
            "to":   phone_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": _personalise_greeting(
                    config.get("greeting", "How can we help you today?"),
                    contact_name,
                )},
                "action": {
                    "button": "See options",
                    "sections": [{
                        "title": config.get("section_title", "Choose an option"),
                        "rows":  rows,
                    }],
                },
            },
        }

        _call_meta_send(phone_id, meta_payload, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_triage_menu failed org=%s phone=%s: %s", org_id, phone_number, exc
        )


# ---------------------------------------------------------------------------
# Conversation window
# ---------------------------------------------------------------------------

def _is_window_open(db, org_id: str, customer_id: str) -> bool:
    """
    Return True if the 24-hour Meta conversation window is currently open
    for this customer.  The window is tracked via the most recent message row's
    window_open / window_expires_at fields.
    """
    result = (
        db.table("whatsapp_messages")
        .select("window_open, window_expires_at")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    data = result.data
    rows = data if isinstance(data, list) else ([data] if data else [])
    if not rows:
        return False   # No prior messages → window closed

    msg = rows[0]
    if not msg.get("window_open"):
        return False

    expires_raw = msg.get("window_expires_at")
    if not expires_raw:
        return False

    try:
        if isinstance(expires_raw, str):
            expires_dt = datetime.fromisoformat(
                expires_raw.replace("Z", "+00:00")
            )
        else:
            expires_dt = expires_raw
        return expires_dt > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False

def _is_lead_window_open(db, org_id: str, lead_id: str) -> bool:
    """
    Return True if the 24-hour Meta conversation window is currently open
    for this lead. Mirror of _is_window_open but queries by lead_id.
    S14 — returns False on any failure.
    """
    try:
        result = (
            db.table("whatsapp_messages")
            .select("window_open, window_expires_at")
            .eq("org_id", org_id)
            .eq("lead_id", lead_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = result.data
        rows = data if isinstance(data, list) else ([data] if data else [])
        if not rows:
            return False

        msg = rows[0]
        if not msg.get("window_open"):
            return False

        expires_raw = msg.get("window_expires_at")
        if not expires_raw:
            return False

        if isinstance(expires_raw, str):
            expires_dt = datetime.fromisoformat(
                expires_raw.replace("Z", "+00:00")
            )
        else:
            expires_dt = expires_raw
        return expires_dt > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Message dispatch
# ---------------------------------------------------------------------------

def send_whatsapp_message(
    db,
    org_id: str,
    user_id: str,
    payload: SendMessageRequest,
) -> dict:
    """
    Send a WhatsApp message to a customer or lead.

    Business rules:
      - Exactly one of customer_id / lead_id must be supplied
      - Exactly one of content / template_name must be supplied
      - When the 24-hour conversation window is closed, template_name is
        required (Meta will reject a free-form message outside the window)
      - The org's whatsapp_phone_id is fetched from the organisations table
    """
    if not payload.customer_id and not payload.lead_id:
        raise HTTPException(
            status_code=422,
            detail="customer_id or lead_id is required",
        )
    if not payload.content and not payload.template_name:
        raise HTTPException(
            status_code=422,
            detail="content or template_name is required",
        )

    # ── Resolve phone_id and token from org ───────────────────────────────
    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
    phone_id = phone_id or ""

    # ── Resolve recipient WhatsApp number and name ───────────────────────
    to_number: Optional[str] = None
    recipient_full_name: Optional[str] = None
    customer_id_str: Optional[str] = None
    lead_id_str: Optional[str] = None

    if payload.customer_id:
        customer = _customer_or_404(db, org_id, str(payload.customer_id))
        # I1: Opt-out guard — never send to a contact who has unsubscribed.
        if customer.get("whatsapp_opted_out"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This contact has opted out of WhatsApp messages. "
                    "They can opt back in by sending START to your WhatsApp number."
                ),
            )
        to_number = customer.get("whatsapp") or customer.get("phone")
        recipient_full_name = customer.get("full_name")
        customer_id_str = str(payload.customer_id)
    else:
        lead_result = (
            db.table("leads")
            .select("whatsapp, phone, full_name, whatsapp_opted_out")
            .eq("id", str(payload.lead_id))
            .eq("org_id", org_id)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        lead_data = _normalise_data(lead_result.data)
        if not lead_data:
            raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
        # I1: Opt-out guard for leads.
        if lead_data.get("whatsapp_opted_out"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "This lead has opted out of WhatsApp messages. "
                    "They can opt back in by sending START to your WhatsApp number."
                ),
            )
        to_number = lead_data.get("whatsapp") or lead_data.get("phone")
        recipient_full_name = lead_data.get("full_name")
        lead_id_str = str(payload.lead_id)

    if not to_number:
        raise HTTPException(
            status_code=422,
            detail="Recipient has no WhatsApp number on record",
        )

    # ── 24-hour window enforcement ─────────────────────────────────────────
    window_open = False
    if customer_id_str:
        window_open = _is_window_open(db, org_id, customer_id_str)
    elif lead_id_str:
        window_open = _is_lead_window_open(db, org_id, lead_id_str)

    if not window_open and not payload.template_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Conversation window is closed — "
                "provide template_name to send a template message"
            ),
        )

    # ── Build Meta API payload ─────────────────────────────────────────────
    if payload.template_name:
        template_dict: dict = {
            "name": payload.template_name,
            "language": {"code": "en"},
        }
        components = _build_template_components(
            payload.template_variables,
            recipient_name=recipient_full_name,
        )
        if components:
            template_dict["components"] = components
        meta_payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": template_dict,
        }
        content_db = None
        template_name_db = payload.template_name
    else:
        meta_payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": payload.content},
        }
        content_db = payload.content
        template_name_db = None

    # ── Call Meta Cloud API ────────────────────────────────────────────────
    meta_response = _call_meta_send(phone_id, meta_payload, token=access_token)
    meta_messages = meta_response.get("messages")
    meta_message_id: Optional[str] = None
    if isinstance(meta_messages, list) and meta_messages:
        meta_message_id = meta_messages[0].get("id")

    # ── Persist to whatsapp_messages ───────────────────────────────────────
    now_ts = _now_iso()
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()

    row: dict = {
        "org_id": org_id,
        "direction": "outbound",
        "message_type": "text",
        "content": content_db,
        "template_name": template_name_db,
        "status": "sent",
        "meta_message_id": meta_message_id,
        "window_open": True,
        "window_expires_at": window_expires,
        "sent_by": user_id,
        "created_at": now_ts,
    }
    if customer_id_str:
        row["customer_id"] = customer_id_str
    if lead_id_str:
        row["lead_id"] = lead_id_str

    insert_chain = db.table("whatsapp_messages").insert(row)
    insert_result = insert_chain.execute()
    msg_data = insert_result.data
    if isinstance(msg_data, list):
        msg_data = msg_data[0] if msg_data else row

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="whatsapp.message_sent",
        resource_type="whatsapp_message",
        resource_id=msg_data.get("id"),
        old_value=None,
        new_value={"to": to_number, "template": template_name_db},
    )
    return msg_data


# ---------------------------------------------------------------------------
# Customer CRUD
# ---------------------------------------------------------------------------

def list_customers(
    db,
    org_id: str,
    churn_risk: Optional[str] = None,
    assigned_to: Optional[str] = None,
    onboarding_complete: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return a paginated list of non-deleted customers for the org.
    Joins the assigned user for display (same pattern as get_lead — Pattern 16).
    """
    query = (
        db.table("customers")
        .select(
            "*, assigned_user:users!assigned_to(id, full_name)",
            count="exact",
        )
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
    )
    if churn_risk:
        query = query.eq("churn_risk", churn_risk)
    if assigned_to:
        query = query.eq("assigned_to", assigned_to)
    if onboarding_complete is not None:
        query = query.eq("onboarding_complete", onboarding_complete)

    result = (
        query
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    items = result.data if isinstance(result.data, list) else []
    total = result.count if result.count is not None else len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_customer(db, org_id: str, customer_id: str) -> dict:
    """
    Fetch a single customer with assigned-user join.
    Raises 404 if not found or soft-deleted.
    """
    result = (
        db.table("customers")
        .select("*, assigned_user:users!assigned_to(id, full_name)")
        .eq("id", customer_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    data = _normalise_data(result.data)
    if not data:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
    return data


def update_customer(
    db,
    org_id: str,
    customer_id: str,
    user_id: str,
    payload: CustomerUpdate,
) -> dict:
    """Partial update of a customer record. Writes an audit log entry."""
    old = _customer_or_404(db, org_id, customer_id)

    updates = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
    }
    # Convert UUID fields to str for Supabase
    if updates.get("assigned_to") is not None:
        updates["assigned_to"] = str(updates["assigned_to"])
    updates["updated_at"] = _now_iso()

    result = (
        db.table("customers")
        .update(updates)
        .eq("id", customer_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = _normalise_data(result.data)
    if not updated:
        updated = {**old, **updates}

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.updated",
        resource_type="customer",
        resource_id=customer_id,
        old_value=old,
        new_value=updates,
    )
    return updated


def get_customer_messages(
    db,
    org_id: str,
    customer_id: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Return paginated WhatsApp message history for a customer."""
    _customer_or_404(db, org_id, customer_id)
    result = (
        db.table("whatsapp_messages")
        .select("*", count="exact")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    items = result.data if isinstance(result.data, list) else []
    total = result.count if result.count is not None else len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_lead_messages(
    db,
    org_id: str,
    lead_id: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return paginated WhatsApp message history for a lead.
    Mirrors get_customer_messages — filters by lead_id instead of customer_id.
    Raises 404 if lead does not exist in this org.
    Also marks all unread inbound messages as read (S14 — failure swallowed).
    """
    # Verify lead exists and belongs to org
    lead_check = (
        db.table("leads")
        .select("id")
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    lead_data = _normalise_data(lead_check.data)
    if not lead_data:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    result = (
        db.table("whatsapp_messages")
        .select("*", count="exact")
        .eq("org_id", org_id)
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    items = result.data if isinstance(result.data, list) else []
    total = result.count if result.count is not None else len(items)

    # Mark all unread inbound messages as read — S14: failure never blocks fetch
    try:
        db.table("whatsapp_messages")             .update({"read_at": _now_iso()})             .eq("org_id", org_id)             .eq("lead_id", lead_id)             .eq("direction", "inbound")             .is_("read_at", "null")             .execute()
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Failed to mark lead messages as read for %s: %s", lead_id, exc
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_customer_tasks(db, org_id: str, customer_id: str) -> list:
    """Return all tasks linked to this customer (source_module = whatsapp)."""
    _customer_or_404(db, org_id, customer_id)
    result = (
        db.table("tasks")
        .select("*")
        .eq("org_id", org_id)
        .eq("source_record_id", customer_id)
        .eq("source_module", "whatsapp")
        .order("due_at", desc=False)
        .execute()
    )
    return result.data if isinstance(result.data, list) else []


def get_customer_nps(db, org_id: str, customer_id: str) -> list:
    """Return NPS response history for a customer, newest first."""
    _customer_or_404(db, org_id, customer_id)
    result = (
        db.table("nps_responses")
        .select("*")
        .eq("org_id", org_id)
        .eq("customer_id", customer_id)
        .order("responded_at", desc=True)
        .execute()
    )
    return result.data if isinstance(result.data, list) else []


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------

#: Allowed source states for the approve action
BROADCAST_APPROVE_FROM: frozenset[str] = frozenset({"draft"})
#: Allowed source states for the cancel action
BROADCAST_CANCEL_FROM: frozenset[str] = frozenset({"draft", "scheduled"})


def list_broadcasts(
    db,
    org_id: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    result = (
        db.table("broadcasts")
        .select("*", count="exact")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    items = result.data if isinstance(result.data, list) else []
    total = result.count if result.count is not None else len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_broadcast(
    db,
    org_id: str,
    user_id: str,
    payload: BroadcastCreate,
) -> dict:
    row: dict = {
        "org_id": org_id,
        "name": payload.name,
        "template_id": str(payload.template_id),
        "segment_filter": payload.segment_filter,
        "recipient_count": 0,
        "status": "draft",
        "created_by": user_id,
        "created_at": _now_iso(),
    }
    if payload.scheduled_at:
        row["scheduled_at"] = payload.scheduled_at.isoformat()

    insert_result = db.table("broadcasts").insert(row).execute()
    data = insert_result.data
    if isinstance(data, list):
        data = data[0] if data else row

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="broadcast.created",
        resource_type="broadcast",
        resource_id=data.get("id"),
        old_value=None,
        new_value={"name": payload.name, "template_id": str(payload.template_id)},
    )
    return data


def get_broadcast(db, org_id: str, broadcast_id: str) -> dict:
    return _broadcast_or_404(db, org_id, broadcast_id)


def approve_broadcast(
    db,
    org_id: str,
    broadcast_id: str,
    user_id: str,
) -> dict:
    """
    Approve a broadcast:
      draft → scheduled  (if scheduled_at is in the future)
      draft → sending    (if scheduled_at is None or in the past)
    """
    broadcast = _broadcast_or_404(db, org_id, broadcast_id)

    if broadcast["status"] not in BROADCAST_APPROVE_FROM:
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.INVALID_TRANSITION,
        )

    now_dt = datetime.now(timezone.utc)
    scheduled_raw = broadcast.get("scheduled_at")
    if scheduled_raw:
        if isinstance(scheduled_raw, str):
            scheduled_dt = datetime.fromisoformat(
                scheduled_raw.replace("Z", "+00:00")
            )
        else:
            scheduled_dt = scheduled_raw
        new_status = "scheduled" if scheduled_dt > now_dt else "sending"
    else:
        new_status = "sending"

    updates: dict = {
        "status": new_status,
        "approved_by": user_id,
        "updated_at": now_dt.isoformat(),
    }
    if new_status == "sending":
        updates["sent_at"] = now_dt.isoformat()

    result = (
        db.table("broadcasts")
        .update(updates)
        .eq("id", broadcast_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = _normalise_data(result.data)
    if not updated:
        updated = {**broadcast, **updates}

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="broadcast.approved",
        resource_type="broadcast",
        resource_id=broadcast_id,
        old_value={"status": broadcast["status"]},
        new_value={"status": new_status},
    )
    return updated


def cancel_broadcast(
    db,
    org_id: str,
    broadcast_id: str,
    user_id: str,
) -> dict:
    """Cancel a draft or scheduled broadcast."""
    broadcast = _broadcast_or_404(db, org_id, broadcast_id)

    if broadcast["status"] not in BROADCAST_CANCEL_FROM:
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.INVALID_TRANSITION,
        )

    updates: dict = {
        "status": "cancelled",
        "updated_at": _now_iso(),
    }
    result = (
        db.table("broadcasts")
        .update(updates)
        .eq("id", broadcast_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = _normalise_data(result.data)
    if not updated:
        updated = {**broadcast, **updates}

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="broadcast.cancelled",
        resource_type="broadcast",
        resource_id=broadcast_id,
        old_value={"status": broadcast["status"]},
        new_value={"status": "cancelled"},
    )
    return updated


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def list_templates(db, org_id: str) -> list:
    """Return all WhatsApp templates for the org, newest first."""
    result = (
        db.table("whatsapp_templates")
        .select("*")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data if isinstance(result.data, list) else []


def _submit_template_to_meta(
    db,
    org_id: str,
    template_id: str,
    template_name: str,
    category: str,
    body: str,
    variables: list,
) -> Optional[str]:
    """
    Submit a template to Meta Cloud API for approval.
    Returns the Meta template ID string on success, None on failure.
    S14 — never raises; logs warning on any failure.

    Meta endpoint: POST /v17.0/{WABA_ID}/message_templates
    Category mapping: Opsra uses lowercase; Meta requires UPPERCASE.
    Variables in body use {{1}}, {{2}} syntax — passed as-is.
    """
    try:
        _, access_token, waba_id = _get_org_wa_credentials(db, org_id)
        if not access_token or not waba_id:
            logger.warning(
                "_submit_template_to_meta: missing access_token or waba_id "
                "for org %s — template %s not submitted to Meta",
                org_id, template_name,
            )
            return None

        # Build components — body text with example values if variables present
        body_component: dict = {"type": "BODY", "text": body}
        if variables:
            body_component["example"] = {
                "body_text": [[f"example_{v}" for v in variables]]
            }

        meta_payload = {
            "name": template_name,
            "language": "en",
            "category": category.upper(),
            "components": [body_component],
        }

        url = f"https://graph.facebook.com/v17.0/{waba_id}/message_templates"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=meta_payload, headers=headers)

        resp_data = resp.json()
        if resp.status_code not in (200, 201):
            logger.warning(
                "_submit_template_to_meta: Meta rejected template '%s' "
                "for org %s — status %s body %s",
                template_name, org_id, resp.status_code, resp_data,
            )
            return None

        meta_template_id = resp_data.get("id")
        logger.info(
            "_submit_template_to_meta: template '%s' submitted successfully "
            "for org %s — meta_id=%s",
            template_name, org_id, meta_template_id,
        )
        return str(meta_template_id) if meta_template_id else None

    except Exception as exc:
        logger.warning(
            "_submit_template_to_meta: unexpected error for template '%s' "
            "org %s: %s",
            template_name, org_id, exc,
        )
        return None


def create_template(
    db,
    org_id: str,
    user_id: str,
    payload: TemplateCreate,
) -> dict:
    """
    Create a template locally and submit it to Meta for approval.
    meta_status starts as 'pending'.
    Raises 422 if category is invalid.
    """
    if payload.category not in TEMPLATE_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"category must be one of {sorted(TEMPLATE_CATEGORIES)}",
        )
    row: dict = {
        "org_id": org_id,
        "name": payload.name,
        "category": payload.category,
        "body": payload.body,
        "variables": payload.variables,
        "meta_status": "pending",
        "created_by": user_id,
        "created_at": _now_iso(),
    }
    insert_result = db.table("whatsapp_templates").insert(row).execute()
    data = insert_result.data
    if isinstance(data, list):
        data = data[0] if data else row

    # ── Submit to Meta for approval ────────────────────────────────────────
    meta_template_id = _submit_template_to_meta(
        db=db,
        org_id=org_id,
        template_id=data.get("id"),
        template_name=payload.name,
        category=payload.category,
        body=payload.body,
        variables=payload.variables or [],
    )
    if meta_template_id:
        db.table("whatsapp_templates").update(
            {"meta_template_id": meta_template_id}
        ).eq("id", data["id"]).execute()
        data["meta_template_id"] = meta_template_id

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="template.created",
        resource_type="whatsapp_template",
        resource_id=data.get("id"),
        old_value=None,
        new_value={"name": payload.name, "category": payload.category},
    )
    return data


def update_template(
    db,
    org_id: str,
    template_id: str,
    user_id: str,
    payload: TemplateUpdate,
) -> dict:
    """
    Edit a rejected template and resubmit to Meta.
    Only templates with meta_status = 'rejected' can be edited.
    After update: meta_status → 'pending', rejection_reason cleared.
    """
    result = (
        db.table("whatsapp_templates")
        .select("*")
        .eq("id", template_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    tmpl = _normalise_data(result.data)
    if not tmpl:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    if tmpl.get("meta_status") != "rejected":
        raise HTTPException(
            status_code=400,
            detail="Only templates with meta_status='rejected' can be edited",
        )

    updates = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    updates["meta_status"] = "pending"
    updates["rejection_reason"] = None

    update_result = (
        db.table("whatsapp_templates")
        .update(updates)
        .eq("id", template_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = _normalise_data(update_result.data)
    if not updated:
        updated = {**tmpl, **updates}

    # ── Resubmit to Meta ──────────────────────────────────────────────────
    final = updated or {**tmpl, **updates}
    meta_template_id = _submit_template_to_meta(
        db=db,
        org_id=org_id,
        template_id=template_id,
        template_name=final.get("name", tmpl.get("name", "")),
        category=final.get("category", tmpl.get("category", "")),
        body=final.get("body", tmpl.get("body", "")),
        variables=final.get("variables") or tmpl.get("variables") or [],
    )
    if meta_template_id:
        db.table("whatsapp_templates").update(
            {"meta_template_id": meta_template_id}
        ).eq("id", template_id).execute()
        final["meta_template_id"] = meta_template_id

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="template.resubmitted",
        resource_type="whatsapp_template",
        resource_id=template_id,
        old_value={"meta_status": "rejected"},
        new_value={"meta_status": "pending"},
    )
    return final


# ---------------------------------------------------------------------------
# Drip sequences
# ---------------------------------------------------------------------------

def get_drip_sequence(db, org_id: str) -> list:
    """
    Return the active drip sequence for the org, ordered by sequence_order.
    Joins the template for display.
    """
    result = (
        db.table("drip_messages")
        .select("*, template:whatsapp_templates(id, name, meta_status)")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .order("sequence_order", desc=False)
        .execute()
    )
    return result.data if isinstance(result.data, list) else []


def update_drip_sequence(
    db,
    org_id: str,
    user_id: str,
    messages: List[DripMessageConfig],
) -> list:
    """
    Replace the active drip sequence for the org.

    Strategy:
      1. Set is_active=False on ALL existing active drip_messages for this org.
         This preserves FK references from drip_sends (history is not lost).
      2. Insert the new set of drip_messages as the active configuration.
    Admin only — enforced in the router.
    """
    # Deactivate all current active messages
    db.table("drip_messages").update({"is_active": False}).eq(
        "org_id", org_id
    ).execute()

    if not messages:
        write_audit_log(
            db=db,
            org_id=org_id,
            user_id=user_id,
            action="drip_sequence.updated",
            resource_type="drip_message",
            resource_id=None,
            old_value=None,
            new_value={"message_count": 0},
        )
        return []

    now_ts = _now_iso()
    rows = [
        {
            "org_id": org_id,
            "name": msg.name,
            "template_id": str(msg.template_id),
            "delay_days": msg.delay_days,
            "business_types": msg.business_types,
            "sequence_order": msg.sequence_order,
            "is_active": msg.is_active,
            "created_at": now_ts,
        }
        for msg in messages
    ]

    insert_result = db.table("drip_messages").insert(rows).execute()
    inserted = insert_result.data if isinstance(insert_result.data, list) else []

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="drip_sequence.updated",
        resource_type="drip_message",
        resource_id=None,
        old_value=None,
        new_value={"message_count": len(inserted)},
    )
    return inserted

# ---------------------------------------------------------------------------
# Unread message counts
# ---------------------------------------------------------------------------

def get_unread_counts(db, org_id: str) -> dict:
    """
    Return unread inbound message counts for all leads and customers in the org.
    An inbound message is "unread" when read_at IS NULL.

    Returns:
        {
            "leads":     {"lead_id_1": 2, ...},
            "customers": {"customer_id_1": 3, ...},
        }

    S14: on any DB failure returns empty dicts — never blocks list views.
    """
    leads_counts:     dict = {}
    customers_counts: dict = {}

    try:
        result = (
            db.table("whatsapp_messages")
            .select("lead_id, customer_id")
            .eq("org_id", org_id)
            .eq("direction", "inbound")
            .is_("read_at", "null")
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
        for row in rows:
            if row.get("lead_id"):
                lid = row["lead_id"]
                leads_counts[lid] = leads_counts.get(lid, 0) + 1
            elif row.get("customer_id"):
                cid = row["customer_id"]
                customers_counts[cid] = customers_counts.get(cid, 0) + 1
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("get_unread_counts failed: %s", exc)

    return {"leads": leads_counts, "customers": customers_counts}

"""

New functions:
  - queue_outbox_message()      — respects org sending mode; auto-sends or parks in outbox
  - list_outbox()               — paginated outbox listing for the approval UI
  - approve_outbox_message()    — rep approves a pending/scheduled message → sends it
  - cancel_outbox_message()     — rep cancels a pending/scheduled message
  - _dispatch_outbox_row()      — internal: calls Meta API + writes whatsapp_messages row

These functions are called by:
  - webhooks.py _send_qualification_reply() (replace direct Meta call with queue_outbox_message)
  - qualification_worker.py (review window auto-sender reads scheduled rows)
  - whatsapp.py router (new outbox routes)
"""


# ---------------------------------------------------------------------------
# Outbox — internal dispatch helper
# ---------------------------------------------------------------------------

def _dispatch_outbox_row(
    db,
    org_id: str,
    outbox_row: dict,
    actioned_by: Optional[str],
) -> dict:
    """
    Send a queued outbox message via Meta Cloud API, write to whatsapp_messages,
    and mark the outbox row as sent.

    S14: on Meta API failure, marks outbox row as failed — never raises to caller.
    Returns the updated outbox row.
    """
    import logging as _log
    logger = _log.getLogger(__name__)

    
    outbox_id = outbox_row["id"]
    lead_id_str    = outbox_row.get("lead_id")
    customer_id_str = outbox_row.get("customer_id")
    content        = outbox_row.get("content")
    template_name  = outbox_row.get("template_name")
    now_ts         = _now_iso()

    # ── Resolve phone_id and token ────────────────────────────────────────
    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
    phone_id = phone_id or ""

    # ── Resolve recipient number ──────────────────────────────────────────
    to_number: Optional[str] = None
    if lead_id_str:
        try:
            lr = (
                db.table("leads")
                .select("whatsapp, phone")
                .eq("id", lead_id_str)
                .eq("org_id", org_id)
                .maybe_single()
                .execute()
            )
            ld = _normalise_data(lr.data)
            to_number = (ld or {}).get("whatsapp") or (ld or {}).get("phone")
        except Exception:
            pass
    elif customer_id_str:
        try:
            cr = (
                db.table("customers")
                .select("whatsapp, phone")
                .eq("id", customer_id_str)
                .eq("org_id", org_id)
                .maybe_single()
                .execute()
            )
            cd = _normalise_data(cr.data)
            to_number = (cd or {}).get("whatsapp") or (cd or {}).get("phone")
        except Exception:
            pass

    if not to_number or not phone_id:
        logger.warning(
            "_dispatch_outbox_row: missing phone_id or to_number for outbox %s", outbox_id
        )
        db.table("whatsapp_outbox").update(
            {"status": "failed", "updated_at": now_ts}
        ).eq("id", outbox_id).execute()
        return {**outbox_row, "status": "failed"}

    # ── Build Meta payload ────────────────────────────────────────────────
    if template_name:
        meta_payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {"name": template_name, "language": {"code": "en"}},
        }
    else:
        meta_payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": content},
        }

    # ── Call Meta API ─────────────────────────────────────────────────────
    meta_message_id: Optional[str] = None
    try:
        meta_resp = _call_meta_send(phone_id, meta_payload, token=access_token)
        msgs = meta_resp.get("messages")
        if isinstance(msgs, list) and msgs:
            meta_message_id = msgs[0].get("id")
    except Exception as exc:
        logger.warning("_dispatch_outbox_row: Meta API failed for outbox %s: %s", outbox_id, exc)
        db.table("whatsapp_outbox").update(
            {"status": "failed", "updated_at": now_ts}
        ).eq("id", outbox_id).execute()
        return {**outbox_row, "status": "failed"}

    # ── Write to whatsapp_messages ────────────────────────────────────────
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()
    msg_row: dict = {
        "org_id": org_id,
        "direction": "outbound",
        "message_type": "text",
        "content": content,
        "template_name": template_name,
        "status": "sent",
        "meta_message_id": meta_message_id,
        "window_open": True,
        "window_expires_at": window_expires,
        "sent_by": actioned_by,
        "created_at": now_ts,
    }
    if lead_id_str:
        msg_row["lead_id"] = lead_id_str
    if customer_id_str:
        msg_row["customer_id"] = customer_id_str

    try:
        db.table("whatsapp_messages").insert(msg_row).execute()
    except Exception as exc:
        logger.warning(
            "_dispatch_outbox_row: failed to write whatsapp_messages for outbox %s: %s",
            outbox_id, exc,
        )

    # ── Mark outbox row sent ──────────────────────────────────────────────
    updates: dict = {
        "status": "sent",
        "meta_message_id": meta_message_id,
        "actioned_by": actioned_by,
        "actioned_at": now_ts,
        "updated_at": now_ts,
    }
    upd_result = (
        db.table("whatsapp_outbox")
        .update(updates)
        .eq("id", outbox_id)
        .execute()
    )
    updated = _normalise_data(upd_result.data)
    return updated if updated else {**outbox_row, **updates}


# ---------------------------------------------------------------------------
# Outbox — queue (M01-4 core)
# ---------------------------------------------------------------------------

VALID_SENDING_MODES = frozenset({"full_approval", "review_window", "auto_send"})


def queue_outbox_message(
    db,
    org_id: str,
    lead_id: Optional[str],
    customer_id: Optional[str],
    content: Optional[str],
    template_name: Optional[str],
    source_type: str,
    queued_by: Optional[str] = None,
) -> dict:
    """
    Queue an AI-drafted message into whatsapp_outbox, respecting the org's
    qualification_sending_mode:

      full_approval  → status=pending   (rep must manually approve)
      review_window  → status=scheduled, send_after=now+review_window_minutes
                       (Celery worker auto-sends unless rep cancels first)
      auto_send      → immediately dispatched via _dispatch_outbox_row()

    Returns the outbox row (with status reflecting the mode applied).
    """
    # ── Fetch org sending mode config ─────────────────────────────────────
    try:
        org_res = (
            db.table("organisations")
            .select("qualification_sending_mode, review_window_minutes")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_cfg = _normalise_data(org_res.data) or {}
    except Exception:
        org_cfg = {}

    mode = org_cfg.get("qualification_sending_mode") or "full_approval"
    if mode not in VALID_SENDING_MODES:
        mode = "full_approval"
    window_minutes: int = int(org_cfg.get("review_window_minutes") or 5)

    now_ts = _now_iso()
    now_dt = datetime.now(timezone.utc)

    # ── Build base row ────────────────────────────────────────────────────
    row: dict = {
        "org_id": org_id,
        "content": content,
        "template_name": template_name,
        "source_type": source_type,
        "queued_by": queued_by,
        "created_at": now_ts,
        "updated_at": now_ts,
    }
    if lead_id:
        row["lead_id"] = lead_id
    if customer_id:
        row["customer_id"] = customer_id

    if mode == "auto_send":
        # Insert as pending first, then immediately dispatch
        row["status"] = "pending"
        insert_res = db.table("whatsapp_outbox").insert(row).execute()
        inserted = _normalise_data(insert_res.data)
        if not inserted:
            inserted = row
        return _dispatch_outbox_row(db, org_id, inserted, actioned_by=queued_by)

    elif mode == "review_window":
        send_after = (now_dt + timedelta(minutes=window_minutes)).isoformat()
        row["status"] = "scheduled"
        row["send_after"] = send_after
        insert_res = db.table("whatsapp_outbox").insert(row).execute()
        inserted = _normalise_data(insert_res.data)
        return inserted if inserted else row

    else:  # full_approval
        row["status"] = "pending"
        insert_res = db.table("whatsapp_outbox").insert(row).execute()
        inserted = _normalise_data(insert_res.data)
        return inserted if inserted else row


# ---------------------------------------------------------------------------
# Outbox — list / approve / cancel
# ---------------------------------------------------------------------------

def list_outbox(
    db,
    org_id: str,
    status: Optional[str] = None,
    lead_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Return paginated outbox rows for the org, newest first."""
    query = (
        db.table("whatsapp_outbox")
        .select("*", count="exact")
        .eq("org_id", org_id)
    )
    if status:
        query = query.eq("status", status)
    if lead_id:
        query = query.eq("lead_id", lead_id)

    result = (
        query
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    items = result.data if isinstance(result.data, list) else []
    total = result.count if result.count is not None else len(items)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def approve_outbox_message(
    db,
    org_id: str,
    outbox_id: str,
    user_id: str,
) -> dict:
    """
    Rep approves a pending or scheduled outbox message → dispatches immediately.
    Raises 404 if not found, 400 if not in an approvable state.
    """
    result = (
        db.table("whatsapp_outbox")
        .select("*")
        .eq("id", outbox_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    row = _normalise_data(result.data)
    if not row:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    if row["status"] not in ("pending", "scheduled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve a message with status '{row['status']}'",
        )

    dispatched = _dispatch_outbox_row(db, org_id, row, actioned_by=user_id)

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="outbox.approved",
        resource_type="whatsapp_outbox",
        resource_id=outbox_id,
        old_value={"status": row["status"]},
        new_value={"status": dispatched.get("status")},
    )
    return dispatched


def cancel_outbox_message(
    db,
    org_id: str,
    outbox_id: str,
    user_id: str,
) -> dict:
    """
    Rep cancels a pending or scheduled outbox message before it is sent.
    Raises 404 if not found, 400 if already sent/cancelled/failed.
    """
    result = (
        db.table("whatsapp_outbox")
        .select("*")
        .eq("id", outbox_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    row = _normalise_data(result.data)
    if not row:
        raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)

    if row["status"] not in ("pending", "scheduled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a message with status '{row['status']}'",
        )

    now_ts = _now_iso()
    updates: dict = {
        "status": "cancelled",
        "actioned_by": user_id,
        "actioned_at": now_ts,
        "updated_at": now_ts,
    }
    upd_result = (
        db.table("whatsapp_outbox")
        .update(updates)
        .eq("id", outbox_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = _normalise_data(upd_result.data)
    if not updated:
        updated = {**row, **updates}

    write_audit_log(
        db=db,
        org_id=org_id,
        user_id=user_id,
        action="outbox.cancelled",
        resource_type="whatsapp_outbox",
        resource_id=outbox_id,
        old_value={"status": row["status"]},
        new_value={"status": "cancelled"},
    )
    return updated

# ---------------------------------------------------------------------------
# WH-1b: Structured Qualification Flow — message senders
# ADD THESE FUNCTIONS to the bottom of app/services/whatsapp_service.py
# ---------------------------------------------------------------------------

def send_qualification_question(
    db,
    org_id: str,
    phone_number: str,
    question: dict,
    question_index: int,
    total: int,
    opening_message: str = None,
) -> None:
    """
    WH-1b: Send one qualification question to the lead via WhatsApp.

    Dispatches the correct message type based on question["type"]:
      "multiple_choice" | "yes_no"  → Interactive button message (up to 3 buttons)
      "list_select"                 → Interactive List Message (up to 10 rows)
      "free_text"                   → Plain text message

    opening_message is prepended only on the first question (question_index == 0).
    S14 — full try/except; logs warning on failure, never raises.
    """
    try:
        # Resolve org phone_id and token
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_qualification_question: no whatsapp_phone_id for org %s", org_id
            )
            return

        # Show typing indicator before sending the question
        _last_msg_id = _get_last_inbound_msg_id(db, org_id, phone_number)
        if _last_msg_id:
            _fire_typing_indicator(phone_id, _last_msg_id, access_token)

        q_type = question.get("type", "free_text")
        q_text = question.get("text", "")
        options = question.get("options") or []

        # Prepend opening_message only on first question
        body_text = q_text
        if question_index == 0 and opening_message:
            body_text = f"{opening_message}\n\n{q_text}"

        if q_type in ("multiple_choice", "yes_no"):
            # WhatsApp Quick Reply buttons — up to 3
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": opt["id"],
                        "title": opt["label"][:20],
                    },
                }
                for opt in options[:3]
            ]
            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {"buttons": buttons},
                },
            }

        elif q_type == "list_select":
            # Interactive List Message — up to 10 rows
            rows = [
                {
                    "id": opt["id"],
                    "title": opt["label"][:24],
                }
                for opt in options[:10]
            ]
            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {
                        "button": "Choose an option",
                        "sections": [
                            {
                                "title": "Choose an option",
                                "rows": rows,
                            }
                        ],
                    },
                },
            }

        else:
            # free_text — plain text message
            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": body_text},
            }

        _call_meta_send(phone_id, meta_payload, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_qualification_question failed org=%s phone=%s q_index=%s: %s",
            org_id, phone_number, question_index, exc,
        )


def send_qualification_handoff_message(
    db,
    org_id: str,
    phone_number: str,
    handoff_message: str,
) -> None:
    """
    WH-1b: Send the configured handoff message to the lead as plain text.
    Called once when all qualification questions have been answered.
    S14 — full try/except; logs warning on failure, never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_qualification_handoff_message: no whatsapp_phone_id for org %s", org_id
            )
            return

        # Show typing indicator before the handoff message
        _last_msg_id = _get_last_inbound_msg_id(db, org_id, phone_number)
        if _last_msg_id:
            _fire_typing_indicator(phone_id, _last_msg_id, access_token)

        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": handoff_message},
        }, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_qualification_handoff_message failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )

def send_abandoned_cart_message(
    db,
    org_id: str,
    phone_number: str,
    checkout_url: Optional[str],
    cart_items: list,
) -> None:
    """
    SHOP-1A: Send a WhatsApp abandoned cart recovery message.
    Includes checkout URL and item count.
    S14 — full try/except; logs warning on failure, never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_abandoned_cart_message: no whatsapp_phone_id for org %s", org_id
            )
            return

        item_count = len(cart_items)
        items_text = f"{item_count} item{'s' if item_count != 1 else ''}"

        body = (
            f"Hi! You left {items_text} in your cart. "
            f"Complete your purchase here:\n{checkout_url}"
            if checkout_url
            else f"Hi! You left {items_text} in your cart. Reply to continue shopping."
        )

        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to":   phone_number,
            "type": "text",
            "text": {"body": body},
        }, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_abandoned_cart_message failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


def send_order_confirmation_message(
    db,
    org_id: str,
    phone_number: str,
    order_name: str,
    total: str,
) -> None:
    """
    SHOP-1A: Send a WhatsApp order confirmation message.
    S14 — full try/except; logs warning on failure, never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_order_confirmation_message: no whatsapp_phone_id for org %s", org_id
            )
            return

        body = (
            f"✅ Order confirmed! Your order {order_name} has been placed successfully. "
            f"Total: {total}. We'll notify you when it ships."
        )

        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to":   phone_number,
            "type": "text",
            "text": {"body": body},
        }, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_order_confirmation_message failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


def send_fulfillment_message(
    db,
    org_id: str,
    phone_number: str,
    tracking_url: Optional[str],
    tracking_company: Optional[str],
) -> None:
    """
    SHOP-1A: Send a WhatsApp dispatch / fulfilment notification.
    Includes tracking link if present.
    S14 — full try/except; logs warning on failure, never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_fulfillment_message: no whatsapp_phone_id for org %s", org_id
            )
            return

        if tracking_url:
            company_text = f" via {tracking_company}" if tracking_company else ""
            body = (
                f"📦 Your order has been dispatched{company_text}! "
                f"Track it here: {tracking_url}"
            )
        else:
            body = "📦 Great news — your order has been dispatched and is on its way!"

        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to":   phone_number,
            "type": "text",
            "text": {"body": body},
        }, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_fulfillment_message failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )

# ---------------------------------------------------------------------------
# COMM-1 — Commerce WhatsApp Functions
# ---------------------------------------------------------------------------

def send_product_list(
    db,
    org_id: str,
    phone_number: str,
    products: list,
    force_text_list: bool = False,
) -> bool:
    """
    SHOP-3 / COMM-1: Send WhatsApp product message.

    If the org has meta_catalog_id set and force_text_list is False:
    sends a native WhatsApp product_list message (shows product images,
    name, price via Meta Commerce Catalog).

    Falls back to the COMM-1 interactive button list if meta_catalog_id
    is not set OR force_text_list=True — used when the catalog is
    configured but rejected by Meta (e.g. test WABA, catalog not linked).

    Returns True if the message was sent successfully, False otherwise.
    S14 -- never raises.
    """
    import re as _re

    def _strip_html(text: str) -> str:
        if not text:
            return ""
        clean = _re.sub(r'<[^>]+>', ' ', text)
        clean = _re.sub(r'\s+', ' ', clean).strip()
        return clean

    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning("send_product_list: no whatsapp_phone_id for org %s", org_id)
            return False

        if not products:
            logger.warning("send_product_list: no products for org %s", org_id)
            return False

        # SHOP-3: check if org has a Meta Catalog ID configured.
        # Skip catalog if force_text_list=True (catalog rejected by Meta).
        catalog_id = None
        if not force_text_list:
            try:
                org_r = (
                    db.table("organisations")
                    .select("meta_catalog_id")
                    .eq("id", org_id)
                    .maybe_single()
                    .execute()
                )
                org_data = org_r.data
                if isinstance(org_data, list):
                    org_data = org_data[0] if org_data else None
                catalog_id = ((org_data or {}).get("meta_catalog_id") or "").strip() or None
            except Exception as _cat_exc:
                logger.warning(
                    "send_product_list: catalog_id lookup failed org=%s: %s", org_id, _cat_exc
                )

        if catalog_id:
            # -- SHOP-3 path: WhatsApp product_list (native Meta Commerce format) --
            # product_retailer_id must match the shopify_id pushed to the catalog.
            tag_map: dict = {}
            for product in products:
                tags = product.get("tags") or []
                tag = tags[0].strip() if tags else "Our Products"
                tag_map.setdefault(tag, []).append(product)

            sections = []
            for section_title, section_products in tag_map.items():
                product_items = []
                for p in section_products[:30]:
                    retailer_id = str(p.get("shopify_id") or p.get("id") or "")
                    if retailer_id:
                        product_items.append({"product_retailer_id": retailer_id})
                if product_items:
                    sections.append({
                        "title": section_title[:24],
                        "product_items": product_items,
                    })
                if len(sections) >= 10:
                    break

            if not sections:
                logger.warning(
                    "send_product_list: no catalog sections built for org %s", org_id
                )
                return False

            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "product_list",
                    "header": {"type": "text", "text": "Our Products"},
                    "body": {"text": "Browse our products below and tap one to add it to your cart."},
                    "action": {
                        "catalog_id": catalog_id,
                        "sections": sections,
                    },
                },
            }
            logger.info(
                "send_product_list: catalog product_list %d products to %s org=%s",
                len(products), phone_number, org_id,
            )

        else:
            # -- COMM-1 fallback: interactive text list (no images) --
            def _make_row(product: dict) -> dict:
                title = (product.get("title") or "Product")[:24]
                price = float(product.get("price") or 0)
                raw_desc = _strip_html(product.get("description") or "").strip()
                price_suffix = f" \u2014 \u20a6{price:,.0f}"
                max_desc_len = 72 - len(price_suffix)
                short_desc = raw_desc[:max_desc_len] if raw_desc else ""
                description = (f"{short_desc}{price_suffix}" if short_desc else price_suffix)[:72]
                return {
                    "id": str(product.get("id", "")),
                    "title": title,
                    "description": description,
                }

            # Fetch Shopify store domain for the browse link
            _shop_domain = None
            try:
                _shop_r = (
                    db.table("organisations")
                    .select("shopify_shop_domain")
                    .eq("id", org_id)
                    .maybe_single()
                    .execute()
                )
                _shop_d = _shop_r.data
                if isinstance(_shop_d, list):
                    _shop_d = _shop_d[0] if _shop_d else None
                _shop_domain = (_shop_d or {}).get("shopify_shop_domain") or None
            except Exception:
                pass

            tag_map2: dict = {}
            for product in products:
                tags = product.get("tags") or []
                tag = tags[0].strip() if tags else "Our Products"
                tag_map2.setdefault(tag, []).append(product)

            sections2 = []
            total_rows = 0
            for section_title, section_products in tag_map2.items():
                # Cap at 9 product rows — 1 slot reserved for "Speak to Sales"
                if total_rows >= 9:
                    break
                remaining = 9 - total_rows
                rows = [_make_row(p) for p in section_products[:remaining]]
                if rows:
                    sections2.append({"title": section_title[:24], "rows": rows})
                    total_rows += len(rows)
                if len(sections2) >= 9:
                    break

            if not sections2:
                logger.warning("send_product_list: no sections built for org %s", org_id)
                return False

            # Always append "Speak to Sales" as the last option.
            sections2.append({
                "title": "Need Help?",
                "rows": [{
                    "id": "talk_sales",
                    "title": "Speak to Sales",
                    "description": "Connect with a sales rep directly",
                }],
            })

            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": (
                        "Here's a selection of our popular products \ud83d\uded2\n\n"
                        "Tap one to order, or tap *Speak to Sales* if you're looking for something specific.\n\n"
                        + (
                            f"Browse our full catalog here:\n"
                            f"https://{_shop_domain}?utm_source=whatsapp&utm_medium=chat&utm_campaign=product_browse"
                            if _shop_domain else
                            "Let us know if you\u2019re looking for something specific \u2014 we\u2019re happy to help!"
                        )
                    )},
                    "action": {"button": "View products", "sections": sections2},
                },
            }
            logger.info(
                "send_product_list: text list %d products to %s org=%s",
                len(products), phone_number, org_id,
            )

        result = _call_meta_send(phone_id, meta_payload, token=access_token)
        logger.info("send_product_list: Meta response for %s: %s", phone_number, result)
        return True

    except Exception as exc:
        logger.warning(
            "send_product_list failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )
        return False

def send_variant_selection(
    db,
    org_id: str,
    phone_number: str,
    product: dict,
) -> None:
    """
    COMM-1: Send variant picker for a product with multiple variants.
    ≤ 3 variants → interactive button message.
    4–10 variants → interactive list message.
    Button/item label: "{variant title} — ₦{price:,.0f}".
    Item ID format: "variant_{variant_id}".
    S14 — never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_variant_selection: no whatsapp_phone_id for org %s", org_id
            )
            return

        variants = product.get("variants") or []
        if not variants:
            logger.warning(
                "send_variant_selection: no variants for product %s", product.get("id")
            )
            return

        product_title = (product.get("title") or "Product").strip()
        body_text = f"Choose an option for *{product_title}*:"

        def _variant_label(v: dict) -> str:
            title = (v.get("title") or "Option").strip()
            price = float(v.get("price") or product.get("price") or 0)
            label = f"{title} — ₦{price:,.0f}"
            return label

        def _variant_id(v: dict) -> str:
            vid = str(v.get("id") or v.get("variant_id") or "")
            return f"variant_{vid}"

        if len(variants) <= 3:
            buttons = [
                {
                    "type": "reply",
                    "reply": {
                        "id": _variant_id(v),
                        "title": _variant_label(v)[:20],
                    },
                }
                for v in variants[:3]
            ]
            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {"buttons": buttons},
                },
            }
        else:
            rows = [
                {
                    "id": _variant_id(v),
                    "title": _variant_label(v)[:24],
                }
                for v in variants[:10]
            ]
            meta_payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {
                        "button": "Choose option",
                        "sections": [{"title": "Available options", "rows": rows}],
                    },
                },
            }

        _call_meta_send(phone_id, meta_payload, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_variant_selection failed org=%s phone=%s product=%s: %s",
            org_id, phone_number, product.get("id"), exc,
        )


def send_cart_summary(
    db,
    org_id: str,
    phone_number: str,
    session: dict,
) -> None:
    """
    COMM-1: Send cart contents as WhatsApp interactive button message.
    Includes: item list + subtotal + two buttons: Add more | Checkout.
    S14 — never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_cart_summary: no whatsapp_phone_id for org %s", org_id
            )
            return

        from app.services.commerce_service import get_cart_summary
        summary_text = get_cart_summary(session)

        meta_payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": summary_text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "add_more", "title": "Add more"},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": "checkout", "title": "Checkout"},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": "talk_sales", "title": "💬 Talk to Sales"},
                        },
                    ]
                },
            },
        }

        _call_meta_send(phone_id, meta_payload, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_cart_summary failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


def send_checkout_link(
    db,
    org_id: str,
    phone_number: str,
    checkout_url: str,
    commerce_config: dict = None,
) -> None:
    """
    COMM-1: Send checkout URL as WhatsApp text message.
    Uses org commerce_config["checkout_message"] if set,
    fallback: "Here's your checkout link:".
    Appends checkout URL + "Reply CANCEL to cancel your order."
    S14 — never raises.
    """
    try:
        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
        phone_id = (phone_id or "").strip()
        if not phone_id:
            logger.warning(
                "send_checkout_link: no whatsapp_phone_id for org %s", org_id
            )
            return

        intro = (
            (commerce_config or {}).get("checkout_message")
            or "Here's your checkout link:"
        ).strip()

        _call_meta_send(phone_id, {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "text",
                    "text": "Your checkout link 🛒",
                },
                "body": {
                    "text": f"{intro}\n{checkout_url}",
                },
                "footer": {
                    "text": "Reply CANCEL to cancel your order.",
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "talk_sales", "title": "💬 Talk to Sales"},
                        },
                    ]
                },
            },
        }, token=access_token)

    except Exception as exc:
        logger.warning(
            "send_checkout_link failed org=%s phone=%s: %s",
            org_id, phone_number, exc,
        )


# ---------------------------------------------------------------------------
# Conversations — unified inbox list
# ---------------------------------------------------------------------------

def get_conversations(
    db,
    org_id: str,
    user_id: str,
    is_scoped: bool,
    channel: Optional[str] = None,
    contact_type: Optional[str] = None,
) -> list:
    """
    Returns one conversation entry per lead/customer, sorted by most recent
    message descending.  Scoped roles (sales_agent etc.) see only their
    assigned contacts.  Admins/owners see all.

    S14: per-section failures are swallowed — the other section still returns.
    """
    conversations: list = []

    # ── Leads ───────────────────────────────────────────────────────────────
    if contact_type in (None, "lead"):
        try:
            leads_q = (
                db.table("leads")
                .select(
                    "id, full_name, whatsapp, assigned_to,"
                    " assigned_user:users!assigned_to(full_name)"
                )
                .eq("org_id", org_id)
                .is_("deleted_at", "null")
                .limit(300)
            )
            if is_scoped:
                leads_q = leads_q.eq("assigned_to", user_id)
            leads = leads_q.execute().data or []

            if leads:
                lead_ids = [l["id"] for l in leads]

                # Latest message per lead (fetch, python-side dedup)
                msgs = (
                    db.table("whatsapp_messages")
                    .select("lead_id, content, created_at, direction, status, message_type")
                    .eq("org_id", org_id)
                    .in_("lead_id", lead_ids)
                    .order("created_at", desc=True)
                    .limit(min(len(lead_ids) * 3, 600))
                    .execute()
                ).data or []
                lead_latest: dict = {}
                for m in msgs:
                    lid = m.get("lead_id")
                    if lid and lid not in lead_latest:
                        lead_latest[lid] = m

                # Unread counts
                unread_rows = (
                    db.table("whatsapp_messages")
                    .select("lead_id")
                    .eq("org_id", org_id)
                    .in_("lead_id", lead_ids)
                    .eq("direction", "inbound")
                    .is_("read_at", "null")
                    .execute()
                ).data or []
                lead_unread: dict = {}
                for u in unread_rows:
                    lid = u.get("lead_id")
                    if lid:
                        lead_unread[lid] = lead_unread.get(lid, 0) + 1

                for lead in leads:
                    try:
                        lid = lead["id"]
                        last = lead_latest.get(lid)
                        conversations.append({
                            "contact_id":             lid,
                            "contact_type":           "lead",
                            "contact_name":           lead.get("full_name") or "Unknown",
                            "phone":                  lead.get("whatsapp") or "",
                            "channel":                "whatsapp",
                            "last_message":           (last.get("content") or "(media)") if last else None,
                            "last_message_at":        last.get("created_at") if last else None,
                            "last_message_direction": last.get("direction") if last else None,
                            "unread_count":           lead_unread.get(lid, 0),
                            "assigned_to":            lead.get("assigned_to"),
                            "assigned_name":          (lead.get("assigned_user") or {}).get("full_name"),
                        })
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("get_conversations leads error org=%s: %s", org_id, exc)

    # ── Customers ───────────────────────────────────────────────────────────
    if contact_type in (None, "customer"):
        try:
            customers_q = (
                db.table("customers")
                .select(
                    "id, full_name, whatsapp, assigned_to,"
                    " assigned_user:users!assigned_to(full_name)"
                )
                .eq("org_id", org_id)
                .is_("deleted_at", "null")
                .limit(300)
            )
            if is_scoped:
                customers_q = customers_q.eq("assigned_to", user_id)
            customers = customers_q.execute().data or []

            if customers:
                customer_ids = [c["id"] for c in customers]

                msgs = (
                    db.table("whatsapp_messages")
                    .select("customer_id, content, created_at, direction, status, message_type")
                    .eq("org_id", org_id)
                    .in_("customer_id", customer_ids)
                    .order("created_at", desc=True)
                    .limit(min(len(customer_ids) * 3, 600))
                    .execute()
                ).data or []
                customer_latest: dict = {}
                for m in msgs:
                    cid = m.get("customer_id")
                    if cid and cid not in customer_latest:
                        customer_latest[cid] = m

                unread_rows = (
                    db.table("whatsapp_messages")
                    .select("customer_id")
                    .eq("org_id", org_id)
                    .in_("customer_id", customer_ids)
                    .eq("direction", "inbound")
                    .is_("read_at", "null")
                    .execute()
                ).data or []
                customer_unread: dict = {}
                for u in unread_rows:
                    cid = u.get("customer_id")
                    if cid:
                        customer_unread[cid] = customer_unread.get(cid, 0) + 1

                for customer in customers:
                    try:
                        cid = customer["id"]
                        last = customer_latest.get(cid)
                        conversations.append({
                            "contact_id":             cid,
                            "contact_type":           "customer",
                            "contact_name":           customer.get("full_name") or "Unknown",
                            "phone":                  customer.get("whatsapp") or "",
                            "channel":                "whatsapp",
                            "last_message":           (last.get("content") or "(media)") if last else None,
                            "last_message_at":        last.get("created_at") if last else None,
                            "last_message_direction": last.get("direction") if last else None,
                            "unread_count":           customer_unread.get(cid, 0),
                            "assigned_to":            customer.get("assigned_to"),
                            "assigned_name":          (customer.get("assigned_user") or {}).get("full_name"),
                        })
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("get_conversations customers error org=%s: %s", org_id, exc)

    # Sort: most recent message first; contacts with no messages go to the end
    conversations.sort(
        key=lambda x: x.get("last_message_at") or "0000",
        reverse=True,
    )

    if channel:
        conversations = [c for c in conversations if c.get("channel") == channel]

    return conversations
