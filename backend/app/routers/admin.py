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
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.database import get_supabase
from app.dependencies import get_current_org, require_permission
import httpx
import os
from app.services import admin_service
from datetime import datetime
from app.models.common import ok


router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────

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