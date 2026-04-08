"""
tests/unit/test_subscription_service.py
Unit tests for Module 04 — Renewal & Upsell Engine service layer.

Patterns used:
  - Pattern 8: separate insert mock with insert_chain.insert.return_value = insert_chain
  - Pattern 9: normalise list vs dict from .maybe_single() responses
  - Pattern 24: all test IDs are valid UUID format
  - Table dispatch by name for functions that call multiple tables
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.subscriptions import (
    BulkConfirmRow,
    CancelSubscriptionRequest,
    ConfirmPaymentRequest,
    SubscriptionUpdate,
)
from app.services.subscription_service import (
    _check_duplicate_reference,
    _next_period_end,
    _normalise_phone,
    _subscription_or_404,
    cancel_subscription,
    confirm_payment,
    create_bulk_confirm_job,
    get_bulk_confirm_job,
    get_subscription,
    list_subscriptions,
    process_bulk_confirm,
    process_flutterwave_webhook,
    process_paystack_webhook,
    update_subscription,
)

# ---------------------------------------------------------------------------
# Test constants — all valid UUIDs (Pattern 24)
# ---------------------------------------------------------------------------
ORG_ID        = "00000000-0000-0000-0000-000000000001"
USER_ID       = "00000000-0000-0000-0000-000000000002"
CUSTOMER_ID   = "00000000-0000-0000-0000-000000000003"
SUB_ID        = "00000000-0000-0000-0000-000000000004"
PAYMENT_ID    = "00000000-0000-0000-0000-000000000005"
JOB_ID_PROC   = "00000000-0000-0000-0000-000000000088"

ACTIVE_SUB = {
    "id": SUB_ID,
    "org_id": ORG_ID,
    "customer_id": CUSTOMER_ID,
    "plan_name": "Starter Plan",
    "plan_tier": "starter",
    "amount": 150000.0,
    "currency": "NGN",
    "billing_cycle": "monthly",
    "status": "active",
    "current_period_start": "2026-03-01",
    "current_period_end": "2026-04-01",
    "grace_period_ends_at": None,
    "created_at": "2026-03-01T00:00:00+00:00",
}


def _make_chain(data=None, count=0):
    """Return a MagicMock Supabase query chain with given result data."""
    chain = MagicMock()
    chain.select.return_value       = chain
    chain.eq.return_value           = chain
    chain.neq.return_value          = chain
    chain.is_.return_value          = chain
    chain.gte.return_value          = chain
    chain.lte.return_value          = chain
    chain.order.return_value        = chain
    chain.range.return_value        = chain
    chain.limit.return_value        = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value       = chain
    chain.insert.return_value       = chain
    chain.execute.return_value      = MagicMock(data=data, count=count)
    return chain


# ---------------------------------------------------------------------------
# Shared helpers for DB-backed bulk confirm tests (Phase 9D)
# ---------------------------------------------------------------------------

def _make_bulk_insert_db():
    """DB mock that accepts bulk_confirm_jobs insert."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    chain.insert.return_value  = chain
    chain.update.return_value  = chain
    chain.eq.return_value      = chain
    db.table.return_value      = chain
    return db


def _make_bulk_get_db(job_id, org_id, **row_overrides):
    """DB mock that returns a single bulk_confirm_jobs row."""
    row = {
        "job_id": job_id, "org_id": org_id, "status": "pending",
        "total": 0, "succeeded": 0, "unmatched": 0, "failed": 0,
        "errors": [], "created_at": "2026-04-07T10:00:00+00:00", "completed_at": None,
        **row_overrides,
    }
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value    = MagicMock(data=[row])
    chain.select.return_value     = chain
    chain.eq.return_value         = chain
    chain.maybe_single.return_value = chain
    db.table.return_value         = chain
    return db


def _make_bulk_get_db_empty():
    """DB mock that returns no row (404 scenario)."""
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value    = MagicMock(data=None)
    chain.select.return_value     = chain
    chain.eq.return_value         = chain
    chain.maybe_single.return_value = chain
    db.table.return_value         = chain
    return db


def _make_process_db(sub_data=None, dup_data=None):
    """
    Multi-table mock for process_bulk_confirm tests.
    Captures every payload passed to bulk_confirm_jobs.update() for assertion.
    Returns (db, captured_updates_list).
    """
    captured: list[dict] = []

    # bulk_confirm_jobs — captures every update payload
    bj_chain = MagicMock()
    bj_chain.eq.return_value      = bj_chain
    bj_chain.execute.return_value = MagicMock(data=[])

    def _bj_update(updates):
        captured.append(dict(updates))
        return bj_chain
    bj_chain.update = _bj_update

    # subscriptions
    sub_calls = {"n": 0}
    sub_chain = MagicMock()
    sub_chain.select.return_value       = sub_chain
    sub_chain.eq.return_value           = sub_chain
    sub_chain.neq.return_value          = sub_chain
    sub_chain.order.return_value        = sub_chain
    sub_chain.limit.return_value        = sub_chain
    sub_chain.is_.return_value          = sub_chain
    sub_chain.maybe_single.return_value = sub_chain
    sub_chain.update.return_value       = sub_chain

    def _sub_exec():
        sub_calls["n"] += 1
        # First call is the lookup; subsequent calls are update returns
        return MagicMock(data=sub_data if sub_calls["n"] == 1 else ([ACTIVE_SUB] if sub_data else None))
    sub_chain.execute.side_effect = _sub_exec

    # payments (duplicate check + insert)
    pay_calls = {"n": 0}
    pay_chain = MagicMock()
    pay_chain.select.return_value       = pay_chain
    pay_chain.eq.return_value           = pay_chain
    pay_chain.maybe_single.return_value = pay_chain
    pay_chain.insert.return_value       = pay_chain

    def _pay_exec():
        pay_calls["n"] += 1
        if pay_calls["n"] == 1:
            return MagicMock(data=dup_data or [])
        return MagicMock(data=[{"id": PAYMENT_ID}])
    pay_chain.execute.side_effect = _pay_exec

    # customers (phone fallback path)
    cust_chain = MagicMock()
    cust_chain.select.return_value       = cust_chain
    cust_chain.eq.return_value           = cust_chain
    cust_chain.is_.return_value          = cust_chain
    cust_chain.maybe_single.return_value = cust_chain
    cust_chain.execute.return_value      = MagicMock(data=None)

    # audit_logs
    audit_chain = MagicMock()
    audit_chain.insert.return_value  = audit_chain
    audit_chain.execute.return_value = MagicMock(data=[])

    def tbl(name):
        if name == "bulk_confirm_jobs": return bj_chain
        if name == "subscriptions":     return sub_chain
        if name == "payments":          return pay_chain
        if name == "customers":         return cust_chain
        if name == "audit_logs":        return audit_chain
        return MagicMock()

    db = MagicMock()
    db.table.side_effect = tbl
    return db, captured


# ===========================================================================
# TestNextPeriodEnd
# ===========================================================================
class TestNextPeriodEnd:
    def test_monthly_normal_day(self):
        assert _next_period_end(date(2026, 3, 15), "monthly") == date(2026, 4, 15)

    def test_monthly_wraps_year(self):
        assert _next_period_end(date(2026, 12, 10), "monthly") == date(2027, 1, 10)

    def test_monthly_jan31_caps_at_feb28(self):
        assert _next_period_end(date(2026, 1, 31), "monthly") == date(2026, 2, 28)

    def test_monthly_mar31_caps_at_apr30(self):
        assert _next_period_end(date(2026, 3, 31), "monthly") == date(2026, 4, 30)

    def test_monthly_oct31_caps_at_nov30(self):
        assert _next_period_end(date(2026, 10, 31), "monthly") == date(2026, 11, 30)

    def test_annual_normal(self):
        assert _next_period_end(date(2026, 3, 15), "annual") == date(2027, 3, 15)

    def test_annual_leap_feb29_gives_feb28_in_non_leap_year(self):
        assert _next_period_end(date(2028, 2, 29), "annual") == date(2029, 2, 28)


# ===========================================================================
# TestNormalisePhone
# ===========================================================================
class TestNormalisePhone:
    def test_strips_dashes_and_spaces(self):
        assert _normalise_phone("+234-803-123-4567") == "+2348031234567"

    def test_returns_none_on_empty_string(self):
        assert _normalise_phone("") is None

    def test_returns_none_on_none(self):
        assert _normalise_phone(None) is None

    def test_handles_excel_scientific_notation(self):
        assert _normalise_phone("2.348E+12") == "2348000000000"


# ===========================================================================
# TestSubscriptionOrFourOhFour
# ===========================================================================
class TestSubscriptionOrFourOhFour:
    def test_returns_dict_when_found_as_dict(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=ACTIVE_SUB)
        assert _subscription_or_404(db, ORG_ID, SUB_ID)["id"] == SUB_ID

    def test_normalises_list_to_dict(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[ACTIVE_SUB])
        assert _subscription_or_404(db, ORG_ID, SUB_ID)["id"] == SUB_ID

    def test_raises_404_when_data_is_none(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=None)
        with pytest.raises(HTTPException) as exc:
            _subscription_or_404(db, ORG_ID, SUB_ID)
        assert exc.value.status_code == 404

    def test_raises_404_when_data_is_empty_list(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[])
        with pytest.raises(HTTPException) as exc:
            _subscription_or_404(db, ORG_ID, SUB_ID)
        assert exc.value.status_code == 404


# ===========================================================================
# TestCheckDuplicateReference
# ===========================================================================
class TestCheckDuplicateReference:
    def test_returns_true_when_reference_exists(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[{"id": PAYMENT_ID}])
        assert _check_duplicate_reference(db, ORG_ID, "TXN_abc") is True

    def test_returns_false_when_no_match(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[])
        assert _check_duplicate_reference(db, ORG_ID, "TXN_abc") is False

    def test_returns_false_when_data_is_none(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=None)
        assert _check_duplicate_reference(db, ORG_ID, "TXN_abc") is False


# ===========================================================================
# TestSubscriptionModels
# ===========================================================================
class TestSubscriptionModels:
    def test_subscription_update_invalid_plan_tier_raises(self):
        with pytest.raises(ValidationError):
            SubscriptionUpdate(plan_tier="gold")

    def test_subscription_update_valid_plan_tier(self):
        assert SubscriptionUpdate(plan_tier="pro").plan_tier == "pro"

    def test_subscription_update_invalid_billing_cycle_raises(self):
        with pytest.raises(ValidationError):
            SubscriptionUpdate(billing_cycle="weekly")

    def test_subscription_update_valid_billing_cycle_annual(self):
        assert SubscriptionUpdate(billing_cycle="annual").billing_cycle == "annual"

    def test_confirm_payment_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(amount=10000, payment_date=date.today(), payment_channel="cheque")

    def test_confirm_payment_valid_channel(self):
        m = ConfirmPaymentRequest(amount=10000, payment_date=date.today(), payment_channel="bank_transfer")
        assert m.payment_channel == "bank_transfer"

    def test_confirm_payment_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(amount=-1, payment_date=date.today(), payment_channel="cash")

    def test_confirm_payment_notes_max_length_enforced(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(amount=10000, payment_date=date.today(), payment_channel="cash", notes="x" * 5001)

    def test_cancel_request_invalid_reason_raises(self):
        with pytest.raises(ValidationError):
            CancelSubscriptionRequest(reason="just_because")

    def test_cancel_request_valid_reason(self):
        assert CancelSubscriptionRequest(reason="too_expensive").reason == "too_expensive"

    def test_bulk_confirm_row_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            BulkConfirmRow(subscription_id=SUB_ID, amount=10000, payment_date=date.today(), payment_channel="crypto")

    def test_bulk_confirm_row_valid(self):
        m = BulkConfirmRow(subscription_id=SUB_ID, amount=10000, payment_date=date.today(), payment_channel="pos")
        assert m.payment_channel == "pos"


# ===========================================================================
# TestListSubscriptions
# ===========================================================================
class TestListSubscriptions:
    def test_no_filters_returns_paginated_result(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[ACTIVE_SUB], count=1)
        result = list_subscriptions(db, ORG_ID)
        assert result["items"] == [ACTIVE_SUB]
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_empty_result(self):
        db = MagicMock()
        db.table.return_value = _make_chain(data=[], count=0)
        result = list_subscriptions(db, ORG_ID)
        assert result["items"] == []
        assert result["total"] == 0

    def test_status_filter_is_applied(self):
        db = MagicMock()
        chain = _make_chain(data=[], count=0)
        db.table.return_value = chain
        list_subscriptions(db, ORG_ID, sub_status="trial")
        chain.eq.assert_called()

    def test_plan_tier_filter_is_applied(self):
        db = MagicMock()
        chain = _make_chain(data=[], count=0)
        db.table.return_value = chain
        list_subscriptions(db, ORG_ID, plan_tier="pro")
        chain.eq.assert_called()

    def test_renewal_window_filter_uses_gte_and_lte(self):
        db = MagicMock()
        chain = _make_chain(data=[], count=0)
        db.table.return_value = chain
        list_subscriptions(db, ORG_ID, renewal_window_days=7)
        chain.gte.assert_called()
        chain.lte.assert_called()

    def test_pagination_calculates_correct_offset(self):
        db = MagicMock()
        chain = _make_chain(data=[], count=0)
        db.table.return_value = chain
        list_subscriptions(db, ORG_ID, page=3, page_size=10)
        chain.range.assert_called_with(20, 29)


# ===========================================================================
# TestListSubscriptionsByCustomerName
# ===========================================================================
CUST_ID       = "00000000-0000-0000-0000-000000000010"
CUST_ROW_AMAKA = {"id": CUST_ID, "full_name": "Amaka Obi"}
CUST_ROW_TEST  = {"id": "00000000-0000-0000-0000-000000000011", "full_name": "Test Lead"}
SUB_ROW = {
    "id": "00000000-0000-0000-0000-000000000020", "org_id": ORG_ID,
    "customer_id": CUST_ID, "plan_tier": "pro", "billing_cycle": "monthly",
    "status": "active", "amount": 45000,
    "current_period_start": "2026-03-01", "current_period_end": "2026-04-01",
}


class TestListSubscriptionsByCustomerName:
    def _make_db(self, customers, subs, sub_count):
        cust_chain = MagicMock()
        cust_chain.execute.return_value = MagicMock(data=customers)
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain

        sub_chain = MagicMock()
        sub_chain.execute.return_value = MagicMock(data=subs, count=sub_count)
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.in_.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain

        db = MagicMock()
        db.table.side_effect = lambda name: cust_chain if name == "customers" else sub_chain
        return db

    def test_returns_matching_subscriptions(self):
        db = self._make_db([CUST_ROW_AMAKA], [SUB_ROW], 1)
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="Amaka")
        assert result["total"] == 1

    def test_returns_empty_when_no_customer_matches(self):
        calls = {"n": 0}
        cust_chain = MagicMock()
        cust_chain.execute.return_value = MagicMock(data=[CUST_ROW_AMAKA])
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain
        db = MagicMock()
        def tbl(name): calls["n"] += 1; return cust_chain
        db.table.side_effect = tbl
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="NonExistent")
        assert result == {"items": [], "total": 0, "page": 1, "page_size": 20}
        assert calls["n"] == 1

    def test_ignores_customer_name_when_blank(self):
        sub_chain = MagicMock()
        sub_chain.execute.return_value = MagicMock(data=[SUB_ROW], count=1)
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain
        db = MagicMock()
        db.table.return_value = sub_chain
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="   ")
        assert result["total"] == 1
        db.table.assert_called_once_with("subscriptions")

    def test_case_insensitive_match(self):
        db = self._make_db([{"id": CUST_ID, "full_name": "AMAKA OBI"}], [SUB_ROW], 1)
        assert list_subscriptions(db=db, org_id=ORG_ID, customer_name="amaka")["total"] == 1

    def test_partial_name_matches_substring(self):
        db = self._make_db([CUST_ROW_AMAKA], [SUB_ROW], 1)
        assert list_subscriptions(db=db, org_id=ORG_ID, customer_name="aka")["total"] == 1

    def test_only_matching_customer_ids_passed_to_subscriptions_query(self):
        sub_chain = MagicMock()
        sub_chain.execute.return_value = MagicMock(data=[SUB_ROW], count=1)
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.in_.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain

        cust_chain = MagicMock()
        cust_chain.execute.return_value = MagicMock(data=[CUST_ROW_AMAKA, CUST_ROW_TEST])
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain

        db = MagicMock()
        db.table.side_effect = lambda name: cust_chain if name == "customers" else sub_chain
        list_subscriptions(db=db, org_id=ORG_ID, customer_name="amaka")
        sub_chain.in_.assert_called_once_with("customer_id", [CUST_ID])


# ===========================================================================
# TestGetSubscription
# ===========================================================================
class TestGetSubscription:
    def test_returns_subscription_with_payment_history(self):
        payments = [{"id": PAYMENT_ID, "amount": 150000}]
        def tbl(name):
            if name == "subscriptions": return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":      return _make_chain(data=payments)
            return MagicMock()
        db = MagicMock()
        db.table.side_effect = tbl
        result = get_subscription(db, ORG_ID, SUB_ID)
        assert result["id"] == SUB_ID
        assert result["payments"] == payments

    def test_returns_empty_list_when_no_payments(self):
        def tbl(name):
            if name == "subscriptions": return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":      return _make_chain(data=[])
            return MagicMock()
        db = MagicMock()
        db.table.side_effect = tbl
        result = get_subscription(db, ORG_ID, SUB_ID)
        assert result["payments"] == []

    def test_raises_404_when_not_found(self):
        def tbl(name):
            if name == "subscriptions": return _make_chain(data=None)
            return _make_chain(data=[])
        db = MagicMock()
        db.table.side_effect = tbl
        with pytest.raises(HTTPException) as exc:
            get_subscription(db, ORG_ID, SUB_ID)
        assert exc.value.status_code == 404


# ===========================================================================
# TestUpdateSubscription
# ===========================================================================
class TestUpdateSubscription:
    def _build_db(self, first_data, second_data=None):
        calls = {"n": 0}
        def tbl(name):
            if name == "subscriptions":
                calls["n"] += 1
                return _make_chain(data=first_data if calls["n"] == 1 else (second_data or first_data))
            return _make_chain(data=None)
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_updates_plan_name(self):
        updated = {**ACTIVE_SUB, "plan_name": "Pro Plan"}
        db = self._build_db([ACTIVE_SUB], [updated])
        result = update_subscription(db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate(plan_name="Pro Plan"))
        assert result["plan_name"] == "Pro Plan"

    def test_empty_payload_returns_current_subscription(self):
        db = self._build_db([ACTIVE_SUB])
        assert update_subscription(db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate())["id"] == SUB_ID

    def test_raises_404_when_not_found(self):
        db = self._build_db(None)
        with pytest.raises(HTTPException) as exc:
            update_subscription(db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate(plan_name="X"))
        assert exc.value.status_code == 404

    def test_serialises_date_fields_to_iso_string(self):
        db = self._build_db([ACTIVE_SUB])
        update_subscription(db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate(current_period_end=date(2026, 5, 1)))


# ===========================================================================
# TestConfirmPayment
# ===========================================================================
class TestConfirmPayment:
    def _build_db(self, sub_data, dup_data=None, update_data=None):
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}
        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                if sub_calls["n"] == 1: return _make_chain(data=sub_data)
                return _make_chain(data=[update_data or ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1: return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_confirms_payment_from_active_subscription(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        payload = ConfirmPaymentRequest(amount=150000, payment_date=date(2026, 4, 1), payment_channel="bank_transfer", reference="TXN_001")
        assert confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload) is not None

    def test_confirms_payment_from_grace_period_subscription(self):
        db = self._build_db(sub_data=[{**ACTIVE_SUB, "status": "grace_period"}])
        assert confirm_payment(db, ORG_ID, SUB_ID, USER_ID, ConfirmPaymentRequest(amount=150000, payment_date=date(2026, 4, 1), payment_channel="pos")) is not None

    def test_confirms_payment_without_reference(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        assert confirm_payment(db, ORG_ID, SUB_ID, USER_ID, ConfirmPaymentRequest(amount=150000, payment_date=date(2026, 4, 1), payment_channel="cash")) is not None

    def test_raises_409_on_duplicate_reference(self):
        db = self._build_db(sub_data=[ACTIVE_SUB], dup_data=[{"id": PAYMENT_ID}])
        with pytest.raises(HTTPException) as exc:
            confirm_payment(db, ORG_ID, SUB_ID, USER_ID, ConfirmPaymentRequest(amount=150000, payment_date=date(2026, 4, 1), payment_channel="bank_transfer", reference="ALREADY_USED"))
        assert exc.value.status_code == 409

    def test_raises_404_when_subscription_missing(self):
        db = self._build_db(sub_data=None)
        with pytest.raises(HTTPException) as exc:
            confirm_payment(db, ORG_ID, SUB_ID, USER_ID, ConfirmPaymentRequest(amount=150000, payment_date=date(2026, 4, 1), payment_channel="card"))
        assert exc.value.status_code == 404


# ===========================================================================
# TestCancelSubscription
# ===========================================================================
class TestCancelSubscription:
    def _build_db(self, sub_data, update_data=None):
        calls = {"n": 0}
        def tbl(name):
            if name == "subscriptions":
                calls["n"] += 1
                if calls["n"] == 1: return _make_chain(data=sub_data)
                return _make_chain(data=[update_data or ACTIVE_SUB])
            return _make_chain(data=None)
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_cancels_active_subscription(self):
        assert cancel_subscription(self._build_db([ACTIVE_SUB]), ORG_ID, SUB_ID, USER_ID, "too_expensive") is not None

    def test_cancels_grace_period_subscription(self):
        assert cancel_subscription(self._build_db([{**ACTIVE_SUB, "status": "grace_period"}]), ORG_ID, SUB_ID, USER_ID, "business_closed") is not None

    def test_raises_400_on_already_cancelled(self):
        with pytest.raises(HTTPException) as exc:
            cancel_subscription(self._build_db([{**ACTIVE_SUB, "status": "cancelled"}]), ORG_ID, SUB_ID, USER_ID, "too_expensive")
        assert exc.value.status_code == 400

    def test_raises_404_when_not_found(self):
        with pytest.raises(HTTPException) as exc:
            cancel_subscription(self._build_db(None), ORG_ID, SUB_ID, USER_ID, "business_closed")
        assert exc.value.status_code == 404


# ===========================================================================
# TestBulkConfirmJobManagement  (Phase 9D: DB-backed — no in-memory dict)
# ===========================================================================
class TestBulkConfirmJobManagement:

    def test_create_job_returns_uuid_string(self):
        job_id = create_bulk_confirm_job(ORG_ID, db=_make_bulk_insert_db())
        assert isinstance(job_id, str) and len(job_id) == 36

    def test_new_job_inserted_with_pending_status(self):
        db = _make_bulk_insert_db()
        job_id = create_bulk_confirm_job(ORG_ID, db=db)
        db.table.assert_called_with("bulk_confirm_jobs")
        inserted = db.table.return_value.insert.call_args[0][0]
        assert inserted["status"]    == "pending"
        assert inserted["org_id"]    == ORG_ID
        assert inserted["succeeded"] == 0
        assert inserted["unmatched"] == 0
        assert inserted["job_id"]    == job_id

    def test_get_job_returns_correct_job(self):
        db_c = _make_bulk_insert_db()
        job_id = create_bulk_confirm_job(ORG_ID, db=db_c)
        result = get_bulk_confirm_job(ORG_ID, job_id, db=_make_bulk_get_db(job_id, ORG_ID))
        assert result["job_id"] == job_id

    def test_get_job_raises_404_for_unknown(self):
        with pytest.raises(HTTPException) as exc:
            get_bulk_confirm_job(ORG_ID, "nonexistent-job-id", db=_make_bulk_get_db_empty())
        assert exc.value.status_code == 404

    def test_get_job_raises_404_for_wrong_org(self):
        with pytest.raises(HTTPException) as exc:
            get_bulk_confirm_job("00000000-0000-0000-0000-000000000099", "some-job-id", db=_make_bulk_get_db_empty())
        assert exc.value.status_code == 404


# ===========================================================================
# TestProcessBulkConfirm  (Phase 9D: asserts on DB update calls)
# ===========================================================================
class TestProcessBulkConfirm:

    def test_empty_rows_marks_job_done(self):
        db, captured = _make_process_db()
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, [])
        assert captured[-1]["status"] == "done"

    def test_row_without_identifier_is_unmatched(self):
        db, captured = _make_process_db()
        rows = [{"amount": "10000", "payment_date": "2026-04-01", "payment_channel": "cash"}]
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, rows)
        assert captured[-1]["unmatched"] == 1
        assert captured[-1]["errors"][0]["row"] == 1

    def test_subscription_id_match_confirms_payment(self):
        db, captured = _make_process_db(sub_data=[ACTIVE_SUB])
        rows = [{"subscription_id": SUB_ID, "amount": "150000",
                 "payment_date": "2026-04-01", "payment_channel": "bank_transfer"}]
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, rows)
        assert captured[-1]["succeeded"] == 1

    def test_duplicate_reference_marks_row_failed(self):
        db, captured = _make_process_db(sub_data=[ACTIVE_SUB], dup_data=[{"id": PAYMENT_ID}])
        rows = [{"subscription_id": SUB_ID, "amount": "150000",
                 "payment_date": "2026-04-01", "payment_channel": "bank_transfer",
                 "reference": "ALREADY_USED"}]
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, rows)
        assert captured[-1]["failed"] == 1
        assert "Duplicate" in captured[-1]["errors"][0]["message"]

    def test_unmatched_subscription_id_is_unmatched(self):
        db, captured = _make_process_db(sub_data=None)
        rows = [{"subscription_id": SUB_ID, "amount": "150000",
                 "payment_date": "2026-04-01", "payment_channel": "cash"}]
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, rows)
        assert captured[-1]["unmatched"] == 1

    def test_multiple_rows_total_written_and_done_at_end(self):
        db, captured = _make_process_db(sub_data=None)
        rows = [
            {"subscription_id": SUB_ID, "amount": "150000",
             "payment_date": "2026-04-01", "payment_channel": "cash"},
            {"subscription_id": "00000000-0000-0000-0000-000000000099",
             "amount": "150000", "payment_date": "2026-04-01", "payment_channel": "cash"},
        ]
        process_bulk_confirm(db, ORG_ID, USER_ID, JOB_ID_PROC, rows)
        assert captured[0]["total"] == 2          # processing update
        assert captured[-1]["status"] == "done"   # final update


# ===========================================================================
# TestProcessPaystackWebhook
# ===========================================================================
class TestProcessPaystackWebhook:
    def _build_db(self, sub_data, dup_data=None):
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}
        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                if sub_calls["n"] == 1: return _make_chain(data=sub_data)
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1: return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def _valid_payload(self, event="charge.success", reference="TXN_ps_001"):
        return {"event": event, "data": {"reference": reference, "amount": 15000000,
                "paid_at": "2026-04-01T10:00:00.000Z",
                "metadata": {"subscription_id": SUB_ID, "org_id": ORG_ID}}}

    def test_processes_charge_success(self):
        process_paystack_webhook(self._build_db([ACTIVE_SUB]), self._valid_payload())

    def test_ignores_non_charge_success_event(self):
        db = MagicMock()
        process_paystack_webhook(db, self._valid_payload(event="transfer.success"))
        db.table.assert_not_called()

    def test_ignores_payload_with_no_metadata(self):
        db = MagicMock()
        process_paystack_webhook(db, {"event": "charge.success", "data": {"reference": "X", "amount": 100, "paid_at": ""}})
        db.table.assert_not_called()

    def test_ignores_missing_subscription_id_in_metadata(self):
        db = MagicMock()
        process_paystack_webhook(db, {"event": "charge.success", "data": {"reference": "X", "amount": 100,
                                 "paid_at": "2026-04-01T10:00:00Z", "metadata": {"org_id": ORG_ID}}})
        db.table.assert_not_called()

    def test_ignores_duplicate_reference(self):
        process_paystack_webhook(self._build_db([ACTIVE_SUB], dup_data=[{"id": PAYMENT_ID}]),
                                 self._valid_payload(reference="DUPE"))

    def test_ignores_unknown_subscription(self):
        process_paystack_webhook(self._build_db(sub_data=None), self._valid_payload())

    def test_converts_kobo_to_naira(self):
        process_paystack_webhook(self._build_db([ACTIVE_SUB]), self._valid_payload())

    def test_handles_malformed_paid_at_gracefully(self):
        payload = self._valid_payload()
        payload["data"]["paid_at"] = "not-a-date"
        process_paystack_webhook(self._build_db([ACTIVE_SUB]), payload)


# ===========================================================================
# TestProcessFlutterwaveWebhook
# ===========================================================================
class TestProcessFlutterwaveWebhook:
    def _build_db(self, sub_data, dup_data=None):
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}
        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                if sub_calls["n"] == 1: return _make_chain(data=sub_data)
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1: return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def _valid_payload(self, event="charge.completed", charge_status="successful"):
        return {"event": event, "data": {"tx_ref": "FLW_TXN_001", "amount": 150000.0,
                "currency": "NGN", "status": charge_status,
                "created_at": "2026-04-01T10:00:00.000Z",
                "meta": {"subscription_id": SUB_ID, "org_id": ORG_ID}}}

    def test_processes_charge_completed_successful(self):
        process_flutterwave_webhook(self._build_db([ACTIVE_SUB]), self._valid_payload())

    def test_ignores_non_charge_completed_event(self):
        db = MagicMock()
        process_flutterwave_webhook(db, self._valid_payload(event="transfer.completed"))
        db.table.assert_not_called()

    def test_ignores_unsuccessful_charge(self):
        db = MagicMock()
        process_flutterwave_webhook(db, self._valid_payload(charge_status="failed"))
        db.table.assert_not_called()

    def test_ignores_payload_with_no_meta(self):
        db = MagicMock()
        process_flutterwave_webhook(db, {"event": "charge.completed",
                                    "data": {"tx_ref": "X", "amount": 150000, "status": "successful", "created_at": ""}})
        db.table.assert_not_called()

    def test_ignores_duplicate_reference(self):
        process_flutterwave_webhook(self._build_db([ACTIVE_SUB], dup_data=[{"id": PAYMENT_ID}]), self._valid_payload())

    def test_ignores_unknown_subscription(self):
        process_flutterwave_webhook(self._build_db(sub_data=None), self._valid_payload())

    def test_handles_malformed_created_at_gracefully(self):
        payload = self._valid_payload()
        payload["data"]["created_at"] = "bad-date"
        process_flutterwave_webhook(self._build_db([ACTIVE_SUB]), payload)