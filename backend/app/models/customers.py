"""
Pydantic models for Module 02 — Customer profiles.
All field names mirror the `customers` table in Technical Spec §3.3.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class CustomerCreate(BaseModel):
    """
    Manual customer creation.
    In practice, customers are usually created automatically by
    lead_service.convert_lead().  This model supports the rare
    manual-creation path and provides a typed contract for that service call.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    full_name: str = Field(..., max_length=255)
    # whatsapp is the primary comms channel and is NOT NULL in the schema
    whatsapp: str = Field(..., max_length=20)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    business_name: str = Field(..., max_length=255)
    business_type: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    branches: Optional[str] = Field(None, max_length=50)  # 1 | 2-3 | 4-10 | 10+
    assigned_to: Optional[UUID] = None
    lead_id: Optional[UUID] = None   # Source lead — carried over on conversion


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class CustomerUpdate(BaseModel):
    """
    Partial update for an existing customer record.
    All fields are optional — only provided fields are written to the DB.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    whatsapp: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    business_name: Optional[str] = Field(None, max_length=255)
    business_type: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    branches: Optional[str] = Field(None, max_length=50)
    assigned_to: Optional[UUID] = None
    whatsapp_opt_in: Optional[bool] = None
    whatsapp_opt_out_broadcasts: Optional[bool] = None
    onboarding_complete: Optional[bool] = None
    feature_adoption: Optional[dict] = None   # jsonb map of feature keys → bool
    updated_at: Optional[str] = None  # C7: optimistic concurrency token