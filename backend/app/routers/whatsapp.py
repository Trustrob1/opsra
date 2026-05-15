"""
whatsapp.py — Module 02 WhatsApp Communication Engine routes.

CONV-UI addition:
  POST /api/v1/messages/send-media  — multipart upload + WhatsApp media send

All existing routes unchanged.
"""
import uuid
from typing import Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form

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


@router.post("/messages/send-media")
async def send_media_message(
    file: UploadFile = File(...),
    customer_id: Optional[str] = Form(None),
    lead_id: Optional[str] = Form(None),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    CONV-UI: Send a WhatsApp media message (image / video / audio / document).

    Accepts multipart/form-data with:
      file        — the media file
      lead_id     — UUID (pass if recipient is a lead)
      customer_id — UUID (pass if recipient is a customer)

    Exactly one of lead_id / customer_id must be supplied.
    File size enforced at 25 MB max (HTTP 413 if exceeded).
    Unsupported MIME type returns HTTP 415.
    """
    if not customer_id and not lead_id:
        raise HTTPException(
            status_code=422,
            detail="customer_id or lead_id is required",
        )

    file_bytes = await file.read()

    msg = whatsapp_service.send_whatsapp_media_message(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        customer_id=customer_id,
        lead_id=lead_id,
    )
    return ok(data=msg, message="Media message sent")


@router.get("/messages/unread-counts")
def get_unread_counts(
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    counts = whatsapp_service.get_unread_counts(db=db, org_id=org["org_id"])
    return ok(data=counts)


# ---------------------------------------------------------------------------
# Conversations — unified inbox
# ---------------------------------------------------------------------------

@router.get("/conversations")
def list_conversations(
    channel: Optional[str] = Query(None),
    contact_type: Optional[str] = Query(None),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    from app.utils.rbac import is_scoped_role
    conversations = whatsapp_service.get_conversations(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        is_scoped=is_scoped_role(org),
        channel=channel,
        contact_type=contact_type,
    )
    return ok(data=conversations)


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


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Conversation status + resume AI
# ---------------------------------------------------------------------------

@router.get("/conversations/{contact_type}/{contact_id}/status")
def get_conversation_status(
    contact_type: str,
    contact_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    if contact_type not in ("lead", "customer"):
        raise HTTPException(status_code=422, detail="contact_type must be 'lead' or 'customer'")
    status = whatsapp_service.get_contact_status(
        db=db,
        org_id=org["org_id"],
        contact_type=contact_type,
        contact_id=contact_id,
    )
    return ok(data=status)


@router.post("/conversations/{contact_type}/{contact_id}/resume-ai")
def resume_ai(
    contact_type: str,
    contact_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    if contact_type not in ("lead", "customer"):
        raise HTTPException(status_code=422, detail="contact_type must be 'lead' or 'customer'")
    whatsapp_service.set_ai_paused(
        db=db,
        org_id=org["org_id"],
        contact_type=contact_type,
        contact_id=contact_id,
        paused=False,
    )
    return ok(message="AI resumed for this conversation")


# ---------------------------------------------------------------------------
# UNIFIED-INBOX-1A — Instagram DM outbound send
# ---------------------------------------------------------------------------

class InstagramSendRequest(BaseModel):
    lead_id: str = Field(..., max_length=36)
    message: str = Field(..., max_length=1000)


@router.post("/conversations/instagram/send")
def send_instagram_dm(
    payload: InstagramSendRequest,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    Send an outbound Instagram DM to a lead.
    Lead must have instagram_scoped_id set (populated automatically when they
    first message the org's Instagram page).
    Enforces the 24-hour Instagram conversation window.
    S1: org_id from JWT only.
    """
    from app.services.instagram_service import send_instagram_message

    org_id = org["org_id"]

    # Fetch instagram_scoped_id from lead — never trust it from the request body
    lead_result = (
        db.table("leads")
        .select("id, instagram_scoped_id")
        .eq("id", payload.lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", None)
        .maybe_single()
        .execute()
    )
    lead_data = lead_result.data
    if isinstance(lead_data, list):
        lead_data = lead_data[0] if lead_data else None
    if not lead_data:
        raise HTTPException(status_code=404, detail="Lead not found")

    instagram_scoped_id = (lead_data or {}).get("instagram_scoped_id")
    if not instagram_scoped_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "This lead has no Instagram identity on record. "
                "They must message you on Instagram first before you can reply."
            ),
        )

    msg = send_instagram_message(
        db=db,
        org_id=org_id,
        lead_id=payload.lead_id,
        instagram_scoped_id=instagram_scoped_id,
        text=payload.message,
        sent_by=org["id"],
    )
    return ok(data=msg, message="Instagram DM sent")


# ---------------------------------------------------------------------------
# UNIFIED-INBOX-1B — Facebook Messenger outbound send
# ---------------------------------------------------------------------------

class MessengerSendRequest(BaseModel):
    lead_id: str = Field(..., max_length=36)
    message: str = Field(..., max_length=2000)


@router.post("/conversations/messenger/send")
def send_messenger_dm(
    payload: MessengerSendRequest,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    Send an outbound Facebook Messenger DM to a lead.
    Lead must have messenger_psid set (populated automatically when they
    first message the org's Facebook Page).
    Enforces the 24-hour Messenger conversation window.
    S1: org_id from JWT only.
    """
    from app.services.messenger_service import (
        send_messenger_message,
        is_messenger_window_open,
    )

    org_id = org["org_id"]

    # Fetch messenger_psid from lead — never trust it from the request body
    lead_result = (
        db.table("leads")
        .select("id, messenger_psid")
        .eq("id", payload.lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", None)
        .maybe_single()
        .execute()
    )
    lead_data = lead_result.data
    if isinstance(lead_data, list):
        lead_data = lead_data[0] if lead_data else None
    if not lead_data:
        raise HTTPException(status_code=404, detail="Lead not found")

    messenger_psid = (lead_data or {}).get("messenger_psid")
    if not messenger_psid:
        raise HTTPException(
            status_code=422,
            detail=(
                "This lead has no Messenger identity on record. "
                "They must message you on Facebook Messenger first before you can reply."
            ),
        )

    if not is_messenger_window_open(db, org_id, payload.lead_id):
        raise HTTPException(
            status_code=400,
            detail="24-hour Messenger window is closed — you can only reply within 24 hours of the last message.",
        )

    msg = send_messenger_message(
        db=db,
        org_id=org_id,
        lead_id=payload.lead_id,
        psid=messenger_psid,
        text=payload.message,
        sent_by=org["id"],
    )
    return ok(data=msg, message="Messenger DM sent")

@router.post("/conversations/{contact_type}/{contact_id}/pause-ai")
def pause_ai(
    contact_type: str,
    contact_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    Rep manually takes over the conversation — sets ai_paused=True.
    AI will stop responding to inbound messages until resume-ai is called.
    """
    if contact_type not in ("lead", "customer"):
        raise HTTPException(status_code=422, detail="contact_type must be 'lead' or 'customer'")
    whatsapp_service.set_ai_paused(
        db=db,
        org_id=org["org_id"],
        contact_type=contact_type,
        contact_id=contact_id,
        paused=True,
    )
    return ok(message="AI paused — conversation handed to human")


# ---------------------------------------------------------------------------
# AI-SUGGEST-1 — On-demand KB suggestion + suggestion analytics
# ---------------------------------------------------------------------------

@router.get("/conversations/lead/{lead_id}/kb-suggestion")
def get_kb_suggestion(
    lead_id: str,
    content: str = Query(..., max_length=2000),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    AI-SUGGEST-1: Rep taps 💡 on an inbound message — returns a KB-sourced
    suggested reply if a confident match exists.

    Query param:
      content — the inbound message text to match against the KB.

    Returns { article_id, title, snippet } or null.
    S1: org_id from JWT only — lead_id verified against org before any lookup.
    S14: returns null on any failure rather than 500.
    """
    from app.services.customer_inbound_service import get_kb_suggestion_for_rep

    org_id = org["org_id"]

    # Verify lead belongs to this org (S1)
    lead_check = (
        db.table("leads")
        .select("id")
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", None)
        .maybe_single()
        .execute()
    )
    lead_data = lead_check.data
    if isinstance(lead_data, list):
        lead_data = lead_data[0] if lead_data else None
    if not lead_data:
        raise HTTPException(status_code=404, detail="Lead not found")

    suggestion = get_kb_suggestion_for_rep(db=db, org_id=org_id, content=content)
    return ok(data=suggestion)


class SuggestionFeedbackRequest(BaseModel):
    message_id: str = Field(..., max_length=36)
    article_id: str = Field(..., max_length=36)
    accepted: bool


@router.post("/conversations/lead/{lead_id}/kb-suggestion/feedback")
def record_suggestion_feedback(
    lead_id: str,
    payload: SuggestionFeedbackRequest,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    """
    AI-SUGGEST-1: Record whether the rep accepted or dismissed a KB suggestion.
    Writes suggested_kb_article_id + suggestion_accepted onto the message row.
    S1: org_id from JWT. message_id verified to belong to this org + lead.
    """
    org_id = org["org_id"]

    # Verify the message belongs to this org and this lead (S1)
    msg_check = (
        db.table("whatsapp_messages")
        .select("id")
        .eq("id", payload.message_id)
        .eq("org_id", org_id)
        .eq("lead_id", lead_id)
        .maybe_single()
        .execute()
    )
    msg_data = msg_check.data
    if isinstance(msg_data, list):
        msg_data = msg_data[0] if msg_data else None
    if not msg_data:
        raise HTTPException(status_code=404, detail="Message not found")

    db.table("whatsapp_messages").update({
        "suggested_kb_article_id": payload.article_id,
        "suggestion_accepted":     payload.accepted,
    }).eq("id", payload.message_id).eq("org_id", org_id).execute()

    return ok(message="Suggestion feedback recorded")
