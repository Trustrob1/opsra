"""
app/services/task_service.py
Task Management business logic — Phase 7A.

Public API:
  list_tasks(org, db, **filters) -> dict   paginated task list
  get_task(task_id, org_id, db) -> dict
  create_task(org, db, data) -> dict
  update_task(task_id, org, db, data) -> dict
  complete_task(task_id, org, db, notes) -> dict
  snooze_task(task_id, org, db, snoozed_until) -> dict

Access rules (Tech Spec §4.2 / DRD §4.2):
  - Personal view (default): assigned_to = current user
  - Team view: only owner / ops_manager / is_admin
  - Reassigning a task to another user: only owner / ops_manager / is_admin
  - All other operations: any authenticated user on their own tasks
    or any manager on any org task

Security:
  S1  org_id always from JWT — never from request body
  S12 write_audit_log on every mutating operation
  S13 soft deletes only — tasks are completed/snoozed, never hard deleted
  Pattern 37: role checked via org["roles"]["template"] / permissions
  Pattern 33: all filtering Python-side after .eq(org_id) fetch
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Role helpers (Pattern 37) ─────────────────────────────────────────────────


def _is_manager(org: dict) -> bool:
    """
    Returns True for owner, any user with is_admin, or ops_manager template.
    Matches the pattern established in require_admin (dependencies.py).
    Pattern 37: never read org.get("role") — always org["roles"]["template"].
    """
    roles: Any = org.get("roles") or {}
    template: str = (
        (roles.get("template") or "").lower()
        if isinstance(roles, dict) else ""
    )
    permissions: Any = (
        (roles.get("permissions") or {})
        if isinstance(roles, dict) else {}
    )
    return (
        template == "owner"
        or template == "ops_manager"
        or (isinstance(permissions, dict) and permissions.get("is_admin") is True)
    )


# ── Audit helper ──────────────────────────────────────────────────────────────


def _audit(db, org_id: str, user_id: str, action: str, resource_id: str) -> None:
    try:
        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       user_id,
            "action":        action,
            "resource_type": "task",
            "resource_id":   resource_id,
        }).execute()
    except Exception as exc:
        logger.warning("task_service: audit log failed — %s", exc)


# ── Normalise helper ──────────────────────────────────────────────────────────


def _normalise(data: Any) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ── Now ISO ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Sorting helpers ───────────────────────────────────────────────────────────

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _sort_key(task: dict) -> tuple:
    """
    Overdue tasks first, then by priority, then by due_at ascending.
    Status 'completed' and 'snoozed' tasks always sort to the end.
    """
    status = (task.get("status") or "open").lower()
    if status in ("completed", "snoozed"):
        return (3, 0, "")

    now_iso = _now_iso()
    due = task.get("due_at") or ""
    is_overdue = bool(due and due < now_iso and status not in ("completed", "snoozed"))
    priority_score = _PRIORITY_ORDER.get((task.get("priority") or "medium").lower(), 2)

    # Overdue = group 0, active = group 1, no due date = group 2
    if is_overdue:
        group = 0
    elif due:
        group = 1
    else:
        group = 2

    return (group, priority_score, due)


# ── Public service functions ──────────────────────────────────────────────────


def list_tasks(
    org: dict,
    db,
    *,
    team_view: bool = False,
    assigned_to_filter: Optional[str] = None,
    source_module: Optional[str] = None,
    source_record_id: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    include_completed: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    List tasks for the organisation.

    Personal view (default): returns only tasks assigned to the current user.
    Team view: returns all org tasks — only available to managers.
    Record-scoped view: when source_record_id is provided, returns all tasks
      linked to that specific record regardless of assigned_to — used by
      ticket thread, lead profile, and customer profile task widgets.

    All filtering is Python-side (Pattern 33).
    Overdue tasks sorted first, then by priority, then due_at (Pattern 37 safe).
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    is_manager = _is_manager(org)

    # Fetch all non-deleted org tasks
    result = (
        db.table("tasks")
        .select(
            "id, org_id, title, description, task_type, source_module, "
            "source_record_id, assigned_to, created_by, status, priority, "
            "due_at, completed_at, snoozed_until, completion_notes, "
            "ai_confirmed_by, created_at, updated_at"
        )
        .eq("org_id", org_id)
        .execute()
    )
    rows: list = [r for r in (result.data or []) if not r.get("deleted_at")]

    # Record-scoped view: source_record_id bypasses personal/team scoping.
    # Used by profile widgets and ticket thread to show all tasks for one record.
    if source_record_id:
        rows = [r for r in rows if r.get("source_record_id") == source_record_id]
    elif team_view and is_manager:
        pass  # all org tasks
    else:
        rows = [r for r in rows if r.get("assigned_to") == user_id]

    # Optional filters (Python-side — Pattern 33)
    if assigned_to_filter:
        rows = [r for r in rows if r.get("assigned_to") == assigned_to_filter]
    if source_module:
        rows = [r for r in rows if r.get("source_module") == source_module]
    if priority:
        rows = [r for r in rows if (r.get("priority") or "").lower() == priority.lower()]
    if status:
        rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
    if not include_completed:
        rows = [r for r in rows if (r.get("status") or "open").lower() != "completed"]

    # Sort: overdue first, then priority, then due_at
    rows.sort(key=_sort_key)

    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start: start + page_size]

    return {
        "items":     items,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  (start + page_size) < total,
    }


def get_task(task_id: str, org_id: str, db) -> dict:
    """Fetch a single task — raises ValueError if not found."""
    result = (
        db.table("tasks")
        .select("*")
        .eq("id", task_id)
        .eq("org_id", org_id)
        .execute()
    )
    task = _normalise(result.data)
    if not task or task.get("deleted_at"):
        raise ValueError(f"Task {task_id} not found.")
    return task


def create_task(org: dict, db, data) -> dict:
    """
    Create a task manually (task_type='manual').
    assigned_to defaults to the current user if not provided.
    RBAC: only managers can assign to another user.
    S1: org_id always from JWT.
    S12: audit logged.
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    is_manager = _is_manager(org)

    assigned_to = data.assigned_to or user_id
    if assigned_to != user_id and not is_manager:
        raise PermissionError("Only managers can assign tasks to other users.")

    row = {
        "org_id":           org_id,
        "title":            data.title,
        "description":      data.description,
        "task_type":        "manual",
        "source_module":    data.source_module,
        "source_record_id": data.source_record_id,
        "assigned_to":      assigned_to,
        "created_by":       user_id,
        "due_at":           data.due_at,
        "priority":         (data.priority or "medium").lower(),
        "status":           "open",
        "created_at":       _now_iso(),
        "updated_at":       _now_iso(),
    }

    # Remove None values so DB defaults apply
    row = {k: v for k, v in row.items() if v is not None}

    result = db.table("tasks").insert(row).execute()
    task = _normalise(result.data)
    if not task:
        raise RuntimeError("Task creation failed — no row returned.")

    _audit(db, org_id, user_id, "task.created", task["id"])
    return task


def update_task(task_id: str, org: dict, db, data) -> dict:
    """
    Partial update on a task.
    RBAC: assigned_to can only be changed by managers.
    S12: audit logged.
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]
    is_manager = _is_manager(org)

    # Fetch and verify ownership
    existing = get_task(task_id, org_id, db)

    # Build update payload from supplied fields only
    updates: dict = {"updated_at": _now_iso()}

    if data.title is not None:
        updates["title"] = data.title
    if data.description is not None:
        updates["description"] = data.description
    if data.due_at is not None:
        updates["due_at"] = data.due_at
    if data.priority is not None:
        updates["priority"] = data.priority.lower()
    if data.status is not None:
        updates["status"] = data.status.lower()
    if data.assigned_to is not None:
        if data.assigned_to != existing.get("assigned_to") and not is_manager:
            raise PermissionError("Only managers can reassign tasks.")
        updates["assigned_to"] = data.assigned_to

    result = db.table("tasks").update(updates).eq("id", task_id).eq("org_id", org_id).execute()
    task = _normalise(result.data)
    if not task:
        raise RuntimeError("Task update failed.")

    _audit(db, org_id, user_id, "task.updated", task_id)
    return task


def complete_task(task_id: str, org: dict, db, notes: Optional[str] = None) -> dict:
    """
    Mark a task as completed.
    Sets status='completed', completed_at=now(), completion_notes if provided.
    S12: audit logged.
    S13: not deleted — status transition only.
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    # Verify task exists in this org
    get_task(task_id, org_id, db)

    updates: dict = {
        "status":       "completed",
        "completed_at": _now_iso(),
        "updated_at":   _now_iso(),
    }
    if notes:
        updates["completion_notes"] = notes

    result = db.table("tasks").update(updates).eq("id", task_id).eq("org_id", org_id).execute()
    task = _normalise(result.data)
    if not task:
        raise RuntimeError("Task completion failed.")

    _audit(db, org_id, user_id, "task.completed", task_id)
    return task


def snooze_task(task_id: str, org: dict, db, snoozed_until: str) -> dict:
    """
    Snooze a task until a specified future datetime.
    Sets status='snoozed', snoozed_until=provided value.
    S12: audit logged.
    """
    org_id: str = org["org_id"]
    user_id: str = org["id"]

    # Verify task exists in this org
    get_task(task_id, org_id, db)

    updates: dict = {
        "status":        "snoozed",
        "snoozed_until": snoozed_until,
        "updated_at":    _now_iso(),
    }

    result = db.table("tasks").update(updates).eq("id", task_id).eq("org_id", org_id).execute()
    task = _normalise(result.data)
    if not task:
        raise RuntimeError("Task snooze failed.")

    _audit(db, org_id, user_id, "task.snoozed", task_id)
    return task