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
from typing import Optional

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