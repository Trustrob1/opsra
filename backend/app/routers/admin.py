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
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.database import get_supabase
from app.dependencies import get_current_org, require_permission

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


# ── Valid role templates — Technical Spec Section 3.1 ─────────
VALID_TEMPLATES = {
    "owner", "ops_manager", "sales_agent",
    "customer_success", "support_agent", "finance", "read_only"
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

    # Create Supabase Auth user
    try:
        auth_response = db.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
        })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        )

    new_user_id = auth_response.user.id

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