# app/routers/admin.py
# Admin routes — Technical Spec Section 5.7
# All routes require Owner/Admin role (manage_users or manage_roles permission)
# GET/POST  /api/v1/admin/users
# PATCH/DELETE /api/v1/admin/users/{id}
# POST      /api/v1/admin/users/{id}/force-logout
# GET/POST  /api/v1/admin/roles
# PATCH/DELETE /api/v1/admin/roles/{id}
# GET/PUT   /api/v1/admin/routing-rules
# GET       /api/v1/admin/integrations
# POST      /api/v1/admin/integrations/{name}/reconnect

from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import Optional, List, ClassVar
from pydantic import BaseModel, field_validator, model_validator, EmailStr, Field
from app.database import get_supabase
from app.dependencies import get_current_org, require_permission
import httpx
import os
from app.services import admin_service
from datetime import datetime
from app.utils.org_gates import SYSTEM_DAILY_CUSTOMER_CEILING
from app.models.common import ok
import re as _re

_VALID_QUESTION_TYPES = {"multiple_choice", "list_select", "free_text", "yes_no"}
_VALID_LEAD_FIELDS = {
    "business_name", "business_type", "location", "problem_stated", "branches"
}
_ANSWER_KEY_RE = _re.compile(r'^[a-zA-Z0-9_]+$')



router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────

class QualificationFlowOption(BaseModel):
    id: str
    label: str  # validated per-question below (max 20 or 24 chars)
 
 
class QualificationFlowQuestion(BaseModel):
    id: str
    text: str  # max 300 chars
    type: str  # one of _VALID_QUESTION_TYPES
    answer_key: str  # max 50 chars, alphanumeric + underscore only
    map_to_lead_field: Optional[str] = None
    options: Optional[List[QualificationFlowOption]] = None
 
    @field_validator("text")
    @classmethod
    def _validate_text(cls, v: str) -> str:
        if len(v) > 300:
            raise ValueError("Question text must be 300 characters or fewer")
        return v
 
    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in _VALID_QUESTION_TYPES:
            raise ValueError(
                f"Question type must be one of: {', '.join(sorted(_VALID_QUESTION_TYPES))}"
            )
        return v
 
    @field_validator("answer_key")
    @classmethod
    def _validate_answer_key(cls, v: str) -> str:
        if len(v) > 50:
            raise ValueError("answer_key must be 50 characters or fewer")
        if not _ANSWER_KEY_RE.match(v):
            raise ValueError(
                "answer_key must contain only alphanumeric characters and underscores"
            )
        return v
 
    @field_validator("map_to_lead_field")
    @classmethod
    def _validate_map_to_lead_field(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_LEAD_FIELDS:
            raise ValueError(
                f"map_to_lead_field must be null or one of: {', '.join(sorted(_VALID_LEAD_FIELDS))}"
            )
        return v
 
    @model_validator(mode="after")
    def _validate_options(self) -> "QualificationFlowQuestion":
        q_type = self.type
        options = self.options or []
 
        if q_type == "free_text":
            if options:
                raise ValueError("free_text questions must not have options")
        else:
            if not options:
                raise ValueError(
                    f"{q_type} questions must have at least one option"
                )
            # Enforce max option counts and label lengths
            if q_type in ("multiple_choice", "yes_no"):
                if len(options) > 3:
                    raise ValueError(
                        f"{q_type} questions support a maximum of 3 options"
                    )
                for opt in options:
                    if len(opt.label) > 20:
                        raise ValueError(
                            "Button option labels must be 20 characters or fewer"
                        )
            elif q_type == "list_select":
                if len(options) > 10:
                    raise ValueError(
                        "list_select questions support a maximum of 10 options"
                    )
                for opt in options:
                    if len(opt.label) > 24:
                        raise ValueError(
                            "List option labels must be 24 characters or fewer"
                        )
        return self
 
 
class QualificationFlowUpdate(BaseModel):
    opening_message: Optional[str] = None  # max 500 chars
    handoff_message: Optional[str] = None  # max 500 chars
    questions: Optional[List[QualificationFlowQuestion]] = None  # max 5
 
    @field_validator("opening_message")
    @classmethod
    def _validate_opening(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("opening_message must be 500 characters or fewer")
        return v
 
    @field_validator("handoff_message")
    @classmethod
    def _validate_handoff(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("handoff_message must be 500 characters or fewer")
        return v
 
    @field_validator("questions")
    @classmethod
    def _validate_questions(cls, v: Optional[list]) -> Optional[list]:
        if v is not None and len(v) > 5:
            raise ValueError("A qualification flow may have a maximum of 5 questions")
        return v
 
 
# ── CONFIG-6 Pydantic models ──────────────────────────────────────────────

_CONFIGURABLE_STAGE_KEYS = {"new", "contacted", "meeting_done", "proposal_sent", "converted"}

_DEFAULT_PIPELINE_STAGES = [
    {"key": "new",           "label": "New Lead",      "enabled": True},
    {"key": "contacted",     "label": "Contacted",     "enabled": True},
    {"key": "meeting_done",  "label": "Demo Done",     "enabled": True},
    {"key": "proposal_sent", "label": "Proposal Sent", "enabled": True},
    {"key": "converted",     "label": "Converted",     "enabled": True},
]


class PipelineStageItem(BaseModel):
    key: str
    label: str = Field(..., min_length=1, max_length=50)
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if v not in _CONFIGURABLE_STAGE_KEYS:
            raise ValueError(
                f"Stage key '{v}' is not configurable. "
                f"Valid keys: {', '.join(sorted(_CONFIGURABLE_STAGE_KEYS))}"
            )
        return v

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Stage label is required")
        if len(v) > 50:
            raise ValueError("Stage label must be 50 characters or fewer")
        return v.strip()


class PipelineStageUpdate(BaseModel):
    stages: List[PipelineStageItem]

    @field_validator("stages")
    @classmethod
    def _validate_stages(cls, v: List[PipelineStageItem]) -> List[PipelineStageItem]:
        # new and converted must be present and enabled
        keys = {s.key for s in v}
        for required in ("new", "converted"):
            if required not in keys:
                raise ValueError(f"Stage '{required}' is required and cannot be removed")
        enabled_count = sum(1 for s in v if s.enabled)
        if enabled_count < 2:
            raise ValueError("At least 2 stages must be enabled (new and converted minimum)")
        return v


# ── Route handlers — add BEFORE any parameterised routes in admin.py ──────
 
# NOTE: `router`, `get_current_org`, `get_supabase`, `require_permission`,
# `success_response`, and `error_response` are already defined in admin.py.
# Do not redeclare them — these route functions slot in alongside existing routes.


@router.get("/pipeline-stages")
def get_pipeline_stages(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-6: Return org pipeline_stages config. Falls back to defaults if null."""
    result = (
        db.table("organisations")
        .select("pipeline_stages")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    stages = (data or {}).get("pipeline_stages") or _DEFAULT_PIPELINE_STAGES
    return ok(data={"stages": stages})


@router.patch("/pipeline-stages")
def update_pipeline_stages(
    payload: PipelineStageUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-6: Save org pipeline_stages config."""
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can update this setting."},
        )
    stages_data = [s.model_dump() for s in payload.stages]
    updates = {
        "pipeline_stages": stages_data,
        "updated_at": datetime.utcnow().isoformat(),
    }
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="pipeline_stages.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"stages": stages_data},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data={"stages": stages_data}, message="Pipeline stages saved")


# ── CONFIG-1 Pydantic models ──────────────────────────────────────────────

_DEFAULT_TICKET_CATEGORIES = [
    {"key": "technical_bug",     "label": "Technical Bug",     "enabled": True},
    {"key": "billing",           "label": "Billing",           "enabled": True},
    {"key": "feature_question",  "label": "Feature Question",  "enabled": True},
    {"key": "onboarding_help",   "label": "Onboarding Help",   "enabled": True},
    {"key": "account_access",    "label": "Account Access",    "enabled": True},
    {"key": "hardware",          "label": "Hardware",          "enabled": True},
]


class TicketCategoryItem(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        import re as _re2
        if not _re2.match(r'^[a-z0-9_]+$', v):
            raise ValueError("key must be lowercase alphanumeric and underscores only")
        return v

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("label is required")
        return v.strip()


class TicketCategoriesUpdate(BaseModel):
    categories: List[TicketCategoryItem]

    @field_validator("categories")
    @classmethod
    def _validate_categories(cls, v: List[TicketCategoryItem]) -> List[TicketCategoryItem]:
        if not v:
            raise ValueError("At least one category is required")
        enabled = [c for c in v if c.enabled]
        if not enabled:
            raise ValueError("At least one category must be enabled")
        keys = [c.key for c in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Category keys must be unique")
        return v


@router.get("/ticket-categories")
def get_ticket_categories(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-1: Return org ticket/KB category config. Falls back to defaults if null."""
    result = (
        db.table("organisations")
        .select("ticket_categories")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    categories = (data or {}).get("ticket_categories") or _DEFAULT_TICKET_CATEGORIES
    return ok(data={"categories": categories})


@router.patch("/ticket-categories")
def update_ticket_categories(
    payload: TicketCategoriesUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-1: Save org ticket/KB category config."""
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can update this setting."},
        )
    cats_data = [c.model_dump() for c in payload.categories]
    updates = {
        "ticket_categories": cats_data,
        "updated_at": datetime.utcnow().isoformat(),
    }
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="ticket_categories.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"categories": cats_data},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data={"categories": cats_data}, message="Ticket categories saved")


@router.get("/qualification-flow")
async def get_qualification_flow(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    WH-1b: Return the org's qualification_flow JSONB config.
    Returns null if not yet configured.
    Owner / ops_manager only.
    Pattern 28 — get_current_org. Pattern 62 — db via Depends.
    """
 
    org_id = org["org_id"]
 
    result = (
        db.table("organisations")
        .select("qualification_flow")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
 
    flow = (data or {}).get("qualification_flow")
    return ok({"qualification_flow": flow})
 
 
@router.patch("/qualification-flow")
async def update_qualification_flow(
    payload: QualificationFlowUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    WH-1b: Save the org's qualification_flow JSONB config.
    Validates question types, answer_key format, map_to_lead_field values,
    and max 5 questions before saving.
    Owner / ops_manager only.
    Pattern 28 — get_current_org. Pattern 62 — db via Depends. S1 — org_id from JWT.
    S3 — Pydantic validation on every field.
    """
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can update this setting."},
        )
 
    org_id = org["org_id"]
 
    # Build the flow dict from validated payload
    # Only include keys that were explicitly provided
    flow_update: dict = {}
 
    if payload.opening_message is not None:
        flow_update["opening_message"] = payload.opening_message
    if payload.handoff_message is not None:
        flow_update["handoff_message"] = payload.handoff_message
    if payload.questions is not None:
        # Serialise validated question models to plain dicts
        flow_update["questions"] = [
            {
                "id": q.id,
                "text": q.text,
                "type": q.type,
                "answer_key": q.answer_key,
                "map_to_lead_field": q.map_to_lead_field,
                "options": [
                    {"id": opt.id, "label": opt.label}
                    for opt in (q.options or [])
                ] if q.options else None,
            }
            for q in payload.questions
        ]
 
    if not flow_update:
        raise HTTPException(status_code=400, detail="No fields provided to update")
 
    # Merge with existing flow (partial update)
    existing_result = (
        db.table("organisations")
        .select("qualification_flow")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    existing_data = existing_result.data
    if isinstance(existing_data, list):
        existing_data = existing_data[0] if existing_data else None
    existing_flow = (existing_data or {}).get("qualification_flow") or {}
 
    merged_flow = {**existing_flow, **flow_update}
 
    db.table("organisations").update(
        {"qualification_flow": merged_flow}
    ).eq("id", org_id).execute()
 
    return ok({"qualification_flow": merged_flow})


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role_id: str
    whatsapp_number: Optional[str] = None
    password: str


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role_id: Optional[str] = None
    is_active: Optional[bool] = None
    is_out_of_office: Optional[bool] = None
    whatsapp_number: Optional[str] = None
    notification_prefs: Optional[dict] = None


class CreateRoleRequest(BaseModel):
    name: str
    template: str
    permissions: dict


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = None
    permissions: Optional[dict] = None


class RoutingRuleItem(BaseModel):
    event_type: str
    route_to_role_id: Optional[str] = None
    route_to_user_id: Optional[str] = None
    also_notify_role_id: Optional[str] = None
    channel: str = "whatsapp_inapp"
    within_hours_only: bool = True
    escalate_after_minutes: Optional[int] = None
    escalate_to_role_id: Optional[str] = None


class UpdateRoutingRulesRequest(BaseModel):
    rules: list[RoutingRuleItem]

class CreateOverrideRequest(BaseModel):
    user_id:        str
    permission_key: str  = Field(max_length=100)
    granted:        bool


class UpdateRoutingRuleRequest(BaseModel):
    event_type:             Optional[str]  = Field(None, max_length=100)
    route_to_role_id:       Optional[str]  = None
    route_to_user_id:       Optional[str]  = None
    also_notify_role_id:    Optional[str]  = None
    channel:                Optional[str]  = Field(None, max_length=50)
    within_hours_only:      Optional[bool] = None
    escalate_after_minutes: Optional[int]  = None
    escalate_to_role_id:    Optional[str]  = None

class CommissionSettingsUpdate(BaseModel):
    """Payload for PATCH /admin/commission-settings."""
    commission_enabled:             Optional[bool]  = None
    commission_eligible_templates:  Optional[list]  = None
    commission_rate_type:           Optional[str]   = Field(None, max_length=20)
    commission_rate_value:          Optional[float] = Field(None, ge=0)
    commission_trigger:             Optional[str]   = Field(None, max_length=20)
    commission_whatsapp_notify:     Optional[bool]  = None


class ScoringRubricUpdate(BaseModel):
    """Payload for PATCH /admin/scoring-rubric — Feature 4 (Module 01 gaps)."""
    scoring_business_context:        Optional[str] = None
    scoring_hot_criteria:            Optional[str] = None
    scoring_warm_criteria:           Optional[str] = None
    scoring_cold_criteria:           Optional[str] = None
    scoring_qualification_questions: Optional[str] = None

class QualificationBotUpdate(BaseModel):
    """M01-3: Update org qualification bot config."""
    org_whatsapp_number:          Optional[str] = Field(None, max_length=20)
    org_business_contact_number:  Optional[str] = Field(None, max_length=20)
    qualification_bot_name:       Optional[str] = Field(None, max_length=100)
    qualification_opening_message: Optional[str] = Field(None, max_length=2000)
    qualification_script:         Optional[str] = Field(None, max_length=3000)
    qualification_fields:         Optional[list] = None
    qualification_handoff_triggers: Optional[str] = Field(None, max_length=500)
    qualification_fallback_hours: Optional[int]  = Field(None, ge=1, le=168)
    qualification_sending_mode: Optional[str] = Field(
            None,
            pattern=r"^(full_approval|review_window|auto_send)$",
        )
    review_window_minutes: Optional[int] = Field(None, ge=1, le=60) 


class SlaConfigUpdate(BaseModel):
    """M01-6: Update org-level lead response SLA targets per score tier."""
    sla_hot_hours:  Optional[int] = Field(None, ge=1, le=72,
        description="Hours before a Hot lead is considered overdue (default 1)")
    sla_warm_hours: Optional[int] = Field(None, ge=1, le=168,
        description="Hours before a Warm lead is considered overdue (default 4)")
    sla_cold_hours: Optional[int] = Field(None, ge=1, le=720,
        description="Hours before a Cold lead is considered overdue (default 24)")


# ── Valid role templates — Technical Spec Section 3.1 ─────────
VALID_TEMPLATES = {
    "owner", "ops_manager", "sales_agent",
    "customer_success", "support_agent", "finance", "read_only", "affiliate_partner"
}


# ── Helper: write audit log ───────────────────────────────────
# db is passed explicitly — never sourced from a module-level global
def write_audit_log(
    db,
    org_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    ip_address: Optional[str] = None,
):
    try:
        db.table("audit_logs").insert({
            "org_id": org_id,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
            "ip_address": ip_address,
        }).execute()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Audit log write failed: %s", exc)


# ============================================================
# USER MANAGEMENT
# ============================================================

@router.get("/users")
async def list_users(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """
    Lists all users in the organisation.
    Admin only — requires manage_users permission.
    """
    result = (
        db.table("users")
        .select("*, roles(id, name, template)")
        .eq("org_id", org["org_id"])
        .order("created_at", desc=False)
        .execute()
    )
    return {"success": True, "data": result.data, "error": None}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """
    Creates a new user in Supabase Auth and inserts into users table.
    Admin only — requires manage_users permission.
    Writes to audit_logs.
    """
    # Validate role belongs to this org
    role_check = (
        db.table("roles")
        .select("id")
        .eq("id", payload.role_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not role_check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Role not found in this organisation"},
        )

    # Create Supabase Auth user via Admin REST API
    # Direct httpx call is more reliable than db.auth.admin.create_user()
    # across different supabase-py versions and project configurations.
    _supabase_url = os.getenv("SUPABASE_URL", "").strip()
    _service_key  = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    print("KEY_REPR:", repr(_service_key[:30]), flush=True)
    try:
        _resp = httpx.post(
            f"{_supabase_url}/auth/v1/admin/users",
            headers={
                "Authorization": f"Bearer {_service_key}",
                "apikey":        _service_key,
                "Content-Type":  "application/json",
            },
            json={
                "email":         payload.email,
                "password":      payload.password,
                "email_confirm": True,
            },
            timeout=10.0,
        )
        _resp.raise_for_status()
        new_user_id = _resp.json()["id"]
    except httpx.HTTPStatusError as e:
        _body = e.response.json()
        _msg  = _body.get("message") or _body.get("msg") or str(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": _msg},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )

    # Insert into users table
    user_data = {
        "id": new_user_id,
        "org_id": org["org_id"],
        "role_id": payload.role_id,
        "email": payload.email,
        "full_name": payload.full_name,
        "whatsapp_number": payload.whatsapp_number,
        "is_active": True,
        "is_out_of_office": False,
    }
    result = db.table("users").insert(user_data).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="user.created",
        resource_type="user",
        resource_id=new_user_id,
        new_value={"email": payload.email, "role_id": payload.role_id},
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": result.data[0], "error": None}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    request: Request,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """
    Updates a user's role, status, or profile fields.
    Admin only. Cannot modify users outside own org.
    Writes to audit_logs.
    """
    existing = (
        db.table("users")
        .select("*")
        .eq("id", user_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )

    if payload.role_id:
        role_check = (
            db.table("roles")
            .select("id")
            .eq("id", payload.role_id)
            .eq("org_id", org["org_id"])
            .maybe_single()
            .execute()
        )
        if not role_check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Role not found in this organisation"},
            )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )

    result = (
        db.table("users")
        .update(update_data)
        .eq("id", user_id)
        .eq("org_id", org["org_id"])
        .execute()
    )

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="user.updated",
        resource_type="user",
        resource_id=user_id,
        old_value=existing.data,
        new_value=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": result.data[0] if result.data else None, "error": None}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    request: Request,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """
    Deactivates a user — sets is_active to false.
    Soft deactivation only, never hard delete — Technical Spec Section 9.5.
    Admin cannot deactivate themselves.
    Writes to audit_logs.
    """
    if user_id == org["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "You cannot deactivate your own account"},
        )

    existing = (
        db.table("users")
        .select("*")
        .eq("id", user_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )

    db.table("users").update({"is_active": False}).eq("id", user_id).eq("org_id", org["org_id"]).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="user.deactivated",
        resource_type="user",
        resource_id=user_id,
        old_value={"is_active": True},
        new_value={"is_active": False},
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": {"message": "User deactivated successfully"}, "error": None}


@router.post("/users/{user_id}/force-logout")
async def force_logout_user(
    user_id: str,
    request: Request,
    org=Depends(require_permission("force_logout_users")),
    db=Depends(get_supabase),
):
    """
    Invalidates all active sessions for a user via Supabase Auth admin.
    Technical Spec Section 11.1 — session invalidation.
    Writes to audit_logs.
    """
    existing = (
        db.table("users")
        .select("id")
        .eq("id", user_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "User not found"},
        )

    try:
        db.auth.admin.sign_out(user_id)
    except Exception:
        pass  # Best-effort — still log the action

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="user.force_logout",
        resource_type="user",
        resource_id=user_id,
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": {"message": "User sessions invalidated"}, "error": None}


# ============================================================
# ROLE MANAGEMENT
# ============================================================

@router.get("/roles")
async def list_roles(
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """Lists all custom roles for the organisation."""
    result = (
        db.table("roles")
        .select("*")
        .eq("org_id", org["org_id"])
        .order("created_at", desc=False)
        .execute()
    )
    return {"success": True, "data": result.data, "error": None}


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: CreateRoleRequest,
    request: Request,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Creates a new role from a permission template.
    Template must be one of the 7 defined in Technical Spec Section 3.1.
    Writes to audit_logs.
    """
    if payload.template not in VALID_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": f"Template must be one of: {', '.join(sorted(VALID_TEMPLATES))}",
            },
        )

    role_data = {
        "org_id": org["org_id"],
        "name": payload.name,
        "template": payload.template,
        "permissions": payload.permissions,
    }
    result = db.table("roles").insert(role_data).execute()
    new_role = result.data[0]

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="role.created",
        resource_type="role",
        resource_id=new_role["id"],
        new_value={"name": payload.name, "template": payload.template},
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": new_role, "error": None}


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: str,
    payload: UpdateRoleRequest,
    request: Request,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Updates a role's name or permissions.
    Cannot update roles outside this org.
    Writes to audit_logs.
    """
    existing = (
        db.table("roles")
        .select("*")
        .eq("id", role_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Role not found"},
        )

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    result = (
        db.table("roles")
        .update(update_data)
        .eq("id", role_id)
        .eq("org_id", org["org_id"])
        .execute()
    )

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="role.updated",
        resource_type="role",
        resource_id=role_id,
        old_value=existing.data,
        new_value=update_data,
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": result.data[0] if result.data else None, "error": None}


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    request: Request,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Deletes a role — blocked if any users are currently assigned to it.
    Technical Spec Section 5.7.
    Writes to audit_logs.
    """
    existing = (
        db.table("roles")
        .select("*")
        .eq("id", role_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Role not found"},
        )

    # Block delete if users are assigned — Technical Spec Section 5.7
    assigned_users = (
        db.table("users")
        .select("id", count="exact")
        .eq("role_id", role_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    if assigned_users.count and assigned_users.count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_DETECTED",
                "message": f"Cannot delete role — {assigned_users.count} user(s) are assigned to it",
            },
        )

    db.table("roles").delete().eq("id", role_id).eq("org_id", org["org_id"]).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="role.deleted",
        resource_type="role",
        resource_id=role_id,
        old_value=existing.data,
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": {"message": "Role deleted successfully"}, "error": None}


# ============================================================
# ROUTING RULES
# ============================================================

@router.get("/routing-rules")
async def get_routing_rules(
    org=Depends(require_permission("manage_routing_rules")),
    db=Depends(get_supabase),
):
    """Gets all routing rule configurations for the organisation."""
    result = (
        db.table("routing_rules")
        .select(
            "*, "
            "roles!routing_rules_route_to_role_id_fkey(name), "
            "users!routing_rules_route_to_user_id_fkey(full_name)"
        )
        .eq("org_id", org["org_id"])
        .execute()
    )
    return {"success": True, "data": result.data, "error": None}


@router.put("/routing-rules")
async def update_routing_rules(
    payload: UpdateRoutingRulesRequest,
    request: Request,
    org=Depends(require_permission("manage_routing_rules")),
    db=Depends(get_supabase),
):
    """
    Full replacement of routing rules for the organisation.
    Deletes all existing rules and inserts new set.
    Technical Spec Section 5.7 — PUT replaces entire ruleset.
    Writes to audit_logs.
    """
    old_rules = (
        db.table("routing_rules")
        .select("*")
        .eq("org_id", org["org_id"])
        .execute()
    )

    db.table("routing_rules").delete().eq("org_id", org["org_id"]).execute()

    if payload.rules:
        new_rules = [
            {**rule.model_dump(), "org_id": org["org_id"]}
            for rule in payload.rules
        ]
        result = db.table("routing_rules").insert(new_rules).execute()
        inserted = result.data
    else:
        inserted = []

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="routing_rules.updated",
        resource_type="routing_rules",
        resource_id=None,
        old_value={"rules": old_rules.data},
        new_value={"rules": inserted},
        ip_address=request.client.host if request.client else None,
    )

    return {"success": True, "data": inserted, "error": None}


# ============================================================
# INTEGRATION STATUS
# ============================================================

@router.get("/integrations")
async def get_integration_status(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Returns live status of all integrations.
    Technical Spec Section 5.7 and Section 12.7.
    """
    from app.config import settings

    integrations = {
        "whatsapp": {
            "name": "WhatsApp (Meta Cloud API)",
            "configured": bool(settings.META_WHATSAPP_TOKEN and settings.META_WHATSAPP_PHONE_ID),
            "status": "connected" if settings.META_WHATSAPP_TOKEN else "not_configured",
        },
        "meta_lead_ads": {
            "name": "Meta Lead Ads",
            "configured": bool(settings.META_VERIFY_TOKEN and settings.META_APP_SECRET),
            "status": "connected" if settings.META_VERIFY_TOKEN else "not_configured",
        },
        "anthropic": {
            "name": "Anthropic Claude API",
            "configured": bool(settings.ANTHROPIC_API_KEY),
            "status": "connected" if settings.ANTHROPIC_API_KEY else "not_configured",
        },
        "email": {
            "name": "Resend (Email)",
            "configured": bool(settings.RESEND_API_KEY),
            "status": "connected" if settings.RESEND_API_KEY else "not_configured",
        },
        "redis": {
            "name": "Redis (Background Jobs)",
            "configured": bool(settings.REDIS_URL),
            "status": "connected" if settings.REDIS_URL else "not_configured",
        },
    }

    return {"success": True, "data": integrations, "error": None}


@router.post("/integrations/{name}/reconnect")
async def reconnect_integration(
    name: str,
    org=Depends(require_permission("manage_integrations")),
    db=Depends(get_supabase),
):
    """
    Triggers reconnection for a named integration.
    Technical Spec Section 5.7.
    Valid names: whatsapp, meta_lead_ads, anthropic, email, redis
    """
    valid_names = {"whatsapp", "meta_lead_ads", "anthropic", "email", "redis"}
    if name not in valid_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": f"Unknown integration '{name}'. Valid: {', '.join(sorted(valid_names))}",
            },
        )

    # In Phase 1 this is a stub — full reconnect logic added per integration in later phases
    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action=f"integration.reconnect_requested",
        resource_type="integration",
        resource_id=name,
        new_value={"integration": name},
    )

    return {
        "success": True,
        "data": {"integration": name, "status": "reconnect_initiated"},
        "error": None,
    }



# ============================================================
# ROLE USER OVERRIDES  (Phase 8A)
# user_permission_overrides table — individual grant/revoke
# ============================================================

@router.get("/roles/{role_id}/overrides")
async def list_user_overrides(
    role_id: str,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Lists all user_permission_overrides for users assigned to this role.
    Returns each override with an attached 'user' sub-object for display.
    """
    overrides = admin_service.list_user_overrides(
        role_id=role_id, org_id=org["org_id"], db=db
    )
    return {"success": True, "data": overrides, "error": None}


@router.post("/roles/{role_id}/overrides", status_code=status.HTTP_201_CREATED)
async def create_user_override(
    role_id: str,
    payload: CreateOverrideRequest,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Grants (or explicitly denies) a single permission to a specific user.
    The user must already be assigned to the specified role in this org.
    Writes to audit_logs.
    """
    override = admin_service.create_user_override(
        role_id=role_id,
        user_id=payload.user_id,
        org_id=org["org_id"],
        db=db,
        permission_key=payload.permission_key,
        granted=payload.granted,
        caller_id=org["id"],
    )
    return {"success": True, "data": override, "error": None}


@router.delete("/roles/{role_id}/overrides/{override_id}")
async def delete_user_override(
    role_id: str,
    override_id: str,
    org=Depends(require_permission("manage_roles")),
    db=Depends(get_supabase),
):
    """
    Removes a single user permission override by its UUID.
    Writes to audit_logs.
    """
    admin_service.delete_user_override(
        override_id=override_id,
        org_id=org["org_id"],
        db=db,
        caller_id=org["id"],
    )
    return {"success": True, "data": {"message": "Override removed"}, "error": None}


# ============================================================
# INDIVIDUAL ROUTING RULE CRUD  (Phase 8A)
# These sit alongside the existing PUT /routing-rules (full-replace).
# Use POST to add one rule; PATCH / DELETE to manage specific rules.
# ============================================================

@router.post("/routing-rules", status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    payload: RoutingRuleItem,
    org=Depends(require_permission("manage_routing_rules")),
    db=Depends(get_supabase),
):
    """
    Creates a single routing rule.  Writes to audit_logs.
    """
    rule = admin_service.create_routing_rule(
        org_id=org["org_id"],
        db=db,
        data=payload.model_dump(),
        caller_id=org["id"],
    )
    return {"success": True, "data": rule, "error": None}


@router.patch("/routing-rules/{rule_id}")
async def update_routing_rule(
    rule_id: str,
    payload: UpdateRoutingRuleRequest,
    org=Depends(require_permission("manage_routing_rules")),
    db=Depends(get_supabase),
):
    """
    Partially updates a single routing rule.
    Only fields explicitly provided in the payload are changed.
    Raises 422 if no fields are provided.
    Writes to audit_logs.
    """
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided to update"},
        )
    rule = admin_service.update_routing_rule(
        rule_id=rule_id,
        org_id=org["org_id"],
        db=db,
        data=update_data,
        caller_id=org["id"],
    )
    return {"success": True, "data": rule, "error": None}


@router.delete("/routing-rules/{rule_id}")
async def delete_routing_rule(
    rule_id: str,
    org=Depends(require_permission("manage_routing_rules")),
    db=Depends(get_supabase),
):
    """
    Deletes a single routing rule.  Writes to audit_logs.
    """
    admin_service.delete_routing_rule(
        rule_id=rule_id,
        org_id=org["org_id"],
        db=db,
        caller_id=org["id"],
    )
    return {"success": True, "data": {"message": "Routing rule deleted"}, "error": None}

# ============================================================
# COMMISSION SETTINGS  (Phase 9C)
# Stored as columns on the organisations table.
# ============================================================

@router.get("/commission-settings")
async def get_commission_settings(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Get the org's commission configuration from the organisations table."""
    result = (
        db.table("organisations")
        .select(
            "commission_enabled, commission_eligible_templates, "
            "commission_rate_type, commission_rate_value, "
            "commission_trigger, commission_whatsapp_notify"
        )
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return {"success": True, "data": data or {}, "error": None}

@router.patch("/commission-settings")
async def update_commission_settings(
    payload: CommissionSettingsUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Update commission configuration for this org."""
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided"},
        )
    db.table("organisations").update(update_data).eq("id", org["org_id"]).execute()
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="commission_settings.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value=update_data,
    )
    return {"success": True, "data": {"message": "Commission settings updated"}, "error": None}
 

# ---------------------------------------------------------------------------
# GET /api/v1/admin/scoring-rubric — Feature 4 (Module 01 gaps)
# ---------------------------------------------------------------------------

@router.get("/scoring-rubric")
async def get_scoring_rubric(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Return the org's AI lead scoring rubric from the organisations table."""
    result = (
        db.table("organisations")
        .select(
            "scoring_business_context, scoring_hot_criteria, "
            "scoring_warm_criteria, scoring_cold_criteria, "
            "scoring_qualification_questions"
        )
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return {"success": True, "data": data or {}, "error": None}

# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/scoring-rubric
# ---------------------------------------------------------------------------

@router.patch("/scoring-rubric")
async def update_scoring_rubric(
    payload: ScoringRubricUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Update the org's AI lead scoring rubric. All fields are optional."""
    # Allow explicit empty string (clears the field) but exclude unset fields
    update_data = {
        k: v for k, v in payload.model_dump().items()
        if v is not None
    }
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": "No fields provided"},
        )
    db.table("organisations").update(update_data).eq("id", org["org_id"]).execute()
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="scoring_rubric.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value=update_data,
    )
    return {"success": True, "data": {"message": "Scoring rubric updated"}, "error": None}

@router.get("/qualification-bot")
def get_qualification_bot(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    result = (
        db.table("organisations")
        .select(
            "org_whatsapp_number, org_business_contact_number, "
            "qualification_bot_name, qualification_opening_message, "
            "qualification_script, qualification_fields, "
            "qualification_handoff_triggers, qualification_fallback_hours, "
            "qualification_sending_mode, review_window_minutes"
        )
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return ok(data=data or {})


@router.patch("/qualification-bot")
def update_qualification_bot(
    payload: QualificationBotUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    updates = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    if not updates:
        return ok(data={}, message="No changes to save")
    updates["updated_at"] = datetime.utcnow().isoformat()
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data=data, message="Qualification bot settings saved")


@router.post("/qualification-bot/ai-recommendations")
def get_qualification_ai_recommendations(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_result = (
        db.table("organisations")
        .select("name, industry")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    org_data = org_result.data
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}
    from app.services.ai_service import generate_qualification_defaults
    suggestions = generate_qualification_defaults(org_data or {})
    return ok(data=suggestions, message="AI recommendations generated")

# ── M01-6 — Lead SLA Config ──────────────────────────────────────────────────

@router.get("/sla-config")
def get_sla_config(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Return org SLA hour targets for hot / warm / cold leads."""
    result = (
        db.table("organisations")
        .select("sla_hot_hours, sla_warm_hours, sla_cold_hours")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    # Return defaults if columns not yet set
    return ok(data={
        "sla_hot_hours":  (data or {}).get("sla_hot_hours",  1),
        "sla_warm_hours": (data or {}).get("sla_warm_hours", 4),
        "sla_cold_hours": (data or {}).get("sla_cold_hours", 24),
    })


@router.patch("/sla-config")
def update_sla_config(
    payload: SlaConfigUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Update org SLA hour targets. Only supplied fields are changed."""
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return ok(data={}, message="No changes to save")
    updates["updated_at"] = datetime.utcnow().isoformat()
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data=data, message="SLA targets saved")


# ── M01-10a — Nurture Config ──────────────────────────────────────────────────

class NurtureConfigUpdate(BaseModel):
    """M01-10a: Update org nurture track configuration."""
    nurture_track_enabled:   Optional[bool] = None
    conversion_attempt_days: Optional[int]  = Field(None, ge=1, le=365,
        description="Days of inactivity before a lead is graduated to nurture (default 14)")
    nurture_interval_days:   Optional[int]  = Field(None, ge=1, le=365,
        description="Days between nurture messages for a lead (default 7)")
    nurture_sequence:        Optional[list] = None


class TriageConfigUpdate(BaseModel):
    """WH-0: Update org WhatsApp triage menu config and unknown-contact behavior."""
    whatsapp_triage_config:    Optional[dict] = None
    unknown_contact_behavior:  Optional[str]  = Field(
        None,
        pattern=r"^(triage_first|qualify_immediately)$",
        description="triage_first (default) or qualify_immediately",
    )

    _VALID_TRIAGE_ACTIONS: ClassVar[frozenset] = frozenset({
        # Unknown contact actions
        "qualify",
        "identify_customer",
        "route_to_role",
        "free_form",
        "commerce_entry",  # COMM-1
        # Customer section actions
        "create_ticket",
        "kb_enquiry",
        "support_ticket",
    })

    @field_validator("whatsapp_triage_config")
    @classmethod
    def validate_triage_action_values(cls, v):
        """
        Reject any triage config item whose 'action' is not in _VALID_TRIAGE_ACTIONS.
        Walks all sections and their items arrays.
        """
        if v is None:
            return v
        valid = cls._VALID_TRIAGE_ACTIONS
        for section_key, section in v.items():
            if not isinstance(section, dict):
                continue
            for item in (section.get("items") or []):
                action = item.get("action")
                if action and action not in valid:
                    raise ValueError(
                        f"Invalid triage action '{action}' in section '{section_key}'. "
                        f"Valid values: {sorted(valid)}"
                    )
        return v


@router.get("/nurture-config")
def get_nurture_config(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Return org nurture track configuration with defaults."""
    result = (
        db.table("organisations")
        .select(
            "nurture_track_enabled, conversion_attempt_days, "
            "nurture_interval_days, nurture_sequence"
        )
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    defaults = {
        "nurture_track_enabled":   False,
        "conversion_attempt_days": 14,
        "nurture_interval_days":   7,
        "nurture_sequence":        [],
    }
    return ok(data={**defaults, **(data or {})})


@router.patch("/nurture-config")
def update_nurture_config(
    payload: NurtureConfigUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Update nurture track configuration for this org."""
    # exclude_unset keeps only fields the caller explicitly sent;
    # filter None to avoid overwriting booleans/lists with null unintentionally,
    # but False and [] are kept (both are not None).
    updates = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    # Explicit False for the toggle must survive the filter above
    if payload.nurture_track_enabled is False:
        updates["nurture_track_enabled"] = False
    # Explicit empty list (clearing the sequence) must survive too
    if payload.nurture_sequence is not None:
        updates["nurture_sequence"] = payload.nurture_sequence

    if not updates:
        return ok(data={}, message="No changes to save")

    updates["updated_at"] = datetime.utcnow().isoformat()
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="nurture_config.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={k: v for k, v in updates.items() if k != "updated_at"},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data=data, message="Nurture configuration saved")


# ============================================================
# WH-0 — TRIAGE CONFIG
# ============================================================

@router.get("/triage-config")
def get_triage_config(
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Return org WhatsApp triage config and unknown-contact behavior. WH-0."""
    result = (
        db.table("organisations")
        .select("whatsapp_triage_config, unknown_contact_behavior")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    defaults = {
        "whatsapp_triage_config":   None,
        "unknown_contact_behavior": "triage_first",
    }
    return ok(data={**defaults, **(data or {})})


@router.patch("/triage-config")
def update_triage_config(
    payload: TriageConfigUpdate,
    org=Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    """Update org WhatsApp triage config and/or unknown-contact behavior. WH-0."""
    updates = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    if not updates:
        return ok(data={}, message="No changes to save")

    updates["updated_at"] = datetime.utcnow().isoformat()
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="triage_config.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={k: v for k, v in updates.items() if k != "updated_at"},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data=data, message="Triage configuration saved")

# ── CONFIG-2 — Drip Business Types ───────────────────────────────────────────

_DEFAULT_DRIP_BUSINESS_TYPES: list = []
# null / empty list = all business types are eligible (unrestricted)


class DripBusinessTypeItem(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        import re as _re3
        if not _re3.match(r'^[a-z0-9_]+$', v):
            raise ValueError("key must be lowercase alphanumeric and underscores only")
        return v

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("label is required")
        if len(v) > 80:
            raise ValueError("label must be 80 characters or fewer")
        return v.strip()


class DripBusinessTypesUpdate(BaseModel):
    business_types: List[DripBusinessTypeItem]

    @field_validator("business_types")
    @classmethod
    def _validate_types(
        cls, v: List[DripBusinessTypeItem]
    ) -> List[DripBusinessTypeItem]:
        keys = [t.key for t in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Business type keys must be unique")
        return v


@router.get("/drip-business-types")
def get_drip_business_types(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-2: Return org drip business types config. Falls back to empty list if null."""
    result = (
        db.table("organisations")
        .select("drip_business_types")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    types = (data or {}).get("drip_business_types") or _DEFAULT_DRIP_BUSINESS_TYPES
    return ok(data={"business_types": types})


@router.patch("/drip-business-types")
def update_drip_business_types(
    payload: DripBusinessTypesUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-2: Save org drip business types config."""
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can update this setting."},
        )
    types_data = [t.model_dump() for t in payload.business_types]
    updates = {
        "drip_business_types": types_data,
        "updated_at": datetime.utcnow().isoformat(),
    }
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="drip_business_types.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"business_types": types_data},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data={"business_types": types_data}, message="Drip business types saved")

# ── CONFIG-3 — SLA Business Hours ────────────────────────────────────────────

_DAYS_OF_WEEK = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

_DEFAULT_SLA_BUSINESS_HOURS = {
    "timezone": "Africa/Lagos",
    "days": {
        "monday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "tuesday":   {"enabled": True,  "open": "08:00", "close": "18:00"},
        "wednesday": {"enabled": True,  "open": "08:00", "close": "18:00"},
        "thursday":  {"enabled": True,  "open": "08:00", "close": "18:00"},
        "friday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "saturday":  {"enabled": False, "open": None,    "close": None},
        "sunday":    {"enabled": False, "open": None,    "close": None},
    },
}


class SLADayConfig(BaseModel):
    enabled: bool = False
    open:    Optional[str] = None   # "HH:MM" 24-hour
    close:   Optional[str] = None   # "HH:MM" 24-hour

    @model_validator(mode="after")
    def _validate_hours(self) -> "SLADayConfig":
        import re as _re4
        _time_re = _re4.compile(r'^\d{2}:\d{2}$')
        if self.enabled:
            if not self.open or not _time_re.match(self.open):
                raise ValueError("open time must be HH:MM when day is enabled")
            if not self.close or not _time_re.match(self.close):
                raise ValueError("close time must be HH:MM when day is enabled")
            # open must be before close
            if self.open >= self.close:
                raise ValueError("open time must be before close time")
        return self


class SLABusinessHoursUpdate(BaseModel):
    timezone: Optional[str] = None
    days:     Optional[dict] = None  # key = day name, value = SLADayConfig-compatible dict

    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Basic sanity check — full pytz validation would add a dependency
        if len(v) > 60 or "/" not in v:
            raise ValueError(
                "timezone must be a valid IANA timezone string e.g. 'Africa/Lagos'"
            )
        return v

    @field_validator("days")
    @classmethod
    def _validate_days(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        _days = {
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        }
        for day_name, day_cfg in v.items():
            if day_name not in _days:
                raise ValueError(
                    f"'{day_name}' is not a valid day. "
                    f"Must be one of: {', '.join(sorted(_days))}"
                )
            # Validate each day's config via the SLADayConfig model
            SLADayConfig(**day_cfg)
        return v


@router.get("/sla-business-hours")
def get_sla_business_hours(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-3: Return org SLA business hours config. Falls back to defaults if null."""
    result = (
        db.table("organisations")
        .select("sla_business_hours")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    hours = (data or {}).get("sla_business_hours") or _DEFAULT_SLA_BUSINESS_HOURS
    return ok(data={"sla_business_hours": hours})


@router.patch("/sla-business-hours")
def update_sla_business_hours(
    payload: SLABusinessHoursUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """CONFIG-3: Save org SLA business hours config."""
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can update this setting."},
        )

    # Load current config so we do a proper merge
    current_result = (
        db.table("organisations")
        .select("sla_business_hours")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    current_data = current_result.data
    if isinstance(current_data, list):
        current_data = current_data[0] if current_data else {}
    current_hours = (current_data or {}).get("sla_business_hours") or _DEFAULT_SLA_BUSINESS_HOURS

    # Merge: only replace fields that were explicitly sent
    merged = dict(current_hours)
    if payload.timezone is not None:
        merged["timezone"] = payload.timezone
    if payload.days is not None:
        # Merge day-by-day so a partial days dict doesn't wipe unconfigured days
        merged_days = dict(merged.get("days") or {})
        for day_name, day_cfg in payload.days.items():
            merged_days[day_name] = day_cfg if isinstance(day_cfg, dict) else day_cfg.model_dump()
        merged["days"] = merged_days

    updates = {
        "sla_business_hours": merged,
        "updated_at": datetime.utcnow().isoformat(),
    }
    result = (
        db.table("organisations")
        .update(updates)
        .eq("id", org["org_id"])
        .execute()
    )
    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="sla_business_hours.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"sla_business_hours": merged},
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else updates
    return ok(data={"sla_business_hours": merged}, message="SLA business hours saved")

# ── SM-1: Sales Mode Engine ───────────────────────────────────────────────────
# Append these routes + models to the bottom of app/routers/admin.py

from typing import Literal

_CONTACT_MENU_ACTION_TYPES = {
    "qualify",
    "kb_enquiry",
    "support_ticket",
    "route_to_role",
    "free_form",
}

_CONTACT_MENU_ROLE_OPTIONS = {"owner", "ops_manager", "sales_agent", "support_agent", "finance"}


class SalesModeUpdate(BaseModel):
    mode: Literal["consultative", "transactional", "hybrid"]


class ContactMenuItem(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=24)
    description: Optional[str] = Field(default=None, max_length=72)
    action: str
    role: Optional[str] = None  # only required when action == "route_to_role"

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label is required")
        if len(v) > 24:
            raise ValueError("label must be 24 characters or fewer")
        return v

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in _CONTACT_MENU_ACTION_TYPES:
            raise ValueError(
                f"action must be one of: {', '.join(sorted(_CONTACT_MENU_ACTION_TYPES))}"
            )
        return v

    @model_validator(mode="after")
    def _validate_role(self) -> "ContactMenuItem":
        if self.action == "route_to_role":
            if not self.role or self.role not in _CONTACT_MENU_ROLE_OPTIONS:
                raise ValueError(
                    f"role is required when action is 'route_to_role'. "
                    f"Must be one of: {', '.join(sorted(_CONTACT_MENU_ROLE_OPTIONS))}"
                )
        return self


class ContactMenuSection(BaseModel):
    greeting: Optional[str] = Field(default=None, max_length=200)
    section_title: Optional[str] = Field(default=None, max_length=24)
    items: List[ContactMenuItem]

    @field_validator("items")
    @classmethod
    def _validate_items(cls, v: list) -> list:
        if len(v) > 10:
            raise ValueError("A contact menu may have a maximum of 10 items")
        return v


class ContactMenusUpdate(BaseModel):
    returning_contact_menu: Optional[ContactMenuSection] = None
    known_customer_menu: Optional[ContactMenuSection] = None


# ── Sales mode routes ─────────────────────────────────────────────────────────

@router.get("/sales-mode")
def get_sales_mode(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """SM-1: Return org sales_mode. Defaults to 'consultative' if null."""
    result = (
        db.table("organisations")
        .select("sales_mode")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    mode = (data or {}).get("sales_mode") or "consultative"
    return ok(data={"mode": mode})


@router.patch("/sales-mode")
def update_sales_mode(
    payload: SalesModeUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """SM-1: Update org sales_mode. Owner + ops_manager only."""
    # RBAC: owner and ops_manager only
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can update the sales mode.",
        )
    db.table("organisations").update({
        "sales_mode": payload.mode,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="sales_mode.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"mode": payload.mode},
    )
    return ok(data={"mode": payload.mode}, message="Sales mode saved")


# ── Contact menus routes ──────────────────────────────────────────────────────

@router.get("/contact-menus")
def get_contact_menus(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """SM-1: Return returning_contact_menu + known_customer_menu from triage config."""
    result = (
        db.table("organisations")
        .select("whatsapp_triage_config")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    triage_config = (data or {}).get("whatsapp_triage_config") or {}
    return ok(data={
        "returning_contact_menu": triage_config.get("returning_contact_menu") or {"items": []},
        "known_customer_menu":    triage_config.get("known_customer_menu")    or {"items": []},
    })


@router.patch("/contact-menus")
def update_contact_menus(
    payload: ContactMenusUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """SM-1: Update returning_contact_menu and/or known_customer_menu. Owner + ops_manager only."""
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can update contact menus.",
        )

    # Load current triage config so we do a safe merge
    current_result = (
        db.table("organisations")
        .select("whatsapp_triage_config")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    current_data = current_result.data
    if isinstance(current_data, list):
        current_data = current_data[0] if current_data else {}
    current_triage = dict((current_data or {}).get("whatsapp_triage_config") or {})

    if payload.returning_contact_menu is not None:
        current_triage["returning_contact_menu"] = payload.returning_contact_menu.model_dump()

    if payload.known_customer_menu is not None:
        current_triage["known_customer_menu"] = payload.known_customer_menu.model_dump()

    db.table("organisations").update({
        "whatsapp_triage_config": current_triage,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="contact_menus.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={
            "returning_contact_menu": current_triage.get("returning_contact_menu"),
            "known_customer_menu":    current_triage.get("known_customer_menu"),
        },
    )
    return ok(data={
        "returning_contact_menu": current_triage.get("returning_contact_menu"),
        "known_customer_menu":    current_triage.get("known_customer_menu"),
    }, message="Contact menus saved")


# ── MULTI-ORG-WA-1: WhatsApp connection management ───────────────────────────

class WhatsAppConnectPayload(BaseModel):
    whatsapp_phone_id: str = Field(..., min_length=1, max_length=100)
    whatsapp_access_token: str = Field(..., min_length=1, max_length=500)
    whatsapp_waba_id: Optional[str] = Field(None, max_length=100)


@router.get("/whatsapp/status")
def get_whatsapp_status(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    MULTI-ORG-WA-1: Return WhatsApp connection status for this org.
    Returns phone_id if connected. Never returns the access token.
    """
    result = (
        db.table("organisations")
        .select("whatsapp_phone_id, whatsapp_access_token, whatsapp_waba_id")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    row = data or {}
    connected = bool(row.get("whatsapp_phone_id") and row.get("whatsapp_access_token"))
    return ok(data={
        "connected": connected,
        "whatsapp_phone_id": row.get("whatsapp_phone_id"),
        "whatsapp_waba_id": row.get("whatsapp_waba_id"),
        # access_token intentionally omitted — never returned to client
    })


@router.post("/whatsapp/connect")
async def connect_whatsapp(
    payload: WhatsAppConnectPayload,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    MULTI-ORG-WA-1: Save WhatsApp phone ID, access token, and WABA ID for this org.
    Verifies the phone_id + token against Meta Graph API before saving.
    RBAC: owner + ops_manager only.
    S3: token is stored but never returned in any response.
    """
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can connect WhatsApp.",
        )

    # Verify credentials against Meta before saving
    try:
        url = f"https://graph.facebook.com/v17.0/{payload.whatsapp_phone_id}"
        headers = {"Authorization": f"Bearer {payload.whatsapp_access_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not verify these credentials with Meta. "
                    "Please check your Phone Number ID and Access Token."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not reach Meta to verify credentials. "
                "Please check your internet connection and try again."
            ),
        )

    db.table("organisations").update({
        "whatsapp_phone_id":     payload.whatsapp_phone_id,
        "whatsapp_access_token": payload.whatsapp_access_token,
        "whatsapp_waba_id":      payload.whatsapp_waba_id,
        "updated_at":            datetime.utcnow().isoformat(),
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="whatsapp.connected",
        resource_type="organisation",
        resource_id=org["org_id"],
        old_value=None,
        new_value={"whatsapp_phone_id": payload.whatsapp_phone_id},
    )
    return ok(data={"connected": True}, message="WhatsApp connected successfully")


@router.delete("/whatsapp/disconnect")
def disconnect_whatsapp(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    MULTI-ORG-WA-1: Clear WhatsApp credentials for this org.
    All automated messaging stops immediately until reconnected.
    RBAC: owner + ops_manager only.
    """
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can disconnect WhatsApp.",
        )

    db.table("organisations").update({
        "whatsapp_phone_id":     None,
        "whatsapp_access_token": None,
        "whatsapp_waba_id":      None,
        "updated_at":            datetime.utcnow().isoformat(),
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="whatsapp.disconnected",
        resource_type="organisation",
        resource_id=org["org_id"],
        old_value=None,
        new_value={"whatsapp_phone_id": None},
    )
    return ok(data={"connected": False}, message="WhatsApp disconnected")

# ============================================================
# COMM-1 — COMMERCE SETTINGS
# ============================================================

class CommerceSettingsUpdate(BaseModel):
    """COMM-1: Toggle commerce and configure checkout message."""
    enabled: Optional[bool] = None
    checkout_message: Optional[str] = Field(
        None,
        max_length=120,
        description="Message prepended to the checkout link sent via WhatsApp",
    )


@router.get("/commerce/settings")
def get_commerce_settings(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    COMM-1: Return org commerce_config + shopify_connected status.
    RBAC: owner + ops_manager only (inline pattern).
    S1 — org_id from JWT only.
    """
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can view commerce settings.",
        )

    result = (
        db.table("organisations")
        .select("commerce_config, shopify_connected")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    data = data or {}

    commerce_config = data.get("commerce_config") or {}
    return ok(data={
        "enabled":           commerce_config.get("enabled", False),
        "checkout_message":  commerce_config.get(
            "checkout_message", "Here's your checkout link:"
        ),
        "shopify_connected": data.get("shopify_connected", False),
    })


@router.patch("/commerce/settings")
def update_commerce_settings(
    payload: CommerceSettingsUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    COMM-1: Toggle commerce and/or update checkout_message.
    Guards: shopify_connected must be True to enable commerce.
    RBAC: owner + ops_manager only (inline pattern).
    S1 — org_id from JWT only.
    """
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can update commerce settings.",
        )

    # Fetch current state
    current_r = (
        db.table("organisations")
        .select("commerce_config, shopify_connected")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    current_d = current_r.data
    if isinstance(current_d, list):
        current_d = current_d[0] if current_d else {}
    current_d = current_d or {}

    shopify_connected = current_d.get("shopify_connected", False)
    existing_config = dict(current_d.get("commerce_config") or {})

    # Guard: cannot enable commerce without Shopify connected
    if payload.enabled is True and not shopify_connected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connect Shopify before enabling commerce.",
        )

    # Build merged config — only update fields the caller sent
    new_config = dict(existing_config)
    if payload.enabled is not None:
        new_config["enabled"] = payload.enabled
    if payload.checkout_message is not None:
        new_config["checkout_message"] = payload.checkout_message.strip()

    if new_config == existing_config:
        return ok(data=new_config, message="No changes to save")

    db.table("organisations").update({
        "commerce_config": new_config,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="commerce_settings.updated",
        resource_type="organisation",
        resource_id=org["org_id"],
        old_value=existing_config,
        new_value=new_config,
    )

    return ok(data=new_config, message="Commerce settings saved")



# Validates daily_customer_message_limit against system ceiling of 20.
# Returns a human-readable 422 when limit exceeds ceiling — never a raw
# HTTP status code. Field key included so frontend can highlight the input.
#
# Pattern 28: get_current_org + inline owner/ops_manager role check
# Pattern 62: db via Depends(get_supabase)
# S1: org_id from JWT only
# S3: Pydantic field constraints on every field
 
 
class MessagingLimitsUpdate(BaseModel):
    """9E-D: Update org messaging limits and quiet hours config."""
 
    daily_customer_message_limit: Optional[int] = Field(
        None,
        ge=1,
        le=SYSTEM_DAILY_CUSTOMER_CEILING,
        description=(
            f"Max automated messages per customer per day. "
            f"Cannot exceed system ceiling of {SYSTEM_DAILY_CUSTOMER_CEILING}."
        ),
    )
    quiet_hours_start: Optional[str] = Field(None, max_length=5)
    quiet_hours_end:   Optional[str] = Field(None, max_length=5)
    timezone:          Optional[str] = Field(None, max_length=60)
 
    @field_validator("daily_customer_message_limit")
    @classmethod
    def _validate_limit(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v > SYSTEM_DAILY_CUSTOMER_CEILING:
            raise ValueError(
                f"Daily message limit cannot exceed {SYSTEM_DAILY_CUSTOMER_CEILING}. "
                f"This is the system-wide maximum to protect your customers from "
                f"receiving too many automated messages in a single day."
            )
        return v
 
    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _validate_time(cls, v: Optional[str]) -> Optional[str]:
        import re as _re_time
        if v is not None and not _re_time.match(r'^\d{2}:\d{2}$', v):
            raise ValueError("Time must be in HH:MM format e.g. 22:00")
        return v
 
    @field_validator("timezone")
    @classmethod
    def _validate_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and ("/" not in v or len(v) > 60):
            raise ValueError(
                "Timezone must be a valid IANA string e.g. Africa/Lagos"
            )
        return v
 
    @model_validator(mode="after")
    def _validate_quiet_hours_pair(self) -> "MessagingLimitsUpdate":
        """Both quiet_hours_start and quiet_hours_end must be set together."""
        start = self.quiet_hours_start
        end   = self.quiet_hours_end
        if (start is None) != (end is None):
            raise ValueError(
                "quiet_hours_start and quiet_hours_end must both be set or both be cleared"
            )
        if start and end and start == end:
            raise ValueError(
                "quiet_hours_start and quiet_hours_end cannot be the same time"
            )
        return self
 
 
@router.get("/messaging-limits")
def get_messaging_limits(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    9E-D: Return org messaging limits and quiet hours config.
    Returns defaults where columns are null.
    Pattern 28 — get_current_org + inline require_permission.
    S1 — org_id from JWT only.
    """
    result = (
        db.table("organisations")
        .select(
            "daily_customer_message_limit, quiet_hours_start, "
            "quiet_hours_end, timezone"
        )
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    data = data or {}
    return ok(data={
        "daily_customer_message_limit": (
            data.get("daily_customer_message_limit") or 3
        ),
        "quiet_hours_start": data.get("quiet_hours_start"),
        "quiet_hours_end":   data.get("quiet_hours_end"),
        "timezone":          data.get("timezone") or "Africa/Lagos",
        "system_ceiling":    SYSTEM_DAILY_CUSTOMER_CEILING,
    })
 
 
@router.patch("/messaging-limits")
def update_messaging_limits(
    payload: MessagingLimitsUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    role = (org.get("roles") or {}).get("template", "").lower()
    if role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and ops managers can update messaging limits.",
        )
    updates = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    if not updates:
        return ok(data={}, message="No changes to save")
 
    updates["updated_at"] = datetime.utcnow().isoformat()
    db.table("organisations").update(updates).eq("id", org["org_id"]).execute()
 
    write_audit_log(
        db=db,
        org_id=org["org_id"],
        user_id=org["id"],
        action="messaging_limits.updated",
        resource_type="organisation",
        resource_id=org["org_id"],
        new_value={k: v for k, v in updates.items() if k != "updated_at"},
    )
    return ok(data=updates, message="Messaging limits saved")

# ===========================================================================
# ASSIGN-1 — Lead Assignment Engine Routes
# ===========================================================================

_VALID_DAYS_SET = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_VALID_STRATEGIES = {"least_loaded", "round_robin", "fixed"}
_TIME_RE = __import__("re").compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ShiftCreate(BaseModel):
    shift_name:    str           = Field(..., max_length=100)
    shift_start:   str           = Field(...)
    shift_end:     str           = Field(...)
    days_active:   list[str]
    assignee_ids:  list[str]     = Field(default_factory=list)
    strategy:      str           = Field(default="least_loaded")
    fixed_user_id: Optional[str] = None

    @field_validator("shift_start", "shift_end")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("Time must be HH:MM format")
        return v

    @field_validator("days_active")
    @classmethod
    def _validate_days(cls, v: list) -> list:
        if not v:
            raise ValueError("days_active must not be empty")
        invalid = set(v) - _VALID_DAYS_SET
        if invalid:
            raise ValueError(f"Invalid days: {invalid}")
        return v

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, v: str) -> str:
        if v not in _VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {_VALID_STRATEGIES}")
        return v


class ShiftUpdate(BaseModel):
    shift_name:    Optional[str]       = Field(None, max_length=100)
    shift_start:   Optional[str]       = None
    shift_end:     Optional[str]       = None
    days_active:   Optional[list[str]] = None
    assignee_ids:  Optional[list[str]] = None
    strategy:      Optional[str]       = None
    fixed_user_id: Optional[str]       = None
    is_active:     Optional[bool]      = None

    @field_validator("shift_start", "shift_end")
    @classmethod
    def _validate_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _TIME_RE.match(v):
            raise ValueError("Time must be HH:MM format")
        return v

    @field_validator("days_active")
    @classmethod
    def _validate_days(cls, v: Optional[list]) -> Optional[list]:
        if v is not None:
            if not v:
                raise ValueError("days_active must not be empty")
            invalid = set(v) - _VALID_DAYS_SET
            if invalid:
                raise ValueError(f"Invalid days: {invalid}")
        return v

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {_VALID_STRATEGIES}")
        return v


class AssignmentModeUpdate(BaseModel):
    mode: str = Field(...)

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        if v not in ("manual", "auto"):
            raise ValueError("mode must be 'manual' or 'auto'")
        return v


def _validate_assignee_ids(db, org_id: str, assignee_ids: list) -> None:
    """Raise 422 if any assignee_id doesn't belong to this org."""
    if not assignee_ids:
        return
    result = (
        db.table("users")
        .select("id")
        .eq("org_id", org_id)
        .in_("id", assignee_ids)
        .execute()
    )
    found = {r["id"] for r in (result.data or [])}
    invalid = set(assignee_ids) - found
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"assignee_ids not in this org: {list(invalid)}",
        )


# ── GET /admin/lead-assignment ───────────────────────────────────────────────
# Pattern 53: static before parameterised

@router.get("/lead-assignment")
def get_lead_assignment(
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id = org["org_id"]

    org_result = (
        db.table("organisations")
        .select("lead_assignment_mode")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_data = org_result.data or {}
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}

    mode = org_data.get("lead_assignment_mode", "manual")

    shifts_result = (
        db.table("lead_assignment_shifts")
        .select("*")
        .eq("org_id", org_id)
        .order("created_at")
        .execute()
    )
    shifts = shifts_result.data or []

    return ok(data={"mode": mode, "shifts": shifts}, message="ok")


# ── PUT /admin/lead-assignment/mode ─────────────────────────────────────────

@router.put("/lead-assignment/mode")
def update_assignment_mode(
    payload: AssignmentModeUpdate,
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id  = org["org_id"]
    user_id = org["id"]

    # Fetch current mode
    org_result = (
        db.table("organisations")
        .select("lead_assignment_mode, sla_business_hours")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    org_data = org_result.data or {}
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}

    current_mode = org_data.get("lead_assignment_mode", "manual")

    # On first switch to auto: pre-fill Day Shift from sla_business_hours
    if payload.mode == "auto" and current_mode == "manual":
        existing_shifts = (
            db.table("lead_assignment_shifts")
            .select("id")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        if not (existing_shifts.data or []):
            # Pre-fill from sla_business_hours or default 08:00–18:00 Mon–Fri
            bh = org_data.get("sla_business_hours") or {}
            shift_start = "08:00"
            shift_end   = "18:00"
            days_active = ["mon", "tue", "wed", "thu", "fri"]
            if isinstance(bh, dict):
                mon = bh.get("mon") or {}
                if mon.get("start"):
                    shift_start = mon["start"]
                if mon.get("end"):
                    shift_end   = mon["end"]
                days_active = [
                    d for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                    if bh.get(d, {}).get("start")
                ]
                if not days_active:
                    days_active = ["mon", "tue", "wed", "thu", "fri"]

            db.table("lead_assignment_shifts").insert({
                "org_id":       org_id,
                "shift_name":   "Day Shift",
                "shift_start":  shift_start,
                "shift_end":    shift_end,
                "days_active":  days_active,
                "assignee_ids": [],
                "strategy":     "least_loaded",
                "is_active":    True,
            }).execute()

    # Update org mode
    db.table("organisations").update(
        {"lead_assignment_mode": payload.mode}
    ).eq("id", org_id).execute()

    # Audit log
    write_audit_log(
        db=db, org_id=org_id, user_id=user_id,
        action="lead_assignment_mode.updated",
        resource_type="organisation", resource_id=org_id,
        new_value={"lead_assignment_mode": payload.mode},
    )

    return ok(data={"mode": payload.mode}, message=f"Assignment mode set to {payload.mode}")


# ── GET /admin/lead-assignment/shifts ────────────────────────────────────────

@router.get("/lead-assignment/shifts")
def list_assignment_shifts(
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id = org["org_id"]

    result = (
        db.table("lead_assignment_shifts")
        .select("*")
        .eq("org_id", org_id)
        .order("created_at")
        .execute()
    )
    return ok(data=result.data or [], message="ok")


# ── POST /admin/lead-assignment/shifts ───────────────────────────────────────

@router.post("/lead-assignment/shifts", status_code=status.HTTP_201_CREATED)
def create_assignment_shift(
    payload: ShiftCreate,
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id = org["org_id"]

    _validate_assignee_ids(db, org_id, payload.assignee_ids)

    if payload.strategy == "fixed" and not payload.fixed_user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fixed_user_id is required when strategy is 'fixed'",
        )
    if payload.fixed_user_id and payload.fixed_user_id not in payload.assignee_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fixed_user_id must be in assignee_ids",
        )

    result = db.table("lead_assignment_shifts").insert({
        "org_id":        org_id,
        "shift_name":    payload.shift_name,
        "shift_start":   payload.shift_start,
        "shift_end":     payload.shift_end,
        "days_active":   payload.days_active,
        "assignee_ids":  payload.assignee_ids,
        "strategy":      payload.strategy,
        "fixed_user_id": payload.fixed_user_id,
        "is_active":     True,
    }).execute()

    shift = result.data[0] if result.data else {}
    return ok(data=shift, message="Shift created")


# ── PATCH /admin/lead-assignment/shifts/{shift_id} ───────────────────────────
# Pattern 53: static routes above, parameterised here

@router.patch("/lead-assignment/shifts/{shift_id}")
def update_assignment_shift(
    shift_id: str,
    payload: ShiftUpdate,
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id = org["org_id"]

    # Verify shift belongs to org
    existing = (
        db.table("lead_assignment_shifts")
        .select("id, org_id")
        .eq("id", shift_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Shift not found")

    updates = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None
    }
    if not updates:
        return ok(data={}, message="No changes")

    if "assignee_ids" in updates:
        _validate_assignee_ids(db, org_id, updates["assignee_ids"])

    updates["updated_at"] = datetime.utcnow().isoformat()

    result = (
        db.table("lead_assignment_shifts")
        .update(updates)
        .eq("id", shift_id)
        .eq("org_id", org_id)
        .execute()
    )
    shift = result.data[0] if result.data else {}
    return ok(data=shift, message="Shift updated")


# ── DELETE /admin/lead-assignment/shifts/{shift_id} ──────────────────────────

@router.delete("/lead-assignment/shifts/{shift_id}")
def delete_assignment_shift(
    shift_id: str,
    org: dict = Depends(require_permission("manage_users")),
    db=Depends(get_supabase),
):
    org_id = org["org_id"]

    # Verify shift belongs to org
    existing = (
        db.table("lead_assignment_shifts")
        .select("id, org_id, is_active")
        .eq("id", shift_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Shift not found")

    # Block deletion if this is the last active shift
    if existing.data.get("is_active"):
        active_count = (
            db.table("lead_assignment_shifts")
            .select("id", count="exact")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        if (active_count.count or 0) <= 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot delete the last active shift. Deactivate it or add another shift first.",
            )

    # Soft delete — set is_active=false
    db.table("lead_assignment_shifts").update(
        {"is_active": False, "updated_at": datetime.utcnow().isoformat()}
    ).eq("id", shift_id).eq("org_id", org_id).execute()

    return ok(data={}, message="Shift deactivated")

# ── LEAD-FORM-CONFIG — Configurable lead capture form per org ─────────────────
#
# Appended to app/routers/admin.py (after the existing ASSIGN-1 routes).
#
# Spec: LEAD-FORM-CONFIG section in Build Status.
# Pattern 28: get_current_org — org_id from JWT only (S1).
# Pattern 62: db via Depends(get_supabase).
# S3: Pydantic validation on every field.
# Pattern 53: static routes declared before any parameterised routes.


_CONFIGURABLE_LEAD_FIELD_KEYS = {
    "email",
    "whatsapp",
    "business_name",
    "business_type",
    "location",
    "branches",
    "problem_stated",
    "product_interest",
    "referrer",
}

# Always mandatory — never configurable
_IMMUTABLE_LEAD_FIELD_KEYS = {"phone", "full_name"}

_DEFAULT_LEAD_FORM_CONFIG = [
    {"key": "email",            "label": "Email Address",    "visible": True,  "required": False},
    {"key": "whatsapp",         "label": "WhatsApp Number",  "visible": True,  "required": False},
    {"key": "business_name",    "label": "Business Name",    "visible": True,  "required": False},
    {"key": "business_type",    "label": "Business Type",    "visible": True,  "required": False},
    {"key": "location",         "label": "Location",         "visible": True,  "required": False},
    {"key": "branches",         "label": "No. of Branches",  "visible": False, "required": False},
    {"key": "problem_stated",   "label": "Problem Stated",   "visible": True,  "required": False},
    {"key": "product_interest", "label": "Product Interest", "visible": False, "required": False},
    {"key": "referrer",         "label": "Referred By",      "visible": False, "required": False},
]


class LeadFormFieldItem(BaseModel):
    key: str
    label: str = Field(..., min_length=1, max_length=50)
    visible: bool = True
    required: bool = False

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        # Silently ignore phone/full_name — never configurable
        if v in _IMMUTABLE_LEAD_FIELD_KEYS:
            return v  # will be filtered out by route handler
        if v not in _CONFIGURABLE_LEAD_FIELD_KEYS:
            raise ValueError(
                f"'{v}' is not a configurable field key. "
                f"Valid keys: {', '.join(sorted(_CONFIGURABLE_LEAD_FIELD_KEYS))}"
            )
        return v

    @field_validator("label")
    @classmethod
    def _validate_label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label is required")
        if len(v) > 50:
            raise ValueError("label must be 50 characters or fewer")
        return v

    @model_validator(mode="after")
    def _validate_required_visible(self) -> "LeadFormFieldItem":
        if self.required and not self.visible:
            raise ValueError(
                f"Field '{self.key}': required=true is not valid when visible=false. "
                "A hidden field cannot be required."
            )
        return self


class LeadFormConfigUpdate(BaseModel):
    fields: List[LeadFormFieldItem]

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, v: List[LeadFormFieldItem]) -> List[LeadFormFieldItem]:
        # Filter out immutable keys — silently ignored per spec
        return [f for f in v if f.key not in _IMMUTABLE_LEAD_FIELD_KEYS]


@router.get("/lead-form-config")
def get_lead_form_config(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    LEAD-FORM-CONFIG: Return org lead_form_config. Falls back to default if null.
    owner + ops_manager access (inline RBAC check).
    S1 — org_id from JWT only. Pattern 28. Pattern 62.
    """
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can view lead form config."},
        )

    result = (
        db.table("organisations")
        .select("lead_form_config")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    fields = (data or {}).get("lead_form_config") or _DEFAULT_LEAD_FORM_CONFIG
    return ok(data={"fields": fields})


@router.patch("/lead-form-config")
def update_lead_form_config(
    payload: LeadFormConfigUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    LEAD-FORM-CONFIG: Save org lead_form_config.
    owner only — ops_manager can view but not save.
    S1 — org_id from JWT only. Pattern 28. Pattern 62. S3 — Pydantic validated above.
    """
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners can update the lead form configuration."},
        )

    fields_data = [f.model_dump() for f in payload.fields]

    updates = {
        "lead_form_config": fields_data,
        "updated_at": datetime.utcnow().isoformat(),
    }
    db.table("organisations").update(updates).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="lead_form_config.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value={"fields": fields_data},
    )
    return ok(data={"fields": fields_data}, message="Lead form configuration saved")


# ── GROWTH-DASH-CONFIG — Configurable Growth Dashboard sections per org ────────
#
# Append to bottom of app/routers/admin.py (after LEAD-FORM-CONFIG routes).
#
# Pattern 28: get_current_org — org_id from JWT only (S1).
# Pattern 62: db via Depends(get_supabase).
# S3: Pydantic validation on every field.
# Pattern 53: static routes before parameterised.

_VALID_SECTION_KEYS = {
    "overview",
    "team_performance",
    "funnel",
    "velocity",
    "pipeline_at_risk",
    "sales_reps",
    "channels",
    "win_loss",
}

# Sections that are always visible — visible:false silently corrected to true
_ALWAYS_VISIBLE_KEYS = {"overview", "pipeline_at_risk"}

_DEFAULT_GROWTH_DASHBOARD_CONFIG = {
    "sections": [
        {"key": "overview",         "visible": True},
        {"key": "team_performance", "visible": True},
        {"key": "funnel",           "visible": True},
        {"key": "velocity",         "visible": True},
        {"key": "pipeline_at_risk", "visible": True},
        {"key": "sales_reps",       "visible": True},
        {"key": "channels",         "visible": True},
        {"key": "win_loss",         "visible": True},
    ]
}


class GrowthDashboardSectionItem(BaseModel):
    key: str
    visible: bool = True

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if v not in _VALID_SECTION_KEYS:
            raise ValueError(
                f"'{v}' is not a valid section key. "
                f"Valid keys: {', '.join(sorted(_VALID_SECTION_KEYS))}"
            )
        return v


class GrowthDashboardConfigUpdate(BaseModel):
    sections: List[GrowthDashboardSectionItem]

    @field_validator("sections")
    @classmethod
    def _validate_sections(
        cls, v: List[GrowthDashboardSectionItem]
    ) -> List[GrowthDashboardSectionItem]:
        # Silently correct always-visible sections if submitted as visible:false
        for item in v:
            if item.key in _ALWAYS_VISIBLE_KEYS:
                item.visible = True
        return v


@router.get("/growth-dashboard-config")
def get_growth_dashboard_config(
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    GROWTH-DASH-CONFIG: Return org growth_dashboard_config. Falls back to default if null.
    owner + ops_manager access.
    S1 — org_id from JWT only. Pattern 28. Pattern 62.
    """
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners and ops managers can view dashboard config."},
        )

    result = (
        db.table("organisations")
        .select("growth_dashboard_config")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    config = (data or {}).get("growth_dashboard_config") or _DEFAULT_GROWTH_DASHBOARD_CONFIG
    return ok(data=config)


@router.patch("/growth-dashboard-config")
def update_growth_dashboard_config(
    payload: GrowthDashboardConfigUpdate,
    org=Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    GROWTH-DASH-CONFIG: Save org growth_dashboard_config.
    Partial payload: only submitted sections updated, others retain current value.
    overview + pipeline_at_risk: silently corrected to visible:true if submitted as false.
    owner only.
    S1 — org_id from JWT only. Pattern 28. Pattern 62. S3 — Pydantic validated above.
    """
    _role = (org.get("roles") or {}).get("template", "").lower()
    if _role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only owners can update the dashboard configuration."},
        )

    # Load current config for partial merge
    current_result = (
        db.table("organisations")
        .select("growth_dashboard_config")
        .eq("id", org["org_id"])
        .maybe_single()
        .execute()
    )
    current_data = current_result.data
    if isinstance(current_data, list):
        current_data = current_data[0] if current_data else {}
    current_config = (current_data or {}).get("growth_dashboard_config") or _DEFAULT_GROWTH_DASHBOARD_CONFIG

    # Merge: build a dict of current sections, update only submitted keys
    current_sections = {s["key"]: s for s in current_config.get("sections", [])}

    for item in payload.sections:
        current_sections[item.key] = {"key": item.key, "visible": item.visible}

    # Preserve original ordering from _DEFAULT_GROWTH_DASHBOARD_CONFIG
    ordered_keys = [s["key"] for s in _DEFAULT_GROWTH_DASHBOARD_CONFIG["sections"]]
    merged_sections = [
        current_sections[k]
        for k in ordered_keys
        if k in current_sections
    ]
    # Also include any keys that exist in current but not in default order (future-proof)
    for k, v in current_sections.items():
        if k not in ordered_keys:
            merged_sections.append(v)

    new_config = {"sections": merged_sections}

    updates = {
        "growth_dashboard_config": new_config,
        "updated_at": datetime.utcnow().isoformat(),
    }
    db.table("organisations").update(updates).eq("id", org["org_id"]).execute()

    write_audit_log(
        db=db, org_id=org["org_id"], user_id=org["id"],
        action="growth_dashboard_config.updated",
        resource_type="organisation", resource_id=org["org_id"],
        new_value=new_config,
    )
    return ok(data=new_config, message="Dashboard configuration saved")