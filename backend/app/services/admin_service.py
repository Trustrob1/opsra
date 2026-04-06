"""
backend/app/services/admin_service.py
Admin service — Phase 8A additions.

Covers the two feature areas not yet implemented in routers/admin.py:
  1. Role user overrides (user_permission_overrides table)
  2. Individual routing rule CRUD (alongside the existing full-replace PUT)

The original user / role / routing-rules / integration logic remains inline
in routers/admin.py from Phase 1.  This service file holds only the new
Phase 8A service functions so that:
  - Unit tests can test them without spinning up FastAPI
  - router additions stay thin (delegate, don't duplicate)

Security:
  S1  — org_id always from the JWT-derived org dict passed in by the router
  S12 — _write_audit_log called on every mutating operation
  Pattern 37 — role checks done in router via require_permission dependency;
               service trusts the caller has already authenticated
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


# ── Internal audit log helper ─────────────────────────────────────────────────
# Defined locally to avoid circular imports with routers/admin.py.
# Failures are swallowed and logged — never raise from audit writes.

def _write_audit_log(
    db,
    org_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> None:
    try:
        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       user_id,
            "action":        action,
            "resource_type": resource_type,
            "resource_id":   resource_id,
            "old_value":     old_value,
            "new_value":     new_value,
        }).execute()
    except Exception as exc:  # pragma: no cover
        logger.error("Audit log write failed: %s", exc)


# ── Internal normaliser ───────────────────────────────────────────────────────
# supabase-py .maybe_single() can return a dict or a list in tests.

def _one(data) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


# ============================================================
# ROLE USER OVERRIDES
# user_permission_overrides table:
#   id, org_id, user_id, permission_key, granted, created_by, created_at
# ============================================================

def list_user_overrides(role_id: str, org_id: str, db) -> list:
    """
    Returns all user_permission_overrides for users currently assigned to
    ``role_id`` within ``org_id``.  Attaches a ``user`` sub-object
    (id, full_name, email) to each override row for UI display.

    Returns an empty list when no users are assigned to the role.
    """
    # Step 1 — get users in this role
    users_result = (
        db.table("users")
        .select("id, full_name, email")
        .eq("role_id", role_id)
        .eq("org_id", org_id)
        .execute()
    )
    users_in_role: list = users_result.data or []
    if not users_in_role:
        return []

    user_ids = [u["id"] for u in users_in_role]
    user_map = {u["id"]: u for u in users_in_role}

    # Step 2 — get their overrides
    overrides_result = (
        db.table("user_permission_overrides")
        .select("*")
        .in_("user_id", user_ids)
        .eq("org_id", org_id)
        .execute()
    )
    overrides: list = overrides_result.data or []

    # Attach user display info for convenience
    for override in overrides:
        uid = override.get("user_id")
        override["user"] = user_map.get(uid, {})

    return overrides


def create_user_override(
    role_id: str,
    user_id: str,
    org_id: str,
    db,
    permission_key: str,
    granted: bool,
    caller_id: str,
) -> dict:
    """
    Grants (or explicitly denies) a single permission override to a specific
    user.  The user must belong to ``org_id`` and be assigned to ``role_id``.

    Raises 404 if the user is not found in this org with this role.
    Writes to audit_logs.
    """
    # Verify user exists in this org with this role
    check = (
        db.table("users")
        .select("id, full_name")
        .eq("id", user_id)
        .eq("org_id", org_id)
        .eq("role_id", role_id)
        .maybe_single()
        .execute()
    )
    user_row = _one(check.data)
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code":    "NOT_FOUND",
                "message": "User not found in this org or not assigned to the specified role",
            },
        )

    insert_payload = {
        "org_id":         org_id,
        "user_id":        user_id,
        "permission_key": permission_key,
        "granted":        granted,
        "created_by":     caller_id,
    }
    result     = db.table("user_permission_overrides").insert(insert_payload).execute()
    new_record = result.data[0] if (result.data) else insert_payload

    _write_audit_log(
        db=db,
        org_id=org_id,
        user_id=caller_id,
        action="role.override_granted",
        resource_type="user_permission_override",
        resource_id=new_record.get("id"),
        new_value={
            "user_id":        user_id,
            "permission_key": permission_key,
            "granted":        granted,
        },
    )

    return new_record


def delete_user_override(
    override_id: str,
    org_id: str,
    db,
    caller_id: str,
) -> None:
    """
    Removes a single user_permission_overrides row by its UUID.
    ``override_id`` is the primary key of the overrides row (not a user_id).

    Raises 404 if the row does not exist or belongs to a different org.
    Writes to audit_logs.
    """
    check = (
        db.table("user_permission_overrides")
        .select("id, user_id, permission_key")
        .eq("id", override_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    record = _one(check.data)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Override not found"},
        )

    db.table("user_permission_overrides") \
      .delete() \
      .eq("id", override_id) \
      .eq("org_id", org_id) \
      .execute()

    _write_audit_log(
        db=db,
        org_id=org_id,
        user_id=caller_id,
        action="role.override_removed",
        resource_type="user_permission_override",
        resource_id=override_id,
        old_value=record,
    )


# ============================================================
# INDIVIDUAL ROUTING RULE CRUD
# routing_rules table:
#   id, org_id, event_type, route_to_role_id, route_to_user_id,
#   also_notify_role_id, channel, within_hours_only,
#   escalate_after_minutes, escalate_to_role_id, updated_at
#
# These routes complement the existing PUT /routing-rules (full-replace).
# Use POST to add individual rules; PATCH / DELETE to manage existing ones.
# ============================================================

def create_routing_rule(
    org_id: str,
    db,
    data: dict,
    caller_id: str,
) -> dict:
    """
    Inserts a single routing rule for ``org_id``.
    ``data`` is the validated model_dump() from the router.
    Writes to audit_logs.
    """
    insert_payload = {"org_id": org_id, **data}
    result   = db.table("routing_rules").insert(insert_payload).execute()
    new_rule = result.data[0] if result.data else insert_payload

    _write_audit_log(
        db=db,
        org_id=org_id,
        user_id=caller_id,
        action="routing_rule.created",
        resource_type="routing_rule",
        resource_id=new_rule.get("id"),
        new_value=data,
    )

    return new_rule


def update_routing_rule(
    rule_id: str,
    org_id: str,
    db,
    data: dict,
    caller_id: str,
) -> dict:
    """
    Updates a single routing rule.
    ``data`` contains only the fields the caller wants to change (partial update).

    Raises 404 if the rule is not found or belongs to a different org.
    Writes to audit_logs.
    """
    check = (
        db.table("routing_rules")
        .select("*")
        .eq("id", rule_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    existing = _one(check.data)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Routing rule not found"},
        )

    result  = (
        db.table("routing_rules")
        .update(data)
        .eq("id", rule_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**existing, **data}

    _write_audit_log(
        db=db,
        org_id=org_id,
        user_id=caller_id,
        action="routing_rule.updated",
        resource_type="routing_rule",
        resource_id=rule_id,
        old_value=existing,
        new_value=data,
    )

    return updated


def delete_routing_rule(
    rule_id: str,
    org_id: str,
    db,
    caller_id: str,
) -> None:
    """
    Deletes a single routing rule.

    Raises 404 if the rule is not found or belongs to a different org.
    Writes to audit_logs.
    """
    check = (
        db.table("routing_rules")
        .select("id, event_type")
        .eq("id", rule_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    existing = _one(check.data)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Routing rule not found"},
        )

    db.table("routing_rules") \
      .delete() \
      .eq("id", rule_id) \
      .eq("org_id", org_id) \
      .execute()

    _write_audit_log(
        db=db,
        org_id=org_id,
        user_id=caller_id,
        action="routing_rule.deleted",
        resource_type="routing_rule",
        resource_id=rule_id,
        old_value=existing,
    )