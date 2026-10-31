"""BOOKING-1 — unit tests for the pure slot calculation (no database)."""
from datetime import date, datetime, timedelta, timezone

from app.services.booking_service import generate_slots, hours_from_business_hours

UTC = timezone.utc
MON_FRI = [{"weekday": i, "start_time": "09:00", "end_time": "17:00"} for i in range(5)]


def _gen(**kw):
    base = dict(tz_name="Africa/Lagos", rules=MON_FRI, duration_minutes=60, buffer_minutes=0, busy=[], blocks=[],
                now=datetime(2026, 11, 1, 0, 0, tzinfo=UTC), min_notice_hours=0, window_days=60,
                from_date=date(2026, 11, 2), to_date=date(2026, 11, 2))   # Monday
    base.update(kw)
    return generate_slots(**base)


def _lagos(slots):  # Lagos is UTC+1 all year
    return [(s + timedelta(hours=1)).strftime("%H:%M") for s in slots]


def test_basic_day_has_eight_hourly_slots_in_local_time():
    assert _lagos(_gen()) == ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]


def test_weekend_has_no_slots():
    assert _gen(from_date=date(2026, 11, 7), to_date=date(2026, 11, 8)) == []


def test_busy_booking_removes_its_slot():
    busy = [(datetime(2026, 11, 2, 9, 0, tzinfo=UTC), datetime(2026, 11, 2, 10, 0, tzinfo=UTC))]  # 10:00 Lagos
    assert "10:00" not in _lagos(_gen(busy=busy))


def test_buffer_blocks_the_following_slot():
    # existing booking 10:00-11:00 Lagos with 30 min buffer -> occupies until 11:30
    busy = [(datetime(2026, 11, 2, 9, 0, tzinfo=UTC), datetime(2026, 11, 2, 10, 30, tzinfo=UTC))]
    got = _lagos(_gen(busy=busy, duration_minutes=30, buffer_minutes=0))
    assert "10:00" not in got and "10:30" not in got and "11:00" not in got   # 11:00 Lagos = 10:00 UTC... still busy window ends 10:30 UTC=11:30
    assert "11:30" in got


def test_own_buffer_leaves_room_before_next_booking():
    # 60 min slots with 30 min buffer, a booking starts at 12:00 Lagos: the 11:00 slot would run to 12:30 -> not allowed
    busy = [(datetime(2026, 11, 2, 11, 0, tzinfo=UTC), datetime(2026, 11, 2, 12, 0, tzinfo=UTC))]
    got = _lagos(_gen(busy=busy, buffer_minutes=30))
    assert "11:00" not in got and "10:00" in got


def test_block_removes_overlapping_slots():
    blocks = [(datetime(2026, 11, 2, 12, 0, tzinfo=UTC), datetime(2026, 11, 2, 14, 0, tzinfo=UTC))]  # 13:00-15:00 Lagos
    got = _lagos(_gen(blocks=blocks))
    assert "13:00" not in got and "14:00" not in got and "15:00" in got and "12:00" in got


def test_min_notice_hides_near_slots():
    now = datetime(2026, 11, 2, 7, 30, tzinfo=UTC)   # 08:30 Lagos
    got = _lagos(_gen(now=now, min_notice_hours=2))   # earliest 10:30 Lagos
    assert got[0] == "11:00"


def test_window_days_limits_future():
    got = _gen(from_date=date(2026, 11, 2), to_date=date(2026, 11, 20), window_days=3, now=datetime(2026, 11, 2, 0, 0, tzinfo=UTC))
    assert max(got) <= datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def test_slot_must_finish_inside_window():
    got = _lagos(_gen(duration_minutes=90, step_minutes=30))
    assert got[-1] == "15:30"          # 15:30 + 90 min = 17:00


def test_two_windows_in_one_day():
    rules = [{"weekday": 0, "start_time": "09:00", "end_time": "11:00"}, {"weekday": 0, "start_time": "14:00", "end_time": "16:00"}]
    assert _lagos(_gen(rules=rules)) == ["09:00", "10:00", "14:00", "15:00"]


def test_dst_zone_converts_correctly():
    # New York: 2026-03-08 clocks go forward. 09:00 local on Mon 9 Mar is UTC-4 -> 13:00 UTC
    got = generate_slots(tz_name="America/New_York", rules=[{"weekday": 0, "start_time": "09:00", "end_time": "10:00"}],
                         duration_minutes=60, buffer_minutes=0, busy=[], blocks=[], now=datetime(2026, 3, 1, tzinfo=UTC),
                         min_notice_hours=0, window_days=60, from_date=date(2026, 3, 9), to_date=date(2026, 3, 9))
    assert got == [datetime(2026, 3, 9, 13, 0, tzinfo=UTC)]


def test_dst_gap_slot_skipped():
    # 02:30 on 8 Mar 2026 does not exist in New York
    got = generate_slots(tz_name="America/New_York", rules=[{"weekday": 6, "start_time": "02:00", "end_time": "04:00"}],
                         duration_minutes=30, buffer_minutes=0, busy=[], blocks=[], now=datetime(2026, 3, 1, tzinfo=UTC),
                         min_notice_hours=0, window_days=60, from_date=date(2026, 3, 8), to_date=date(2026, 3, 8))
    # 02:00 start itself does not exist, so the whole window is skipped rather than producing a wrong time
    assert got == []


def test_business_hours_conversion():
    bh = {"mon": {"start": "08:00", "end": "17:00"}, "sun": {"start": None, "end": None}, "sat": None}
    r = hours_from_business_hours(bh)
    assert r == [{"weekday": 0, "start_time": "08:00", "end_time": "17:00"}]


def test_slots_are_unique_and_sorted():
    got = _gen(from_date=date(2026, 11, 2), to_date=date(2026, 11, 6))
    assert got == sorted(set(got)) and len(got) == 40
