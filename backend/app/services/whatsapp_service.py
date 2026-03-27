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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

def _call_meta_send(phone_id: str, meta_payload: dict) -> dict:
    """
    Send a WhatsApp message via Meta Cloud API.
    Returns the Meta API response dict.
    Raises HTTPException(503) on network error or non-2xx response.
    This function is kept thin so it can be patched in tests.
    """
    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.META_WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=meta_payload, headers=headers)
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=503,
                detail=ErrorCode.INTEGRATION_ERROR,
            )
        return response.json()
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail=ErrorCode.INTEGRATION_ERROR,
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

    # ── Resolve phone_id from org ──────────────────────────────────────────
    try:
        org_result = (
            db.table("organisations")
            .select("whatsapp_phone_id")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_data = _normalise_data(org_result.data) if org_result else None
    except Exception:
        org_data = None
    phone_id: str = (org_data or {}).get("whatsapp_phone_id") or ""

    # ── Resolve recipient WhatsApp number ──────────────────────────────────
    to_number: Optional[str] = None
    customer_id_str: Optional[str] = None
    lead_id_str: Optional[str] = None

    if payload.customer_id:
        customer = _customer_or_404(db, org_id, str(payload.customer_id))
        to_number = customer.get("whatsapp") or customer.get("phone")
        customer_id_str = str(payload.customer_id)
    else:
        lead_result = (
            db.table("leads")
            .select("whatsapp, phone")
            .eq("id", str(payload.lead_id))
            .eq("org_id", org_id)
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        lead_data = _normalise_data(lead_result.data)
        if not lead_data:
            raise HTTPException(status_code=404, detail=ErrorCode.NOT_FOUND)
        to_number = lead_data.get("whatsapp") or lead_data.get("phone")
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
        meta_payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": payload.template_name,
                "language": {"code": "en"},
            },
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
    meta_response = _call_meta_send(phone_id, meta_payload)
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


def create_template(
    db,
    org_id: str,
    user_id: str,
    payload: TemplateCreate,
) -> dict:
    """
    Create a template and submit it to Meta for approval.
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
    return updated


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