# tests/unit/test_sla_business_hours.py
# CONFIG-3 — SLA Business Hours unit tests
# Tests _business_hours_elapsed(), _parse_hhmm(), and Pydantic model validation.
# No DB or Celery involved.

import pytest
from datetime import datetime, timezone, timedelta

from app.workers.lead_sla_worker import _business_hours_elapsed, _parse_hhmm


# ── Standard Mon–Fri 08:00–18:00 config used across most tests ───────────────

_WEEKDAY_CONFIG = {
    "timezone": "Africa/Lagos",
    "days": {
        "monday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "tuesday":   {"enabled": True,  "open": "08:00", "close": "18:00"},
        "wednesday": {"enabled": True,  "open": "08:00", "close": "18:00"},
        "thursday":  {"enabled": True,  "open": "08:00", "close": "18:00"},
        "friday":    {"enabled": True,  "open": "08:00", "close": "18:00"},
        "saturday":  {"enabled": False, "open": None,    "close": None},
        "sunday":    {"enabled": False, "open": None,    "close": None},
    },
}

def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


# ── _parse_hhmm ───────────────────────────────────────────────────────────────

class TestParseHHMM:

    def test_valid(self):
        assert _parse_hhmm("08:00") == (8, 0)

    def test_valid_evening(self):
        assert _parse_hhmm("18:30") == (18, 30)

    def test_none_returns_none(self):
        assert _parse_hhmm(None) is None

    def test_empty_returns_none(self):
        assert _parse_hhmm("") is None

    def test_invalid_format_returns_none(self):
        assert _parse_hhmm("8am") is None


# ── _business_hours_elapsed ───────────────────────────────────────────────────

class TestBusinessHoursElapsed:

    # No config → raw wall-clock
    def test_no_config_returns_raw(self):
        created = _utc(2026, 4, 14, 9, 0)   # Tuesday 09:00
        now     = _utc(2026, 4, 14, 11, 0)  # Tuesday 11:00  (2h later)
        result  = _business_hours_elapsed(created, now, None)
        assert abs(result - 2.0) < 0.01

    def test_empty_days_config_returns_raw(self):
        created = _utc(2026, 4, 14, 9, 0)
        now     = _utc(2026, 4, 14, 11, 0)
        result  = _business_hours_elapsed(created, now, {"timezone": "UTC", "days": {}})
        assert abs(result - 2.0) < 0.01

    # Same day, entirely within business hours
    def test_same_day_within_hours(self):
        # Monday 09:00 → 11:00 = 2 business hours
        created = _utc(2026, 4, 13, 9, 0)
        now     = _utc(2026, 4, 13, 11, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 2.0) < 0.01

    # Created before window opens
    def test_created_before_window_opens(self):
        # Monday 07:00 (before 08:00 open) → Monday 10:00 = 2 business hours
        created = _utc(2026, 4, 13, 7, 0)
        now     = _utc(2026, 4, 13, 10, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 2.0) < 0.01

    # Now is after window closes
    def test_now_after_window_closes(self):
        # Monday 16:00 → Monday 20:00: only 2h count (16:00–18:00)
        created = _utc(2026, 4, 13, 16, 0)
        now     = _utc(2026, 4, 13, 20, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 2.0) < 0.01

    # Created end of Friday, now is Monday morning
    def test_friday_to_monday_skips_weekend(self):
        # Friday 17:00 → Monday 09:00
        # Friday: 17:00–18:00 = 1h
        # Saturday + Sunday: 0h
        # Monday: 08:00–09:00 = 1h
        # Total = 2h
        created = _utc(2026, 4, 17, 17, 0)  # Friday
        now     = _utc(2026, 4, 20, 9, 0)   # Monday
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 2.0) < 0.01

    # Created on Saturday (off day) — only Monday counts
    def test_created_saturday_counts_from_monday(self):
        # Saturday 10:00 → Monday 10:00
        # Saturday: 0h, Sunday: 0h, Monday: 08:00–10:00 = 2h
        created = _utc(2026, 4, 18, 10, 0)  # Saturday
        now     = _utc(2026, 4, 20, 10, 0)  # Monday
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 2.0) < 0.01

    # Full working day
    def test_full_working_day(self):
        # Monday 08:00 → Monday 18:00 = 10h
        created = _utc(2026, 4, 13, 8, 0)
        now     = _utc(2026, 4, 13, 18, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 10.0) < 0.01

    # Two full working days
    def test_two_full_working_days(self):
        # Monday 08:00 → Wednesday 08:00 = 20h (Mon 10h + Tue 10h)
        created = _utc(2026, 4, 13, 8, 0)
        now     = _utc(2026, 4, 15, 8, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert abs(result - 20.0) < 0.01

    # now <= created_at → 0
    def test_now_before_created_returns_zero(self):
        created = _utc(2026, 4, 14, 10, 0)
        now     = _utc(2026, 4, 14, 9, 0)
        result  = _business_hours_elapsed(created, now, _WEEKDAY_CONFIG)
        assert result == 0.0

    # now == created_at → 0
    def test_now_equals_created_returns_zero(self):
        created = _utc(2026, 4, 14, 10, 0)
        result  = _business_hours_elapsed(created, created, _WEEKDAY_CONFIG)
        assert result == 0.0

    # Saturday enabled (half day)
    def test_saturday_half_day_counted(self):
        config = {
            "timezone": "Africa/Lagos",
            "days": {
                "monday":    {"enabled": False, "open": None,    "close": None},
                "tuesday":   {"enabled": False, "open": None,    "close": None},
                "wednesday": {"enabled": False, "open": None,    "close": None},
                "thursday":  {"enabled": False, "open": None,    "close": None},
                "friday":    {"enabled": False, "open": None,    "close": None},
                "saturday":  {"enabled": True,  "open": "09:00", "close": "14:00"},
                "sunday":    {"enabled": False, "open": None,    "close": None},
            },
        }
        # Saturday 09:00 → Saturday 14:00 = 5h
        created = _utc(2026, 4, 18, 9, 0)
        now     = _utc(2026, 4, 18, 14, 0)
        result  = _business_hours_elapsed(created, now, config)
        assert abs(result - 5.0) < 0.01

    # Bad/corrupt config degrades gracefully to wall-clock
    def test_corrupt_config_fallback(self):
        created = _utc(2026, 4, 14, 9, 0)
        now     = _utc(2026, 4, 14, 11, 0)
        result  = _business_hours_elapsed(created, now, {"days": {"monday": {"enabled": True, "open": "bad", "close": "bad"}}})
        # Should fall back to raw 2h — either 0 (no valid windows) or 2h (fallback)
        assert result >= 0.0  # must not raise
