"""
app/routers/internal_issues.py
OPS-1 — Internal Issue Tracker

Routes (static before parameterised — Pattern 53):
  GET    /internal-issues/summary   — counts by team + status (manager view)
  GET    /internal-issues           — list, filterable
  POST   /internal-issues           — create
  GET    /internal-issues/{id}      — single issue
  PATCH  /internal-issues/{id}      — update
  DELETE /internal-issues/{id}      — soft delete (owner/ops_manager only)

Security:
  Pattern 11 — JWT only (handled by get_current_org dependency)
  Pattern 12 — org_id never from payload, always from JWT via get_current_org
  Pattern 28 — get_current_org
  Pattern 62 — db via Depends(get_supabase)
  Pattern 53 — static routes before parameterised

No AI, no Celery workers, no WhatsApp hooks.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from datetime import datetime, timezone

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class IssueCreate(BaseModel):
    title: str
    description: Optional[str] = None
    team: str
    category: str
    priority: str = "medium"
    assigned_to: Optional[str] = None


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    team: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_manager(org: dict) -> bool:
    """True if the current user is owner or ops_manager."""
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _generate_reference(db, org_id: str) -> str:
    """Generate next ISS-NNN reference for this org."""
    result = (
        db.table("internal_issues")
        .select("reference")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        try:
            last_num = int(result.data[0]["reference"].split("-")[1])
            return f"ISS-{str(last_num + 1).zfill(3)}"
        except (IndexError, ValueError):
            pass
    return "ISS-001"


def _fetch_issue(db, issue_id: str, org_id: str) -> dict:
    """Fetch a single non-deleted issue. Raises 404 if not found."""
    result = (
        db.table("internal_issues")
        .select("*")
        .eq("id", issue_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Issue not found"},
        )
    data = result.data
    if isinstance(data, list):
        data = data[0]
    return data


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/internal-issues/summary")
def get_issues_summary(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Return issue counts by status and by team.
    All roles: scoped to own team unless owner/ops_manager.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    manager = _is_manager(org)

    query = (
        db.table("internal_issues")
        .select("status, team, created_at")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
    )
    if not manager:
        # non-managers scoped to their own team
        user_team = org.get("team") or ""
        if user_team:
            query = query.eq("team", user_team)
        else:
            # user has no team — return empty summary
            return ok(data={"by_status": {}, "by_team": {}, "overdue": 0})

    result = query.execute()
    issues = result.data or []

    by_status = {"open": 0, "in_progress": 0, "resolved": 0}
    by_team: dict = {}
    overdue = 0

    cutoff = datetime.now(timezone.utc)

    for iss in issues:
        s = iss.get("status", "open")
        if s in by_status:
            by_status[s] += 1

        t = iss.get("team", "")
        if t not in by_team:
            by_team[t] = {"open": 0, "in_progress": 0, "resolved": 0}
        if s in by_team[t]:
            by_team[t][s] += 1

        # Overdue: unresolved + older than 7 days
        if s != "resolved":
            try:
                created = datetime.fromisoformat(iss["created_at"].replace("Z", "+00:00"))
                if (cutoff - created).days >= 7:
                    overdue += 1
            except Exception:
                pass

    return ok(data={"by_status": by_status, "by_team": by_team, "overdue": overdue})


@router.get("/internal-issues")
def list_issues(
    team: Optional[str] = None,
    status_filter: Optional[str] = None,
    assigned_to: Optional[str] = None,
    reported_by: Optional[str] = None,
    priority: Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: List issues. Non-managers scoped to own team.
    Filterable by team, status, assigned_to, reported_by, priority.
    """
    org_id = org["org_id"]
    manager = _is_manager(org)

    query = (
        db.table("internal_issues")
        .select("*, reporter:reported_by(id, full_name), assignee:assigned_to(id, full_name)")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
    )

    if not manager:
        user_team = org.get("team") or ""
        query = query.eq("team", user_team)
    elif team:
        query = query.eq("team", team)

    if status_filter:
        query = query.eq("status", status_filter)
    if assigned_to:
        query = query.eq("assigned_to", assigned_to)
    if reported_by:
        query = query.eq("reported_by", reported_by)
    if priority:
        query = query.eq("priority", priority)

    result = query.execute()
    issues = result.data or []
    if isinstance(issues, dict):
        issues = [issues]

    return ok(data={"items": issues, "total": len(issues)})


@router.post("/internal-issues")
def create_issue(
    payload: IssueCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Create a new internal issue.
    reported_by always set from current user — never from payload.
    """
    org_id = org["org_id"]
    user_id = org["id"]

    if not payload.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Title is required"},
        )
    if not payload.team.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Team is required"},
        )
    if not payload.category.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Category is required"},
        )

    reference = _generate_reference(db, org_id)

    row = {
        "org_id":      org_id,
        "reference":   reference,
        "title":       payload.title.strip(),
        "description": payload.description,
        "team":        payload.team.strip(),
        "category":    payload.category.strip(),
        "priority":    payload.priority,
        "status":      "open",
        "reported_by": user_id,
        "assigned_to": payload.assigned_to or None,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }

    result = db.table("internal_issues").insert(row).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else row

    return ok(data=data, message="Issue created")


@router.get("/internal-issues/{issue_id}")
def get_issue(
    issue_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """OPS-1: Get a single issue by ID."""
    org_id = org["org_id"]
    manager = _is_manager(org)
    issue = _fetch_issue(db, issue_id, org_id)

    # Non-managers can only view issues from their own team
    if not manager:
        user_team = org.get("team") or ""
        if issue.get("team") != user_team:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "Access denied"},
            )

    return ok(data=issue)


@router.patch("/internal-issues/{issue_id}")
def update_issue(
    issue_id: str,
    payload: IssueUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Update an issue.
    Managers can update any field on any issue in their org.
    Non-managers can update status/resolution_notes on issues assigned to them.
    auto-sets resolved_at when status → resolved; clears it when status reverts.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    manager = _is_manager(org)
    issue = _fetch_issue(db, issue_id, org_id)

    # RBAC: non-manager can only update their assigned issues
    if not manager:
        if issue.get("assigned_to") != user_id and issue.get("reported_by") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You can only update issues assigned to or reported by you"},
            )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    # Auto-manage resolved_at
    new_status = update_data.get("status")
    if new_status == "resolved" and not issue.get("resolved_at"):
        update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    elif new_status in ("open", "in_progress") and issue.get("resolved_at"):
        update_data["resolved_at"] = None

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("internal_issues")
        .update(update_data)
        .eq("id", issue_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Issue updated")


@router.delete("/internal-issues/{issue_id}")
def delete_issue(
    issue_id: str,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """OPS-1: Soft-delete an issue. Owner/ops_manager only."""
    org_id = org["org_id"]

    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can delete issues"},
        )

    _fetch_issue(db, issue_id, org_id)  # confirms exists and belongs to org

    db.table("internal_issues").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", issue_id).eq("org_id", org_id).execute()

    return ok(data={"id": issue_id}, message="Issue deleted")
