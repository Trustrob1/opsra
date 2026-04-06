"""
app/services/subscription_service.py
Business logic for Module 04 — Renewal & Upsell Engine.

Conventions:
  - All functions take `db` as first arg (Supabase client from get_supabase())
  - org_id always from JWT — never from request body
  - Subscription history preserved via status transitions — never hard deleted
  - audit_logs written after every significant action (Pattern 5)
  - Status machine enforced — Technical Spec Section 4.3
  - All 4 payment confirmation methods write to the same payments table (DRD §6.4)
  - Duplicate reference detection on every payment path (DRD §6.4)
"""
from __future__ import annotations

import calendar
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from app.models.common import ErrorCode
from app.models.subscriptions import (
    BulkConfirmRow,
    ConfirmPaymentRequest,
    SubscriptionUpdate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_period_end(payment_date: date, billing_cycle: str) -> date:
    """
    Calculate the next subscription period end date from a payment date.
    monthly → advance by 1 calendar month (handles month-end edge cases).
    annual  → advance by 1 year (handles leap-year edge cases).
    DRD §6.4: Renewal date recalculated from actual payment date, not missed date.
    """
    if billing_cycle == "annual":
        try:
            return payment_date.replace(year=payment_date.year + 1)
        except ValueError:
            # Feb 29 in a non-leap year → Feb 28
            return payment_date.replace(year=payment_date.year + 1, day=28)
    else:  # monthly
        month = payment_date.month + 1
        year = payment_date.year
        if month > 12:
            month = 1
            year += 1
        max_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(payment_date.day, max_day))


def _normalise_phone(value: Optional[str]) -> Optional[str]:
    """Strip all non-digit characters (except leading +) for phone matching."""
    if not value:
        return None
    v = str(value).strip()
    if "E+" in v.upper():
        try:
            v = str(int(float(v)))
        except (ValueError, OverflowError):
            pass
    v = re.sub(r"[^\d+]", "", v)
    return v or None


def write_audit_log(
    db: Any,
    org_id: str,
    user_id: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> None:
    """Write an immutable audit log entry — Technical Spec Section 9.5."""
    db.table("audit_logs").insert(
        {
            "org_id": org_id,
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
        }
    ).execute()


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _subscription_or_404(db: Any, org_id: str, subscription_id: str) -> dict:
    """Fetch subscription by id scoped to org, raise 404 if absent."""
    result = (
        db.table("subscriptions")
        .select("*")
        .eq("id", subscription_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Subscription {subscription_id} not found in this organisation",
            },
        )
    return data


def _check_duplicate_reference(db: Any, org_id: str, reference: str) -> bool:
    """
    Return True if a payment with this reference already exists in this org.
    Duplicate reference check — DRD §6.4: second submission rejected with duplicate flag.
    """
    result = (
        db.table("payments")
        .select("id")
        .eq("org_id", org_id)
        .eq("reference", reference)
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        return bool(data)
    return bool(data)


# ---------------------------------------------------------------------------
# list_subscriptions
# ---------------------------------------------------------------------------


def list_subscriptions(
    db: Any,
    org_id: str,
    sub_status: Optional[str] = None,
    plan_tier: Optional[str] = None,
    renewal_window_days: Optional[int] = None,
    customer_name: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    List subscriptions with optional filters and pagination.
    renewal_window_days — return subscriptions renewing within the next N days.
    customer_name       — case-insensitive partial match on customer full_name.
                          Two-step: customers ILIKE lookup → filter by IDs.
                          Returns empty immediately when no customers match.
    Ordered by current_period_end ascending (most urgent first).
    """
    # ── customer_name: fetch all org customers, filter in Python ────────────
    # PostgREST ILIKE/filter queries crash the Supabase edge worker in the
    # current configuration. Fetching by org_id and filtering in Python is
    # reliable for any realistic org size and avoids all compatibility issues.
    customer_ids: Optional[list] = None
    if customer_name and customer_name.strip():
        name_lower = customer_name.strip().lower()
        cust_result = (
            db.table("customers")
            .select("id, full_name")
            .eq("org_id", org_id)
            .execute()
        )
        matching = [
            c for c in (cust_result.data or [])
            if name_lower in (c.get("full_name") or "").lower()
        ]
        if not matching:
            # No customers match — skip subscriptions query entirely
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        customer_ids = [c["id"] for c in matching]

    # ── Build subscriptions query ────────────────────────────────────────────
    query = (
        db.table("subscriptions")
        .select(
            "*, customer:customers(id, full_name, phone, business_name)",
            count="exact",
        )
        .eq("org_id", org_id)
    )

    if sub_status:
        query = query.eq("status", sub_status)
    if plan_tier:
        query = query.eq("plan_tier", plan_tier)
    if customer_ids is not None:
        query = query.in_("customer_id", customer_ids)
    if renewal_window_days is not None:
        today = date.today()
        window_end = (today + timedelta(days=renewal_window_days)).isoformat()
        query = (
            query
            .gte("current_period_end", today.isoformat())
            .lte("current_period_end", window_end)
        )

    offset = (page - 1) * page_size
    result = (
        query
        .range(offset, offset + page_size - 1)
        .order("current_period_end", desc=False)
        .execute()
    )
    return {
        "items": result.data or [],
        "total": result.count or 0,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# get_subscription
# ---------------------------------------------------------------------------


def get_subscription(db: Any, org_id: str, subscription_id: str) -> dict:
    """
    Get a subscription with customer info and full payment history.
    Technical Spec §8.4 — GET /api/v1/subscriptions/{id}.
    """
    result = (
        db.table("subscriptions")
        .select(
            "*, customer:customers(id, full_name, phone, business_name, whatsapp)"
        )
        .eq("id", subscription_id)
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Subscription {subscription_id} not found in this organisation",
            },
        )

    # Fetch full payment history
    payments_result = (
        db.table("payments")
        .select("*")
        .eq("subscription_id", subscription_id)
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    data["payments"] = payments_result.data or []
    return data


# ---------------------------------------------------------------------------
# update_subscription — Admin only
# ---------------------------------------------------------------------------


def update_subscription(
    db: Any,
    org_id: str,
    subscription_id: str,
    user_id: str,
    payload: SubscriptionUpdate,
) -> dict:
    """
    Update subscription plan and billing details.
    Admin only — enforced at router level.
    """
    old_sub = _subscription_or_404(db, org_id, subscription_id)

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        return old_sub

    # Serialise date fields to ISO strings for storage
    for field in ("current_period_start", "current_period_end"):
        if field in updates and isinstance(updates[field], date):
            updates[field] = updates[field].isoformat()

    updates["updated_at"] = _now_iso()

    result = (
        db.table("subscriptions")
        .update(updates)
        .eq("id", subscription_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**old_sub, **updates}

    write_audit_log(
        db, org_id, user_id,
        action="subscription.updated",
        resource_type="subscription",
        resource_id=subscription_id,
        old_value={k: old_sub.get(k) for k in updates if k != "updated_at"},
        new_value=updates,
    )
    return updated


# ---------------------------------------------------------------------------
# _confirm_payment_internal — shared by all 4 payment methods (DRD §6.4)
# ---------------------------------------------------------------------------


def _confirm_payment_internal(
    db: Any,
    org_id: str,
    subscription: dict,
    amount: float,
    payment_date: date,
    payment_channel: str,
    reference: Optional[str],
    notes: Optional[str],
    method: str,
    confirmed_by: Optional[str] = None,
) -> dict:
    """
    Core payment confirmation logic shared by all 4 payment methods.

    1. Inserts a confirmed payment record in the payments table.
    2. Recalculates subscription period from actual payment date (DRD §6.4).
    3. Updates subscription status to 'active', clears grace_period_ends_at.

    DRD §6.4: All four methods write to the same payment history log.
    """
    subscription_id = subscription["id"]
    billing_cycle = subscription.get("billing_cycle", "monthly")

    payment_data: dict = {
        "org_id": org_id,
        "subscription_id": subscription_id,
        "amount": amount,
        "currency": subscription.get("currency", "NGN"),
        "payment_method": method,
        "payment_channel": payment_channel,
        "status": "confirmed",
        "payment_date": payment_date.isoformat(),
    }
    if reference:
        payment_data["reference"] = reference
    if notes:
        payment_data["notes"] = notes
    if confirmed_by:
        payment_data["confirmed_by"] = confirmed_by

    db.table("payments").insert(payment_data).execute()

    # Recalculate period from actual payment date — DRD §6.4
    next_period_end = _next_period_end(payment_date, billing_cycle)

    updates: dict = {
        "status": "active",
        "current_period_start": payment_date.isoformat(),
        "current_period_end": next_period_end.isoformat(),
        "grace_period_ends_at": None,
        "updated_at": _now_iso(),
    }

    result = (
        db.table("subscriptions")
        .update(updates)
        .eq("id", subscription_id)
        .eq("org_id", org_id)
        .execute()
    )

    # Phase 9C: auto-create commission if customer has an assigned rep
    # S14: never fail the core payment confirmation
    try:
        from app.services.commissions_service import auto_create_commission
        _cust = (
            db.table("customers")
            .select("assigned_to")
            .eq("id", subscription.get("customer_id", ""))
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        _cust_row = _cust.data
        if isinstance(_cust_row, list):
            _cust_row = _cust_row[0] if _cust_row else None
        _assigned = (_cust_row or {}).get("assigned_to")
        if _assigned:
            auto_create_commission(
                db=db,
                org_id=org_id,
                affiliate_user_id=_assigned,
                event_type="payment_confirmed",
                customer_id=subscription.get("customer_id"),
                subscription_id=subscription_id,
            )
    except Exception as _ce:
        import logging as _log
        _log.getLogger(__name__).warning(
            "confirm_payment: commission creation failed — %s", _ce
        )

    return result.data[0] if result.data else {**subscription, **updates}


# ---------------------------------------------------------------------------
# confirm_payment — Method 2: Manual confirmation
# ---------------------------------------------------------------------------


def confirm_payment(
    db: Any,
    org_id: str,
    subscription_id: str,
    user_id: str,
    payload: ConfirmPaymentRequest,
) -> dict:
    """
    Method 2 — Manual payment confirmation.
    An authorised user opens the subscription record and clicks Confirm Payment.
    Duplicate reference check per DRD §6.4.
    """
    subscription = _subscription_or_404(db, org_id, subscription_id)

    if payload.reference and _check_duplicate_reference(
        db, org_id, payload.reference
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.DUPLICATE_DETECTED,
                "message": (
                    f"Payment reference '{payload.reference}' has already been "
                    "recorded for this organisation."
                ),
            },
        )

    updated = _confirm_payment_internal(
        db=db,
        org_id=org_id,
        subscription=subscription,
        amount=payload.amount,
        payment_date=payload.payment_date,
        payment_channel=payload.payment_channel,
        reference=payload.reference,
        notes=payload.notes,
        method="manual",
        confirmed_by=user_id,
    )

    write_audit_log(
        db, org_id, user_id,
        action="subscription.payment_confirmed",
        resource_type="subscription",
        resource_id=subscription_id,
        old_value={"status": subscription.get("status")},
        new_value={
            "status": "active",
            "method": "manual",
            "amount": payload.amount,
            "payment_channel": payload.payment_channel,
            "reference": payload.reference,
        },
    )
    return updated


# ---------------------------------------------------------------------------
# cancel_subscription — CEO (owner) only
# ---------------------------------------------------------------------------


def cancel_subscription(
    db: Any,
    org_id: str,
    subscription_id: str,
    user_id: str,
    reason: str,
) -> dict:
    """
    CEO-only subscription cancellation.
    DRD: Cancellation requires CEO approval — no subscription cancelled without authorisation.
    Records cancelled_at, cancelled_by, and cancellation_reason.
    """
    subscription = _subscription_or_404(db, org_id, subscription_id)

    if subscription.get("status") == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.INVALID_TRANSITION,
                "message": "Subscription is already cancelled.",
            },
        )

    cancelled_at = _now_iso()
    updates: dict = {
        "status": "cancelled",
        "cancelled_at": cancelled_at,
        "cancelled_by": user_id,
        "cancellation_reason": reason,
        "updated_at": cancelled_at,
    }

    result = (
        db.table("subscriptions")
        .update(updates)
        .eq("id", subscription_id)
        .eq("org_id", org_id)
        .execute()
    )
    updated = result.data[0] if result.data else {**subscription, **updates}

    write_audit_log(
        db, org_id, user_id,
        action="subscription.cancelled",
        resource_type="subscription",
        resource_id=subscription_id,
        old_value={"status": subscription.get("status")},
        new_value={"status": "cancelled", "cancellation_reason": reason},
    )
    return updated


# ---------------------------------------------------------------------------
# Bulk confirm job store — Method 3: CSV/Excel bulk upload
# ---------------------------------------------------------------------------

_bulk_jobs: dict[str, dict] = {}


def create_bulk_confirm_job(org_id: str) -> str:
    """Create a new bulk confirmation job, return its job_id."""
    job_id = str(uuid.uuid4())
    _bulk_jobs[job_id] = {
        "job_id": job_id,
        "org_id": org_id,
        "status": "pending",
        "total_rows": 0,
        "confirmed": 0,
        "unmatched": 0,
        "failed": 0,
        "errors": [],
        "created_at": _now_iso(),
        "completed_at": None,
    }
    return job_id


def get_bulk_confirm_job(org_id: str, job_id: str) -> dict:
    """Return bulk confirmation job status. Raises 404 if not found or wrong org."""
    job = _bulk_jobs.get(job_id)
    if not job or job.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ErrorCode.NOT_FOUND,
                "message": f"Bulk confirmation job {job_id} not found",
            },
        )
    return job


def process_bulk_confirm(
    db: Any,
    org_id: str,
    user_id: str,
    job_id: str,
    rows: list[dict],
) -> None:
    """
    Method 3 — CSV/Excel Bulk Upload processing.
    Matches each row to a subscription by subscription_id or customer phone.
    Unmatched rows flagged for manual review.
    Summary: confirmed, unmatched, error count — DRD §6.4.
    """
    job = _bulk_jobs[job_id]
    job["status"] = "processing"
    job["total_rows"] = len(rows)

    if not rows:
        job["status"] = "done"
        job["completed_at"] = _now_iso()
        return

    for i, row in enumerate(rows):
        try:
            parsed = BulkConfirmRow(**row)

            if not parsed.subscription_id and not parsed.phone:
                job["unmatched"] += 1
                job["errors"].append({
                    "row": i + 1,
                    "message": "Row must have subscription_id or phone to match a subscription",
                })
                continue

            subscription = None

            # Primary match: direct subscription_id lookup
            if parsed.subscription_id:
                try:
                    subscription = _subscription_or_404(
                        db, org_id, parsed.subscription_id
                    )
                except HTTPException:
                    subscription = None

            # Fallback match: phone → customer → latest non-cancelled subscription
            if subscription is None and parsed.phone:
                phone_norm = _normalise_phone(parsed.phone)
                if phone_norm:
                    cust_result = (
                        db.table("customers")
                        .select("id")
                        .eq("org_id", org_id)
                        .eq("phone", phone_norm)
                        .is_("deleted_at", "null")
                        .maybe_single()
                        .execute()
                    )
                    cust_data = cust_result.data
                    if isinstance(cust_data, list):
                        cust_data = cust_data[0] if cust_data else None
                    if cust_data:
                        sub_result = (
                            db.table("subscriptions")
                            .select("*")
                            .eq("org_id", org_id)
                            .eq("customer_id", cust_data["id"])
                            .neq("status", "cancelled")
                            .order("created_at", desc=True)
                            .limit(1)
                            .maybe_single()
                            .execute()
                        )
                        sub_data = sub_result.data
                        if isinstance(sub_data, list):
                            sub_data = sub_data[0] if sub_data else None
                        subscription = sub_data

            if subscription is None:
                job["unmatched"] += 1
                job["errors"].append({
                    "row": i + 1,
                    "message": "No subscription found matching the provided phone or subscription_id",
                })
                continue

            # Duplicate reference check — DRD §6.4
            if parsed.reference and _check_duplicate_reference(
                db, org_id, parsed.reference
            ):
                job["failed"] += 1
                job["errors"].append({
                    "row": i + 1,
                    "message": f"Duplicate payment reference: {parsed.reference}",
                })
                continue

            _confirm_payment_internal(
                db=db,
                org_id=org_id,
                subscription=subscription,
                amount=parsed.amount,
                payment_date=parsed.payment_date,
                payment_channel=parsed.payment_channel,
                reference=parsed.reference,
                notes=parsed.notes,
                method="csv_upload",
                confirmed_by=user_id,
            )

            write_audit_log(
                db, org_id, user_id,
                action="subscription.payment_confirmed",
                resource_type="subscription",
                resource_id=subscription["id"],
                old_value={"status": subscription.get("status")},
                new_value={
                    "status": "active",
                    "method": "csv_upload",
                    "amount": parsed.amount,
                },
            )
            job["confirmed"] += 1

        except HTTPException as exc:
            job["failed"] += 1
            detail = exc.detail or {}
            job["errors"].append({
                "row": i + 1,
                "message": detail.get("message", str(exc)),
            })
        except Exception as exc:  # pylint: disable=broad-except
            job["failed"] += 1
            job["errors"].append({"row": i + 1, "message": str(exc)})

    job["status"] = "done"
    job["completed_at"] = _now_iso()


# ---------------------------------------------------------------------------
# Webhook handlers — Method 1: Paystack and Flutterwave
# ---------------------------------------------------------------------------


def process_paystack_webhook(db: Any, payload: dict) -> None:
    """
    Method 1 — Paystack charge.success webhook handler.
    Technical Spec §8.5. Called from POST /webhooks/payment/paystack.

    Expected payload structure:
    {
      "event": "charge.success",
      "data": {
        "reference": "TXN_abc123",
        "amount": 4500000,       # kobo — divide by 100 for naira
        "paid_at": "2026-03-23T10:00:00.000Z",
        "metadata": {
          "subscription_id": "<uuid>",
          "org_id": "<uuid>"
        }
      }
    }

    Signature verification is performed by the webhook router before calling
    this function (PAYSTACK_SECRET_KEY environment variable).
    """
    event = payload.get("event")
    if event != "charge.success":
        logger.info("Paystack webhook ignored — unhandled event type: %s", event)
        return

    data = payload.get("data", {})
    metadata = data.get("metadata", {})
    org_id = metadata.get("org_id")
    subscription_id = metadata.get("subscription_id")

    if not org_id or not subscription_id:
        logger.warning(
            "Paystack webhook: missing org_id or subscription_id in metadata. "
            "Ensure Opsra subscription_id and org_id are passed in payment metadata."
        )
        return

    reference = data.get("reference")

    # Amount is in kobo — convert to naira (NGN)
    amount_kobo = data.get("amount", 0)
    amount_ngn = round(amount_kobo / 100, 2) if amount_kobo else 0

    paid_at_str = data.get("paid_at", "")
    try:
        paid_at_dt = datetime.fromisoformat(paid_at_str.replace("Z", "+00:00"))
        payment_date = paid_at_dt.date()
    except (ValueError, AttributeError):
        payment_date = date.today()
        logger.warning(
            "Paystack webhook: could not parse paid_at '%s', using today", paid_at_str
        )

    # Duplicate reference check — DRD §6.4
    if reference and _check_duplicate_reference(db, org_id, reference):
        logger.warning(
            "Paystack webhook: duplicate reference '%s' for org %s — ignored",
            reference, org_id,
        )
        return

    try:
        subscription = _subscription_or_404(db, org_id, subscription_id)
    except HTTPException:
        logger.warning(
            "Paystack webhook: subscription %s not found for org %s",
            subscription_id, org_id,
        )
        return

    _confirm_payment_internal(
        db=db,
        org_id=org_id,
        subscription=subscription,
        amount=amount_ngn,
        payment_date=payment_date,
        payment_channel="paystack",
        reference=reference,
        notes=f"Paystack webhook — event: {event}",
        method="webhook",
        confirmed_by=None,
    )

    write_audit_log(
        db, org_id, user_id=None,
        action="subscription.payment_confirmed",
        resource_type="subscription",
        resource_id=subscription_id,
        old_value={"status": subscription.get("status")},
        new_value={
            "status": "active",
            "method": "webhook",
            "channel": "paystack",
            "reference": reference,
        },
    )
    logger.info(
        "Paystack webhook: confirmed — subscription %s org %s amount %.2f NGN",
        subscription_id, org_id, amount_ngn,
    )


def process_flutterwave_webhook(db: Any, payload: dict) -> None:
    """
    Method 1 — Flutterwave charge.completed webhook handler.
    Technical Spec §8.5. Called from POST /webhooks/payment/flutterwave.

    Expected payload structure:
    {
      "event": "charge.completed",
      "data": {
        "tx_ref": "TXN_abc123",
        "amount": 45000.0,
        "currency": "NGN",
        "status": "successful",
        "created_at": "2026-03-23T10:00:00.000Z",
        "meta": {
          "subscription_id": "<uuid>",
          "org_id": "<uuid>"
        }
      }
    }

    Signature verification (verif-hash header) is performed by the webhook
    router before calling this function (FLUTTERWAVE_SECRET_HASH env var).
    """
    event = payload.get("event")
    if event != "charge.completed":
        logger.info("Flutterwave webhook ignored — unhandled event type: %s", event)
        return

    data = payload.get("data", {})

    # Only process successful charges
    if data.get("status") != "successful":
        logger.info(
            "Flutterwave webhook ignored — charge status: %s", data.get("status")
        )
        return

    meta = data.get("meta", {})
    org_id = meta.get("org_id")
    subscription_id = meta.get("subscription_id")

    if not org_id or not subscription_id:
        logger.warning(
            "Flutterwave webhook: missing org_id or subscription_id in meta. "
            "Ensure Opsra subscription_id and org_id are passed in payment meta."
        )
        return

    reference = data.get("tx_ref")
    amount = float(data.get("amount", 0))

    created_at_str = data.get("created_at", "")
    try:
        created_at_dt = datetime.fromisoformat(
            created_at_str.replace("Z", "+00:00")
        )
        payment_date = created_at_dt.date()
    except (ValueError, AttributeError):
        payment_date = date.today()
        logger.warning(
            "Flutterwave webhook: could not parse created_at '%s', using today",
            created_at_str,
        )

    # Duplicate reference check — DRD §6.4
    if reference and _check_duplicate_reference(db, org_id, reference):
        logger.warning(
            "Flutterwave webhook: duplicate reference '%s' for org %s — ignored",
            reference, org_id,
        )
        return

    try:
        subscription = _subscription_or_404(db, org_id, subscription_id)
    except HTTPException:
        logger.warning(
            "Flutterwave webhook: subscription %s not found for org %s",
            subscription_id, org_id,
        )
        return

    _confirm_payment_internal(
        db=db,
        org_id=org_id,
        subscription=subscription,
        amount=amount,
        payment_date=payment_date,
        payment_channel="flutterwave",
        reference=reference,
        notes=f"Flutterwave webhook — event: {event}",
        method="webhook",
        confirmed_by=None,
    )

    write_audit_log(
        db, org_id, user_id=None,
        action="subscription.payment_confirmed",
        resource_type="subscription",
        resource_id=subscription_id,
        old_value={"status": subscription.get("status")},
        new_value={
            "status": "active",
            "method": "webhook",
            "channel": "flutterwave",
            "reference": reference,
        },
    )
    logger.info(
        "Flutterwave webhook: confirmed — subscription %s org %s amount %.2f NGN",
        subscription_id, org_id, amount,
    )