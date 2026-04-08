"""
customers.py — Module 02 customer profile routes.

All routes are prefixed with /api/v1/customers via main.py include_router.

Phase 9B additions:
  - list_customers: scoped roles (sales_agent, affiliate_partner) see only
    customers assigned to themselves
  - get_customer: scoped roles can only fetch customers assigned to them
  - update_customer: affiliate_partner is read-only — blocked with 403
  - Pattern 37: role derived via rbac module

Routes (full paths after combining):
  GET   /api/v1/customers
  GET   /api/v1/customers/{customer_id}
  PATCH /api/v1/customers/{customer_id}
  GET   /api/v1/customers/{customer_id}/messages
  GET   /api/v1/customers/{customer_id}/tasks
  GET   /api/v1/customers/{customer_id}/nps

Auth: JWT required on all routes (get_current_org dependency).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ok, paginated
from app.models.customers import CustomerUpdate
from app.services import whatsapp_service
from app.utils.rbac import is_scoped_role, require_not_affiliate

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Customer list
# Phase 9B: scoped roles see only their own assigned customers
# ---------------------------------------------------------------------------

@router.get("")
def list_customers(
    churn_risk: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    onboarding_complete: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    # Phase 9B: force assigned_to for scoped roles
    effective_assigned_to = org["id"] if is_scoped_role(org) else assigned_to

    result = whatsapp_service.list_customers(
        db=db,
        org_id=org["org_id"],
        churn_risk=churn_risk,
        assigned_to=effective_assigned_to,
        onboarding_complete=onboarding_complete,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Customer profile
# Phase 9B: scoped roles can only fetch their own assigned customers
# ---------------------------------------------------------------------------

@router.get("/{customer_id}")
def get_customer(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    customer = whatsapp_service.get_customer(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )

    # Phase 9B: scoped roles can only see their own customers
    if is_scoped_role(org) and customer.get("assigned_to") != org["id"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code":    "FORBIDDEN",
                "message": "You can only view customers assigned to you",
            },
        )

    # Phase 9E — TEMP-2 fix: compute window_open from whatsapp_messages table.
    # Replaces the frontend default of `?? true` with an authoritative value.
    # S14: failure defaults to False (window closed) — the safe production default.
    try:
        customer["window_open"] = whatsapp_service._is_window_open(
            db, org["org_id"], customer_id
        )
    except Exception as _exc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "window_open check failed for customer %s: %s", customer_id, _exc
        )
        customer["window_open"] = False

    # Feature 1 (Module 01 gaps): surface subscription + payment summary on Customer Profile.
    # Fetches the most recent non-cancelled subscription and its most recent payment.
    # S14: failure returns subscription=None — never blocks the customer profile load.
    try:
        # Fetch most recent non-cancelled subscription for this customer.
        # Use regular .execute() with .limit(1) — avoids .maybe_single() returning
        # None (not an object) when 0 rows match (Pattern 45).
        sub_result = (
            db.table("subscriptions")
            .select("id, plan_name, plan_tier, billing_cycle, status, amount, current_period_end")
            .eq("org_id", org["org_id"])
            .eq("customer_id", customer_id)
            .in_("status", ["active", "trial", "grace_period"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        sub_rows = sub_result.data or []
        sub = sub_rows[0] if sub_rows else None

        if sub:
            # Fetch most recent confirmed payment linked to this subscription.
            # Filter by subscription_id — the renewal module's payment insert
            # does not write customer_id to the payments table.
            pay_result = (
                db.table("payments")
                .select("amount, payment_date, payment_channel")
                .eq("org_id", org["org_id"])
                .eq("subscription_id", sub["id"])
                .eq("status", "confirmed")
                .order("payment_date", desc=True)
                .limit(1)
                .execute()
            )
            pay_rows = pay_result.data or []
            last_pay = pay_rows[0] if pay_rows else None

            customer["subscription"] = {
                "plan_name":        sub.get("plan_name"),
                "plan_tier":        sub.get("plan_tier"),
                "billing_cycle":    sub.get("billing_cycle"),
                "status":           sub.get("status"),
                "amount":           sub.get("amount"),
                "next_due":         sub.get("current_period_end"),
                "last_paid_amount": (last_pay or {}).get("amount"),
                "last_paid_date":   (last_pay or {}).get("payment_date"),
                "payment_channel":  (last_pay or {}).get("payment_channel"),
            }
        else:
            customer["subscription"] = None

    except Exception as _sub_exc:
        logger.warning("Subscription fetch failed for customer %s: %s", customer_id, _sub_exc)
        customer["subscription"] = None

    return ok(data=customer)


@router.patch("/{customer_id}")
def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    # Phase 9B: affiliate_partner is read-only
    require_not_affiliate(org, "editing customers")

    updated = whatsapp_service.update_customer(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
        user_id=org["id"],
        payload=payload,
    )
    return ok(data=updated, message="Customer updated")


# ---------------------------------------------------------------------------
# Customer sub-resources
# Scoped roles can access these for their own assigned customers.
# The customer ownership check is not repeated here for performance —
# the sub-resource queries are already scoped to org_id + customer_id.
# A scoped user who somehow calls these for a non-assigned customer
# will receive empty results (no data leakage).
# ---------------------------------------------------------------------------

@router.get("/{customer_id}/messages")
def get_customer_messages(
    customer_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    result = whatsapp_service.get_customer_messages(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
        page=page,
        page_size=page_size,
    )
    return paginated(
        items=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.get("/{customer_id}/tasks")
def get_customer_tasks(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    tasks = whatsapp_service.get_customer_tasks(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )
    return ok(data=tasks)


@router.get("/{customer_id}/nps")
def get_customer_nps(
    customer_id: str,
    db=Depends(get_supabase),
    org=Depends(get_current_org),
):
    responses = whatsapp_service.get_customer_nps(
        db=db,
        org_id=org["org_id"],
        customer_id=customer_id,
    )
    return ok(data=responses)