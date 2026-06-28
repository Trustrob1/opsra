"""
app/models/project_planner_models.py — Pydantic models for PROJECT-PLANNER v2.

Conventions (matching app/models/leads.py, app/models/whatsapp.py):
  - Field(..., max_length=...) on every free-text field (S4)
  - Field(None, pattern="^(...)$") for enum-like string fields
  - org_id is NEVER a field on any Create/Update model — it always comes
    from get_current_org in the router, never from the request body (S1)
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class PlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class PlanUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class StrategyCreate(BaseModel):
    plan_id: str = Field(..., description="UUID of the parent project plan")
    phase: int = Field(1, ge=1, le=4)
    channel: str = Field("online", pattern="^(online|offline)$")
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)


class StrategyUpdate(BaseModel):
    phase: Optional[int] = Field(None, ge=1, le=4)
    channel: Optional[str] = Field(None, pattern="^(online|offline)$")
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    included: Optional[bool] = None
    detail_link: Optional[str] = Field(None, max_length=2000)
    position: Optional[int] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Phases & Tasks
# ---------------------------------------------------------------------------

class PhaseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    sub_label: Optional[str] = Field(None, max_length=120)
    position: int = Field(0, ge=0)


class PhaseUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    sub_label: Optional[str] = Field(None, max_length=120)


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    owner_user_id: Optional[str] = Field(None, description="UUID of an Opsra user, if assigned to a teammate")
    owner_label: Optional[str] = Field(None, max_length=120, description="Free-text owner name, if not a real Opsra user")
    due_date: Optional[str] = Field(None, description="ISO date, e.g. 2026-07-01")


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, max_length=5000)
    owner_user_id: Optional[str] = None
    owner_label: Optional[str] = Field(None, max_length=120)
    due_date: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(not_started|in_progress|done|blocked)$")
    position: Optional[int] = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Strategy documents (Storage upload + external link)
# ---------------------------------------------------------------------------

class DocumentLinkSet(BaseModel):
    external_link: str = Field(..., max_length=2000)
