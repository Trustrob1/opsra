"""
app/routers/subscriptions.py
FastAPI router for Module 04 — Renewal & Upsell Engine.

Prefix: /api/v1/subscriptions (set in main.py — Pattern 7)

ROUTE ORDERING — CRITICAL:
  Static paths (/bulk-confirm, /bulk-confirm/{job_id}) are registered BEFORE
  parameterised paths (/{subscription_id}) so FastAPI does not consume the
  literal string "bulk-confirm" as a subscription UUID.

All routes:
  - Use get_current_org, not get_current_user (Pattern 28)
  - Extract org_id from JWT only — never from request body (S1)
  - No react-router, no org_id in responses that the frontend sends back (F2)

Admin enforcement:
  PATCH and cancel routes require owner role.
  Full RBAC (all roles, all transitions) deferred to Phase 6A (S17).
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.database import get_supabase
from app.dependencies import get_current_org
from app.models.common import ErrorCode, ok, paginated
from app.models.subscriptions import (
    CancelSubscriptionRequest,
    ConfirmPaymentRequest,
    SubscriptionUpdate,
)
from app.services.subscription_service import (
    cancel_subscription,
    confirm_payment,
    create_bulk_confirm_job,
    get_bulk_confirm_job,
    get_subscription,
    list_subscriptions,
    process_bulk_confirm,
    update_subscription,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Role sets — inline checks (full RBAC deferred to Phase 6A per S17)
# ---------------------------------------------------------------------------
_ADMIN_ROLES: frozenset[str] = frozenset({"owner", "ops_manager"})
_CEO_ROLES: frozenset[str] = frozenset({"owner"})


def _require_role(
    org: dict,
    allowed: frozenset[str],
    detail: str = "Insufficient permissions for this action",
) -> None:
    """Raise 403 if the authenticated user's role is not in allowed."""
    if org.get("role") not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": detail},
        )


# ---------------------------------------------------------------------------
# Allowed MIME types for CSV/Excel bulk upload (S10)
# ---------------------------------------------------------------------------
_ALLOWED_BULK_MIME: frozenset[str] = frozenset({
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # some browsers send this for .csv
})

_MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB — S10


# ---------------------------------------------------------------------------
# GET / — list subscriptions
# ---------------------------------------------------------------------------


@router.get("")
async def list_subscriptions_route(
    sub_status: Optional[str] = Query(None, alias="status"),
    plan_tier: Optional[str] = Query(None),
    renewal_window_days: Optional[int] = Query(None, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    List subscriptions for this organisation.
    Filters: status, plan_tier, renewal_window_days (renewals due within N days).
    Ordered by current_period_end ascending — most urgent first.
    """
    org_id = org["org_id"]
    result = list_subscriptions(
        db=db,
        org_id=org_id,
        sub_status=sub_status,
        plan_tier=plan_tier,
        renewal_window_days=renewal_window_days,
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
# POST /bulk-confirm — CSV bulk payment upload ← MUST be before /{id}
# ---------------------------------------------------------------------------


@router.post("/bulk-confirm", status_code=status.HTTP_202_ACCEPTED)
async def bulk_confirm_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Method 3 — CSV/Excel bulk payment confirmation upload.
    Accepts a CSV file with columns: subscription_id|phone, amount,
    payment_date, payment_channel, reference (optional), notes (optional).
    Returns a job_id immediately — processing runs in the background.
    Poll GET /bulk-confirm/{job_id} for status.
    DRD §6.4: Unmatched rows flagged for manual review.
    """
    org_id = org["org_id"]
    user_id = org["id"]

    # S10 — MIME type allowlist check
    if file.content_type not in _ALLOWED_BULK_MIME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": (
                    f"Unsupported file type '{file.content_type}'. "
                    "Upload a .csv or .xlsx file."
                ),
            },
        )

    contents = await file.read()

    # S10 — 25 MB cap
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "File exceeds the maximum allowed size of 25 MB",
            },
        )

    # Parse CSV (utf-8-sig handles BOM from Excel exports)
    try:
        decoded = contents.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        rows = list(reader)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": f"Could not parse file as CSV: {exc}",
            },
        )

    job_id = create_bulk_confirm_job(org_id)
    background_tasks.add_task(
        process_bulk_confirm, db, org_id, user_id, job_id, rows
    )

    return ok(
        data={"job_id": job_id, "total_rows": len(rows)},
        message=f"Bulk confirmation job queued. Processing {len(rows)} rows.",
    )


# ---------------------------------------------------------------------------
# GET /bulk-confirm/{job_id} — poll job status ← MUST be before /{id}
# ---------------------------------------------------------------------------


@router.get("/bulk-confirm/{job_id}")
async def get_bulk_confirm_job_route(
    job_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Poll bulk confirmation job status."""
    org_id = org["org_id"]
    job = get_bulk_confirm_job(org_id, job_id)
    return ok(data=job)


# ---------------------------------------------------------------------------
# GET /{subscription_id}
# ---------------------------------------------------------------------------


@router.get("/{subscription_id}")
async def get_subscription_route(
    subscription_id: str,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """Get subscription with customer info and full payment history."""
    org_id = org["org_id"]
    sub = get_subscription(db=db, org_id=org_id, subscription_id=subscription_id)
    return ok(data=sub)


# ---------------------------------------------------------------------------
# PATCH /{subscription_id} — Admin only
# ---------------------------------------------------------------------------


@router.patch("/{subscription_id}")
async def update_subscription_route(
    subscription_id: str,
    payload: SubscriptionUpdate,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Update subscription plan and billing details.
    Admin only (owner or ops_manager role).
    Full RBAC deferred to Phase 6A.
    """
    _require_role(org, _ADMIN_ROLES, "Admin access required to update subscriptions")
    org_id = org["org_id"]
    user_id = org["id"]
    updated = update_subscription(
        db=db,
        org_id=org_id,
        subscription_id=subscription_id,
        user_id=user_id,
        payload=payload,
    )
    return ok(data=updated, message="Subscription updated")


# ---------------------------------------------------------------------------
# POST /{subscription_id}/confirm-payment — Method 2: Manual confirmation
# ---------------------------------------------------------------------------


@router.post("/{subscription_id}/confirm-payment")
async def confirm_payment_route(
    subscription_id: str,
    payload: ConfirmPaymentRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Method 2 — Manual payment confirmation.
    Finance/Billing is the primary user of this route — any authenticated
    org member can confirm. Full RBAC (Finance/Billing only) deferred to Phase 6A.
    """
    org_id = org["org_id"]
    user_id = org["id"]
    updated = confirm_payment(
        db=db,
        org_id=org_id,
        subscription_id=subscription_id,
        user_id=user_id,
        payload=payload,
    )
    return ok(data=updated, message="Payment confirmed. Subscription activated.")


# ---------------------------------------------------------------------------
# POST /{subscription_id}/cancel — CEO (owner) only
# ---------------------------------------------------------------------------


@router.post("/{subscription_id}/cancel")
async def cancel_subscription_route(
    subscription_id: str,
    payload: CancelSubscriptionRequest,
    org: dict = Depends(get_current_org),
    db=Depends(get_supabase),
):
    """
    Cancel a subscription.
    Owner (CEO) only — DRD: Cancellation requires CEO approval.
    No subscription can be cancelled without the owner's authorisation.
    """
    _require_role(
        org, _CEO_ROLES, "Only the organisation owner can cancel a subscription"
    )
    org_id = org["org_id"]
    user_id = org["id"]
    updated = cancel_subscription(
        db=db,
        org_id=org_id,
        subscription_id=subscription_id,
        user_id=user_id,
        reason=payload.reason,
    )
    return ok(data=updated, message="Subscription cancelled")