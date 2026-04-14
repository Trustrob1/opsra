"""
whatsapp.py — Module 02 WhatsApp Communication Engine routes.

Included in main.py with prefix="/api/v1" (no trailing slash — Pattern 7).
Internal prefix: none — routes define their own sub-paths.

Routes (full paths after combining):
  POST  /api/v1/messages/send                    send_message        [JWT]
  GET   /api/v1/broadcasts                       list_broadcasts     [JWT]
  POST  /api/v1/broadcasts                       create_broadcast    [JWT]
  GET   /api/v1/broadcasts/{broadcast_id}        get_broadcast       [JWT]
  POST  /api/v1/broadcasts/{broadcast_id}/approve  approve_broadcast [JWT]
  POST  /api/v1/broadcasts/{broadcast_id}/cancel   cancel_broadcast  [JWT]
  GET   /api/v1/templates                        list_templates      [JWT]
  POST  /api/v1/templates                        create_template     [JWT]
  PATCH /api/v1/templates/{template_id}          update_template     [JWT]
  GET   /api/v1/drip-sequences                   get_drip_sequence   [JWT]
  PUT   /api/v1/drip-sequences                   update_drip_sequence [Admin]

Admin check on PUT /drip-sequences: requires roles.template = "owner".
All other routes: any authenticated staff member.
"""
import uuid
from typing import Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ErrorCode, ok, paginated
from app.models.whatsapp import (
    BroadcastCreate,
    DripSequenceUpdate,
    SendMessageRequest,
    TemplateCreate,
    TemplateUpdate,
)
from app.services import whatsapp_service
from app.utils.rbac import require_not_affiliate, require_permission_key
from app.services.whatsapp_service import (
      queue_outbox_message,
      list_outbox,
      approve_outbox_message,
      cancel_outbox_message,
  )

class OutboxMessageCreate(BaseModel):
    lead_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    content: Optional[str] = Field(None, max_length=5000)
    template_name: Optional[str] = Field(None, max_length=100)
    source_type: str = Field(..., max_length=50)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal admin check (owner role only)
# ---------------------------------------------------------------------------

def _assert_owner(org: dict) -> None:
    """Raise 403 if the requesting user is not owner/admin."""
    role = org.get("roles") or {}
    template = role.get("template") if isinstance(role, dict) else None
    if template != "owner":
        raise HTTPException(status_code=403, detail=ErrorCode.FORBIDDEN)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.post("/messages/send")
def send_message(
    payload: SendMessageRequest,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    msg = whatsapp_service.send_whatsapp_message(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=msg, message="Message sent")


@router.get("/messages/unread-counts")
def get_unread_counts(
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    Returns unread inbound message counts keyed by lead_id and customer_id.
    An inbound message is unread when read_at IS NULL.
    Used by LeadsPipeline and CustomerList to show 💬 unread badges.
    Response: { leads: {lead_id: count}, customers: {customer_id: count} }
    """
    counts = whatsapp_service.get_unread_counts(db=db, org_id=org["org_id"])
    return ok(data=counts)


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------

@router.get("/broadcasts")
def list_broadcasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = whatsapp_service.list_broadcasts(
        db=db,
        org_id=org["org_id"],
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.post("/broadcasts")
def create_broadcast(
    payload: BroadcastCreate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    require_not_affiliate(org, "creating broadcasts")
    broadcast = whatsapp_service.create_broadcast(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=broadcast, message="Broadcast created")


@router.get("/broadcasts/{broadcast_id}")
def get_broadcast(
    broadcast_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    broadcast = whatsapp_service.get_broadcast(
        db=db,
        org_id=org["org_id"],
        broadcast_id=broadcast_id,
    )
    return ok(data=broadcast)


@router.post("/broadcasts/{broadcast_id}/approve")
def approve_broadcast(
    broadcast_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    broadcast = whatsapp_service.approve_broadcast(
        db=db,
        org_id=org["org_id"],
        broadcast_id=broadcast_id,
        user_id=org["id"],
    )
    return ok(data=broadcast, message="Broadcast approved")


@router.post("/broadcasts/{broadcast_id}/cancel")
def cancel_broadcast(
    broadcast_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    broadcast = whatsapp_service.cancel_broadcast(
        db=db,
        org_id=org["org_id"],
        broadcast_id=broadcast_id,
        user_id=org["id"],
    )
    return ok(data=broadcast, message="Broadcast cancelled")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_templates(
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    templates = whatsapp_service.list_templates(db=db, org_id=org["org_id"])
    return ok(data=templates)


@router.post("/templates")
def create_template(
    payload: TemplateCreate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    require_permission_key(
        org, "manage_templates",
        "Template management requires owner, admin, or the manage_templates permission",
    )
    template = whatsapp_service.create_template(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=template, message="Template created")


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    payload: TemplateUpdate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    require_permission_key(
        org, "manage_templates",
        "Template management requires owner, admin, or the manage_templates permission",
    )
    template = whatsapp_service.update_template(
        db=db,
        org_id=org["org_id"],
        template_id=template_id,
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=template, message="Template updated and resubmitted")


# ---------------------------------------------------------------------------
# Drip sequences (PUT is Admin only)
# ---------------------------------------------------------------------------

@router.get("/drip-sequences")
def get_drip_sequence(
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    sequence = whatsapp_service.get_drip_sequence(db=db, org_id=org["org_id"])
    return ok(data=sequence)


@router.put("/drip-sequences")
def update_drip_sequence(
    payload: DripSequenceUpdate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    _assert_owner(org)
    sequence = whatsapp_service.update_drip_sequence(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        messages=payload.messages,
    )
    return ok(data=sequence, message="Drip sequence updated")


# ── Route 1 — GET /api/v1/outbox ─────────────────────────────────────────────
# List outbox messages for the org.
# Query params: status (str), lead_id (uuid), page (int), page_size (int)
 
@router.get("/outbox")
def get_outbox(
    status: Optional[str] = None,
    lead_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = list_outbox(
        db=db,
        org_id=org["org_id"],
        status=status,
        lead_id=lead_id,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/outbox", status_code=201)
def create_outbox_message(
    payload: OutboxMessageCreate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = queue_outbox_message(
        db=db,
        org_id=org["org_id"],
        lead_id=str(payload.lead_id) if payload.lead_id else None,
        customer_id=str(payload.customer_id) if payload.customer_id else None,
        content=payload.content,
        template_name=payload.template_name,
        source_type=payload.source_type,
        queued_by=org["id"],
    )
    return ok(data=result, message="Message queued")


@router.post("/outbox/{outbox_id}/approve")
def approve_outbox(
    outbox_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = approve_outbox_message(
        db=db,
        org_id=org["org_id"],
        outbox_id=outbox_id,
        user_id=org["id"],
    )
    return ok(data=result, message="Message approved and sent")


@router.post("/outbox/{outbox_id}/cancel")
def cancel_outbox(
    outbox_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = cancel_outbox_message(
        db=db,
        org_id=org["org_id"],
        outbox_id=outbox_id,
        user_id=org["id"],
    )
    return ok(data=result, message="Message cancelled")