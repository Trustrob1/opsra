"""
backend/app/utils/rbac.py
Shared RBAC helpers — Phase 9B.

All role checks use Pattern 37: role is at org["roles"]["template"],
never at a flat "role" key (which is always None from get_current_org).

Imported by routers that need:
  - role template lookup
  - scoped-role detection (sales_agent / affiliate_partner)
  - affiliate-only blocks
  - per-permission-key checks
"""
from __future__ import annotations

from fastapi import HTTPException

# Roles that see only their own assigned records (leads, customers, tickets)
SCOPED_ROLES: frozenset = frozenset({"sales_agent", "affiliate_partner"})


def get_role_template(org: dict) -> str:
    """
    Returns the role template string for the requesting user.
    Pattern 37: role is at org["roles"]["template"] — never a flat "role" key.
    Returns "" (empty string) if roles data is absent or malformed.
    """
    roles = org.get("roles") or {}
    return (roles.get("template") or "").lower() if isinstance(roles, dict) else ""


def is_scoped_role(org: dict) -> bool:
    """
    Returns True when the user should only see their own assigned records.
    Applies to: sales_agent, affiliate_partner.
    """
    return get_role_template(org) in SCOPED_ROLES


def require_not_affiliate(org: dict, action: str = "this action") -> None:
    """
    Raises HTTP 403 if the user is an affiliate_partner.
    Affiliate partners are read-only — they cannot mutate any record.
    """
    if get_role_template(org) == "affiliate_partner":
        raise HTTPException(
            status_code=403,
            detail={
                "code":    "FORBIDDEN",
                "message": f"Affiliate partners cannot perform {action}.",
            },
        )


def require_permission_key(
    org: dict,
    key: str,
    message: str = "Insufficient permissions for this action",
) -> None:
    """
    Raises HTTP 403 unless the user has the given permission key.
    Grants automatically for:
      - template == "owner"
      - permissions.is_admin == True
    Otherwise checks permissions[key] == True.
    """
    roles = org.get("roles") or {}
    if not isinstance(roles, dict):
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": message},
        )
    template    = (roles.get("template")    or "").lower()
    permissions = (roles.get("permissions") or {})

    if template == "owner":
        return
    if permissions.get("is_admin") is True:
        return
    if not permissions.get(key, False):
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": message},
        )
