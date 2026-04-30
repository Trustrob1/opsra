"""
app/models/tickets.py
Pydantic request/response models for Module 03 — Support.
Tables: tickets, ticket_messages, ticket_attachments,
        knowledge_base_articles, interaction_logs.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Domain constants  (Technical Spec §3.4 / §4.2)
# ---------------------------------------------------------------------------
TICKET_CATEGORIES: frozenset = frozenset(
    {
        "technical_bug",
        "billing",
        "feature_question",
        "onboarding_help",
        "account_access",
        "hardware",
    }
)

TICKET_URGENCIES: frozenset = frozenset({"critical", "high", "medium", "low"})

TICKET_STATUSES: frozenset = frozenset(
    {"open", "in_progress", "awaiting_customer", "resolved", "closed"}
)

TICKET_MESSAGE_TYPES: frozenset = frozenset(
    {"customer", "agent_reply", "internal_note", "ai_draft", "system"}
)

AI_HANDLING_MODES: frozenset = frozenset({"auto", "draft_review", "human_only"})

INTERACTION_TYPES: frozenset = frozenset(
    {"outbound_call", "inbound_call", "whatsapp", "in_person", "email"}
)

KB_CATEGORIES: frozenset = frozenset(
    {
        "product_overview",
        "pricing",
        "faq",
        "troubleshooting",
        "hardware",
        "contact",
    }
)

# Technical Spec §11.5 — allowed MIME types and size ceiling
ALLOWED_ATTACHMENT_TYPES: frozenset = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "video/mp4",
        "video/3gpp",
        "audio/mpeg",
        "audio/ogg",
        "application/pdf",
        "text/csv",
    }
)

MAX_ATTACHMENT_BYTES: int = 25 * 1024 * 1024  # 25 MB


# ---------------------------------------------------------------------------
# Ticket models
# ---------------------------------------------------------------------------
class TicketCreate(BaseModel):
    """
    Manually create a support ticket.
    category / urgency / title are optional — AI triage fills them if omitted.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    category: Optional[str] = None  # CONFIG-1: validated against org config, not hardcoded enum
    urgency: Optional[str] = None
    title: Optional[str] = None
    content: str = Field(..., max_length=10000)  # S5: ticket problem description
    ai_handling_mode: str = "draft_review"
    assigned_to: Optional[UUID] = None

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in TICKET_URGENCIES:
            raise ValueError(
                f"urgency must be one of {sorted(TICKET_URGENCIES)}"
            )
        return v

    @field_validator("ai_handling_mode")
    @classmethod
    def validate_ai_handling_mode(cls, v: str) -> str:
        if v not in AI_HANDLING_MODES:
            raise ValueError(
                f"ai_handling_mode must be one of {sorted(AI_HANDLING_MODES)}"
            )
        return v


class TicketUpdate(BaseModel):
    """
    PATCH /tickets/{id} — only category, urgency, assigned_to are mutable.
    Technical Spec §5.4.
    """

    model_config = ConfigDict(extra="ignore")

    category: Optional[str] = None  # CONFIG-1: validated against org config, not hardcoded enum
    urgency: Optional[str] = None
    assigned_to: Optional[UUID] = None
    updated_at: Optional[str] = None  # C7: optimistic concurrency token

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in TICKET_URGENCIES:
            raise ValueError(
                f"urgency must be one of {sorted(TICKET_URGENCIES)}"
            )
        return v


class AddMessageRequest(BaseModel):
    """Body for POST /tickets/{id}/messages."""

    model_config = ConfigDict(extra="forbid")

    message_type: str
    content: str = Field(..., max_length=5000)  # S4: ticket message body

    @field_validator("message_type")
    @classmethod
    def validate_message_type(cls, v: str) -> str:
        if v not in TICKET_MESSAGE_TYPES:
            raise ValueError(
                f"message_type must be one of {sorted(TICKET_MESSAGE_TYPES)}"
            )
        return v


class ResolveRequest(BaseModel):
    """Body for POST /tickets/{id}/resolve — resolution_notes required."""

    model_config = ConfigDict(extra="forbid")

    resolution_notes: str = Field(..., max_length=5000)  # S4: free text field


# ---------------------------------------------------------------------------
# Knowledge-base models
# ---------------------------------------------------------------------------
class KBArticleCreate(BaseModel):
    """
    Technical Spec §11.2:
      title   — max 255 chars
      content — max 10,000 chars (KB articles / ticket content limit)
    """
    model_config = ConfigDict(extra="forbid")

    category:     str  # CONFIG-1: validated against org config, not hardcoded enum
    title:        str                      = Field(..., max_length=255)
    content:      str                      = Field(..., max_length=10000)
    tags:         Optional[List[str]]      = None
    is_published: bool                     = True
    action_type: Literal["informational", "action_required"] = "informational"
    action_label: Optional[str] = None


class KBArticleUpdate(BaseModel):
    """
    All fields optional; content/title changes auto-increment version.
    Technical Spec §11.2: title max 255, content max 10,000 chars.
    """

    model_config = ConfigDict(extra="forbid")

    category:     Optional[str]       = None  # CONFIG-1: org config is source of truth
    title:        Optional[str]       = Field(None, max_length=255)
    content:      Optional[str]       = Field(None, max_length=10000)
    tags:         Optional[List[str]] = None
    is_published: Optional[bool]      = None
    action_type: Optional[Literal["informational", "action_required"]] = None
    action_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Interaction log models
# ---------------------------------------------------------------------------
class InteractionLogCreate(BaseModel):
    """
    POST /interaction-logs — logged_by is always derived from the JWT,
    never sent in the payload.
    """

    model_config = ConfigDict(extra="forbid")

    lead_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    ticket_id: Optional[UUID] = None
    interaction_type: str
    duration_minutes: Optional[int] = None
    outcome: Optional[str]   = Field(None, max_length=100)   # S3: matches DB varchar(100)
    raw_notes: Optional[str] = Field(None, max_length=5000)  # S4: free text field
    interaction_date: datetime

    @field_validator("interaction_type")
    @classmethod
    def validate_interaction_type(cls, v: str) -> str:
        if v not in INTERACTION_TYPES:
            raise ValueError(
                f"interaction_type must be one of {sorted(INTERACTION_TYPES)}"
            )
        return v
