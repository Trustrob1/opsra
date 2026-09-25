"""
app/models/funnels.py
----------------------
FUNNEL-1 — Pydantic models for Event Funnels (S3/S4/S13).

Used by:
  • routers/funnels.py (create/update validation)
  • services/funnel_service.py + workers/funnel_worker.py (validate the stored
    jsonb config before acting on it — S13)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TEXT_MAX = 1000          # WhatsApp body limit is 1,024 — keep headroom for placeholders
_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_TEMPLATE_RE = re.compile(r"^[a-z0-9_]{1,512}$")

PricingMode = Literal["window", "deadline"]
FunnelStatus = Literal["draft", "active", "closed"]
StepAnchor = Literal["first_message", "window_end", "early_deadline", "event_start", "registration_close"]
StepAudience = Literal["unpaid", "paid", "all"]


def _https_or_none(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    v = v.strip()
    if not v.lower().startswith("https://") or len(v) > 500 or any(c.isspace() for c in v):
        raise ValueError("must be an https:// link")
    return v


class AdCode(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    code: str = Field(..., min_length=1, max_length=12)
    label: Optional[str] = Field(None, max_length=100)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _CODE_RE.match(v):
            raise ValueError("ad code must be letters/digits only (max 12)")
        return v.upper()


class FaqItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=20)     # WhatsApp reply-button title limit
    answer: str = Field(..., min_length=1, max_length=_TEXT_MAX)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("faq id must be lowercase letters, digits, underscore")
        return v


class FunnelMessages(BaseModel):
    """Every text supports the placeholders listed in funnel_service.PLACEHOLDERS."""
    model_config = ConfigDict(str_strip_whitespace=True)
    greeting: Optional[str] = Field(None, max_length=_TEXT_MAX)
    pay_button: Optional[str] = Field(None, max_length=20)          # e.g. "Pay {price}"
    faq_prompt: Optional[str] = Field(None, max_length=_TEXT_MAX)
    faq: Optional[list[FaqItem]] = Field(None, max_length=3)
    pay_link_resend: Optional[str] = Field(None, max_length=_TEXT_MAX)
    group_offer: Optional[str] = Field(None, max_length=_TEXT_MAX)
    paid_confirmation: Optional[str] = Field(None, max_length=_TEXT_MAX)
    already_paid: Optional[str] = Field(None, max_length=_TEXT_MAX)
    email_thanks: Optional[str] = Field(None, max_length=_TEXT_MAX)
    handoff_ack: Optional[str] = Field(None, max_length=_TEXT_MAX)
    closed: Optional[str] = Field(None, max_length=_TEXT_MAX)
    no_funnel: Optional[str] = Field(None, max_length=_TEXT_MAX)
    opted_out: Optional[str] = Field(None, max_length=_TEXT_MAX)


class FunnelStep(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    key: str = Field(..., min_length=1, max_length=40)
    anchor: StepAnchor
    offset_minutes: int = Field(..., ge=-60 * 24 * 30, le=60 * 24 * 30)
    audience: StepAudience = "unpaid"
    text: Optional[str] = Field(None, max_length=_TEXT_MAX)
    template_name: Optional[str] = Field(None, max_length=512)
    template_params: Optional[list[str]] = Field(None, max_length=10)
    only_if_early: bool = False
    include_pay_button: bool = False
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY_RE.match(v):
            raise ValueError("step key must be lowercase letters, digits, underscore")
        return v

    @field_validator("template_name")
    @classmethod
    def _tpl(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if not _TEMPLATE_RE.match(v):
            raise ValueError("template name must be lowercase letters, digits, underscore")
        return v

    @model_validator(mode="after")
    def _has_content(self):
        if not self.text and not self.template_name:
            raise ValueError("a step needs text, a template, or both")
        return self


class FunnelSettings(BaseModel):
    pause_minutes_after_reply: int = Field(60, ge=0, le=24 * 60)
    max_auto_per_day_after_window: int = Field(1, ge=0, le=5)
    respect_quiet_hours: bool = True
    stale_after_minutes: int = Field(360, ge=15, le=48 * 60)
    convert_on_paid: bool = False
    # FUNNEL-1B: dashboard pause flag + optional template budget cap
    pause_spend_threshold: float = Field(10000, ge=0, le=100_000_000)
    template_cost_estimate: Optional[float] = Field(None, gt=0, le=100_000)   # ₦ per template message
    template_budget_cap: Optional[float] = Field(None, gt=0, le=100_000_000)  # ₦ total; cap is ON only when both are set


class _FunnelBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    status: Optional[FunnelStatus] = None
    whatsapp_number_id: Optional[str] = Field(None, max_length=36)
    event_title: Optional[str] = Field(None, max_length=200)
    event_starts_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    pricing_mode: Optional[PricingMode] = None
    window_hours: Optional[int] = Field(None, ge=1, le=168)
    early_deadline_at: Optional[datetime] = None
    early_price: Optional[float] = Field(None, gt=0, le=10_000_000)
    regular_price: Optional[float] = Field(None, gt=0, le=10_000_000)
    group_size: Optional[int] = Field(None, ge=2, le=20)
    group_price: Optional[float] = Field(None, gt=0, le=10_000_000)
    paid_group_link: Optional[str] = None
    prep_group_link: Optional[str] = None
    bonus_link: Optional[str] = None
    ad_codes: Optional[list[AdCode]] = Field(None, max_length=20)
    messages: Optional[FunnelMessages] = None
    sequence: Optional[list[FunnelStep]] = Field(None, max_length=15)
    settings: Optional[FunnelSettings] = None

    @field_validator("paid_group_link", "prep_group_link", "bonus_link")
    @classmethod
    def _links(cls, v: Optional[str]) -> Optional[str]:
        return _https_or_none(v)

    @field_validator("sequence")
    @classmethod
    def _unique_keys(cls, v):
        if v:
            keys = [s.key for s in v]
            if len(keys) != len(set(keys)):
                raise ValueError("step keys must be unique")
        return v


class FunnelCreate(_FunnelBase):
    name: str = Field(..., min_length=1, max_length=120)
    event_title: str = Field(..., min_length=1, max_length=200)
    event_starts_at: datetime
    registration_closes_at: datetime
    pricing_mode: PricingMode = "window"
    early_price: float = Field(..., gt=0, le=10_000_000)
    regular_price: float = Field(..., gt=0, le=10_000_000)

    @model_validator(mode="after")
    def _check(self):
        if self.registration_closes_at > self.event_starts_at:
            raise ValueError("registration must close before the event starts")
        if self.pricing_mode == "deadline" and not self.early_deadline_at:
            raise ValueError("deadline mode needs early_deadline_at")
        if (self.group_size is None) != (self.group_price is None):
            raise ValueError("set both group_size and group_price, or neither")
        return self


class FunnelUpdate(_FunnelBase):
    pass


class GrantEarly(BaseModel):
    hours: int = Field(24, ge=1, le=48)


class ManualPaid(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    amount: float = Field(..., gt=0, le=10_000_000)
    seats: int = Field(1, ge=1, le=20)
    note: Optional[str] = Field(None, max_length=500)


class RegistrationPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: Optional[str] = Field(None, max_length=255)
    needs_human: Optional[bool] = None
    name: Optional[str] = Field(None, max_length=255)
