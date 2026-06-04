"""
app/routers/activity_logs.py
OPS-1 — Daily / Weekly Activity Log

Routes (static before parameterised — Pattern 53):
  GET    /activity-logs/summary   — weekly rollup per team member (manager view)
  POST   /activity-logs           — create or update (upsert on unique key)
  GET    /activity-logs           — list, filterable
  PATCH  /activity-logs/{id}      — edit own log only

Security:
  Pattern 11 — JWT only
  Pattern 12 — org_id, user_id, team never from payload — always from JWT
  Pattern 28 — get_current_org
  Pattern 53 — static routes before parameterised
  Pattern 62 — db via Depends(get_supabase)

No AI, no Celery workers, no WhatsApp hooks.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from pydantic import BaseModel
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok
from datetime import datetime, timezone, timedelta, date

router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class ActivityLogCreate(BaseModel):
    log_date: str        # ISO date string "YYYY-MM-DD"
    log_type: str = "daily"
    activities: str
    blockers: Optional[str] = None
    plan: Optional[str] = None


class ActivityLogUpdate(BaseModel):
    activities: Optional[str] = None
    blockers: Optional[str] = None
    plan: Optional[str] = None


class ActivityEntry(BaseModel):
    activity_description: str
    activity_type:        str = "General"
    duration_minutes:     Optional[int] = None
    has_blocker:          bool = False
    blocker_note:         Optional[str] = None
    plan:                 Optional[str] = None


class ActivityLogBulkCreate(BaseModel):
    log_date:  str
    log_type:  str = "daily"
    entries:   list[ActivityEntry]

# ── Helper ────────────────────────────────────────────────────────────────────

def _is_manager(org: dict) -> bool:
    template = (org.get("roles") or {}).get("template", "").lower()
    return template in ("owner", "ops_manager")


def _week_start(iso_date: str) -> str:
    """Return the ISO Monday of the week containing iso_date."""
    d = date.fromisoformat(iso_date)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/activity-logs/summary")
def get_activity_logs_summary(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Weekly summary — lists all team members and their log activity
    for the current week. Owner/ops_manager only.
    """
    if not _is_manager(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Manager access required"},
        )

    org_id = org["org_id"]
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (today + timedelta(days=6 - today.weekday())).isoformat()

    # Fetch all active users in the org with their team
    users_result = (
        db.table("users")
        .select("id, full_name, team")
        .eq("org_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    users = users_result.data or []
    if isinstance(users, dict):
        users = [users]

    # Fetch logs for this week
    logs_result = (
        db.table("activity_logs")
        .select("user_id, log_date, log_type")
        .eq("org_id", org_id)
        .gte("log_date", week_start)
        .lte("log_date", week_end)
        .execute()
    )
    logs = logs_result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    # Build a lookup: user_id → { daily_count, has_weekly, latest_date }
    log_map: dict = {}
    for log in logs:
        uid = log["user_id"]
        if uid not in log_map:
            log_map[uid] = {"daily_count": 0, "has_weekly": False, "latest_date": None}
        if log["log_type"] == "weekly":
            log_map[uid]["has_weekly"] = True
        else:
            log_map[uid]["daily_count"] += 1
        ld = log["log_date"]
        if not log_map[uid]["latest_date"] or ld > log_map[uid]["latest_date"]:
            log_map[uid]["latest_date"] = ld

    members = []
    for u in users:
        uid = u["id"]
        entry = log_map.get(uid, {})
        members.append({
            "user_id":        uid,
            "full_name":      u.get("full_name", ""),
            "team":           u.get("team") or "",
            "logs_this_week": entry.get("daily_count", 0),
            "has_weekly_log": entry.get("has_weekly", False),
            "latest_log_date": entry.get("latest_date"),
        })

    return ok(data={"week_start": week_start, "members": members})


@router.post("/activity-logs")
def submit_activity_log(
    payload: ActivityLogCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Submit a daily or weekly log.
    Upserts on (org_id, user_id, log_date, log_type) unique key.
    user_id and team are always set from current user — never from payload.
    For weekly logs, log_date is normalised to the Monday of that week.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    user_team = org.get("team") or ""

    if not payload.activities.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "Activities field is required"},
        )

    # Normalise weekly log_date to Monday of that week
    log_date = payload.log_date
    if payload.log_type == "weekly":
        log_date = _week_start(log_date)

    now = datetime.now(timezone.utc).isoformat()

    # Check for existing log (upsert logic)
    existing = (
        db.table("activity_logs")
        .select("id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("log_date", log_date)
        .eq("log_type", payload.log_type)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data
    if isinstance(existing_data, list):
        existing_data = existing_data[0] if existing_data else None

    update_fields = {
        "activities": payload.activities.strip(),
        "blockers":   payload.blockers or None,
        "plan":       payload.plan or None,
        "updated_at": now,
    }

    if existing_data:
        result = (
            db.table("activity_logs")
            .update(update_fields)
            .eq("id", existing_data["id"])
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else update_fields
        return ok(data=data, message="Activity log updated")
    else:
        row = {
            "org_id":     org_id,
            "user_id":    user_id,
            "log_date":   log_date,
            "log_type":   payload.log_type,
            "team":       user_team,
            "created_at": now,
            **update_fields,
        }
        result = db.table("activity_logs").insert(row).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else row
        return ok(data=data, message="Activity log submitted")

@router.post("/activity-logs/bulk")
def submit_activity_log_bulk(
    payload: ActivityLogBulkCreate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Submit multiple activity entries for a single day/week.
    Upserts on (org_id, user_id, log_date, log_type).
    Stores structured entries in the `entries` JSONB column.
    Generates a plain-text summary in `activities` for backwards compatibility.
    """
    org_id    = org["org_id"]
    user_id   = org["id"]
    user_team = org.get("team") or ""

    if not payload.entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "At least one activity entry is required"},
        )

    valid_entries = [e for e in payload.entries if e.activity_description.strip()]
    if not valid_entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "At least one activity description is required"},
        )

    log_date = payload.log_date
    if payload.log_type == "weekly":
        log_date = _week_start(log_date)

    # Build plain-text summary for backwards compatibility
    activities_text = "\n".join(
        f"[{e.activity_type}] {e.activity_description.strip()}"
        + (f" ({e.duration_minutes}h)" if e.duration_minutes else "")
        for e in valid_entries
    )
    blockers_text = "\n".join(
        e.blocker_note for e in valid_entries
        if e.has_blocker and e.blocker_note
    ) or None
    plan_text = next(
        (e.plan for e in reversed(valid_entries) if e.plan and e.plan.strip()),
        None
    )

    entries_json = [
        {
            "activity_description": e.activity_description.strip(),
            "activity_type":        e.activity_type,
            "duration_minutes":     e.duration_minutes,
            "has_blocker":          e.has_blocker,
            "blocker_note":         e.blocker_note if e.has_blocker else None,
            "plan":                 e.plan or None,
        }
        for e in valid_entries
    ]

    now = datetime.now(timezone.utc).isoformat()

    existing = (
        db.table("activity_logs")
        .select("id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .eq("log_date", log_date)
        .eq("log_type", payload.log_type)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data
    if isinstance(existing_data, list):
        existing_data = existing_data[0] if existing_data else None

    update_fields = {
        "activities": activities_text,
        "blockers":   blockers_text,
        "plan":       plan_text,
        "entries":    entries_json,
        "updated_at": now,
    }

    if existing_data:
        result = (
            db.table("activity_logs")
            .update(update_fields)
            .eq("id", existing_data["id"])
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else update_fields
        return ok(data=data, message="Activity log updated")
    else:
        row = {
            "org_id":     org_id,
            "user_id":    user_id,
            "log_date":   log_date,
            "log_type":   payload.log_type,
            "team":       user_team,
            "created_at": now,
            **update_fields,
        }
        result = db.table("activity_logs").insert(row).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else row
        return ok(data=data, message="Activity log submitted")


@router.get("/activity-logs")
def list_activity_logs(
    user_id_filter: Optional[str] = None,
    team: Optional[str] = None,
    log_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: List activity logs.
    Non-managers see only their own logs.
    Managers can filter by user_id or team.
    """
    org_id = org["org_id"]
    current_user_id = org["id"]
    manager = _is_manager(org)

    query = (
        db.table("activity_logs")
        .select("*, user:user_id(id, full_name, team)")
        .eq("org_id", org_id)
        .order("log_date", desc=True)
    )

    if not manager:
        # Non-managers always see only their own logs
        query = query.eq("user_id", current_user_id)
    elif user_id_filter:
        query = query.eq("user_id", user_id_filter)
    elif team:
        query = query.eq("team", team)

    if log_type:
        query = query.eq("log_type", log_type)
    if date_from:
        query = query.gte("log_date", date_from)
    if date_to:
        query = query.lte("log_date", date_to)

    result = query.execute()
    logs = result.data or []
    if isinstance(logs, dict):
        logs = [logs]

    return ok(data={"items": logs, "total": len(logs)})


@router.patch("/activity-logs/{log_id}")
def update_activity_log(
    log_id: str,
    payload: ActivityLogUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    OPS-1: Edit an activity log.
    Users can only edit their own logs.
    """
    org_id = org["org_id"]
    user_id = org["id"]

    existing = (
        db.table("activity_logs")
        .select("*")
        .eq("id", log_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    log_data = existing.data
    if isinstance(log_data, list):
        log_data = log_data[0] if log_data else None

    if not log_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Activity log not found"},
        )

    # Only the owner of the log can edit it
    if log_data.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "You can only edit your own activity logs"},
        )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("activity_logs")
        .update(update_data)
        .eq("id", log_id)
        .eq("org_id", org_id)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else update_data

    return ok(data=data, message="Activity log updated")
