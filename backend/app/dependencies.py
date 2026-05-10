"""
app/dependencies.py
--------------------
Shared FastAPI dependency functions injected into every authenticated route.

All functions defined here are used via FastAPI's Depends() mechanism.
They extract and validate the authenticated user and organisation context
from the incoming JWT on every request.

Security rules applied (Technical Spec Section 9.4 and 11.1):
  - org_id is ALWAYS extracted from the verified JWT — never from request body
  - Every authenticated request checks users.is_active = true
  - Deactivated users receive 401 regardless of JWT validity
  - has_permission() checks the role permissions map for the current user
"""

from __future__ import annotations

import logging
from typing import Optional

from cachetools import TTLCache
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_supabase

logger = logging.getLogger(__name__)
security = HTTPBearer()

# ---------------------------------------------------------------------------
# User record cache — reduces Supabase users table queries under burst load.
# On login, 10+ concurrent startup requests all call get_current_org and all
# query the users table simultaneously. This saturates Supabase's connection
# pool and causes transient empty results → 401 → sign-out loop.
#
# TTL of 30 seconds: user record changes (role, is_active) propagate within
# 30s — acceptable for a CRM where role changes are infrequent admin actions.
# maxsize=500: supports 500 concurrent active sessions before eviction.
# ---------------------------------------------------------------------------
_user_cache: TTLCache = TTLCache(maxsize=500, ttl=30)

# Per-user async locks — prevents cache stampede on cold cache (first login).
# Without this, all concurrent startup requests miss the empty cache simultaneously
# and all query Supabase at once, saturating the connection pool.
# With this, only ONE request per user_id queries the DB; all others wait
# and then read from cache when the lock is released.
_user_locks: dict = {}


# ---------------------------------------------------------------------------
# get_current_user — verify JWT with Supabase Auth
# ---------------------------------------------------------------------------

async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(security),
    supabase=Depends(get_supabase),
) -> object:
    """
    Verify the Bearer JWT with Supabase Auth.
    Retries once on network/SSL timeout before raising 401.
    """
    last_exc = None
    for attempt in range(2):
        try:
            auth_response = supabase.auth.get_user(token.credentials)
            if not auth_response or not auth_response.user:
                raise ValueError("No user returned from Supabase Auth.")
            return auth_response.user
        except Exception as exc:
            last_exc = exc
            logger.warning("JWT verification failed (attempt %d/2): %s", attempt + 1, exc)
            if attempt == 0:
                # Brief pause before retry — gives the SSL connection time to recover
                import asyncio
                await asyncio.sleep(0.5)

    raise HTTPException(
        status_code=401,
        detail={
            "success": False,
            "data": None,
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid or expired authentication token.",
                "field": None,
            },
        },
    )


# ---------------------------------------------------------------------------
# get_current_org — fetch user record + org context from database
# ---------------------------------------------------------------------------

async def get_current_org(
    current_user=Depends(get_current_user),
    supabase=Depends(get_supabase),
) -> dict:
    """
    Fetch the authenticated user's full record from the users table,
    including their role and permissions.

    Returns a dict with:
        id, org_id, email, full_name, is_active, roles (with permissions)

    Raises HTTP 401 if:
        - The user record does not exist in our users table
        - users.is_active = false (deactivated — Section 11.1)

    The org_id in the returned dict is the authoritative org_id for the
    request — every route uses this value for DB scoping, never
    anything from the request body.

    Uses double-checked locking to prevent cache stampede on first login:
    - First cache check (no lock) handles the common case cheaply
    - Per-user asyncio.Lock ensures only ONE request queries the DB
    - Second cache check inside the lock means waiting requests read
      from cache once the first request populates it, never hitting DB
    """
    import asyncio

    # First cache check — no lock needed, handles all non-cold-cache cases
    cached = _user_cache.get(current_user.id)
    if cached:
        return cached

    # Get or create a per-user lock — one lock per active user ID
    if current_user.id not in _user_locks:
        _user_locks[current_user.id] = asyncio.Lock()

    async with _user_locks[current_user.id]:
        # Second cache check inside the lock — the request that got here
        # first may have already fetched and cached the result while
        # the current request was waiting to acquire the lock
        cached = _user_cache.get(current_user.id)
        if cached:
            return cached

        # Only ONE request per user_id reaches here at a time
        db_user = None
        last_exc = None

        for attempt in range(3):
            try:
                result = (
                    supabase.table("users")
                    .select("id, org_id, email, full_name, is_active, whatsapp_number, notification_prefs, roles(*)")
                    .eq("id", current_user.id)
                    .execute()
                )
                rows = result.data or []
                if rows:
                    db_user = rows[0]
                    _user_cache[current_user.id] = db_user  # cache for 30s
                    break
                logger.warning(
                    "User record returned 0 rows for %s (attempt %d/3) — retrying",
                    getattr(current_user, "id", "?"),
                    attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "User fetch exception for %s (attempt %d/3): %s",
                    getattr(current_user, "id", "?"),
                    attempt + 1,
                    exc,
                )
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))

    # Lock released — clean up the lock entry to prevent unbounded dict growth
    _user_locks.pop(current_user.id, None)

    if db_user is None:
        logger.error(
            "Failed to fetch user record for %s after 3 attempts. Last exception: %s",
            getattr(current_user, "id", "?"),
            last_exc,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "User account not found.",
                    "field": None,
                },
            },
        )

    # Deactivated user check — Technical Spec Section 11.1
    # Must be enforced on every authenticated request regardless of valid JWT
    if not db_user.get("is_active"):
        logger.warning("Deactivated user attempted access: %s", db_user.get("id"))
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "This account has been deactivated. Contact your administrator.",
                    "field": None,
                },
            },
        )

    return db_user


# ---------------------------------------------------------------------------
# require_admin — restrict route to Owner/Admin roles only
# ---------------------------------------------------------------------------

async def require_admin(
    current_org: dict = Depends(get_current_org),
) -> dict:
    """
    Dependency for Admin-only routes (Technical Spec Section 5 auth column).

    Checks that the user's role template is 'owner' or the user has the
    'is_admin' permission in their role's permissions map.

    Raises HTTP 403 if the user is not an admin.
    Returns the full user dict (same as get_current_org) on success.
    """
    role = current_org.get("roles") or {}
    permissions = role.get("permissions") or {}
    template = role.get("template", "")

    is_admin = template in ("owner",) or permissions.get("is_admin") is True

    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "data": None,
                "error": {
                    "code": "FORBIDDEN",
                    "message": "This action requires administrator access.",
                    "field": None,
                },
            },
        )

    return current_org


# ---------------------------------------------------------------------------
# require_permission — factory for permission-checked dependencies
# ---------------------------------------------------------------------------

def require_permission(permission_key: str):
    """
    Returns a FastAPI dependency that checks a specific permission key.

    Usage in a route:
        @router.post("/leads/{id}/convert")
        async def convert_lead(
            org = Depends(require_permission("convert_leads"))
        ):
            ...

    Raises HTTP 403 if the user's role does not grant the permission.
    """
    async def _check(current_org: dict = Depends(get_current_org)) -> dict:
        if not has_permission(current_org, permission_key):
            raise HTTPException(
                status_code=403,
                detail={
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"You do not have permission to perform this action ({permission_key}).",
                        "field": None,
                    },
                },
            )
        return current_org

    return _check


# ---------------------------------------------------------------------------
# has_permission — pure helper (no FastAPI dependency, safe to call directly)
# ---------------------------------------------------------------------------

def has_permission(user: dict, permission_key: str) -> bool:
    """
    Check whether `user` has `permission_key` set to True in their role.

    Also checks user_permission_overrides logic:
      - The role's permissions map is checked first
      - Individual overrides (granted=True/False) take precedence

    Currently implements role-level check only. Override table check is
    added in Phase 2A when user_permission_overrides table is queried.

    Args:
        user:           The dict returned by get_current_org().
        permission_key: The permission key to check, e.g. 'view_leads'.

    Returns:
        True if the permission is explicitly granted, False otherwise.
        Defaults to False for any missing or null permission.
    """
    try:
        role = user.get("roles") or {}
        permissions = role.get("permissions") or {}
        return permissions.get(permission_key) is True
    except Exception:
        return False