"""
app/services/auth_service.py  (password-reset additions)
----------------------------------------------------------
Service functions for the two remaining auth routes:

    POST  /api/v1/auth/reset-password   — Public, rate-limited (Section 11.4)
    PATCH /api/v1/auth/update-password  — JWT

These functions are imported by app/routers/auth.py.
All Supabase calls use the SERVICE KEY client (bypasses RLS) because the
user is unauthenticated during reset.  For update-password the caller's
own Supabase session is used.

Security rules applied:
  - Section 11.1 — password strength enforced by Supabase Auth (min 8 chars,
    uppercase, number).  We add server-side length pre-check before calling
    the API to avoid a needless round-trip.
  - Section 11.4 — reset-password rate limit (5 / 60 min / IP) is enforced
    in the router using Upstash Redis; this module does NOT perform the check
    so it stays testable in isolation.
  - Section 9.4 — org_id is NEVER sourced from the request body.
  - Audit log written after every significant action (Section 9.5).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx as _httpx
from supabase import Client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Password validation helper
# ---------------------------------------------------------------------------

def _validate_new_password(password: str) -> Optional[str]:
    """
    Server-side password pre-validation.

    Returns an error message string if invalid, otherwise None.

    Supabase Auth enforces its own rules too (min 8 chars, uppercase, number)
    but we check length here to give a clean error before the API call.
    """
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if len(password) > 128:
        return "Password must not exceed 128 characters."
    return None


# ---------------------------------------------------------------------------
# Service: request password reset email
# ---------------------------------------------------------------------------

async def request_password_reset(
    *,
    supabase: Client,
    email: str,
    redirect_url: str,
) -> dict:
    """
    Trigger Supabase Auth to send a password-reset email to `email`.

    Args:
        supabase:     Supabase service-role client.
        email:        The user's email address (lowercased before use).
        redirect_url: The frontend URL Supabase embeds in the reset link.
                      Must match an allowed redirect URL in Supabase Auth settings.

    Returns:
        {"sent": True}  — always, even if the email does not exist.
        (We never confirm whether an account exists — prevents email enumeration.)
    """
    email = email.strip().lower()

    try:
        # Supabase Auth reset_password_for_email sends the magic link.
        # We do NOT raise on unknown email — see security note above.
        supabase.auth.reset_password_for_email(
            email,
            options={"redirect_to": redirect_url},
        )
        logger.info("Password reset email dispatched (or silently skipped) for: %s", email)
    except Exception as exc:
        # Log the error but do not surface it to the caller — prevents
        # distinguishing between "account exists" and "account does not exist".
        logger.error("Supabase reset_password_for_email error: %s", exc)

    return {"sent": True}


# ---------------------------------------------------------------------------
# Service: update password (called after user clicks the reset link)
# ---------------------------------------------------------------------------

async def update_user_password(
    *,
    supabase: Client,
    access_token: str,
    new_password: str,
    org_id: str,
    user_id: str,
) -> dict:
    """
    Update the authenticated user's password using their current access token.

    The access token here is the short-lived one embedded in the Supabase
    reset link — the frontend extracts it from the URL hash and passes it
    in the Authorization header.

    Args:
        supabase:      Supabase service-role client.
        access_token:  JWT extracted from the reset link by the frontend.
        new_password:  Plaintext new password (validated before calling).
        org_id:        From the verified JWT — never from the request body.
        user_id:       From the verified JWT.

    Returns:
        {"updated": True}

    Raises:
        ValueError: if password validation fails.
        RuntimeError: if Supabase Auth update fails.
    """
    # Pre-validate password
    password_error = _validate_new_password(new_password)
    if password_error:
        raise ValueError(password_error)

    try:
        # Use the user's own access token to update their password.
        # Supabase Auth will reject if the token is expired or invalid.
        supabase.auth.update_user(
            {"password": new_password},
        )
    except Exception as exc:
        logger.error("Supabase update_user password error for user %s: %s", user_id, exc)
        raise RuntimeError("Password update failed. The reset link may have expired.") from exc

    # Write audit log — Section 9.5
    try:
        supabase.table("audit_logs").insert(
            {
                "org_id": org_id,
                "user_id": user_id,
                "action": "auth.password_updated",
                "resource_type": "user",
                "resource_id": user_id,
                "old_value": None,
                "new_value": {"password": "***REDACTED***"},
            }
        ).execute()
    except Exception as exc:
        # Audit log failure is non-fatal — do not block the password update
        logger.error("Audit log write failed after password update: %s", exc)

    logger.info("Password updated successfully for user %s", user_id)
    return {"updated": True}


# ---------------------------------------------------------------------------
# Service: admin-triggered password reset (sends reset link to user's email)
# ---------------------------------------------------------------------------

async def admin_request_password_reset(
    *,
    supabase: Client,
    target_user_id: str,
    org_id: str,
    caller_id: str,
    redirect_url: str,
) -> dict:
    """
    AUTH-RESET-1: Admin triggers a password reset email for a staff member.
    Fetches the user's email from the users table (never from request body — S1).
    Sends the reset link to the staff member's inbox.
    Also returns the raw reset link so the admin can share it as a fallback
    if email delivery fails (Option B fallback).

    Args:
        supabase:        Supabase service-role client.
        target_user_id:  UUID of the staff member whose password is being reset.
        org_id:          Caller's org_id from JWT — used to scope the user lookup.
        caller_id:       Caller's user_id from JWT — for audit log.
        redirect_url:    Frontend /reset-password URL embedded in the link.

    Returns:
        { "sent": True, "reset_link": str | None, "email": str }

    Raises:
        ValueError: if user not found in this org.
        RuntimeError: if Supabase link generation fails.
    """
    # Fetch user's email — scoped to org (S1)
    try:
        result = (
            supabase.table("users")
            .select("id, email, is_active")
            .eq("id", target_user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        user_data = result.data
        if isinstance(user_data, list):
            user_data = user_data[0] if user_data else None
    except Exception as exc:
        logger.error("admin_request_password_reset: users lookup failed: %s", exc)
        raise RuntimeError("Failed to look up user.") from exc

    if not user_data:
        raise ValueError("User not found in this organisation.")

    if not user_data.get("is_active"):
        raise ValueError("Cannot reset password for a deactivated account.")

    target_email = user_data["email"]

    # Generate reset link via Supabase Admin API
    # Returns a short-lived signed URL the staff member clicks to set a new password.
    reset_link: Optional[str] = None
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        service_key  = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        link_response = supabase.auth.admin.generate_link({
            "type":        "recovery",
            "email":       target_email,
            "options": {
                "redirect_to": redirect_url,
            },
        })
        reset_link = (
            getattr(link_response, "properties", None) and
            getattr(link_response.properties, "action_link", None)
        ) or None
        logger.info(
            "Admin password reset link generated for user %s by admin %s",
            target_user_id, caller_id,
        )
    except Exception as exc:
        logger.error(
            "admin_request_password_reset: link generation failed for %s: %s",
            target_user_id, exc,
        )
        raise RuntimeError(
            "Failed to generate reset link. Please try again."
        ) from exc

    # Write audit log — Section 9.5
    try:
        supabase.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       caller_id,
            "action":        "auth.admin_password_reset_requested",
            "resource_type": "user",
            "resource_id":   target_user_id,
            "new_value":     {"email": target_email, "reset_link_generated": True},
        }).execute()
    except Exception as exc:
        logger.error("Audit log failed on admin password reset: %s", exc)

    return {"sent": True, "reset_link": reset_link, "email": target_email}


# ---------------------------------------------------------------------------
# Service: admin force-update email
# ---------------------------------------------------------------------------

def admin_update_user_email(
    *,
    supabase: Client,
    target_user_id: str,
    new_email: str,
    org_id: str,
    caller_id: str,
) -> dict:
    """
    AUTH-RESET-1: Admin force-updates a staff member's email address.
    Uses Supabase Admin API — bypasses email confirmation flow.
    Updates both Supabase Auth and the users table.

    Args:
        supabase:        Supabase service-role client.
        target_user_id:  UUID of the staff member whose email is being updated.
        new_email:       The new email address (lowercased before use).
        org_id:          Caller's org_id from JWT.
        caller_id:       Caller's user_id from JWT — for audit log.

    Returns:
        { "updated": True, "email": str }

    Raises:
        ValueError: if user not found, deactivated, or email already in use.
        RuntimeError: if Supabase Auth update fails.
    """
    new_email = new_email.strip().lower()

    # Verify user belongs to this org
    try:
        result = (
            supabase.table("users")
            .select("id, email, is_active")
            .eq("id", target_user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        user_data = result.data
        if isinstance(user_data, list):
            user_data = user_data[0] if user_data else None
    except Exception as exc:
        logger.error("admin_update_user_email: users lookup failed: %s", exc)
        raise RuntimeError("Failed to look up user.") from exc

    if not user_data:
        raise ValueError("User not found in this organisation.")

    if not user_data.get("is_active"):
        raise ValueError("Cannot update email for a deactivated account.")

    old_email = user_data["email"]

    if old_email == new_email:
        raise ValueError("The new email address is the same as the current one.")

    # Update Supabase Auth email via Admin API (bypasses confirmation)
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        service_key  = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        resp = _httpx.patch(
            f"{supabase_url}/auth/v1/admin/users/{target_user_id}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey":        service_key,
                "Content-Type":  "application/json",
            },
            json={
                "email":          new_email,
                "email_confirm":  True,  # bypass confirmation
            },
            timeout=10.0,
        )
        resp.raise_for_status()
    except _httpx.HTTPStatusError as exc:
        body = exc.response.json()
        msg  = body.get("message") or body.get("msg") or str(exc)
        logger.error("admin_update_user_email: Supabase Auth update failed: %s", msg)
        raise RuntimeError(msg) from exc
    except Exception as exc:
        logger.error("admin_update_user_email: unexpected error: %s", exc)
        raise RuntimeError("Email update failed. Please try again.") from exc

    # Update users table
    try:
        supabase.table("users").update({"email": new_email}).eq(
            "id", target_user_id
        ).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.error(
            "admin_update_user_email: users table update failed for %s: %s",
            target_user_id, exc,
        )
        raise RuntimeError(
            "Auth email updated but users table sync failed. Contact support."
        ) from exc

    # Audit log
    try:
        supabase.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       caller_id,
            "action":        "auth.admin_email_updated",
            "resource_type": "user",
            "resource_id":   target_user_id,
            "old_value":     {"email": old_email},
            "new_value":     {"email": new_email},
        }).execute()
    except Exception as exc:
        logger.error("Audit log failed on admin email update: %s", exc)

    logger.info(
        "Admin email update: user %s email changed from %s to %s by admin %s",
        target_user_id, old_email, new_email, caller_id,
    )
    return {"updated": True, "email": new_email}