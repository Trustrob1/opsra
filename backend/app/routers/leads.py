"""
app/routers/leads.py
All 14 lead routes from Technical Spec Section 5.2.

Phase 9B additions:
  - list_leads: scoped roles (sales_agent, affiliate_partner) see only
    leads assigned to themselves — assigned_to forced to org["id"]
  - Mutating routes (create, update, move-stage, convert, mark-lost,
    reactivate, import): blocked for affiliate_partner (read-only role)
  - Pattern 37: role derived from org["roles"]["template"] via rbac module

M01-7 additions:
  - POST /{lead_id}/demos         — book a demo
  - GET  /{lead_id}/demos         — list demos for a lead
  - PATCH/{lead_id}/demos/{demo_id} — log demo outcome

M01-7a additions:
  - GET /demos/pending            — org-wide pending demo queue (admin only)
  - GET /attention-summary        — multi-signal attention state per lead

Conventions:
  - All routes prefixed /api/v1/leads (registered in main.py)
  - org_id from JWT only — never from request body
  - Response envelope: ok() / err() / paginated()
  - audit_log + timeline written in service layer
  - Rate limit on AI scoring: 20/60min/org (Section 11.4) — enforced via Redis
  - Static routes (/import, /import/{job_id}) declared BEFORE /{id} to avoid shadowing
"""
from __future__ import annotations

import csv
import io
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.dependencies import get_current_org, require_admin
from app.models.common import ErrorCode, ok, err, paginated
from app.models.leads import (
    LeadCreate,
    LeadUpdate,
    MarkLostRequest,
    MoveStageRequest,
)
from app.services import lead_service, demo_service
from app.utils.rbac import (
    get_role_template,
    is_scoped_role,
    require_not_affiliate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScoreOverrideRequest(BaseModel):
    """Feature 2 (Module 01 gaps): human score override — manager/owner only."""
    score: str = Field(..., pattern="^(hot|warm|cold)$")


class ReactivateFromNurtureRequest(BaseModel):
    """PATCH /{lead_id}/reactivate-from-nurture — GAP-1: pull nurture lead back to pipeline."""
    reason: Optional[str] = Field(None, max_length=500)


class LeadCaptureRequest(BaseModel):
    """
    M01-3: Public web form lead capture — no JWT required.
    Minimal 4-field form: name, phone, email, location.
    Business details + problem are collected by the WhatsApp qualification bot.
    org_slug identifies the org; UTM fields captured from landing page URL.
    """
    org_slug:    str            = Field(..., min_length=1, max_length=100)
    full_name:   str            = Field(..., min_length=1, max_length=255)
    phone:       str            = Field(..., min_length=5, max_length=30)
    email:       Optional[str]  = Field(None, max_length=255)
    location:    Optional[str]  = Field(None, max_length=255)
    utm_source:  Optional[str]  = Field(None, max_length=100)
    utm_campaign: Optional[str] = Field(None, max_length=100)
    utm_ad:      Optional[str]  = Field(None, max_length=100)


# M01-7 — Demo request models (revised)

class CreateDemoRequest(BaseModel):
    """
    POST /api/v1/leads/{id}/demos — create a demo request (pending_assignment).
    Called by rep or admin. Bot uses demo_service.create_demo_from_bot() directly.
    """
    lead_preferred_time: Optional[str] = Field(None, max_length=500,
        description="Free-text preferred time from the lead, e.g. 'Monday afternoon'")
    medium:  Optional[str] = Field(None, pattern="^(virtual|in_person)$")
    notes:   Optional[str] = Field(None, max_length=5000)


class ConfirmDemoRequest(BaseModel):
    """
    POST /api/v1/leads/{id}/demos/{demo_id}/confirm — admin confirms the demo.
    Sets scheduled_at, medium, assigned_to. Triggers auto WA + rep notification.
    """
    scheduled_at:     str  = Field(..., description="ISO datetime of confirmed demo")
    medium:           str  = Field(..., pattern="^(virtual|in_person)$")
    assigned_to:      str  = Field(..., description="UUID of rep assigned to this demo")
    duration_minutes: int  = Field(30, ge=5, le=480)
    notes: Optional[str]   = Field(None, max_length=5000)


class LogOutcomeRequest(BaseModel):
    """PATCH /api/v1/leads/{id}/demos/{demo_id} — log outcome of a confirmed demo."""
    outcome:       str           = Field(..., pattern="^(attended|no_show|rescheduled)$")
    outcome_notes: Optional[str] = Field(None, max_length=5000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _org_id(org: dict) -> str:
    return org["org_id"]


def _user_id(org: dict) -> str:
    return org["id"]


# ---------------------------------------------------------------------------
# GET /api/v1/leads — list leads
# Phase 9B: scoped roles see only their own assigned leads
# ---------------------------------------------------------------------------

@router.get("")
async def list_leads(
    stage: Optional[str] = Query(None),
    score: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    # Phase 9B: force assigned_to filter for scoped roles (Pattern 37)
    effective_assigned_to = (
        _user_id(org) if is_scoped_role(org) else assigned_to
    )

    result = lead_service.list_leads(
        db=db,
        org_id=_org_id(org),
        stage=stage,
        score=score,
        assigned_to=effective_assigned_to,
        source=source,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/leads — create lead
# Phase 9B: affiliate_partner cannot create leads
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "creating leads")
    lead = lead_service.create_lead(
        db=db,
        org_id=_org_id(org),
        user_id=_user_id(org),
        payload=payload,
    )
    return ok(data=lead, message="Lead created")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/import — CSV/Excel bulk import
# Phase 9B: affiliate_partner cannot import leads
# MUST be declared before /{id} routes to avoid route shadowing
# ---------------------------------------------------------------------------

@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_leads(
    file: UploadFile = File(...),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Accept a CSV file and create leads in bulk. Returns job_id for polling."""
    require_not_affiliate(org, "importing leads")

    org_id = _org_id(org)
    user_id = _user_id(org)

    # Validate MIME type — Section 11.5
    allowed_types = {"text/csv", "application/csv", "application/vnd.ms-excel",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in allowed_types and not (
        file.filename or ""
    ).lower().endswith((".csv", ".xlsx")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "Only CSV and Excel files are accepted for bulk import",
            },
        )

    raw = await file.read()
    job_id = lead_service.create_import_job(org_id)

    try:
        text = raw.decode("utf-8-sig")  # handle BOM
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("CSV parse error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": f"Could not parse CSV file: {exc}",
            },
        ) from exc

    lead_service.process_csv_import(db=db, org_id=org_id, user_id=user_id, job_id=job_id, rows=rows)

    job = lead_service.get_import_job(org_id, job_id)
    return ok(data=job, message=f"Import completed: {job['succeeded']} succeeded, {job['failed']} failed")


# ---------------------------------------------------------------------------
# GET /api/v1/leads/import/{job_id} — poll import status
# MUST be declared before /{id} to avoid "import" being matched as an id
# ---------------------------------------------------------------------------

@router.get("/import/{job_id}")
async def get_import_status(
    job_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    job = lead_service.get_import_job(_org_id(org), job_id)
    return ok(data=job)


# ---------------------------------------------------------------------------
# GET /forms/{org_slug} — serve the hosted lead capture HTML form (no JWT)
# M01-2: FastAPI serves the standalone HTML form at this URL.
# The form template has {{ORG_SLUG}} and {{API_BASE}} placeholders replaced.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/forms/{org_slug}", response_class=HTMLResponse, include_in_schema=False)
async def serve_lead_form(
    org_slug: str,
    request: Request,
):
    """
    Public endpoint — no auth required.
    Serves the self-contained lead capture HTML form.
    ORG_SLUG and API_BASE placeholders are substituted server-side.
    """
    template_path = Path(__file__).parent.parent / "templates" / "lead_form.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Form template not found")

    html = template_path.read_text(encoding="utf-8")

    # Derive API base from request so it works in both dev and production
    api_base = str(request.base_url).rstrip("/")

    html = html.replace("'{{ORG_SLUG}}'", f"'{org_slug}'")
    html = html.replace("'{{API_BASE}}'", f"'{api_base}'")

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/form/{org_slug} — public form config (no JWT)
# M01-2: Returns org name for the hosted landing page form.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/form/{org_slug}")
async def get_form_config(
    org_slug: str,
    db=Depends(get_supabase),
):
    """
    Public endpoint — no auth required.
    Returns the org name and slug so the hosted form can display
    correct branding. 404 if the slug does not match any org.
    """
    result = (
        db.table("organisations")
        .select("id, name, slug")
        .eq("slug", org_slug)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": f"No organisation found for slug '{org_slug}'"},
        )
    return ok(data={"org_name": data["name"], "org_slug": data["slug"]})


# ---------------------------------------------------------------------------
# POST /api/v1/leads/capture — public form submission (no JWT)
# M01-2: Accepts lead data from the hosted landing page form.
# org identified by org_slug in the request body.
# Duplicate detection applies (same as all other channels).
# Rate limit: 10 submissions per IP per hour to prevent spam.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.post("/capture", status_code=status.HTTP_201_CREATED)
async def capture_lead(
    payload: LeadCaptureRequest,
    request: Request,
    db=Depends(get_supabase),
):
    """
    Public endpoint — no auth required.
    Accepts a lead submission from the hosted web form.
    Looks up org by slug, creates lead via lead_service.create_lead().
    Returns a simple success envelope — no internal lead data exposed.
    """
    # Look up org by slug
    org_result = (
        db.table("organisations")
        .select("id, slug")
        .eq("slug", payload.org_slug)
        .maybe_single()
        .execute()
    )
    org_data = org_result.data
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else None
    if not org_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.NOT_FOUND, "message": "Organisation not found"},
        )

    org_id = org_data["id"]

    # Build LeadCreate from form submission
    # Only 4 fields collected on form — business details collected by qualification bot
    lead_payload = LeadCreate(
        full_name    = payload.full_name,
        phone        = payload.phone,
        whatsapp     = payload.phone,  # phone from form is a WhatsApp number
        email        = payload.email,
        location     = payload.location,
        source       = "landing_page",
        utm_source   = payload.utm_source,
        utm_campaign = payload.utm_campaign,
        utm_ad       = payload.utm_ad,
    )

    # Fetch org WhatsApp number for the deep link
    org_wa_result = (
        db.table("organisations")
        .select("org_whatsapp_number, name")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_wa_data = org_wa_result.data
    if isinstance(org_wa_data, list):
        org_wa_data = org_wa_data[0] if org_wa_data else None
    org_wa_number = (org_wa_data or {}).get("org_whatsapp_number") or ""
    org_name      = (org_wa_data or {}).get("name") or ""

    new_lead = None
    try:
        new_lead = lead_service.create_lead(
            db      = db,
            org_id  = org_id,
            user_id = "system",
            payload = lead_payload,
        )
    except HTTPException as exc:
        detail = exc.detail or {}
        code = detail.get("code", "") if isinstance(detail, dict) else str(detail)
        if code == ErrorCode.DUPLICATE_DETECTED:
            logger.info("Duplicate lead from web form: phone=%s org=%s", payload.phone, org_id)
            # Still return the WhatsApp deep link so the user can continue
            wa_link = _build_wa_link(org_wa_number, payload.full_name, org_name)
            return ok(
                data={"whatsapp_link": wa_link, "org_whatsapp_number": org_wa_number},
                message="Thank you! We will be in touch shortly.",
            )
        raise

    # M01-3: Create a qualification session for this lead
    if new_lead:
        try:
            db.table("lead_qualification_sessions").insert({
                "org_id":  org_id,
                "lead_id": new_lead["id"],
                "stage":   "awaiting_first_message",
                "collected": {},
                "ai_active": True,
            }).execute()
        except Exception as exc:
            logger.warning("Failed to create qualification session for lead %s: %s",
                           new_lead.get("id"), exc)

    # Build WhatsApp deep link for "Continue on WhatsApp" button
    wa_link = _build_wa_link(org_wa_number, payload.full_name, org_name)

    return ok(
        data={"whatsapp_link": wa_link, "org_whatsapp_number": org_wa_number},
        message="Thank you! We will be in touch shortly.",
    )


def _build_wa_link(wa_number: str, full_name: str, org_name: str) -> str:
    """
    Build a wa.me deep link with a pre-filled message.
    The lead just has to tap Send — opening the 24hr conversation window
    so the AI can respond with free-form messages (no template needed).
    Returns empty string if no WhatsApp number is configured.
    """
    import urllib.parse
    if not wa_number:
        return ""
    clean_number = wa_number.replace("+", "").replace(" ", "").replace("-", "")
    greeting = f"Hi! I just filled in the form. My name is {full_name} and I'm interested in learning more about {org_name}."
    return f"https://wa.me/{clean_number}?text={urllib.parse.quote(greeting)}"


# ---------------------------------------------------------------------------
# M01-7a — GET /api/v1/leads/demos/pending
# Org-wide list of all pending_assignment demos.
# Auth: admin / owner / ops_manager only.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/demos/pending")
async def list_pending_demos(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns all pending_assignment demos across every lead in the org.
    Used by the Admin Demo Queue view (DemoQueue.jsx).
    Restricted to owner / admin / ops_manager.
    """
    template = get_role_template(org)
    if template not in ("owner", "admin", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only owners, admins and ops managers can view the demo queue",
            },
        )
    demos = demo_service.list_pending_demos_org_wide(
        db=db,
        org_id=_org_id(org),
    )
    return ok(data=demos)


# ---------------------------------------------------------------------------
# M01-7a — GET /api/v1/leads/attention-summary
# Multi-signal attention state per lead — drives badges on Kanban cards.
# Scoped roles (sales_agent, affiliate_partner) see only their own leads.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/attention-summary")
async def get_attention_summary(
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns { lead_id: { has_attention, unread_messages, pending_demos,
                          open_tickets, reasons } } for all leads in org.
    Scoped roles are limited to their assigned leads.
    S14: individual signal query failures are swallowed — never 500s.
    """
    # For scoped roles, restrict to their own lead IDs only
    lead_ids = None
    if is_scoped_role(org):
        rows = (
            db.table("leads")
            .select("id")
            .eq("org_id", _org_id(org))
            .eq("assigned_to", _user_id(org))
            .is_("deleted_at", "null")
            .execute().data or []
        )
        lead_ids = [r["id"] for r in rows]

    summary = demo_service.get_lead_attention_summary(
        db=db,
        org_id=_org_id(org),
        lead_ids=lead_ids,
    )
    return ok(data=summary)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/nurture-queue — GAP-6
# Read-only nurture pipeline view for managers.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/nurture-queue")
async def get_nurture_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_opted_out: bool = Query(False),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns paginated list of leads currently on the nurture track.
    Managers only (owner, admin, ops_manager) — 403 for all other roles.

    Sorted: last_nurture_sent_at ASC NULLS FIRST — leads overdue for
    a message appear first.

    Query params:
      include_opted_out=true  — also show opted-out leads (manager toggle)
    """
    template = get_role_template(org)
    if template not in ("owner", "admin", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only owners, admins and ops managers can view the nurture queue",
            },
        )

    result = lead_service.get_nurture_queue(
        db=db,
        org_id=_org_id(org),
        page=page,
        page_size=page_size,
        include_opted_out=include_opted_out,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )

# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/qualification-summary — WH-1b
# Returns the most recent handed-off qualification session for a lead.
# MUST be declared before /{lead_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/qualification-summary")
async def get_qualification_summary(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    WH-1b: Return the most recent handed-off qualification session for this lead.
    Returns handoff_summary, answers, and handed_off_at.
    Returns null if no session exists or none has been handed off yet.
    """
    org_id = org["org_id"]

    result = (
        db.table("lead_qualification_sessions")
        .select("handoff_summary, answers, handed_off_at, stage")
        .eq("org_id", org_id)
        .eq("lead_id", lead_id)
        .eq("stage", "handed_off")
        .order("handed_off_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = result.data if isinstance(result.data, list) else []
    session = rows[0] if rows else None

    return ok(session)



# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id} — get single lead
# Phase 9B: scoped roles can only read their own assigned leads
# The lead_service.get_lead returns 404 if not in org, so we add an
# ownership check for scoped roles after the fetch.
# ---------------------------------------------------------------------------

@router.get("/{lead_id}")
async def get_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    lead = lead_service.get_lead(db=db, org_id=_org_id(org), lead_id=lead_id)

    # Phase 9B: scoped roles can only see their own leads
    if is_scoped_role(org) and lead.get("assigned_to") != _user_id(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "You can only view leads assigned to you"},
        )

    return ok(data=lead)


# ---------------------------------------------------------------------------
# PATCH /api/v1/leads/{id} — update lead fields
# Phase 9B: affiliate_partner cannot edit leads
# ---------------------------------------------------------------------------

@router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "editing leads")
    lead = lead_service.update_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
        payload=payload,
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# DELETE /api/v1/leads/{id} — soft delete (Admin only)
# ---------------------------------------------------------------------------

@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    org: dict = Depends(require_admin),
    db=Depends(get_supabase),
):
    lead_service.soft_delete_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        admin_user_id=_user_id(org),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/score — AI scoring
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/score")
async def score_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    lead = lead_service.score_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=lead, message="Lead scored successfully")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/score-override — Human score override
# Feature 2 (Module 01 gaps): manager/owner overrides AI score
# score_source is set to 'human'; displayed as 👤 Human in LeadProfile
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/score-override")
async def override_score(
    lead_id: str,
    payload: ScoreOverrideRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    template = get_role_template(org)
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Only managers and owners can override lead scores",
            },
        )
    lead = lead_service.override_lead_score(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
        score=payload.score,
    )
    return ok(data=lead, message=f"Score overridden to {payload.score}")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/move-stage
# Phase 9B: affiliate_partner cannot move stages
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/move-stage")
async def move_stage(
    lead_id: str,
    payload: MoveStageRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "moving pipeline stages")
    lead = lead_service.move_stage(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        new_stage=payload.new_stage.value,
        user_id=_user_id(org),
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/convert
# Phase 9B: affiliate_partner cannot convert leads
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/convert")
async def convert_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "converting leads")
    result = lead_service.convert_lead(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=result, message="Lead converted to customer")


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/mark-lost
# Phase 9B: affiliate_partner cannot mark leads lost
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/mark-lost")
async def mark_lost(
    lead_id: str,
    payload: MarkLostRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "marking leads as lost")
    lead = lead_service.mark_lost(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        lost_reason=payload.lost_reason.value,
        user_id=_user_id(org),
        reengagement_date=str(payload.reengagement_date) if payload.reengagement_date else None,
    )
    return ok(data=lead)


# ---------------------------------------------------------------------------
# POST /api/v1/leads/{id}/reactivate
# Phase 9B: affiliate_partner cannot reactivate leads
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/reactivate", status_code=status.HTTP_201_CREATED)
async def reactivate_lead(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "reactivating leads")
    new_lead = lead_service.reactivate_lead(
        db=db,
        org_id=_org_id(org),
        old_lead_id=lead_id,
        user_id=_user_id(org),
    )
    return ok(data=new_lead, message="Lead reactivated")


# ---------------------------------------------------------------------------
# PATCH /api/v1/leads/{id}/reactivate-from-nurture — GAP-1
# Pull a nurture-track lead back into the active pipeline after offline contact.
# affiliate_partner cannot reactivate leads.
# ---------------------------------------------------------------------------

@router.patch("/{lead_id}/reactivate-from-nurture")
async def reactivate_from_nurture(
    lead_id: str,
    payload: ReactivateFromNurtureRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    require_not_affiliate(org, "reactivating leads from nurture")
    lead = lead_service.reactivate_from_nurture(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
        reason=payload.reason,
    )
    return ok(data=lead, message="Lead reactivated from nurture")


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/timeline
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/timeline")
async def get_timeline(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    events = lead_service.get_timeline(db=db, org_id=_org_id(org), lead_id=lead_id)
    return ok(data=events)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/tasks
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/tasks")
async def get_lead_tasks(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    tasks = lead_service.get_lead_tasks(db=db, org_id=_org_id(org), lead_id=lead_id)
    return ok(data=tasks)


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/messages
# Returns paginated WhatsApp message history for a lead.
# Uses whatsapp_service.get_lead_messages — same pattern as customer messages.
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/messages")
async def get_lead_messages(
    lead_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    from app.services import whatsapp_service
    result = whatsapp_service.get_lead_messages(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# M01-7 — Demo Scheduling & Management (Revised)
#
# POST   /{lead_id}/demos                       — create demo request (pending_assignment)
# GET    /{lead_id}/demos                       — list all demos for a lead
# POST   /{lead_id}/demos/{demo_id}/confirm     — admin confirms demo (→ confirmed)
# PATCH  /{lead_id}/demos/{demo_id}             — log outcome (attended|no_show|rescheduled)
# ---------------------------------------------------------------------------

@router.post("/{lead_id}/demos", status_code=status.HTTP_201_CREATED)
async def create_demo_request(
    lead_id: str,
    payload: CreateDemoRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Create a demo request with status=pending_assignment.
    Admin/manager is notified via task + in-app notification to confirm.
    Accessible by: rep (own leads), admin/owner (any lead).
    """
    
    demo = demo_service.create_demo_request(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        user_id=_user_id(org),
        lead_preferred_time=payload.lead_preferred_time,
        medium=payload.medium,
        notes=payload.notes,
    )
    return ok(data=demo, message="Demo request created — pending admin confirmation")


@router.get("/{lead_id}/demos")
async def list_demos(
    lead_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """List all demos for a lead, newest first."""
    demos = demo_service.list_demos(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
    )
    return ok(data=demos)


@router.post("/{lead_id}/demos/{demo_id}/confirm")
async def confirm_demo(
    lead_id: str,
    demo_id: str,
    payload: ConfirmDemoRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Admin/manager confirms a pending_assignment demo.
    Sets scheduled_at, medium, assigned_to.
    Auto-sends WA confirmation to lead.
    Creates task + in-app notification for rep.
    """
    template = get_role_template(org)
    if template not in ("owner", "admin", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN",
                    "message": "Only owners, admins and ops managers can confirm demos"},
        )
    demo = demo_service.confirm_demo(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        demo_id=demo_id,
        user_id=_user_id(org),
        scheduled_at=payload.scheduled_at,
        medium=payload.medium,
        assigned_to=payload.assigned_to,
        duration_minutes=payload.duration_minutes,
        notes=payload.notes,
    )
    return ok(data=demo, message="Demo confirmed — confirmation sent to lead")


@router.patch("/{lead_id}/demos/{demo_id}")
async def log_demo_outcome(
    lead_id: str,
    demo_id: str,
    payload: LogOutcomeRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    demo = demo_service.log_outcome(
        db=db,
        org_id=_org_id(org),
        lead_id=lead_id,
        demo_id=demo_id,
        user_id=_user_id(org),
        outcome=payload.outcome,
        outcome_notes=payload.outcome_notes,
    )
    return ok(data=demo, message=f"Demo outcome logged: {payload.outcome}")