"""
app/models/tasks.py
Task Management Pydantic models — Phase 7A.

Tech Spec §3.6 — tasks table columns confirmed against opsra_test:
  status default is 'open' (not 'pending' as in spec) — code matches actual DB.
  due_at is nullable in DB (spec says NOT NULL) — optional in create model.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

# ── Allowed value sets ────────────────────────────────────────────────────────

TASK_TYPES    = frozenset({"ai_recommended", "system_event", "manual"})
TASK_STATUSES = frozenset({"open", "in_progress", "completed", "snoozed", "escalated"})
TASK_PRIORITIES = frozenset({"critical", "high", "medium", "low"})
SOURCE_MODULES  = frozenset({"leads", "whatsapp", "support", "renewal", "ops"})


# ── Request models ─────────────────────────────────────────────────────────────


class TaskCreate(BaseModel):
    """
    POST /api/v1/tasks — manual task creation.
    task_type for manually created tasks is always 'manual'.
    """
    title:            str            = Field(..., min_length=1, max_length=255)
    description:      Optional[str]  = Field(None, max_length=5000)
    source_module:    Optional[str]  = Field(None)  # leads|whatsapp|support|renewal|ops
    source_record_id: Optional[str]  = None          # UUID of linked lead/customer/ticket
    assigned_to:      Optional[str]  = None          # UUID of user to assign; None = self
    due_at:           Optional[str]  = None          # ISO 8601 datetime string
    priority:         str            = Field("medium")


class TaskUpdate(BaseModel):
    """
    PATCH /api/v1/tasks/{id} — partial update.
    All fields optional — only supplied fields are written.
    RBAC: assigned_to can only be changed to another user by owner/ops_manager.
    """
    title:            Optional[str]  = Field(None, min_length=1, max_length=255)
    description:      Optional[str]  = Field(None, max_length=5000)
    assigned_to:      Optional[str]  = None
    due_at:           Optional[str]  = None
    priority:         Optional[str]  = None
    status:           Optional[str]  = None


class CompleteRequest(BaseModel):
    """
    POST /api/v1/tasks/{id}/complete
    completion_notes optional — staff can explain what was done.
    """
    completion_notes: Optional[str] = Field(None, max_length=5000)


class SnoozeRequest(BaseModel):
    """
    POST /api/v1/tasks/{id}/snooze
    snoozed_until required — must be a future ISO 8601 datetime.
    """
    snoozed_until: str = Field(..., description="ISO 8601 datetime — must be in the future")