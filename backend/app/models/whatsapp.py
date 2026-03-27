"""
Pydantic models for Module 02 — WhatsApp Communication Engine.
Field names mirror the Technical Spec §3.3 tables:
  whatsapp_messages, whatsapp_templates, broadcasts, drip_messages.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Constants — validated values from the schema
# ---------------------------------------------------------------------------

TEMPLATE_CATEGORIES: frozenset[str] = frozenset(
    {"marketing", "utility", "authentication"}
)

BROADCAST_STATUSES: frozenset[str] = frozenset(
    {"draft", "scheduled", "sending", "sent", "cancelled"}
)


# ---------------------------------------------------------------------------
# Message send request
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    """
    POST /api/v1/messages/send
    Exactly one of customer_id / lead_id must be provided.
    Exactly one of content / template_name must be provided.
    When the 24-hour conversation window is closed, template_name is required.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    # content — free-form text (requires open window)
    content: Optional[str] = None
    # template_name — approved WhatsApp template name (works even if window closed)
    template_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateCreate(BaseModel):
    """
    POST /api/v1/templates — create and submit a new template to Meta.
    category must be one of TEMPLATE_CATEGORIES.
    variables is the array of {{variable_name}} placeholders in body.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(..., max_length=100)
    category: str = Field(...)       # marketing | utility | authentication
    body: str = Field(...)
    variables: List[str] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """
    PATCH /api/v1/templates/{id} — edit a rejected template and resubmit.
    Only templates with meta_status = 'rejected' may be edited.
    After update, meta_status is reset to 'pending' automatically.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    body: Optional[str] = None
    variables: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------

class BroadcastCreate(BaseModel):
    """
    POST /api/v1/broadcasts — create a broadcast in draft status.
    scheduled_at = None means send immediately upon approval.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(..., max_length=255)
    template_id: UUID
    segment_filter: dict = Field(default_factory=dict)
    scheduled_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Drip sequences
# ---------------------------------------------------------------------------

class DripMessageConfig(BaseModel):
    """Single drip message in the sequence — mirrors drip_messages table."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(..., max_length=100)
    template_id: UUID
    delay_days: int = Field(..., ge=0)       # Days after conversion to send
    business_types: List[str] = Field(default_factory=list)  # [] = all types
    sequence_order: int = Field(..., ge=1)
    is_active: bool = True


class DripSequenceUpdate(BaseModel):
    """
    PUT /api/v1/drip-sequences — replace the org's entire drip configuration.
    Admin only.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: List[DripMessageConfig]