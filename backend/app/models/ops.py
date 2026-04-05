"""
app/models/ops.py
Operations Intelligence Pydantic models — Phase 6A.

Routes:
  GET  /api/v1/dashboard/metrics  — executive dashboard metrics
  POST /api/v1/ask                — ask-your-data (Claude Sonnet)

§11.2: free-text fields capped at max_length.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DashboardMetrics(BaseModel):
    """
    Aggregated executive dashboard metrics — scoped by org and caller role.
    Revenue fields (mrr_ngn, revenue_at_risk_ngn) are None unless the caller
    has the view_revenue permission (owner / admin by default).
    """

    # ── Leads ─────────────────────────────────────────────────────────────────
    leads_total: int = 0
    leads_this_week: int = 0

    # ── Customers ─────────────────────────────────────────────────────────────
    active_customers: int = 0

    # ── Revenue (view_revenue permission required) ────────────────────────────
    mrr_ngn: Optional[float] = None
    revenue_at_risk_ngn: Optional[float] = None

    # ── Tickets ───────────────────────────────────────────────────────────────
    open_tickets: int = 0
    sla_breached_tickets: int = 0

    # ── Churn ─────────────────────────────────────────────────────────────────
    churn_risk_high: int = 0
    churn_risk_critical: int = 0

    # ── Renewals ──────────────────────────────────────────────────────────────
    renewals_due_30_days: int = 0

    # ── NPS ───────────────────────────────────────────────────────────────────
    nps_average: Optional[float] = None

    # ── Tasks (task module deferred to Phase 6B+) ─────────────────────────────
    overdue_tasks: int = 0


class AskRequest(BaseModel):
    """
    POST /api/v1/ask — ask-your-data natural language query.
    §12.5: free-form question capped at 1,000 characters.
    §11.2: max_length enforced.
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language question about the organisation's data.",
    )