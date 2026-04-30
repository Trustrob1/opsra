# tests/unit/test_org_gates.py
# 9E-D — Unit tests for app/utils/org_gates.py
# Covers D1 (subscription gating), D2 (quiet hours), D3 (daily limit).
# No DB required — has_exceeded_daily_limit uses a mock db.

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.utils.org_gates import (
    is_org_active,
    is_org_processable,
    is_quiet_hours,
    get_quiet_hours_end_utc,
    get_daily_customer_limit,
    has_exceeded_daily_limit,
    DEFAULT_DAILY_CUSTOMER_LIMIT,
    SYSTEM_DAILY_CUSTOMER_CEILING,
)


# ── D1: Subscription status gating ───────────────────────────────────────────

class TestIsOrgActive:
    def test_active_returns_true(self):
        assert is_org_active({"subscription_status": "active"}) is True

    def test_grace_returns_true(self):
        assert is_org_active({"subscription_status": "grace"}) is True

    def test_suspended_returns_false(self):
        assert is_org_active({"subscription_status": "suspended"}) is False

    def test_read_only_returns_false(self):
        assert is_org_active({"subscription_status": "read_only"}) is False

    def test_null_returns_false(self):
        assert is_org_active({"subscription_status": None}) is False

    def test_missing_key_returns_false(self):
        assert is_org_active({}) is False

    def test_unknown_value_returns_false(self):
        assert is_org_active({"subscription_status": "unknown_state"}) is False

    def test_case_insensitive(self):
        assert is_org_active({"subscription_status": "ACTIVE"}) is True
        assert is_org_active({"subscription_status": "Grace"}) is True


class TestIsOrgProcessable:
    def test_active_returns_true(self):
        assert is_org_processable({"subscription_status": "active"}) is True

    def test_grace_returns_false(self):
        assert is_org_processable({"subscription_status": "grace"}) is False

    def test_suspended_returns_false(self):
        assert is_org_processable({"subscription_status": "suspended"}) is False

    def test_null_returns_false(self):
        assert is_org_processable({"subscription_status": None}) is False

    def test_missing_key_returns_false(self):
        assert is_org_processable({}) is False


# ── D2: Quiet hours ───────────────────────────────────────────────────────────

def _org_with_quiet(start, end, tz="Africa/Lagos"):
    return {
        "quiet_hours_start": start,
        "quiet_hours_end":   end,
        "timezone":          tz,
    }


class TestIsQuietHours:
    def test_inside_window_returns_true(self):
        # Lagos midnight = UTC midnight (UTC+1, but we use UTC time directly here)
        # quiet 22:00–06:00, test at 23:00 UTC = 00:00 Lagos (UTC+1)
        org = _org_with_quiet("22:00", "06:00", "Africa/Lagos")
        # 23:00 UTC = 00:00 Lagos → inside quiet window
        now = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is True

    def test_outside_window_returns_false(self):
        # 10:00 UTC = 11:00 Lagos → outside 22:00–06:00 window
        org = _org_with_quiet("22:00", "06:00", "Africa/Lagos")
        now = datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_no_config_returns_false(self):
        org = {"quiet_hours_start": None, "quiet_hours_end": None, "timezone": "Africa/Lagos"}
        now = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_missing_start_returns_false(self):
        org = {"quiet_hours_start": None, "quiet_hours_end": "06:00", "timezone": "Africa/Lagos"}
        now = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_missing_end_returns_false(self):
        org = {"quiet_hours_start": "22:00", "quiet_hours_end": None, "timezone": "Africa/Lagos"}
        now = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_daytime_window_inside(self):
        # Non-overnight window: 13:00–14:00, test at 13:30 Lagos = 12:30 UTC
        org = _org_with_quiet("13:00", "14:00", "Africa/Lagos")
        now = datetime(2026, 4, 30, 12, 30, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is True

    def test_daytime_window_outside(self):
        # 15:00 Lagos = 14:00 UTC → outside 13:00–14:00 window
        org = _org_with_quiet("13:00", "14:00", "Africa/Lagos")
        now = datetime(2026, 4, 30, 14, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_invalid_timezone_returns_false(self):
        # S14: bad config must never block — returns False
        org = _org_with_quiet("22:00", "06:00", "Not/ATimezone")
        now = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)
        assert is_quiet_hours(org, now) is False

    def test_naive_datetime_handled(self):
        # Naive UTC datetime should not raise
        org = _org_with_quiet("22:00", "06:00", "Africa/Lagos")
        now = datetime(2026, 4, 30, 23, 0, 0)  # no tzinfo
        result = is_quiet_hours(org, now)
        assert isinstance(result, bool)


# ── D3: Daily customer message limit ─────────────────────────────────────────

class TestGetDailyCustomerLimit:
    def test_returns_org_value_when_set(self):
        org = {"daily_customer_message_limit": 5}
        assert get_daily_customer_limit(org) == 5

    def test_returns_default_when_null(self):
        assert get_daily_customer_limit({"daily_customer_message_limit": None}) == DEFAULT_DAILY_CUSTOMER_LIMIT

    def test_returns_default_when_missing(self):
        assert get_daily_customer_limit({}) == DEFAULT_DAILY_CUSTOMER_LIMIT

    def test_enforces_system_ceiling(self):
        org = {"daily_customer_message_limit": 99}
        assert get_daily_customer_limit(org) == SYSTEM_DAILY_CUSTOMER_CEILING

    def test_ceiling_value_itself_allowed(self):
        org = {"daily_customer_message_limit": SYSTEM_DAILY_CUSTOMER_CEILING}
        assert get_daily_customer_limit(org) == SYSTEM_DAILY_CUSTOMER_CEILING

    def test_one_is_valid(self):
        assert get_daily_customer_limit({"daily_customer_message_limit": 1}) == 1

    def test_default_constant_is_3(self):
        assert DEFAULT_DAILY_CUSTOMER_LIMIT == 3

    def test_ceiling_constant_is_20(self):
        assert SYSTEM_DAILY_CUSTOMER_CEILING == 20


class TestHasExceededDailyLimit:
    def _mock_db(self, count):
        """Build a mock Supabase client returning a given message count."""
        mock_result = MagicMock()
        mock_result.count = count
        mock_result.data = []

        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.execute.return_value = mock_result

        db = MagicMock()
        db.table.return_value = chain
        return db

    def test_under_limit_returns_false(self):
        db = self._mock_db(count=2)
        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is False

    def test_at_limit_returns_true(self):
        db = self._mock_db(count=3)
        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is True

    def test_over_limit_returns_true(self):
        db = self._mock_db(count=10)
        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is True

    def test_zero_messages_returns_false(self):
        db = self._mock_db(count=0)
        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is False

    def test_db_exception_returns_false(self):
        # S14: any DB error must return False — never block sending
        db = MagicMock()
        db.table.side_effect = Exception("DB connection failed")
        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is False

    def test_count_none_falls_back_to_data_len(self):
        # When .count is None, falls back to len(result.data)
        mock_result = MagicMock()
        mock_result.count = None
        mock_result.data = [{"id": "msg-1"}, {"id": "msg-2"}, {"id": "msg-3"}]

        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.execute.return_value = mock_result

        db = MagicMock()
        db.table.return_value = chain

        assert has_exceeded_daily_limit(db, "org-1", "cust-1", limit=3) is True
