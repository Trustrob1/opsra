"""
backend/app/services/commissions_service.py
Commission tracking service — Phase 9C (updated with org settings).

Behaviour:
  auto_create_commission:
    - Always fetches org commission settings from organisations table
    - If commission_enabled = False (default): creates row with amount_ngn=0
      for all assigned users — backwards compatible, manager reviews manually
    - If commission_enabled = True: applies full rules:
        1. Checks affiliate_user_id's role template is in
           commission_eligible_templates
        2. If commission_trigger = 'first_payment' and event_type =
           'payment_confirmed': skips if a payment_confirmed row already
           exists for this customer+affiliate
        3. Calculates amount_ngn from rate_type + rate_value
           ('flat' = fixed NGN; 'percentage' = % of deal_amount)

  update_commission:
    - Managers only
    - On status → 'approved' or 'paid': inserts in-app notification for
      the affiliate user
    - If org.commission_whatsapp_notify = True and affiliate has
      whatsapp_number: inserts a queued whatsapp_messages row

S14: auto_create_commission NEVER raises — failures are logged and swallowed.
Pattern 37: _can_manage() reads org["roles"]["template"].
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.utils.rbac import get_role_template

logger = logging.getLogger(__name__)

COMMISSION_STATUSES    = frozenset({"pending", "approved", "paid", "rejected"})
COMMISSION_EVENT_TYPES = frozenset({"lead_converted", "payment_confirmed"})
_MANAGER_TEMPLATES     = frozenset({"owner", "ops_manager"})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _can_manage(org: dict) -> bool:
    template    = get_role_template(org)
    permissions = (org.get("roles") or {}).get("permissions") or {}
    return template in _MANAGER_TEMPLATES or permissions.get("is_admin") is True


def _one(data) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_audit(db, org_id, user_id, action, resource_id,
                 old_val=None, new_val=None) -> None:
    try:
        db.table("audit_logs").insert({
            "org_id":        org_id,
            "user_id":       user_id,
            "action":        action,
            "resource_type": "commission",
            "resource_id":   resource_id,
            "old_value":     old_val,
            "new_value":     new_val,
        }).execute()
    except Exception as exc:
        logger.error("Commission audit log write failed: %s", exc)


def _fetch_org_commission_settings(db, org_id: str) -> dict:
    """Fetch commission config columns from organisations table."""
    try:
        result = (
            db.table("organisations")
            .select(
                "commission_enabled, commission_eligible_templates, "
                "commission_rate_type, commission_rate_value, "
                "commission_trigger, commission_whatsapp_notify"
            )
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        row = _one(result.data)
        return row or {}
    except Exception as exc:
        logger.warning("_fetch_org_commission_settings failed: %s", exc)
        return {}


def _get_user_role_template(db, user_id: str, org_id: str) -> str:
    """Return the role template string for a user, or '' on error."""
    try:
        user_result = (
            db.table("users")
            .select("role_id")
            .eq("id", user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        user_row = _one(user_result.data)
        if not user_row or not user_row.get("role_id"):
            return ""
        role_result = (
            db.table("roles")
            .select("template")
            .eq("id", user_row["role_id"])
            .maybe_single()
            .execute()
        )
        role_row = _one(role_result.data)
        return (role_row or {}).get("template", "")
    except Exception:
        return ""


def _has_existing_payment_commission(
    db, org_id: str, affiliate_user_id: str, customer_id: str
) -> bool:
    """Returns True if a payment_confirmed commission already exists for
    this customer+affiliate — used for first_payment trigger check."""
    try:
        result = (
            db.table("commissions")
            .select("id")
            .eq("org_id", org_id)
            .eq("affiliate_user_id", affiliate_user_id)
            .eq("customer_id", customer_id)
            .eq("event_type", "payment_confirmed")
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


# ============================================================
# auto_create_commission
# ============================================================

def auto_create_commission(
    db,
    org_id: str,
    affiliate_user_id: str,
    event_type: str,
    lead_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    deal_amount: Optional[float] = None,
) -> None:
    """
    Auto-creates a commission row.

    commission_enabled = False (default):
      Creates row for ALL assigned users with amount_ngn=0.
      Manager reviews manually.

    commission_enabled = True (configured):
      Applies eligibility check, trigger check, and rate calculation.

    S14: Never raises.
    """
    if not affiliate_user_id or not org_id:
        return

    try:
        settings           = _fetch_org_commission_settings(db, org_id)
        commission_enabled = settings.get("commission_enabled", False)

        if commission_enabled:
            # 1. Eligibility check
            eligible_templates = settings.get("commission_eligible_templates")
            if not isinstance(eligible_templates, list):
                eligible_templates = ["affiliate_partner"]
            if eligible_templates:
                user_template = _get_user_role_template(db, affiliate_user_id, org_id)
                if user_template and user_template not in eligible_templates:
                    return

            # 2. Trigger check for payment events
            if event_type == "payment_confirmed" and customer_id:
                trigger = settings.get("commission_trigger", "every_payment")
                if trigger == "first_payment":
                    if _has_existing_payment_commission(
                        db, org_id, affiliate_user_id, customer_id
                    ):
                        return

            # 3. Calculate amount
            rate_type  = settings.get("commission_rate_type", "flat")
            rate_value = float(settings.get("commission_rate_value") or 0)
            amount_ngn: float = 0
            if rate_value > 0:
                if rate_type == "flat":
                    amount_ngn = rate_value
                elif rate_type == "percentage" and deal_amount:
                    amount_ngn = round(deal_amount * rate_value / 100, 2)
        else:
            amount_ngn = 0

        row: dict = {
            "org_id":            org_id,
            "affiliate_user_id": affiliate_user_id,
            "event_type":        event_type,
            "amount_ngn":        amount_ngn,
            "status":            "pending",
        }
        if lead_id:
            row["lead_id"] = lead_id
        if customer_id:
            row["customer_id"] = customer_id
        if subscription_id:
            row["subscription_id"] = subscription_id

        db.table("commissions").insert(row).execute()

    except Exception as exc:
        logger.warning(
            "auto_create_commission: failed for affiliate %s event %s — %s",
            affiliate_user_id, event_type, exc,
        )


# ============================================================
# _notify_affiliate_commission — internal
# ============================================================

def _notify_affiliate_commission(
    db,
    org_id: str,
    affiliate_user_id: str,
    commission_id: str,
    new_status: str,
    amount_ngn: float,
) -> None:
    """Insert in-app notification and optionally a queued WhatsApp message."""
    status_label = "approved" if new_status == "approved" else "marked as paid"

    # In-app notification — always
    try:
        db.table("notifications").insert({
            "org_id":        org_id,
            "user_id":       affiliate_user_id,
            "title":         f"Commission {status_label}",
            "body":          (
                f"Your commission of \u20a6{amount_ngn:,.2f} has been "
                f"{status_label} by your manager."
            ),
            "type":          "commission",
            "resource_type": "commission",
            "resource_id":   commission_id,
            "is_read":       False,
        }).execute()
    except Exception as exc:
        logger.warning("_notify_affiliate_commission: notification insert failed — %s", exc)

    # WhatsApp — only if org setting enabled + user has whatsapp_number
    try:
        settings = _fetch_org_commission_settings(db, org_id)
        if not settings.get("commission_whatsapp_notify", False):
            return

        user_result = (
            db.table("users")
            .select("whatsapp_number, full_name")
            .eq("id", affiliate_user_id)
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        user_row = _one(user_result.data)
        if not user_row or not user_row.get("whatsapp_number"):
            return

        wa_number  = user_row["whatsapp_number"]
        full_name  = user_row.get("full_name", "")
        body = (
            f"Hi {full_name}, your commission of \u20a6{amount_ngn:,.2f} has been "
            f"{status_label}. Please log in to Opsra to view the details."
        )

        db.table("whatsapp_messages").insert({
            "org_id":       org_id,
            "direction":    "outbound",
            "message_type": "notification",
            "body":         body,
            "status":       "queued",
            "phone_number": wa_number,
        }).execute()

    except Exception as exc:
        logger.warning(
            "_notify_affiliate_commission: WhatsApp notification failed — %s", exc
        )


# ============================================================
# list_commissions
# ============================================================

def list_commissions(
    org: dict,
    db,
    affiliate_user_id: Optional[str] = None,
    comm_status: Optional[str] = None,
    event_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    org_id   = org["org_id"]
    caller   = org["id"]
    managing = _can_manage(org)

    result = (
        db.table("commissions")
        .select("*, affiliate:users!affiliate_user_id(id, full_name, email)")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    all_items: list = result.data or []

    if not managing:
        all_items = [c for c in all_items if c.get("affiliate_user_id") == caller]
    elif affiliate_user_id:
        all_items = [c for c in all_items if c.get("affiliate_user_id") == affiliate_user_id]

    if comm_status:
        all_items = [c for c in all_items if c.get("status") == comm_status]
    if event_type:
        all_items = [c for c in all_items if c.get("event_type") == event_type]

    total = len(all_items)
    start = (page - 1) * page_size
    items = all_items[start: start + page_size]

    return {
        "items":     items,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  (start + page_size) < total,
    }


# ============================================================
# get_commission_summary
# ============================================================

def get_commission_summary(org: dict, db) -> dict:
    org_id   = org["org_id"]
    caller   = org["id"]
    managing = _can_manage(org)

    result = (
        db.table("commissions")
        .select("affiliate_user_id, status, amount_ngn")
        .eq("org_id", org_id)
        .execute()
    )
    all_rows: list = result.data or []

    if not managing:
        all_rows = [r for r in all_rows if r.get("affiliate_user_id") == caller]

    totals = {s: {"count": 0, "amount_ngn": 0} for s in COMMISSION_STATUSES}
    for row in all_rows:
        s = row.get("status", "pending")
        if s in totals:
            totals[s]["count"]      += 1
            totals[s]["amount_ngn"] += float(row.get("amount_ngn") or 0)

    return {
        "total_count":      len(all_rows),
        "total_amount_ngn": sum(float(r.get("amount_ngn") or 0) for r in all_rows),
        "by_status":        totals,
    }


# ============================================================
# update_commission
# ============================================================

def update_commission(
    commission_id: str,
    org: dict,
    db,
    amount_ngn: Optional[float] = None,
    comm_status: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    if not _can_manage(org):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Only managers can update commission records"},
        )

    org_id = org["org_id"]

    check = (
        db.table("commissions")
        .select("*")
        .eq("id", commission_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    existing = _one(check.data)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Commission not found"},
        )

    if comm_status and comm_status not in COMMISSION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code":    "VALIDATION_ERROR",
                "message": f"Invalid status. Must be one of: {', '.join(sorted(COMMISSION_STATUSES))}",
            },
        )

    update_data: dict = {}
    if amount_ngn is not None:
        update_data["amount_ngn"] = amount_ngn
    if comm_status:
        update_data["status"] = comm_status
        if comm_status == "paid":
            update_data["paid_at"] = _now()
    if notes is not None:
        update_data["notes"] = notes

    if not update_data:
        return existing

    result = (
        db.table("commissions")
        .update(update_data)
        .eq("id", commission_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**existing, **update_data}

    _write_audit(
        db=db, org_id=org_id, user_id=org["id"],
        action="commission.updated", resource_id=commission_id,
        old_val={k: existing.get(k) for k in update_data},
        new_val=update_data,
    )

    # Notify affiliate on approval or payment
    if comm_status in ("approved", "paid"):
        final_amount = float(
            update_data.get("amount_ngn") or existing.get("amount_ngn") or 0
        )
        _notify_affiliate_commission(
            db=db,
            org_id=org_id,
            affiliate_user_id=existing["affiliate_user_id"],
            commission_id=commission_id,
            new_status=comm_status,
            amount_ngn=final_amount,
        )

    return updated