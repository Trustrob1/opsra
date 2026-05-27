"""
app/routers/report_analytics.py
Management Reports — RPT-1A.

Routes (all mounted under /api/v1 prefix in main.py):
  GET  /reports/full
  GET  /reports/download
  GET  /reports/sections
  GET  /reports/scheduled
  POST /reports/scheduled
  PATCH  /reports/scheduled/{report_id}
  DELETE /reports/scheduled/{report_id}

Pattern 53: static routes registered before parameterised.
Pattern 62: db via Depends(get_supabase) in route signature.
S1:  org_id extracted from JWT only — never from request body or query param.
RBAC: all routes require owner or ops_manager.
     POST / PATCH / DELETE /scheduled: owner only.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app.database import get_supabase
from app.routers.auth import get_current_org
from app.services.report_analytics_service import (
    get_full_report,
    generate_report_pdf,
    _resolve_period_preset,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Valid section keys (must match report_analytics_service._ALL_SECTIONS)
# ---------------------------------------------------------------------------

_VALID_SECTION_KEYS = frozenset({
    "executive_summary", "lead_pipeline", "revenue", "response_time",
    "rep_performance", "team_performance", "whatsapp", "support",
    "customer_health", "tasks", "lost_leads", "channel_roi",
})

_SECTION_LABELS = {
    "executive_summary": {
        "key": "executive_summary",
        "label": "Executive Summary",
        "description": "Top-level KPIs: revenue, leads, conversions, CAC, close time.",
    },
    "lead_pipeline": {
        "key": "lead_pipeline",
        "label": "Lead & Pipeline Performance",
        "description": "Leads by source and score, funnel breakdown, pipeline value, lost reasons.",
    },
    "revenue": {
        "key": "revenue",
        "label": "Revenue Summary",
        "description": "Revenue by source and team, weekly trend, average deal value.",
    },
    "response_time": {
        "key": "response_time",
        "label": "Response Time Analysis",
        "description": "First-response and average response times, SLA compliance, per-rep breakdown.",
    },
    "rep_performance": {
        "key": "rep_performance",
        "label": "Sales Rep Performance",
        "description": "Per-rep leads, conversions, revenue, response time, and task completion.",
    },
    "team_performance": {
        "key": "team_performance",
        "label": "Team Performance",
        "description": "Team-level leads, conversion rate, and revenue with period-over-period deltas.",
    },
    "whatsapp": {
        "key": "whatsapp",
        "label": "WhatsApp Activity",
        "description": "Messages sent, AI vs human split, reply rate, conversations opened.",
    },
    "support": {
        "key": "support",
        "label": "Support & Tickets",
        "description": "Tickets opened, resolved, escalated, resolution time, per-agent breakdown.",
    },
    "customer_health": {
        "key": "customer_health",
        "label": "Customer Health",
        "description": "Active customers, churn risk distribution, NPS scores.",
    },
    "tasks": {
        "key": "tasks",
        "label": "Task & Activity",
        "description": "Tasks created, completed, overdue, completion rate, per-rep breakdown.",
    },
    "lost_leads": {
        "key": "lost_leads",
        "label": "Lost Lead Analysis",
        "description": "Lost leads by reason, rep, and team with period comparison.",
    },
    "channel_roi": {
        "key": "channel_roi",
        "label": "Channel ROI",
        "description": "Per-channel leads, conversion rate, revenue, and ROI.",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _success(data) -> dict:
    return {"success": True, "data": data, "error": None}


def _require_reports_access(org: dict) -> None:
    """Allow owner and ops_manager only. Raises 403 otherwise."""
    roles    = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner or ops_manager access required"},
        )


def _require_owner(org: dict) -> None:
    """Allow owner only. Raises 403 otherwise."""
    roles    = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner access required"},
        )


def _resolve_dates(
    period_preset: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[str, str]:
    """
    Resolve date_from and date_to for a report request.
    Priority: explicit date_from + date_to > period_preset > default (last_30d).
    Raises 422 on invalid ISO date strings or unknown preset.
    """
    if date_from and date_to:
        try:
            date.fromisoformat(date_from)
            date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_DATE", "message": "date_from and date_to must be ISO date strings (YYYY-MM-DD)"},
            )
        return date_from, date_to

    preset = period_preset or "last_30d"
    if preset == "custom":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PRESET", "message": "Use date_from and date_to for custom ranges"},
        )
    try:
        return _resolve_period_preset(preset)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PRESET", "message": str(exc)},
        )


def _parse_sections(sections_param: Optional[str]) -> Optional[list[str]]:
    """
    Parse comma-separated sections query param.
    Returns None (all sections) if not provided.
    Raises 422 if any section key is invalid.
    """
    if not sections_param:
        return None
    keys = [s.strip() for s in sections_param.split(",") if s.strip()]
    if not keys:
        return None
    invalid = [k for k in keys if k not in _VALID_SECTION_KEYS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_SECTIONS",
                "message": f"Unknown section keys: {invalid}. Valid: {sorted(_VALID_SECTION_KEYS)}",
            },
        )
    return keys


def _check_download_rate_limit(org_id: str) -> bool:
    """
    Enforce 10 PDF downloads per org per hour via Redis INCR.
    Returns True if allowed, False if limit exceeded.
    Fail open: returns True if Redis is unavailable (log warning only).
    """
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return True
        r = _redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        key   = f"report_download_limit:{org_id}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 3600)
        return count <= 10
    except Exception as exc:
        logger.warning(
            "_check_download_rate_limit: Redis unavailable — allowing download: %s", exc
        )
        return True


def _next_send_at(row: dict) -> Optional[str]:
    """
    Compute the next scheduled delivery datetime in UTC for a scheduled_report row.
    S14: returns None on any failure.
    """
    try:
        freq      = row.get("frequency")
        send_hour = int(row.get("send_hour") or 8)
        now       = datetime.now(timezone.utc)
        today     = now.date()

        if freq == "weekly":
            dow = row.get("day_of_week")   # 0=Mon … 6=Sun (Python weekday())
            if dow is None:
                return None
            days_ahead = dow - today.weekday()
            if days_ahead < 0 or (days_ahead == 0 and now.hour >= send_hour):
                days_ahead += 7
            next_d = today + timedelta(days=days_ahead)
            return datetime(
                next_d.year, next_d.month, next_d.day, send_hour, 0, 0,
                tzinfo=timezone.utc,
            ).isoformat()

        if freq == "monthly":
            dom = row.get("day_of_month")  # 1–28
            if dom is None:
                return None
            if today.day < dom or (today.day == dom and now.hour < send_hour):
                next_d = today.replace(day=dom)
            else:
                if today.month == 12:
                    next_d = date(today.year + 1, 1, dom)
                else:
                    next_d = date(today.year, today.month + 1, dom)
            return datetime(
                next_d.year, next_d.month, next_d.day, send_hour, 0, 0,
                tzinfo=timezone.utc,
            ).isoformat()

        return None
    except Exception as exc:
        logger.warning("_next_send_at failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
_PHONE_RE = re.compile(r'^\+[1-9]\d{7,14}$')   # E.164


def _valid_recipient(r: str) -> bool:
    return bool(_EMAIL_RE.match(r) or _PHONE_RE.match(r))


class ScheduledReportCreate(BaseModel):
    label:            str            = Field(..., max_length=100)
    frequency:        str            = Field(..., pattern="^(weekly|monthly)$")
    day_of_week:      Optional[int]  = Field(None, ge=0, le=6)
    day_of_month:     Optional[int]  = Field(None, ge=1, le=28)
    send_hour:        int            = Field(8, ge=0, le=23)
    sections:         list[str]      = Field(..., min_length=1, max_length=12)
    period_preset:    str            = Field("last_7d")
    team_filter:      Optional[str]  = None
    rep_filter:       Optional[UUID] = None
    delivery_channel: str            = Field("email", pattern="^(email|whatsapp)$")
    recipients:       list[str]      = Field(..., min_length=1, max_length=10)

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in _VALID_SECTION_KEYS]
        if invalid:
            raise ValueError(f"Invalid section keys: {invalid}")
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        invalid = [r for r in v if not _valid_recipient(r)]
        if invalid:
            raise ValueError(
                f"Invalid recipient format (must be email or E.164 phone number): {invalid}"
            )
        return v

    @model_validator(mode="after")
    def validate_day_fields(self) -> "ScheduledReportCreate":
        if self.frequency == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required when frequency is 'weekly'")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required when frequency is 'monthly'")
        return self


class ScheduledReportUpdate(BaseModel):
    label:            Optional[str]       = Field(None, max_length=100)
    frequency:        Optional[str]       = Field(None, pattern="^(weekly|monthly)$")
    day_of_week:      Optional[int]       = Field(None, ge=0, le=6)
    day_of_month:     Optional[int]       = Field(None, ge=1, le=28)
    send_hour:        Optional[int]       = Field(None, ge=0, le=23)
    sections:         Optional[list[str]] = Field(None, min_length=1, max_length=12)
    period_preset:    Optional[str]       = None
    team_filter:      Optional[str]       = None
    rep_filter:       Optional[UUID]      = None
    delivery_channel: Optional[str]       = Field(None, pattern="^(email|whatsapp)$")
    recipients:       Optional[list[str]] = Field(None, min_length=1, max_length=10)
    is_active:        Optional[bool]      = None

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        invalid = [s for s in v if s not in _VALID_SECTION_KEYS]
        if invalid:
            raise ValueError(f"Invalid section keys: {invalid}")
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        invalid = [r for r in v if not _valid_recipient(r)]
        if invalid:
            raise ValueError(
                f"Invalid recipient format (must be email or E.164 phone number): {invalid}"
            )
        return v

    @model_validator(mode="after")
    def validate_day_fields(self) -> "ScheduledReportUpdate":
        if self.frequency == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week is required when updating frequency to 'weekly'")
        if self.frequency == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required when updating frequency to 'monthly'")
        return self


# ---------------------------------------------------------------------------
# Static routes — Pattern 53: all static routes before parameterised
# ---------------------------------------------------------------------------

# GET /reports/full
@router.get("/reports/full")
def get_report(
    period_preset: Optional[str] = Query(None),
    date_from:     Optional[str] = Query(None),
    date_to:       Optional[str] = Query(None),
    sections:      Optional[str] = Query(None),
    team:          Optional[str] = Query(None),
    rep_id:        Optional[str] = Query(None),
    compare:       str           = Query("previous_period"),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Return a full JSON report for the requested period and sections.
    Used by the frontend to render the live report preview.

    Date resolution: date_from + date_to > period_preset > last_30d.
    Sections: comma-separated list of section keys. Default: all sections.
    Compare: previous_period | year_on_year | none.
    """
    _require_reports_access(org)

    resolved_from, resolved_to = _resolve_dates(period_preset, date_from, date_to)
    active_sections = _parse_sections(sections)

    if compare not in ("previous_period", "year_on_year", "none"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_COMPARE", "message": "compare must be previous_period, year_on_year, or none"},
        )

    report = get_full_report(
        db=db,
        org_id=org["org_id"],
        date_from=resolved_from,
        date_to=resolved_to,
        sections=active_sections,
        team=team,
        rep_id=rep_id,
        compare=compare,
    )
    return _success(report)


# GET /reports/download
@router.get("/reports/download")
def download_report(
    period_preset: Optional[str] = Query(None),
    date_from:     Optional[str] = Query(None),
    date_to:       Optional[str] = Query(None),
    sections:      Optional[str] = Query(None),
    team:          Optional[str] = Query(None),
    rep_id:        Optional[str] = Query(None),
    compare:       str           = Query("previous_period"),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Generate and return the report as a downloadable PDF.
    Rate limited: 10 downloads per org per hour.
    Returns 429 if limit exceeded.
    """
    _require_reports_access(org)

    org_id = org["org_id"]

    if not _check_download_rate_limit(org_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "You can download up to 10 reports per hour.",
            },
        )

    resolved_from, resolved_to = _resolve_dates(period_preset, date_from, date_to)
    active_sections = _parse_sections(sections)

    if compare not in ("previous_period", "year_on_year", "none"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_COMPARE", "message": "compare must be previous_period, year_on_year, or none"},
        )

    report = get_full_report(
        db=db,
        org_id=org_id,
        date_from=resolved_from,
        date_to=resolved_to,
        sections=active_sections,
        team=team,
        rep_id=rep_id,
        compare=compare,
    )

    try:
        pdf_bytes = generate_report_pdf(report)
    except Exception as exc:
        logger.error("download_report: PDF generation failed org=%s: %s", org_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PDF_GENERATION_FAILED", "message": "PDF generation failed — please try again"},
        )

    filename = f"report-{resolved_from}_{resolved_to}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# GET /reports/sections
@router.get("/reports/sections")
def get_sections(
    org: dict = Depends(get_current_org),
):
    """Return the list of available report section keys with labels and descriptions."""
    _require_reports_access(org)
    # Return in canonical order matching _ALL_SECTIONS
    ordered = [
        "executive_summary", "lead_pipeline", "revenue", "response_time",
        "rep_performance", "team_performance", "whatsapp", "support",
        "customer_health", "tasks", "lost_leads", "channel_roi",
    ]
    return _success([_SECTION_LABELS[k] for k in ordered])


# GET /reports/scheduled
@router.get("/reports/scheduled")
def list_scheduled_reports(
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """Return all scheduled reports for the org, including computed next_send_at."""
    _require_reports_access(org)

    result = (
        db.table("scheduled_reports")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("created_at", desc=True)
        .execute()
    )
    rows = result.data if isinstance(result.data, list) else []

    # Enrich each row with next_send_at
    enriched = [
        {**row, "next_send_at": _next_send_at(row)}
        for row in rows
    ]
    return _success(enriched)


# POST /reports/scheduled
@router.post("/reports/scheduled", status_code=status.HTTP_201_CREATED)
def create_scheduled_report(
    payload: ScheduledReportCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """Create a new scheduled report. Owner only."""
    _require_owner(org)

    now_ts = _now_iso()
    row = {
        "org_id":           org["org_id"],
        "created_by":       org["id"],
        "label":            payload.label,
        "frequency":        payload.frequency,
        "day_of_week":      payload.day_of_week,
        "day_of_month":     payload.day_of_month,
        "send_hour":        payload.send_hour,
        "sections":         payload.sections,
        "period_preset":    payload.period_preset,
        "team_filter":      payload.team_filter,
        "rep_filter":       str(payload.rep_filter) if payload.rep_filter else None,
        "delivery_channel": payload.delivery_channel,
        "recipients":       payload.recipients,
        "is_active":        True,
        "created_at":       now_ts,
        "updated_at":       now_ts,
    }

    insert_result = db.table("scheduled_reports").insert(row).execute()
    data = insert_result.data
    if isinstance(data, list):
        data = data[0] if data else row

    return _success({**data, "next_send_at": _next_send_at(data)})


# ---------------------------------------------------------------------------
# Parameterised routes — Pattern 53: after all static routes
# ---------------------------------------------------------------------------

# PATCH /reports/scheduled/{report_id}
@router.patch("/reports/scheduled/{report_id}")
def update_scheduled_report(
    report_id: str,
    payload: ScheduledReportUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """Update a scheduled report. Owner only."""
    _require_owner(org)

    # Verify ownership
    existing = (
        db.table("scheduled_reports")
        .select("id, org_id")
        .eq("id", report_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    row = existing.data
    if isinstance(row, list):
        row = row[0] if row else None
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "NOT_FOUND", "message": "Scheduled report not found"})

    updates = {
        k: (str(v) if isinstance(v, UUID) else v)
        for k, v in payload.model_dump(exclude_unset=True).items()
    }
    updates["updated_at"] = _now_iso()

    result = (
        db.table("scheduled_reports")
        .update(updates)
        .eq("id", report_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    updated = result.data
    if isinstance(updated, list):
        updated = updated[0] if updated else None
    if not updated:
        updated = {**row, **updates}

    return _success({**updated, "next_send_at": _next_send_at(updated)})


# DELETE /reports/scheduled/{report_id}
@router.delete("/reports/scheduled/{report_id}")
def delete_scheduled_report(
    report_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """Soft-delete a scheduled report (sets is_active=False). Owner only."""
    _require_owner(org)

    # Verify ownership
    existing = (
        db.table("scheduled_reports")
        .select("id, org_id")
        .eq("id", report_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    row = existing.data
    if isinstance(row, list):
        row = row[0] if row else None
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "NOT_FOUND", "message": "Scheduled report not found"})

    db.table("scheduled_reports").update({
        "is_active":  False,
        "updated_at": _now_iso(),
    }).eq("id", report_id).eq("org_id", org["org_id"]).execute()

    return _success({"deleted": True, "report_id": report_id})
