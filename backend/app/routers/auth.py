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
  - S15:          login rate-limited 10 failed attempts/15min/IP via Redis
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ApiResponse, ErrorCode, err, ok
from app.services.auth_service import request_password_reset, update_user_password

load_dotenv()  # Pattern 29

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
    mfa_required: bool = False
    factor_id: Optional[str] = None


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


# MFA models — Phase 9E
class MFAEnrollRequest(BaseModel):
    friendly_name: str = Field(default="Opsra Auth", max_length=100)


class MFAChallengeRequest(BaseModel):
    factor_id: str = Field(..., max_length=200)


class MFAVerifyRequest(BaseModel):
    factor_id: str   = Field(..., max_length=200)
    challenge_id: str = Field(..., max_length=200)
    code: str        = Field(..., min_length=6, max_length=6)


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
# Login rate-limit helpers — S15
# Tracks *failed* login attempts only (successful login is not penalised).
# Key: rate:login_fail:{ip}   Limit: 10 failures / 900 s (15 min) / IP
# Uses the same Redis client stored on app.state as the reset-password helper.
# Fails open gracefully if Redis is unavailable.
# ---------------------------------------------------------------------------

_LOGIN_FAIL_LIMIT = 10
_LOGIN_FAIL_WINDOW = 900  # seconds — 15 minutes


def _is_login_rate_limited(client_ip: str, redis_client) -> bool:
    """
    Returns True if this IP has already exceeded _LOGIN_FAIL_LIMIT failed
    login attempts within the current window.
    Read-only: does NOT increment the counter.
    """
    if redis_client is None:
        return False
    try:
        raw = redis_client.get(f"rate:login_fail:{client_ip}")
        return int(raw or 0) >= _LOGIN_FAIL_LIMIT
    except Exception as exc:
        logger.warning("S15: login rate-limit peek failed — %s. Failing open.", exc)
        return False


def _record_login_failure(client_ip: str, redis_client) -> None:
    """
    Increment the failed-login counter for this IP.
    Called ONLY after a confirmed authentication failure — successful logins
    do not increment the counter.
    Silently no-ops if Redis is unavailable.
    """
    if redis_client is None:
        return
    try:
        key = f"rate:login_fail:{client_ip}"
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_FAIL_WINDOW)
        pipe.execute()
    except Exception as exc:
        logger.warning("S15: login failure counter update failed — %s.", exc)


# ---------------------------------------------------------------------------
# Device alert helpers — Phase 9E (9E-4)
# ---------------------------------------------------------------------------

_SUPABASE_URL     = os.getenv("SUPABASE_URL", "").strip()
_SUPABASE_SVC_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
_META_WA_TOKEN    = os.getenv("META_WHATSAPP_TOKEN", "").strip()
_GRAPH_BASE       = "https://graph.facebook.com/v18.0"


def _check_new_device(
    db,
    user_id: str,
    org_id: str,
    user_name: str,
    whatsapp_number: Optional[str],
    ip_address: str,
    user_agent: str,
) -> None:
    """
    Check whether this login IP is known for the user.
    New IP → insert device row + in-app notification + WhatsApp alert (if configured).
    S14: entire body is wrapped — this function NEVER raises under any circumstances.
    """
    try:
        # --- Lookup existing device ---
        result = (
            db.table("user_devices")
            .select("id")
            .eq("user_id", user_id)
            .eq("ip_address", ip_address)
            .maybe_single()
            .execute()
        )
        device = result.data
        if isinstance(device, list):
            device = device[0] if device else None

        if device:
            # Known IP — just refresh last_seen_at
            db.table("user_devices").update(
                {"last_seen_at": "now()"}
            ).eq("id", device["id"]).execute()
            return

        # New IP — insert device row
        db.table("user_devices").insert({
            "user_id":    user_id,
            "org_id":     org_id,
            "ip_address": ip_address,
            "user_agent": (user_agent or "")[:500],
        }).execute()
        logger.warning(
            "New device login detected — user %s from IP %s", user_id, ip_address
        )

        # In-app notification
        try:
            db.table("notifications").insert({
                "org_id":        org_id,
                "user_id":       user_id,
                "title":         "New device login",
                "body":          f"Your account was accessed from a new location: {ip_address}",
                "type":          "security_alert",
                "resource_type": "user",
                "resource_id":   user_id,
            }).execute()
        except Exception as _exc:
            logger.warning("Device alert: in-app notification failed: %s", _exc)

        # WhatsApp direct alert — only if user has a number and org has phone_id
        if not whatsapp_number or not _META_WA_TOKEN:
            return
        try:
            org_row = (
                db.table("organisations")
                .select("whatsapp_phone_id")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_data = org_row.data
            if isinstance(org_data, list):
                org_data = org_data[0] if org_data else None
            phone_id = (org_data or {}).get("whatsapp_phone_id")
            if not phone_id:
                return
            import httpx as _httpx
            msg = (
                f"🔐 *Security alert — Opsra*\n\n"
                f"Hi {user_name or 'there'}, your account was accessed from a new "
                f"IP address: *{ip_address}*.\n\n"
                f"If this wasn't you, contact your administrator immediately."
            )
            _httpx.post(
                f"{_GRAPH_BASE}/{phone_id}/messages",
                headers={"Authorization": f"Bearer {_META_WA_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "to":   whatsapp_number,
                    "type": "text",
                    "text": {"body": msg},
                },
                timeout=5.0,
            )
        except Exception as _exc:
            logger.warning("Device alert: WhatsApp send failed: %s", _exc)

    except Exception as exc:  # pylint: disable=broad-except
        # S14 outer guard — no error inside this function must ever propagate
        logger.warning("_check_new_device failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login — Public
# ---------------------------------------------------------------------------

@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(
    body: LoginRequest,
    request: Request,
    supabase=Depends(get_supabase),
) -> ApiResponse:
    """Email + password login via Supabase Auth. Returns JWT access and refresh tokens."""
    # S15: reject IPs that have already exceeded the failed-login threshold
    client_ip = request.client.host if request.client else "unknown"
    redis_client = getattr(request.app.state, "redis", None)
    if _is_login_rate_limited(client_ip, redis_client):
        logger.warning("S15: login blocked for IP %s — rate limit exceeded.", client_ip)
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(_LOGIN_FAIL_WINDOW)},
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": ErrorCode.RATE_LIMITED,
                    "message": "Too many failed login attempts. Try again in 15 minutes.",
                    "field": None,
                },
            },
        )

    try:
        response = supabase.auth.sign_in_with_password({
            "email": body.email.strip().lower(),
            "password": body.password,
        })
        # supabase-py calls postgrest.auth(user_jwt) on SIGNED_IN event, which
        # replaces the service-key header with the user JWT on the singleton client.
        # Every subsequent table() call would then run under RLS as the user.
        # Restore the service key immediately so the singleton stays privileged.
        try:
            supabase.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
        except Exception:
            pass
        if not response.session:
            raise ValueError("No session returned from Supabase Auth.")
    except Exception as exc:
        logger.warning("Login failed for %s: %s", body.email, exc)
        # S15: only increment the counter on a genuine auth failure
        _record_login_failure(client_ip, redis_client)
        return err(
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid email or password.",
        )

    # Update last_login_at and fetch user profile for device alert — best-effort
    user_profile: dict = {}
    try:
        user_row = (
            supabase.table("users")
            .select("id, org_id, full_name, whatsapp_number")
            .eq("id", response.user.id)
            .maybe_single()
            .execute()
        )
        data = user_row.data
        if isinstance(data, list):
            data = data[0] if data else None
        if data:
            user_profile = data
            supabase.table("users").update({"last_login_at": "now()"}).eq(
                "id", response.user.id
            ).execute()
    except Exception as exc:
        logger.warning("Failed to update last_login_at for %s: %s", response.user.id, exc)

    # 9E-4: New device / IP alert — S14: never block login
    try:
        _check_new_device(
            db=supabase,
            user_id=response.user.id,
            org_id=user_profile.get("org_id", ""),
            user_name=user_profile.get("full_name", ""),
            whatsapp_number=user_profile.get("whatsapp_number"),
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", ""),
        )
    except Exception as exc:
        logger.warning("Device check failed (non-blocking): %s", exc)

    # 9E-3: Detect MFA requirement for owner/admin users
    # If the user has verified TOTP factors, the frontend must complete
    # the MFA challenge before calling /auth/me (to get an aal2 session).
    user_factors = []
    try:
        raw_factors = getattr(response.user, "factors", None) or []
        for f in raw_factors:
            if isinstance(f, dict):
                user_factors.append(f)
            else:
                user_factors.append({
                    "id":          getattr(f, "id", None),
                    "factor_type": getattr(f, "factor_type", None),
                    "status":      getattr(f, "status", None),
                })
    except Exception:
        user_factors = []

    verified_totp = [
        f for f in user_factors
        if f.get("factor_type") == "totp" and f.get("status") == "verified"
    ]
    mfa_required = bool(verified_totp)
    first_factor_id = verified_totp[0]["id"] if verified_totp else None

    return ok(
        data=LoginResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            token_type="bearer",
            user={"id": response.user.id, "email": response.user.email},
            mfa_required=mfa_required,
            factor_id=first_factor_id,
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
        # Same singleton contamination fix as login — restore service key
        try:
            supabase.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
        except Exception:
            pass
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


# ---------------------------------------------------------------------------
# MFA routes — Phase 9E (9E-3)
# All calls proxied directly to Supabase Auth REST API (Pattern 38).
# Requires the caller's own access token — Bearer JWT from Authorization header.
# ---------------------------------------------------------------------------

def _supabase_auth_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "apikey":        _SUPABASE_SVC_KEY,
        "Content-Type":  "application/json",
    }


@router.post("/mfa/enroll")
async def mfa_enroll(
    body: MFAEnrollRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> ApiResponse:
    """
    Start TOTP MFA enrollment for the calling user.
    Returns a QR code (SVG data URI), TOTP secret, and otpauth URI.
    The user must scan the QR code in an authenticator app and then call
    POST /mfa/verify-enrollment with the first generated code to activate.
    Technical Spec §11.1 — MFA for Owner/Admin.
    """
    token = credentials.credentials
    try:
        resp = httpx.post(
            f"{_SUPABASE_URL}/auth/v1/factors",
            headers=_supabase_auth_headers(token),
            json={
                "factor_type":   "totp",
                "issuer":        "Opsra",
                "friendly_name": body.friendly_name,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("MFA enroll failed: %s %s", exc.response.status_code, exc.response.text)
        raise HTTPException(status_code=exc.response.status_code, detail="MFA enrollment failed")
    except Exception as exc:
        logger.error("MFA enroll error: %s", exc)
        raise HTTPException(status_code=500, detail="MFA enrollment failed")

    return ok(data={
        "factor_id": data.get("id"),
        "totp": {
            "qr_code": data.get("totp", {}).get("qr_code"),
            "secret":  data.get("totp", {}).get("secret"),
            "uri":     data.get("totp", {}).get("uri"),
        },
    }, message="Scan the QR code with your authenticator app, then verify with the first code.")


@router.post("/mfa/challenge")
async def mfa_challenge(
    body: MFAChallengeRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> ApiResponse:
    """
    Create a new MFA challenge for the given factor.
    Returns a challenge_id — pass it with the TOTP code to POST /mfa/verify.
    Called by the frontend immediately before showing the code-entry screen.
    """
    token = credentials.credentials
    try:
        resp = httpx.post(
            f"{_SUPABASE_URL}/auth/v1/factors/{body.factor_id}/challenge",
            headers=_supabase_auth_headers(token),
            json={},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="MFA challenge failed")
    except Exception as exc:
        logger.error("MFA challenge error: %s", exc)
        raise HTTPException(status_code=500, detail="MFA challenge failed")

    return ok(data={"challenge_id": data.get("id"), "factor_id": body.factor_id})


@router.post("/mfa/verify")
async def mfa_verify(
    body: MFAVerifyRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> ApiResponse:
    """
    Verify a TOTP code to complete MFA login or enrollment.
    On success, Supabase upgrades the session to aal2 and returns new tokens.
    The frontend must replace its stored access_token with the one returned here.
    """
    token = credentials.credentials
    try:
        resp = httpx.post(
            f"{_SUPABASE_URL}/auth/v1/factors/{body.factor_id}/verify",
            headers=_supabase_auth_headers(token),
            json={
                "challenge_id": body.challenge_id,
                "code":         body.code,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = "Invalid MFA code." if exc.response.status_code == 422 else "MFA verification failed."
        raise HTTPException(status_code=exc.response.status_code, detail=detail)
    except Exception as exc:
        logger.error("MFA verify error: %s", exc)
        raise HTTPException(status_code=500, detail="MFA verification failed")

    session = data.get("session") or {}
    return ok(
        data={
            "access_token":  session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "token_type":    "bearer",
            "aal":           session.get("aal", "aal2"),
        },
        message="MFA verified. Session upgraded to aal2.",
    )


@router.delete("/mfa/unenroll/{factor_id}")
async def mfa_unenroll(
    factor_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    org: dict = Depends(get_current_org),
) -> ApiResponse:
    """
    Remove a TOTP factor from the current user's account.
    Owner/Admin only — cannot remove another user's factor.
    """
    from app.utils.rbac import get_role_template
    role = get_role_template(org)
    if role not in ("owner", "ops_manager") and not (
        (org.get("roles") or {}).get("permissions", {}).get("is_admin")
    ):
        raise HTTPException(status_code=403, detail="Owner or admin required to remove MFA factor")

    token = credentials.credentials
    try:
        resp = httpx.delete(
            f"{_SUPABASE_URL}/auth/v1/factors/{factor_id}",
            headers=_supabase_auth_headers(token),
            timeout=10.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="MFA unenroll failed")
    except Exception as exc:
        logger.error("MFA unenroll error: %s", exc)
        raise HTTPException(status_code=500, detail="MFA unenroll failed")

    return ok(data={"unenrolled": True}, message="MFA factor removed.")