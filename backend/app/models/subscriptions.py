"""
app/models/subscriptions.py
Pydantic models and domain constants for Module 04 — Renewal & Upsell Engine.

Constants match Technical Spec Section 3.5 (subscriptions + payments tables).
Status transitions from Technical Spec Section 4.3.
Field length constraints per Technical Spec §11.2.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Domain constants — Technical Spec Section 3.5
# ---------------------------------------------------------------------------

SUBSCRIPTION_STATUSES: frozenset[str] = frozenset({
    "trial",
    "active",
    "grace_period",
    "expired",
    "suspended",
    "cancelled",
})

PLAN_TIERS: frozenset[str] = frozenset({
    "starter",
    "basic",
    "pro",
    "enterprise",
})

BILLING_CYCLES: frozenset[str] = frozenset({
    "monthly",
    "annual",
})

PAYMENT_METHODS: frozenset[str] = frozenset({
    "webhook",
    "manual",
    "csv_upload",
    "whatsapp",
})

PAYMENT_CHANNELS: frozenset[str] = frozenset({
    "bank_transfer",
    "card",
    "cash",
    "ussd",
    "pos",
    "paystack",
    "flutterwave",
})

PAYMENT_STATUSES: frozenset[str] = frozenset({
    "confirmed",
    "failed",
    "pending_confirmation",
})

CANCELLATION_REASONS: frozenset[str] = frozenset({
    "too_expensive",
    "switching_competitor",
    "business_closed",
    "missing_features",
    "poor_support",
    "other",
})

# ---------------------------------------------------------------------------
# Request models — all free-text fields have max_length per §11.2
# ---------------------------------------------------------------------------


class SubscriptionUpdate(BaseModel):
    """
    Admin-only — update subscription plan and billing details.
    Technical Spec §8.4 — PATCH /api/v1/subscriptions/{id}.
    """
    plan_name: Optional[str] = Field(None, max_length=100)
    plan_tier: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    billing_cycle: Optional[str] = None
    current_period_start: Optional[date] = None
    current_period_end: Optional[date] = None

    @field_validator("plan_tier")
    @classmethod
    def validate_plan_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PLAN_TIERS:
            raise ValueError(f"plan_tier must be one of: {sorted(PLAN_TIERS)}")
        return v

    @field_validator("billing_cycle")
    @classmethod
    def validate_billing_cycle(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in BILLING_CYCLES:
            raise ValueError(f"billing_cycle must be one of: {sorted(BILLING_CYCLES)}")
        return v


class ConfirmPaymentRequest(BaseModel):
    """
    Manual payment confirmation — Method 2 (DRD §6.4).
    POST /api/v1/subscriptions/{id}/confirm-payment.
    """
    amount: float = Field(..., gt=0, description="Payment amount in NGN")
    payment_date: date = Field(..., description="Actual date payment was received")
    payment_channel: str = Field(..., description="Channel through which payment was made")
    reference: Optional[str] = Field(None, max_length=255, description="Payment reference number")
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("payment_channel")
    @classmethod
    def validate_payment_channel(cls, v: str) -> str:
        if v not in PAYMENT_CHANNELS:
            raise ValueError(f"payment_channel must be one of: {sorted(PAYMENT_CHANNELS)}")
        return v


class CancelSubscriptionRequest(BaseModel):
    """
    CEO-only subscription cancellation — requires reason.
    POST /api/v1/subscriptions/{id}/cancel.
    DRD: Cancellation requires CEO approval — no subscription cancelled without authorisation.
    """
    reason: str = Field(..., description="Reason for cancellation")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if v not in CANCELLATION_REASONS:
            raise ValueError(f"reason must be one of: {sorted(CANCELLATION_REASONS)}")
        return v


class BulkConfirmRow(BaseModel):
    """
    Single row parsed from a bulk payment confirmation CSV/Excel file.
    Method 3 — CSV/Excel Bulk Upload (DRD §6.4).
    At least one of phone or subscription_id must be present (validated in service).
    """
    phone: Optional[str] = Field(None, max_length=20)
    subscription_id: Optional[str] = None
    amount: float = Field(..., gt=0)
    payment_date: date
    payment_channel: str
    reference: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("payment_channel")
    @classmethod
    def validate_payment_channel(cls, v: str) -> str:
        if v not in PAYMENT_CHANNELS:
            raise ValueError(f"payment_channel must be one of: {sorted(PAYMENT_CHANNELS)}")
        return v