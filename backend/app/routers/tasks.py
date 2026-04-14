"""
app/routers/tasks.py
Task Management routes — Phase 7A (updated M01-9b).

Routes (prefix /api/v1 set in main.py):
  GET    /api/v1/tasks                    — list tasks (personal or team view)
  POST   /api/v1/tasks                    — create task manually
  GET    /api/v1/tasks/{id}               — get single task
  PATCH  /api/v1/tasks/{id}               — update task
  DELETE /api/v1/tasks/{id}               — soft-delete (archive) task  NEW M01-9b
  POST   /api/v1/tasks/{id}/complete      — mark complete
  POST   /api/v1/tasks/{id}/snooze        — snooze task
  POST   /api/v1/tasks/{id}/restore       — restore archived task        NEW M01-9b

Pattern 28: get_current_org on every route.
Pattern 37: RBAC via service layer — never org.get("role").
Pattern 53: no static-vs-parameterised conflict here — all sub-paths
  (/complete, /snooze, /restore) appear as {id}/action, FastAPI matches
  them correctly because the action segment disambiguates.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.models.tasks import CompleteRequest, SnoozeRequest, TaskCreate, TaskUpdate
from app.services import task_service

router = APIRouter()


@router.get("/tasks")
async def list_tasks(
    team:             bool          = Query(False,  description="true = team view (managers only)"),
    assigned_to:      Optional[str] = Query(None,   description="Filter by user UUID (managers only)"),
    module:           Optional[str] = Query(None,   description="leads|whatsapp|support|renewal|ops"),
    source_record_id: Optional[str] = Query(None,   description="UUID — returns all tasks for this specific record"),
    priority:         Optional[str] = Query(None,   description="critical|high|medium|low"),
    status:           Optional[str] = Query(None,   description="open|in_progress|completed|snoozed|escalated"),
    completed:        bool          = Query(False,  description="Include completed tasks"),
    archived:         bool          = Query(False,  description="Show archived (soft-deleted) tasks only"),
    created_from:     Optional[str] = Query(None,   description="ISO datetime — filter by created_at >= value"),
    created_to:       Optional[str] = Query(None,   description="ISO datetime — filter by created_at <= value"),
    due_from:         Optional[str] = Query(None,   description="ISO datetime — filter by due_at >= value"),
    due_to:           Optional[str] = Query(None,   description="ISO datetime — filter by due_at <= value"),
    page:             int           = Query(1,       ge=1),
    page_size:        int           = Query(20,      ge=1, le=100),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """List tasks — personal view by default; team view for managers;
    record-scoped when source_record_id is supplied;
    archived view when archived=True."""
    result = task_service.list_tasks(
        org,
        db,
        team_view=team,
        assigned_to_filter=assigned_to,
        source_module=module,
        source_record_id=source_record_id,
        priority=priority,
        status=status,
        include_completed=completed,
        archived=archived,
        created_from=created_from,
        created_to=created_to,
        due_from=due_from,
        due_to=due_to,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post("/tasks", status_code=201)
async def create_task(
    data: TaskCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Create a task manually."""
    try:
        task = task_service.create_task(org, db, data)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ok(data=task, message="Task created")


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Get a single task by ID."""
    try:
        task = task_service.get_task(task_id, org["org_id"], db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ok(data=task)


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    data: TaskUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Update task fields. Reassigning to another user requires manager role."""
    try:
        task = task_service.update_task(task_id, org, db, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ok(data=task, message="Task updated")


@router.delete("/tasks/{task_id}", status_code=200)
async def delete_task(
    task_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Soft-delete (archive) a task.
    Sets deleted_at = now(). Task disappears from active list and appears
    in the Archived tab (GET /tasks?archived=true).
    RBAC: own task (created or assigned) or manager.
    """
    try:
        task = task_service.soft_delete_task(task_id, org, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ok(data=task, message="Task archived")


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    data: CompleteRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Mark a task as completed."""
    try:
        task = task_service.complete_task(task_id, org, db, notes=data.completion_notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ok(data=task, message="Task completed")


@router.post("/tasks/{task_id}/snooze")
async def snooze_task(
    task_id: str,
    data: SnoozeRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Snooze a task until the specified datetime."""
    try:
        task = task_service.snooze_task(task_id, org, db, snoozed_until=data.snoozed_until)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ok(data=task, message="Task snoozed")


@router.post("/tasks/{task_id}/restore")
async def restore_task(
    task_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Restore an archived task by clearing deleted_at.
    Task returns to its previous status (open/completed/snoozed).
    RBAC: own task (created or assigned) or manager.
    """
    try:
        task = task_service.restore_task(task_id, org, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ok(data=task, message="Task restored")