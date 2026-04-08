"""
app/services/lead_service.py
Business logic for Module 01 — Leads.

Conventions:
  - All functions take `db` as first arg (Supabase client from get_supabase())
  - org_id always from JWT — never from request body
  - Soft deletes only — set deleted_at, never hard delete
  - audit_logs written after every significant action
  - State machine enforced — Technical Spec Section 4.1 (11 transitions)
  - Duplicate detection — Technical Spec Section 9.3 (DUPLICATE_DETECTED)
  - Prompt injection protection — Technical Spec Section 11.3
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import HTTPException, status

from app.models.common import ErrorCode
from app.models.leads import LeadCreate, LeadUpdate, LostReason, LeadStage
from app.services.ai_service import sanitise_for_prompt, score_lead_with_ai

load_dotenv()  # Pattern 29 — required for os.getenv() calls in notification helper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine — Technical Spec Section 4.1 (all 11 transitions)
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, set[str]] = {
    "new": {"contacted", "lost"},
    "contacted": {"demo_done", "lost", "not_ready"},
    "demo_done": {"proposal_sent", "lost"},
    "proposal_sent": {"converted", "lost"},
    "lost": {"new"},
    "not_ready": {"new"},
    "converted": set(),   # terminal — cannot move backward
}

# Stages from which mark_lost is valid
CAN_MARK_LOST: set[str] = {"new", "contacted", "demo_done", "proposal_sent"}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lead_or_404(db: Any, org_id: str, lead_id: str) -> dict:
    """Fetch a non-deleted lead by id scoped to org, or raise 404."""
    result = (
        db.table("leads")
        .select("*")
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    # Real supabase .maybe_single() returns a single dict or None.
    # Test mocks return a list — normalise both to a dict here.
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Lead {lead_id} not found in this organisation",
            },
        )
    return data


# ---------------------------------------------------------------------------
# audit_log + timeline helpers (db always passed explicitly)
# ---------------------------------------------------------------------------

def write_audit_log(
    db: Any,
    org_id: str,
    user_id: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> None:
    """Write an immutable audit log entry — Technical Spec Section 9.5."""
    db.table("audit_logs").insert(
        {
            "org_id": org_id,
            "user_id": user_id,
            "action": action,
            "resource_type": "lead",
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
        }
    ).execute()


def write_timeline_event(
    db: Any,
    org_id: str,
    lead_id: str,
    event_type: str,
    actor_id: Optional[str],
    description: str,
    metadata: Optional[dict] = None,
) -> None:
    """Append an event to lead_timeline — every mutating service calls this."""
    db.table("lead_timeline").insert(
        {
            "org_id": org_id,
            "lead_id": lead_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "description": description,
            "metadata": metadata or {},
        }
    ).execute()


# ---------------------------------------------------------------------------
# New lead notification helper — Feature 3 (Module 01 gap)
# ---------------------------------------------------------------------------

_GRAPH_BASE = "https://graph.facebook.com/v18.0"
_META_WA_TOKEN = os.getenv("META_WHATSAPP_TOKEN", "").strip()


def _notify_new_lead(db: Any, org_id: str, lead: dict, lead_id: str) -> None:
    """
    Notify assigned rep + all owner/ops_manager users when a new lead arrives.
    Sends both in-app notification and WhatsApp (if org's WhatsApp is configured).
    S14: entire body wrapped — NEVER raises, never blocks lead creation.
    DRD §5 Channel 1: "Assigned rep notified via WhatsApp and in-app."
    """
    try:
        lead_name  = lead.get("full_name", "New lead")
        assigned_to = lead.get("assigned_to")
        source      = (lead.get("source") or "unknown").replace("_", " ").title()
        biz_name    = lead.get("business_name") or ""

        # Fetch all active users in org with their roles
        users_result = (
            db.table("users")
            .select("id, whatsapp_number, roles(template)")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        all_users: list[dict] = users_result.data or []
        if isinstance(all_users, dict):
            all_users = [all_users]

        # Collect users to notify: assigned rep + all owner/ops_manager
        notify_users: list[dict] = []
        seen: set[str] = set()
        for u in all_users:
            uid = u.get("id")
            if not uid or uid in seen:
                continue
            roles = u.get("roles") or {}
            if isinstance(roles, list):
                roles = roles[0] if roles else {}
            template = (roles.get("template") or "").lower()
            if template in ("owner", "ops_manager") or uid == assigned_to:
                seen.add(uid)
                notify_users.append(u)

        if not notify_users:
            return

        title = f"New lead: {lead_name}"
        body  = (
            f"A new {source} lead has arrived."
            + (f" Business: {biz_name}." if biz_name else "")
            + " Open Opsra to view and action."
        )

        # In-app notifications
        for u in notify_users:
            try:
                db.table("notifications").insert({
                    "org_id":        org_id,
                    "user_id":       u["id"],
                    "title":         title,
                    "body":          body,
                    "type":          "new_lead",
                    "resource_type": "lead",
                    "resource_id":   lead_id,
                }).execute()
            except Exception as _exc:
                logger.warning("New lead in-app notification failed for %s: %s", u.get("id"), _exc)

        # WhatsApp notifications — only if META token + org phone_id configured
        wa_token = _META_WA_TOKEN or os.getenv("META_WHATSAPP_TOKEN", "").strip()
        if not wa_token:
            return

        try:
            org_result = (
                db.table("organisations")
                .select("whatsapp_phone_id")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_data = org_result.data
            if isinstance(org_data, list):
                org_data = org_data[0] if org_data else None
            phone_id = (org_data or {}).get("whatsapp_phone_id")
        except Exception:
            phone_id = None

        if not phone_id:
            return

        import httpx as _httpx
        wa_msg = (
            f"🎯 *New Lead: {lead_name}*\n\n"
            f"Source: {source}\n"
            + (f"Business: {biz_name}\n" if biz_name else "")
            + "\nOpen Opsra to view, score, and action this lead."
        )

        for u in notify_users:
            wa_num = u.get("whatsapp_number")
            if not wa_num:
                continue
            try:
                _httpx.post(
                    f"{_GRAPH_BASE}/{phone_id}/messages",
                    headers={"Authorization": f"Bearer {wa_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to":   wa_num,
                        "type": "text",
                        "text": {"body": wa_msg},
                    },
                    timeout=5.0,
                )
            except Exception as _exc:
                logger.warning("New lead WhatsApp alert failed for %s: %s", u.get("id"), _exc)

    except Exception as exc:
        # S14 outer guard — lead creation must never fail due to notification errors
        logger.warning("_notify_new_lead failed entirely (non-fatal): %s", exc)


def _normalise_phone(value: Optional[str]) -> Optional[str]:
    """
    Normalise phone numbers before storing or duplicate-checking.
    Handles Excel scientific notation (2.348E+12) and common formatting issues.
    """
    if not value:
        return None
    
    v = str(value).strip()
    
    # Handle Excel scientific notation e.g. 2.348E+12 → 2348000000000
    if 'E+' in v.upper() or 'e+' in v:
        try:
            v = str(int(float(v)))
        except (ValueError, OverflowError):
            pass
    
    # Remove all non-digit characters except leading +
    import re
    v = re.sub(r'[^\d+]', '', v)
    
    # Remove spaces, dashes, brackets that slipped through
    v = v.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    if not v:
        return None
    
    return v


# ---------------------------------------------------------------------------
# Duplicate detection — Section 9.3 (DUPLICATE_DETECTED / 409)
# ---------------------------------------------------------------------------

def check_duplicate(
    db: Any,
    org_id: str,
    phone: Optional[str],
    email: Optional[str],
) -> bool:
    """
    Return True if any active lead in org has matching phone OR email.
    Two DB queries to avoid supabase-py OR complexity.
    """
    if not phone and not email:
        return False

    if phone:
        r = (
            db.table("leads")
            .select("id")
            .eq("org_id", org_id)
            .eq("phone", phone)
            .is_("deleted_at", "null")
            .execute()
        )
        if r.data:
            return True

    if email:
        r = (
            db.table("leads")
            .select("id")
            .eq("org_id", org_id)
            .eq("email", email)
            .is_("deleted_at", "null")
            .execute()
        )
        if r.data:
            return True

    return False


# ---------------------------------------------------------------------------
# list_leads
# ---------------------------------------------------------------------------

def list_leads(
    db: Any,
    org_id: str,
    stage: Optional[str] = None,
    score: Optional[str] = None,
    assigned_to: Optional[str] = None,
    source: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    List leads with optional filters and pagination.
    Returns dict compatible with paginated() envelope.
    """
    query = (
        db.table("leads")
        .select("*", count="exact")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
    )

    if stage:
        query = query.eq("stage", stage)
    if score:
        query = query.eq("score", score)
    if assigned_to:
        query = query.eq("assigned_to", assigned_to)
    if source:
        query = query.eq("source", source)
    if from_date:
        query = query.gte("created_at", from_date)
    if to_date:
        query = query.lte("created_at", to_date)

    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size - 1).order("created_at", desc=True)

    result = query.execute()
    return {
        "items": result.data or [],
        "total": result.count or 0,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# get_lead
# ---------------------------------------------------------------------------

def get_lead(db: Any, org_id: str, lead_id: str) -> dict:
    result = (
        db.table("leads")
        .select("*, assigned_user:users!assigned_to(id, full_name)")
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Lead {lead_id} not found in this organisation",
            },
        )
    return data


# ---------------------------------------------------------------------------
# create_lead
# ---------------------------------------------------------------------------

def create_lead(
    db: Any,
    org_id: str,
    user_id: str,
    payload: LeadCreate,
) -> dict:
    """
    Create a lead.
    - Auto-assigns to creating user (unless assigned_to is explicitly set)
    - Checks for duplicate phone/email in org → 409
    - Writes timeline event + audit log
    """
    data = payload.model_dump(exclude_none=True)

    # Normalise LeadSource enum value — "import" stored as "import" in DB
    source_val = data.get("source")
    if hasattr(source_val, "value"):
        data["source"] = source_val.value
    # "import_" internal alias → store as "import"
    if data.get("source") == "import_":
        data["source"] = "import"

    # Normalise phone numbers — handles Excel scientific notation,
    # spaces, dashes, brackets before duplicate check and storage
    if data.get("phone"):
        data["phone"] = _normalise_phone(data["phone"])
    if data.get("whatsapp"):
        data["whatsapp"] = _normalise_phone(data["whatsapp"])

    # Auto-assign
    if not data.get("assigned_to"):
        data["assigned_to"] = user_id

    data["org_id"] = org_id
    data["stage"] = "new"
    data["score"] = "unscored"

    # Duplicate detection — Section 9.3
    if check_duplicate(db, org_id, data.get("phone"), data.get("email")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.DUPLICATE_DETECTED,
                "message": "A lead with this phone or email already exists in your organisation",
            },
        )

    result = db.table("leads").insert(data).execute()
    lead = result.data[0] if result.data else data
    lead_id = lead.get("id", data.get("id", ""))

    write_timeline_event(
        db, org_id, lead_id,
        event_type="lead_created",
        actor_id=user_id,
        description=f"Lead created from {data.get('source', 'unknown')}",
        metadata={"source": data.get("source")},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.created",
        resource_type="lead",
        resource_id=lead_id,
        new_value={"stage": "new", "source": data.get("source")},
    )

    # Feature 3: notify assigned rep + all owner/ops_manager users (S14 — never blocks)
    _notify_new_lead(db, org_id, lead, lead_id)

    return lead


# ---------------------------------------------------------------------------
# update_lead
# ---------------------------------------------------------------------------

def update_lead(
    db: Any,
    org_id: str,
    lead_id: str,
    user_id: str,
    payload: LeadUpdate,
) -> dict:
    """Update allowed lead fields. Does NOT allow stage changes (use move_stage)."""
    _lead_or_404(db, org_id, lead_id)   # 404 guard

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return _lead_or_404(db, org_id, lead_id)

    updates["updated_at"] = _now_iso()
    updates["last_activity_at"] = _now_iso()

    result = (
        db.table("leads")
        .update(updates)
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {}

    write_timeline_event(
        db, org_id, lead_id,
        event_type="note_added",
        actor_id=user_id,
        description="Lead details updated",
        metadata={"fields": list(updates.keys())},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.updated",
        resource_type="lead",
        resource_id=lead_id,
        new_value=updates,
    )
    return updated


# ---------------------------------------------------------------------------
# soft_delete_lead
# ---------------------------------------------------------------------------

def soft_delete_lead(
    db: Any,
    org_id: str,
    lead_id: str,
    admin_user_id: str,
) -> None:
    """Soft delete — sets deleted_at. Admin only (enforced at router level)."""
    lead = _lead_or_404(db, org_id, lead_id)

    db.table("leads").update({"deleted_at": _now_iso()}).eq("id", lead_id).eq(
        "org_id", org_id
    ).execute()

    write_audit_log(
        db, org_id, admin_user_id,
        action="lead.deleted",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"stage": lead.get("stage")},
    )


# ---------------------------------------------------------------------------
# move_stage — validates ALL 11 transitions from Section 4.1
# ---------------------------------------------------------------------------

def move_stage(
    db: Any,
    org_id: str,
    lead_id: str,
    new_stage: str,
    user_id: str,
) -> dict:
    """
    General stage mover. Validates against VALID_TRANSITIONS.
    Note: dedicated routes (mark_lost, convert, reactivate) handle transitions
    that require extra data or side-effects.
    The full state machine including those transitions is validated here so that
    all 11 transitions can be unit-tested through this function.
    """
    lead = _lead_or_404(db, org_id, lead_id)
    current_stage = lead["stage"]

    allowed = VALID_TRANSITIONS.get(current_stage, set())
    if new_stage not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_TRANSITION,
                "message": (
                    f"Cannot move lead from '{current_stage}' to '{new_stage}'. "
                    f"Allowed: {sorted(allowed) or 'none (terminal stage)'}"
                ),
            },
        )

    updates: dict = {
        "stage": new_stage,
        "updated_at": _now_iso(),
        "last_activity_at": _now_iso(),
    }

    result = (
        db.table("leads")
        .update(updates)
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**lead, **updates}

    write_timeline_event(
        db, org_id, lead_id,
        event_type="stage_changed",
        actor_id=user_id,
        description=f"Stage moved from {current_stage} to {new_stage}",
        metadata={"from_stage": current_stage, "to_stage": new_stage},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.stage_changed",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"stage": current_stage},
        new_value={"stage": new_stage},
    )
    return updated


# ---------------------------------------------------------------------------
# mark_lost — requires lost_reason (Section 4.1)
# ---------------------------------------------------------------------------

def mark_lost(
    db: Any,
    org_id: str,
    lead_id: str,
    lost_reason: str,
    user_id: str,
    reengagement_date: Optional[str] = None,
) -> dict:
    """
    Mark a lead as lost. Validates the transition, requires lost_reason.
    Valid from: new, contacted, demo_done, proposal_sent.
    """
    if not lost_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "lost_reason is required when marking a lead as lost",
                "field": "lost_reason",
            },
        )

    lead = _lead_or_404(db, org_id, lead_id)
    current_stage = lead["stage"]

    if current_stage not in CAN_MARK_LOST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_TRANSITION,
                "message": (
                    f"Cannot mark lead as lost from stage '{current_stage}'. "
                    f"Valid from: {sorted(CAN_MARK_LOST)}"
                ),
            },
        )

    updates: dict = {
        "stage": "lost",
        "lost_reason": lost_reason,
        "lost_at": _now_iso(),
        "updated_at": _now_iso(),
        "last_activity_at": _now_iso(),
    }
    if reengagement_date:
        updates["reengagement_date"] = reengagement_date

    result = (
        db.table("leads")
        .update(updates)
        .eq("id", lead_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**lead, **updates}

    write_timeline_event(
        db, org_id, lead_id,
        event_type="stage_changed",
        actor_id=user_id,
        description=f"Lead marked as lost — reason: {lost_reason}",
        metadata={"from_stage": current_stage, "to_stage": "lost", "lost_reason": lost_reason},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.lost",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"stage": current_stage},
        new_value={"stage": "lost", "lost_reason": lost_reason},
    )
    return updated


# ---------------------------------------------------------------------------
# reactivate_lead — creates a NEW lead, sets previous_lead_id
# ---------------------------------------------------------------------------

def reactivate_lead(
    db: Any,
    org_id: str,
    old_lead_id: str,
    user_id: str,
) -> dict:
    """
    Reactivate a lost lead.
    Creates a new lead record with previous_lead_id pointing to the old one.
    The old lead remains in 'lost' stage.
    """
    old_lead = _lead_or_404(db, org_id, old_lead_id)

    if old_lead["stage"] != "lost":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_TRANSITION,
                "message": "Only leads in 'lost' stage can be reactivated",
            },
        )

    # Build new lead from old lead data, reset stage/score
    new_lead_data: dict = {
        "org_id": org_id,
        "full_name": old_lead.get("full_name"),
        "phone": old_lead.get("phone"),
        "whatsapp": old_lead.get("whatsapp"),
        "email": old_lead.get("email"),
        "business_name": old_lead.get("business_name"),
        "business_type": old_lead.get("business_type"),
        "location": old_lead.get("location"),
        "branches": old_lead.get("branches"),
        "problem_stated": old_lead.get("problem_stated"),
        "source": old_lead.get("source"),
        "referrer": old_lead.get("referrer"),
        "assigned_to": old_lead.get("assigned_to") or user_id,
        "stage": "new",
        "score": "unscored",
        "previous_lead_id": old_lead_id,   # ← links to old record
    }
    # Remove None values
    new_lead_data = {k: v for k, v in new_lead_data.items() if v is not None}

    result = db.table("leads").insert(new_lead_data).execute()
    new_lead = result.data[0] if result.data else new_lead_data
    new_lead_id = new_lead.get("id", "")

    # Gap 7 — auto-create a task for the rep so reactivation appears on the Task Board
    assigned_rep = new_lead_data.get("assigned_to") or user_id
    if assigned_rep and new_lead_id:
        try:
            _now = datetime.now(timezone.utc).isoformat()
            prior_context = old_lead.get("problem_stated") or ""
            db.table("tasks").insert({
                "org_id":           org_id,
                "assigned_to":      assigned_rep,
                "title":            f"Follow up: {old_lead.get('full_name', 'Lead')} reactivated",
                "description":      (
                    f"This lead was reactivated from a previous record.\n"
                    + (f"Previous context: {prior_context}" if prior_context else "")
                ).strip(),
                "task_type":        "system_event",
                "source_module":    "leads",
                "source_record_id": new_lead_id,
                "priority":         "high",
                "status":           "open",
                "created_at":       _now,
                "updated_at":       _now,
            }).execute()
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "reactivate_lead: task creation failed — %s", exc
            )

    write_timeline_event(
        db, org_id, new_lead_id,
        event_type="lead_created",
        actor_id=user_id,
        description=f"Lead reactivated from previous lead {old_lead_id}",
        metadata={"previous_lead_id": old_lead_id, "source": "reactivation"},
    )
    write_timeline_event(
        db, org_id, old_lead_id,
        event_type="stage_changed",
        actor_id=user_id,
        description=f"Lead reactivated — new lead created: {new_lead_id}",
        metadata={"new_lead_id": new_lead_id},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.reactivated",
        resource_type="lead",
        resource_id=new_lead_id,
        old_value={"previous_lead_id": old_lead_id},
        new_value={"stage": "new", "previous_lead_id": old_lead_id},
    )
    return new_lead


# ---------------------------------------------------------------------------
# convert_lead — creates customer + subscription stub
# ---------------------------------------------------------------------------

def convert_lead(
    db: Any,
    org_id: str,
    lead_id: str,
    user_id: str,
) -> dict:
    """
    Convert a lead to a customer.
    - Lead must be in 'proposal_sent' stage
    - Sets converted_at on lead, moves to 'converted'
    - Creates customer record stub (Section 3.3)
    - Creates subscription stub (Section 3.5)
    """
    lead = _lead_or_404(db, org_id, lead_id)
    current_stage = lead["stage"]

    if current_stage != "proposal_sent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_TRANSITION,
                "message": (
                    f"Lead must be in 'proposal_sent' stage to convert. "
                    f"Current stage: '{current_stage}'"
                ),
            },
        )

    converted_at = _now_iso()

    # Update lead
    db.table("leads").update(
        {
            "stage": "converted",
            "converted_at": converted_at,
            "updated_at": converted_at,
            "last_activity_at": converted_at,
        }
    ).eq("id", lead_id).eq("org_id", org_id).execute()

    # Create customer stub — Section 3.3
    customer_data: dict = {
        "org_id": org_id,
        "lead_id": lead_id,
        "full_name": lead.get("full_name", ""),
        "phone": lead.get("phone"),
        "whatsapp": lead.get("whatsapp") or lead.get("phone") or "",
        "email": lead.get("email"),
        "business_name": lead.get("business_name", ""),
        "business_type": lead.get("business_type"),
        "location": lead.get("location"),
        "branches": lead.get("branches"),
        "assigned_to": lead.get("assigned_to"),
        "whatsapp_opt_in": True,
        "onboarding_complete": False,
        "churn_risk": "low",
    }
    # Remove None values
    customer_data = {k: v for k, v in customer_data.items() if v is not None}

    customer_result = db.table("customers").insert(customer_data).execute()
    print(f"[DEBUG] customer insert result: data={customer_result.data}")
    customer = customer_result.data[0] if customer_result.data else customer_data
    customer_id = customer.get("id", "")
    print(f"[DEBUG] customer_id resolved to: '{customer_id}'")

    # Gap 4 — re-link any tasks created against this lead to the new customer record
    # so they surface correctly on the customer profile Tasks tab.
    if customer_id:
        try:
            _now_relink = datetime.now(timezone.utc).isoformat()
            db.table("tasks").update({
                "source_record_id": customer_id,
                "updated_at":       _now_relink,
            }).eq("source_record_id", lead_id).eq("org_id", org_id).execute()
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "convert_lead: task re-linking failed — %s", exc
            )

    # Create subscription stub — Section 3.5
    # TEMP-3 resolved: subscriptions table created in Phase 5A.
    subscription_data: dict = {
        "org_id": org_id,
        "customer_id": customer_id,
        "plan_name": "Starter Plan",
        "plan_tier": "starter",
        "amount": 0,
        "currency": "NGN",
        "billing_cycle": "monthly",
        "status": "trial",
        "current_period_start": datetime.now(timezone.utc).date().isoformat(),
        "current_period_end": datetime.now(timezone.utc).date().isoformat(),
    }
    db.table("subscriptions").insert(subscription_data).execute()

    # Phase 9C: auto-create commission row if this lead had an assigned rep
    # S14: never fail the core conversion due to commission creation
    if lead.get("assigned_to") and customer_id:
        try:
            from app.services.commissions_service import auto_create_commission
            auto_create_commission(
                db=db,
                org_id=org_id,
                affiliate_user_id=lead["assigned_to"],
                event_type="lead_converted",
                lead_id=lead_id,
                customer_id=customer_id,
            )
        except Exception as _ce:
            import logging as _log
            _log.getLogger(__name__).warning(
                "convert_lead: commission creation failed — %s", _ce
            )
    write_timeline_event(
        db, org_id, lead_id,
        event_type="stage_changed",
        actor_id=user_id,
        description="Lead converted to customer",
        metadata={
            "from_stage": "proposal_sent",
            "to_stage": "converted",
            "customer_id": customer_id,
        },
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.converted",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"stage": "proposal_sent"},
        new_value={"stage": "converted", "customer_id": customer_id},
    )

    return {**lead, "stage": "converted", "converted_at": converted_at, "customer_id": customer_id}


# ---------------------------------------------------------------------------
# score_lead — Claude Sonnet call (Section 8.1)
# ---------------------------------------------------------------------------

def score_lead(
    db: Any,
    org_id: str,
    lead_id: str,
    user_id: str,
) -> dict:
    """
    Trigger AI scoring via Claude Sonnet.
    Fetches org scoring rubric from organisations table — Feature 4.
    Updates lead.score, lead.score_reason, and lead.score_source = 'ai'.
    Writes timeline event + audit log.
    Gracefully handles AI unavailability — Section 12.7.
    """
    lead = _lead_or_404(db, org_id, lead_id)

    # Feature 4: fetch org-configurable scoring rubric
    rubric: dict = {}
    try:
        org_result = (
            db.table("organisations")
            .select(
                "scoring_business_context, scoring_hot_criteria, "
                "scoring_warm_criteria, scoring_cold_criteria, "
                "scoring_qualification_questions"
            )
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_data = org_result.data
        if isinstance(org_data, list):
            org_data = org_data[0] if org_data else None
        rubric = org_data or {}
    except Exception as _exc:
        logger.warning("Could not fetch scoring rubric for org %s: %s", org_id, _exc)

    score_result = score_lead_with_ai(lead, rubric=rubric)

    db.table("leads").update(
        {
            "score":        score_result["score"],
            "score_reason": score_result["score_reason"],
            "score_source": "ai",
            "updated_at":   _now_iso(),
        }
    ).eq("id", lead_id).eq("org_id", org_id).execute()

    write_timeline_event(
        db, org_id, lead_id,
        event_type="score_updated",
        actor_id=user_id,
        description=f"AI score updated to {score_result['score']}",
        metadata=score_result,
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.scored",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"score": lead.get("score")},
        new_value={**score_result, "score_source": "ai"},
    )

    return {**lead, **score_result, "score_source": "ai"}


# ---------------------------------------------------------------------------
# override_lead_score — Feature 2 (Module 01 gaps)
# ---------------------------------------------------------------------------

def override_lead_score(
    db: Any,
    org_id: str,
    lead_id: str,
    user_id: str,
    score: str,
) -> dict:
    """
    Manager/owner manually overrides the AI lead score.
    Sets score_source = 'human' — displayed as '👤 Human' in the UI.
    The AI score is preserved in audit history; timeline records the override.
    """
    if score not in {"hot", "warm", "cold"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "score must be one of: hot, warm, cold",
            },
        )

    lead = _lead_or_404(db, org_id, lead_id)

    db.table("leads").update({
        "score":        score,
        "score_reason": "Manually scored by team member",
        "score_source": "human",
        "updated_at":   _now_iso(),
    }).eq("id", lead_id).eq("org_id", org_id).execute()

    write_timeline_event(
        db, org_id, lead_id,
        event_type="score_updated",
        actor_id=user_id,
        description=f"Score manually overridden to {score}",
        metadata={"score": score, "score_source": "human",
                  "previous_score": lead.get("score"),
                  "previous_source": lead.get("score_source")},
    )
    write_audit_log(
        db, org_id, user_id,
        action="lead.score_overridden",
        resource_type="lead",
        resource_id=lead_id,
        old_value={"score": lead.get("score"), "score_source": lead.get("score_source")},
        new_value={"score": score, "score_source": "human"},
    )

    return {
        **lead,
        "score":        score,
        "score_reason": "Manually scored by team member",
        "score_source": "human",
    }

def get_timeline(db: Any, org_id: str, lead_id: str) -> list[dict]:
    """Return lead timeline events ordered by created_at descending."""
    _lead_or_404(db, org_id, lead_id)  # 404 guard

    result = (
        db.table("lead_timeline")
        .select("*")
        .eq("org_id", org_id)
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# get_lead_tasks
# ---------------------------------------------------------------------------

def get_lead_tasks(db: Any, org_id: str, lead_id: str) -> list[dict]:
    """Return tasks linked to this lead."""
    _lead_or_404(db, org_id, lead_id)  # 404 guard

    result = (
        db.table("tasks")
        .select("*")
        .eq("org_id", org_id)
        .eq("source_record_id", lead_id)
        .eq("source_module", "leads")
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# Import job helpers (in-memory store — use Redis in production)
# ---------------------------------------------------------------------------
_import_jobs: dict[str, dict] = {}


def create_import_job(org_id: str) -> str:
    """Create a new import job and return its job_id."""
    job_id = str(uuid.uuid4())
    _import_jobs[job_id] = {
        "job_id": job_id,
        "org_id": org_id,
        "status": "pending",
        "total_rows": 0,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "created_at": _now_iso(),
        "completed_at": None,
    }
    return job_id


def get_import_job(org_id: str, job_id: str) -> dict:
    """Get import job status. Raises 404 if not found or wrong org."""
    job = _import_jobs.get(job_id)
    if not job or job.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Import job {job_id} not found",
            },
        )
    return job


def process_csv_import(
    db: Any,
    org_id: str,
    user_id: str,
    job_id: str,
    rows: list[dict],
) -> None:
    """
    Process a list of CSV rows and create leads.
    Updates the in-memory job record.
    Each row is sanitised per Section 11.2 before processing.
    """
    job = _import_jobs[job_id]
    job["status"] = "processing"
    job["total_rows"] = len(rows)

    required_fields = {"full_name", "source"}
    valid_sources = {
        "facebook_ad", "instagram_ad", "landing_page",
        "whatsapp_inbound", "manual_phone", "manual_referral", "import",
    }

    for i, row in enumerate(rows):
        try:
            # Sanitise all cell values — Section 11.2
            sanitised = {}
            for k, v in row.items():
                if isinstance(v, str):
                    sanitised[k] = v.strip()[:5000]
                else:
                    sanitised[k] = v

            # Normalise phone numbers — handles Excel scientific notation
            if sanitised.get('phone'):
                sanitised['phone'] = _normalise_phone(sanitised['phone'])
            if sanitised.get('whatsapp'):
                sanitised['whatsapp'] = _normalise_phone(sanitised['whatsapp'])

            print(f"DEBUG ROW {i+1}: phone={sanitised.get('phone')!r} email={sanitised.get('email')!r}")
            # Validate required fields
            if not sanitised.get("full_name"):
                raise ValueError("full_name is required")
            src = sanitised.get("source", "import")
            if src not in valid_sources:
                sanitised["source"] = "import"

            payload = LeadCreate(**sanitised)
            create_lead(db, org_id, user_id, payload)
            job["succeeded"] += 1
        except HTTPException as exc:
            detail = exc.detail or {}
            job["failed"] += 1
            job["errors"].append(
                {"row": i + 1, "message": detail.get("message", str(exc))}
            )
        except Exception as exc:  # pylint: disable=broad-except
            job["failed"] += 1
            job["errors"].append({"row": i + 1, "message": str(exc)})
        finally:
            job["processed"] += 1

    job["status"] = "done"
    job["completed_at"] = _now_iso()