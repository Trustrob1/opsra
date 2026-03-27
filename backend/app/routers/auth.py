"""
app/routers/auth.py
--------------------
All authentication routes — Technical Spec Section 5.1.

Routes:
    POST  /api/v1/auth/login            Public — email+password login
    POST  /api/v1/auth/logout           JWT    — invalidate session
    POST  /api/v1/auth/refresh          Public — refresh access token
    GET   /api/v1/auth/me               JWT    — current user profile
    POST  /api/v1/auth/reset-password   Public — send reset email (rate-limited)
    PATCH /api/v1/auth/update-password  JWT    — update password after reset

Security rules applied:
  - Section 11.1: is_active checked on every authenticated request
  - Section 11.4: reset-password rate-limited 5/60min/IP via Redis
  - Section 9.4:  org_id always from JWT, never from request body
  - Section 9.2:  all responses use the ApiResponse envelope
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ApiResponse, ErrorCode, err, ok
from app.services.auth_service import request_password_reset, update_user_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Pydantic request/response schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class LogoutResponse(BaseModel):
    logged_out: bool = True


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ResetPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordResponse(BaseModel):
    sent: bool = True


class UpdatePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class UpdatePasswordResponse(BaseModel):
    updated: bool = True


# ---------------------------------------------------------------------------
# Rate-limit helper — Section 11.4
# Redis counter per IP. 5 attempts / 60 minutes / per IP.
# ---------------------------------------------------------------------------

def _check_reset_rate_limit(client_ip: str, redis_client) -> None:
    """
    Enforce 5 reset-password attempts per IP per 60 minutes.
    Raises HTTPException 429 if limit exceeded.
    Skips check gracefully if redis_client is None.
    """
    if redis_client is None:
        logger.warning("Redis not available — reset-password rate limit check skipped.")
        return

    key = f"rate:reset_password:{client_ip}"
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)
    results = pipe.execute()
    count = results[0]

    if count > 5:
        logger.warning("reset-password rate limit hit for IP %s (count=%d)", client_ip, count)
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": "3600"},
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": ErrorCode.RATE_LIMITED,
                    "message": "Too many password reset requests. Try again in 60 minutes.",
                    "field": None,
                },
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login — Public
# ---------------------------------------------------------------------------

@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(
    body: LoginRequest,
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """Email + password login via Supabase Auth. Returns JWT access and refresh tokens."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": body.email.strip().lower(),
            "password": body.password,
        })
        if not response.session:
            raise ValueError("No session returned from Supabase Auth.")
    except Exception as exc:
        logger.warning("Login failed for %s: %s", body.email, exc)
        return err(
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid email or password.",
        )

    # Update last_login_at — best-effort, don't block login if it fails
    try:
        supabase.table("users").update({"last_login_at": "now()"}).eq(
            "id", response.user.id
        ).execute()
    except Exception as exc:
        logger.warning("Failed to update last_login_at for %s: %s", response.user.id, exc)

    return ok(
        data=LoginResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            token_type="bearer",
            user={"id": response.user.id, "email": response.user.email},
        )
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout — JWT required
# ---------------------------------------------------------------------------

@router.post("/logout", response_model=ApiResponse[LogoutResponse])
async def logout(
    org=Depends(get_current_org),
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """Invalidate the current session token via Supabase Auth."""
    try:
        supabase.auth.sign_out()
    except Exception as exc:
        logger.warning("Sign-out call failed (token may already be expired): %s", exc)

    # Audit log
    try:
        supabase.table("audit_logs").insert({
            "org_id": org["org_id"],
            "user_id": org["id"],
            "action": "auth.logout",
            "resource_type": "user",
            "resource_id": org["id"],
        }).execute()
    except Exception as exc:
        logger.error("Audit log failed on logout: %s", exc)

    return ok(data=LogoutResponse(logged_out=True), message="Logged out successfully.")


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh — Public
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=ApiResponse[RefreshResponse])
async def refresh_token(
    body: RefreshRequest,
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """Refresh an expired access token using the refresh token."""
    try:
        response = supabase.auth.refresh_session(body.refresh_token)
        if not response.session:
            raise ValueError("No session returned.")
    except Exception as exc:
        logger.warning("Token refresh failed: %s", exc)
        return err(
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid or expired refresh token. Please log in again.",
        )

    return ok(
        data=RefreshResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            token_type="bearer",
        )
    )


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me — JWT required
# ---------------------------------------------------------------------------

@router.get("/me", response_model=ApiResponse)
async def me(org=Depends(get_current_org)) -> ApiResponse:
    """Return the current user's profile and role permissions."""
    # Remove sensitive internal fields before returning
    safe_user = {
        "id": org.get("id"),
        "org_id": org.get("org_id"),
        "email": org.get("email"),
        "full_name": org.get("full_name"),
        "whatsapp_number": org.get("whatsapp_number"),
        "is_active": org.get("is_active"),
        "is_out_of_office": org.get("is_out_of_office", False),
        "notification_prefs": org.get("notification_prefs", {}),
        "roles": org.get("roles"),
    }
    return ok(data=safe_user)


# ---------------------------------------------------------------------------
# POST /api/v1/auth/reset-password — Public, rate-limited
# ---------------------------------------------------------------------------

@router.post("/reset-password", response_model=ApiResponse[ResetPasswordResponse])
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """
    Send a password-reset email via Supabase Auth.
    Always returns success — never reveals whether the email exists.
    Rate-limited: 5 requests / 60 min / per IP (Section 11.4).
    """
    client_ip = request.client.host if request.client else "unknown"
    redis_client = getattr(request.app.state, "redis", None)
    _check_reset_rate_limit(client_ip, redis_client)

    redirect_url = f"{settings.FRONTEND_URL}/auth/update-password"
    await request_password_reset(
        supabase=supabase,
        email=body.email,
        redirect_url=redirect_url,
    )

    return ok(
        data=ResetPasswordResponse(sent=True),
        message="If an account exists with that email, a reset link has been sent.",
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/auth/update-password — JWT required
# ---------------------------------------------------------------------------

@router.patch("/update-password", response_model=ApiResponse[UpdatePasswordResponse])
async def update_password(
    body: UpdatePasswordRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """
    Update password after clicking a reset link.
    The Bearer token is the short-lived token from the reset email link.
    """
    # Verify the token
    try:
        auth_response = supabase.auth.get_user(credentials.credentials)
        if not auth_response or not auth_response.user:
            raise ValueError("Invalid token.")
    except Exception as exc:
        logger.warning("update-password: invalid token — %s", exc)
        return err(
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid or expired session token. Please request a new reset link.",
        )

    supabase_user = auth_response.user

    # Fetch org_id from users table — never from request body (Section 9.4)
    try:
        user_row = (
            supabase.table("users")
            .select("id, org_id, is_active")
            .eq("id", supabase_user.id)
            .single()
            .execute()
        )
        db_user = user_row.data
    except Exception as exc:
        logger.error("update-password: users lookup failed: %s", exc)
        return err(code=ErrorCode.NOT_FOUND, message="User account not found.")

    # Deactivated user check — Section 11.1
    if not db_user.get("is_active"):
        return err(
            code=ErrorCode.FORBIDDEN,
            message="This account has been deactivated. Contact your administrator.",
        )

    try:
        await update_user_password(
            supabase=supabase,
            access_token=credentials.credentials,
            new_password=body.new_password,
            org_id=db_user["org_id"],
            user_id=db_user["id"],
        )
    except ValueError as exc:
        return err(code=ErrorCode.VALIDATION_ERROR, message=str(exc), field="new_password")
    except RuntimeError as exc:
        return err(code=ErrorCode.INTEGRATION_ERROR, message=str(exc))

    return ok(
        data=UpdatePasswordResponse(updated=True),
        message="Password updated successfully. Please log in with your new password.",
    )