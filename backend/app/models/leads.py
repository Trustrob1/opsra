"""
app/models/leads.py
Pydantic V2 models for Module 01 — Leads.
All fields match the leads and lead_timeline table schema in Technical Spec Section 3.2.
Enums match the values specified in Section 3.2 and Section 4.1.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


# ---------------------------------------------------------------------------
# Enums — exact values from Technical Spec Section 3.2 / 4.1
# ---------------------------------------------------------------------------

class LeadSource(str, Enum):
    facebook_ad = "facebook_ad"
    instagram_ad = "instagram_ad"
    landing_page = "landing_page"
    whatsapp_inbound = "whatsapp_inbound"
    manual_phone = "manual_phone"
    manual_referral = "manual_referral"
    import_ = "import"  # 'import' is a Python keyword — use import_ internally

    @classmethod
    def _missing_(cls, value: str):  # type: ignore[override]
        # allow the raw string "import" from the DB / JSON
        if value == "import":
            return cls.import_
        return None


class LeadScore(str, Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"
    unscored = "unscored"


class LeadStage(str, Enum):
    new = "new"
    contacted = "contacted"
    meeting_done = "meeting_done"
    proposal_sent = "proposal_sent"
    converted = "converted"
    lost = "lost"
    not_ready = "not_ready"


class LostReason(str, Enum):
    not_ready = "not_ready"
    price = "price"
    competitor = "competitor"
    wrong_size = "wrong_size"
    wrong_contact = "wrong_contact"
    other = "other"


class LeadBranches(str, Enum):
    one = "1"
    two_three = "2-3"
    four_ten = "4-10"
    ten_plus = "10+"

class LeadContactType(str, Enum):
    sales_lead        = "sales_lead"        # enters qualification pipeline
    business_inquiry  = "business_inquiry"  # routed to a role, no qualification
    support_contact   = "support_contact"   # unknown identifier, team follow-up
    other             = "other"             # free-form, rep notified

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Required
    full_name: str
    source: LeadSource

    # Optional — all nullable in DB
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    location: Optional[str] = None
    branches: Optional[LeadBranches] = None
    problem_stated: Optional[str] = None
    referrer: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_ad: Optional[str] = None
    assigned_to: Optional[str] = None
    contact_type: Optional[str] = LeadContactType.sales_lead.value

    @field_validator("source", mode="before")
    @classmethod
    def _coerce_source(cls, v: Any) -> Any:
        # Accept "import" string from JSON
        if v == "import":
            return "import"
        return v


class LeadUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    location: Optional[str] = None
    branches: Optional[LeadBranches] = None
    problem_stated: Optional[str] = None
    referrer: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_ad: Optional[str] = None
    assigned_to: Optional[str] = None
    contact_type: Optional[str] = None
    reengagement_date: Optional[date] = None


class MoveStageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    new_stage: LeadStage


class MarkLostRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    lost_reason: LostReason           # required — Technical Spec Section 4.1
    reengagement_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class LeadResponse(BaseModel):
    """Full lead record — mirrors the leads table from Section 3.2."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    full_name: str
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    location: Optional[str] = None
    branches: Optional[str] = None
    problem_stated: Optional[str] = None
    source: str
    referrer: Optional[str] = None
    campaign_id: Optional[str] = None
    ad_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_ad: Optional[str] = None
    score: str = "unscored"
    score_reason: Optional[str] = None
    stage: str = "new"
    lost_reason: Optional[str] = None
    reengagement_date: Optional[date] = None
    assigned_to: Optional[str] = None
    contact_type: str = "sales_lead"
    previous_lead_id: Optional[str] = None
    converted_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LeadTimelineEntry(BaseModel):
    """Mirrors the lead_timeline table from Technical Spec Section 3.2."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    lead_id: str
    event_type: str
    actor_id: Optional[str] = None
    description: str
    metadata: Optional[dict] = None
    created_at: Optional[datetime] = None


class LeadImportStatus(BaseModel):
    """Returned by GET /api/v1/leads/import/{job_id}."""
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str                      # pending | processing | completed | failed
    total_rows: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[dict] = []          # per-row errors: {row, field, message}
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None