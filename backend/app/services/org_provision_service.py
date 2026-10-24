"""
app/services/org_provision_service.py
-------------------------------------
WA-AUTO-5 - creates a business and its owner login for PUBLIC sign-up (the Superadmin route does the same for staff).
Steps: organisation row, Supabase Auth user, 7 roles, owner user row. A failure part-way removes what was made.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ProvisionError(Exception):
    def __init__(self, message: str, status_code: int = 500, code: str = "PROVISION_FAILED"):
        super().__init__(message)
        self.status_code, self.code = status_code, code


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40].strip("-")
    return base or "business"


def ticket_prefix(name: str) -> str:
    letters = re.sub(r"[^A-Z0-9]", "", (name or "").upper())[:3]
    return letters if len(letters) >= 2 else "WA"


def unique_slug(db: Any, name: str) -> str:
    base = slugify(name)
    for _ in range(8):
        cand = f"{base}-{secrets.token_hex(2)}"
        if not (db.table("organisations").select("id").eq("slug", cand).limit(1).execute().data or []):
            return cand
    raise ProvisionError("Could not pick a web name for your business. Please try again.")


def _admin_headers() -> tuple:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ProvisionError("Sign-up is not available right now.", 503, "SERVICE_UNAVAILABLE")
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def auth_email_exists(email: str) -> bool:
    """True when a login already uses this email. Fails OPEN to False only if Supabase cannot be asked (the create step still refuses duplicates)."""
    try:
        url, headers = _admin_headers()
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{url}/auth/v1/admin/users", headers=headers, params={"page": 1, "per_page": 1, "filter": email})
        if resp.status_code == 200:
            return any((u.get("email") or "").lower() == email.lower() for u in resp.json().get("users", []))
    except ProvisionError:
        raise
    except Exception as exc:
        logger.warning("org_provision: email lookup failed: %s", exc)
    return False


def provision_wa_org(db: Any, *, business_name: str, owner_name: str, email: str, password: str, whatsapp: str) -> dict:
    """Returns {org_id, user_id, slug}. Raises ProvisionError with a plain message."""
    from app.routers.superadmin import ROLE_TEMPLATES
    url, headers = _admin_headers()
    org_id = auth_user_id = None
    try:
        slug = unique_slug(db, business_name)
        row = db.table("organisations").insert({
            "name": business_name, "slug": slug, "industry": "other", "timezone": "Africa/Lagos", "ticket_prefix": ticket_prefix(business_name),
            "subscription_tier": "starter", "subscription_status": "active", "is_live": False, "product_mode": "wa_automation",
            "plans_enforced": True,
            "business_hours": {d: {"start": "08:00", "end": "17:00"} for d in ("mon", "tue", "wed", "thu", "fri")}
                              | {"sat": {"start": "09:00", "end": "13:00"}, "sun": {"start": None, "end": None}},
        }).execute()
        org_id = row.data[0]["id"]
        with httpx.Client(timeout=20) as client:
            resp = client.post(f"{url}/auth/v1/admin/users", headers=headers, json={"email": email, "password": password, "email_confirm": True})
        if resp.status_code not in (200, 201):
            if resp.status_code in (409, 422):
                raise ProvisionError("That email already has an account. Please sign in instead.", 409, "EMAIL_TAKEN")
            raise RuntimeError(f"auth user creation failed ({resp.status_code})")
        auth_user_id = resp.json()["id"]
        owner_role_id = None
        for tmpl in ROLE_TEMPLATES:
            r = db.table("roles").insert({"org_id": org_id, "name": tmpl["name"], "template": tmpl["template"], "permissions": tmpl["permissions"]}).execute()
            if tmpl["template"] == "owner":
                owner_role_id = r.data[0]["id"]
        if not owner_role_id:
            raise RuntimeError("owner role missing")
        db.table("users").upsert({"id": auth_user_id, "org_id": org_id, "role_id": owner_role_id, "email": email, "full_name": owner_name,
                                  "whatsapp_number": whatsapp, "is_active": True}, on_conflict="id").execute()
        return {"org_id": org_id, "user_id": auth_user_id, "slug": slug}
    except ProvisionError:
        _cleanup(db, url, headers, org_id, auth_user_id)
        raise
    except Exception as exc:
        logger.error("org_provision: failed: %s", exc)
        _cleanup(db, url, headers, org_id, auth_user_id)
        raise ProvisionError("We could not create your account. Please try again in a few minutes.")


def _cleanup(db: Any, url: str, headers: dict, org_id, auth_user_id) -> None:
    if org_id:
        try:
            db.table("organisations").delete().eq("id", org_id).execute()
        except Exception as exc:
            logger.error("org_provision cleanup org failed: %s", exc)
    if auth_user_id:
        try:
            with httpx.Client(timeout=15) as client:
                client.delete(f"{url}/auth/v1/admin/users/{auth_user_id}", headers=headers)
        except Exception as exc:
            logger.error("org_provision cleanup auth user failed: %s", exc)
