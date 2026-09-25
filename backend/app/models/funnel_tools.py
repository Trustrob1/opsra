"""
app/models/funnel_tools.py
---------------------------
FUNNEL-1B — Pydantic models for the Event Funnel dashboard tools (S3/S4).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.funnels import FunnelMessages, FunnelStep

_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_TEMPLATE_RE = re.compile(r"^[a-z0-9_]{1,512}$")


class AdSpendRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    date: date
    ad_code: str = Field(..., min_length=1, max_length=12)
    amount: float = Field(..., ge=0, le=100_000_000)

    @field_validator("ad_code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _CODE_RE.match(v):
            raise ValueError("ad code must be letters/digits only (max 12)")
        return v.upper()


class AdSpendPut(BaseModel):
    rows: list[AdSpendRow] = Field(..., min_length=1, max_length=100)


class PreviewSample(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field("Ada Obi", max_length=100)
    hours_since_first: float = Field(0, ge=0, le=24 * 60)
    paid: bool = False
    email: Optional[str] = Field(None, max_length=255)


class PreviewRequest(BaseModel):
    """Render a message the way a lead would see it — from saved config, or from
    unsaved edits passed in `messages` / `sequence` (nothing is stored or sent)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    message_key: Optional[str] = Field(None, max_length=40)      # e.g. "greeting", "paid_confirmation"
    step_key: Optional[str] = Field(None, max_length=40)         # a sequence step
    text: Optional[str] = Field(None, max_length=1000)           # free text with placeholders
    messages: Optional[FunnelMessages] = None
    sequence: Optional[list[FunnelStep]] = Field(None, max_length=15)
    sample: PreviewSample = PreviewSample()


class BroadcastCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    template_name: str = Field(..., min_length=1, max_length=512)
    template_params: list[str] = Field(default_factory=list, max_length=10)
    language: str = Field("en", min_length=2, max_length=10)
    audience: Literal["unpaid", "paid", "all"] = "unpaid"
    ad_code: Optional[str] = Field(None, max_length=12)
    dry_run: bool = False      # True → only return recipient count + cost estimate

    @field_validator("template_name")
    @classmethod
    def _tpl(cls, v: str) -> str:
        if not _TEMPLATE_RE.match(v):
            raise ValueError("template name must be lowercase letters, digits, underscore")
        return v

    @field_validator("template_params")
    @classmethod
    def _params(cls, v: list[str]) -> list[str]:
        for p in v:
            if len(p) > 1000:
                raise ValueError("each template parameter must be at most 1000 characters")
        return v

    @field_validator("ad_code")
    @classmethod
    def _code(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if not _CODE_RE.match(v):
            raise ValueError("ad code must be letters/digits only (max 12)")
        return v.upper()
