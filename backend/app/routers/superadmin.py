"""
app/routers/superadmin.py
Super-admin org provisioning endpoint.
Auth: X-Superadmin-Secret header — no org-scoped JWT involved.
"""
from __future__ import annotations

import logging
import os
import re
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

from app.database import get_supabase
from app.routers.superadmin_health import require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Permission map — 36 canonical keys derived from existing roles in Supabase
# ---------------------------------------------------------------------------

_ALL_PERMS_TRUE = {
    "edit_leads": True,
    "view_leads": True,
    "export_data": True,
    "assign_leads": True,
    "assign_tasks": True,
    "create_leads": True,
    "delete_leads": True,
    "manage_roles": True,
    "manage_users": True,
    "view_reports": True,
    "view_revenue": True,
    "view_tickets": True,
    "ask_your_data": True,
    "close_tickets": True,
    "create_tickets": True,
    "edit_customers": True,
    "reopen_tickets": True,
    "view_all_leads": True,
    "view_analytics": True,
    "view_customers": True,
    "move_lead_stage": True,
    "resolve_tickets": True,
    "view_audit_logs": True,
    "approve_messages": True,
    "confirm_payments": True,
    "escalate_tickets": True,
    "log_interactions": True,
    "manage_templates": True,
    "manage_broadcasts": True,
    "view_churn_scores": True,
    "edit_subscriptions": True,
    "force_logout_users": True,
    "view_subscriptions": True,
    "view_system_health": True,
    "manage_routing_rules": True,
    "approve_cancellations": True,
    "manage_drip_sequences": True,
    "manage_knowledge_base": True,
    "view_team_performance": True,
}

_ALL_PERMS_FALSE = {k: False for k in _ALL_PERMS_TRUE}


def _perms(**overrides: bool) -> dict:
    """Start from all-False and apply overrides."""
    p = dict(_ALL_PERMS_FALSE)
    p.update(overrides)
    return p


ROLE_TEMPLATES: list[dict] = [
    {
        "template": "owner",
        "name": "Owner",
        "permissions": dict(_ALL_PERMS_TRUE),
    },
    {
        "template": "ops_manager",
        "name": "Operations Manager",
        "permissions": _perms(
            edit_leads=True,
            view_leads=True,
            assign_leads=True,
            assign_tasks=True,
            create_leads=True,
            delete_leads=True,
            manage_roles=True,
            view_reports=True,
            view_revenue=True,
            view_tickets=True,
            ask_your_data=True,
            close_tickets=True,
            create_tickets=True,
            edit_customers=True,
            reopen_tickets=True,
            view_all_leads=True,
            view_analytics=True,
            view_customers=True,
            move_lead_stage=True,
            resolve_tickets=True,
            view_audit_logs=True,
            approve_messages=True,
            confirm_payments=True,
            escalate_tickets=True,
            log_interactions=True,
            manage_templates=True,
            manage_broadcasts=True,
            view_churn_scores=True,
            edit_subscriptions=True,
            force_logout_users=True,
            view_subscriptions=True,
            view_system_health=True,
            manage_routing_rules=True,
            manage_drip_sequences=True,
            manage_knowledge_base=True,
            view_team_performance=True,
            # manage_users=False, approve_cancellations=False (default False)
        ),
    },
    {
        "template": "sales_agent",
        "name": "Sales Agent",
        "permissions": _perms(
            view_leads=True,
            create_leads=True,
            edit_leads=True,
            view_all_leads=False,  # own leads only
            assign_leads=False,
            move_lead_stage=True,
            approve_messages=True,
            log_interactions=True,
            view_analytics=True,
            view_customers=True,
            create_tickets=True,
            view_tickets=True,
            view_team_performance=True,
        ),
    },
    {
        "template": "customer_success",
        "name": "Customer Success",
        "permissions": _perms(
            view_customers=True,
            edit_customers=True,
            view_leads=True,
            view_all_leads=True,
            log_interactions=True,
            approve_messages=True,
            manage_broadcasts=True,
            view_tickets=True,
            create_tickets=True,
            view_analytics=True,
            view_subscriptions=True,
            view_churn_scores=True,
            view_team_performance=True,
        ),
    },
    {
        "template": "support_agent",
        "name": "Support Agent",
        "permissions": _perms(
            view_tickets=True,
            create_tickets=True,
            close_tickets=True,
            resolve_tickets=True,
            reopen_tickets=True,
            escalate_tickets=True,
            manage_knowledge_base=True,
            log_interactions=True,
            view_customers=True,
            view_system_health=True,
            view_analytics=True,
        ),
    },
    {
        "template": "finance",
        "name": "Finance",
        "permissions": _perms(
            view_revenue=True,
            view_subscriptions=True,
            edit_subscriptions=True,
            confirm_payments=True,
            export_data=True,
            view_analytics=True,
        ),
    },
    {
        "template": "read_only",
        "name": "Read Only",
        "permissions": _perms(
            view_leads=True,
            view_all_leads=True,
            view_customers=True,
            view_tickets=True,
            view_analytics=True,
            view_reports=True,
            view_revenue=True,
            view_subscriptions=True,
            view_team_performance=True,
            view_churn_scores=True,
            view_system_health=True,
            view_audit_logs=True,
        ),
    },
]

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
_PREFIX_RE = re.compile(r"^[A-Z0-9]+$")


class OrgProvisionPayload(BaseModel):
    org_name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100)
    industry: str = Field(..., max_length=100)
    timezone: str = Field(default="Africa/Lagos", max_length=50)
    ticket_prefix: str = Field(..., max_length=10)
    subscription_tier: str = Field(default="starter")
    owner_email: EmailStr
    owner_full_name: str = Field(..., max_length=255)
    owner_password: str = Field(..., min_length=8)
    owner_whatsapp: Optional[str] = Field(default=None, max_length=20)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase alphanumeric with hyphens only, "
                "and must start and end with a letter or digit"
            )
        return v

    @field_validator("ticket_prefix")
    @classmethod
    def validate_ticket_prefix(cls, v: str) -> str:
        if not _PREFIX_RE.match(v):
            raise ValueError("ticket_prefix must be uppercase alphanumeric only")
        return v


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/superadmin/organisations")
async def provision_organisation(
    payload: OrgProvisionPayload,
    _: None = Depends(require_superadmin),
    db=Depends(get_supabase),
):
    """
    Atomically provision a new organisation:
      1. Check slug uniqueness
      2. Check email uniqueness in Supabase Auth
      3. Insert organisations row
      4. Create Supabase Auth user
      5. Insert 7 default roles
      6. Insert users row (owner)
    On partial failure: cleanup org row + auth user, return 500.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY")

    # ------------------------------------------------------------------
    # Step 1 — slug uniqueness
    # ------------------------------------------------------------------
    slug_check = (
        db.table("organisations")
        .select("id")
        .eq("slug", payload.slug)
        .execute()
    )
    if slug_check.data:
        raise HTTPException(status_code=409, detail="slug already taken")

    # ------------------------------------------------------------------
    # Step 2 — email uniqueness via Supabase Auth admin list
    # ------------------------------------------------------------------
    async with httpx.AsyncClient() as client:
        list_resp = await client.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers={
                "apikey": supabase_service_key,
                "Authorization": f"Bearer {supabase_service_key}",
            },
            params={"page": 1, "per_page": 1, "filter": payload.owner_email},
        )

    if list_resp.status_code == 200:
        list_data = list_resp.json()
        users_found = list_data.get("users", [])
        # Filter Python-side (Pattern 33 — no server-side filter on email)
        existing = [u for u in users_found if u.get("email") == payload.owner_email]
        if existing:
            raise HTTPException(status_code=409, detail="email already registered")

    org_id: Optional[str] = None
    auth_user_id: Optional[str] = None

    try:
        # ------------------------------------------------------------------
        # Step 3 — create organisations row
        # ------------------------------------------------------------------
        org_insert = (
            db.table("organisations")
            .insert({
                "name": payload.org_name,
                "slug": payload.slug,
                "industry": payload.industry,
                "timezone": payload.timezone,
                "ticket_prefix": payload.ticket_prefix,
                "subscription_tier": payload.subscription_tier,
                "subscription_status": "active",
                "is_live": False,
                "business_hours": {
                    "mon": {"start": "08:00", "end": "17:00"},
                    "tue": {"start": "08:00", "end": "17:00"},
                    "wed": {"start": "08:00", "end": "17:00"},
                    "thu": {"start": "08:00", "end": "17:00"},
                    "fri": {"start": "08:00", "end": "17:00"},
                    "sat": {"start": "09:00", "end": "13:00"},
                    "sun": {"start": None, "end": None},
                },
            })
            .execute()
        )
        org_id = org_insert.data[0]["id"]

        # ------------------------------------------------------------------
        # Step 4 — create Supabase Auth user (Pattern 38 — httpx direct REST)
        # ------------------------------------------------------------------
        async with httpx.AsyncClient() as client:
            auth_resp = await client.post(
                f"{supabase_url}/auth/v1/admin/users",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "email": payload.owner_email,
                    "password": payload.owner_password,
                    "email_confirm": True,
                },
            )

        if auth_resp.status_code not in (200, 201):
            logger.error("Supabase Auth user creation failed: %s", auth_resp.text)
            raise RuntimeError("auth_user_creation_failed")

        auth_user_id = auth_resp.json()["id"]

        # ------------------------------------------------------------------
        # Step 5 — create 7 default roles, capture owner_role_id
        # ------------------------------------------------------------------
        owner_role_id: Optional[str] = None
        for tmpl in ROLE_TEMPLATES:
            role_insert = (
                db.table("roles")
                .insert({
                    "org_id": org_id,
                    "name": tmpl["name"],
                    "template": tmpl["template"],
                    "permissions": tmpl["permissions"],
                })
                .execute()
            )
            if tmpl["template"] == "owner":
                owner_role_id = role_insert.data[0]["id"]

        if not owner_role_id:
            raise RuntimeError("owner_role_not_created")

        # ------------------------------------------------------------------
        # Step 6 — create users row
        # ------------------------------------------------------------------
        db.table("users").insert({
            "id": auth_user_id,
            "org_id": org_id,
            "role_id": owner_role_id,
            "email": payload.owner_email,
            "full_name": payload.owner_full_name,
            "whatsapp_number": payload.owner_whatsapp,
            "is_active": True,
        }).execute()

        # ------------------------------------------------------------------
        # Step 7 — return
        # ------------------------------------------------------------------
        return {
            "success": True,
            "data": {
                "org_id": org_id,
                "user_id": auth_user_id,
                "org_name": payload.org_name,
                "slug": payload.slug,
                "owner_email": payload.owner_email,
            },
            "message": "Organisation provisioned successfully",
            "error": None,
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.error("provision_organisation failed: %s", exc)

        # Cleanup — best effort, never raise
        if org_id:
            try:
                db.table("organisations").delete().eq("id", org_id).execute()
                logger.info("Cleanup: deleted org row %s", org_id)
            except Exception as cleanup_err:
                logger.error("Cleanup org failed: %s", cleanup_err)

        if auth_user_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.delete(
                        f"{supabase_url}/auth/v1/admin/users/{auth_user_id}",
                        headers={
                            "apikey": supabase_service_key,
                            "Authorization": f"Bearer {supabase_service_key}",
                        },
                    )
                logger.info("Cleanup: deleted auth user %s", auth_user_id)
            except Exception as cleanup_err:
                logger.error("Cleanup auth user failed: %s", cleanup_err)

        raise HTTPException(status_code=500, detail="Organisation provisioning failed")