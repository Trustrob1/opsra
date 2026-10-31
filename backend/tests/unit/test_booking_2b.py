"""BOOKING-2B - per-staff calendars: slot union, ranking, assignment, race fallback, staff hours."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import booking_service as bk

ORG = {"id": "org-1", "timezone": "Africa/Lagos"}
START = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
SVC = {"id": "svc-1", "assignment_mode": "anyone", "duration_minutes": 30}


class Q:
    def __init__(self, db, name): self.db, self.name, self.op, self.p = db, name, "select", None
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def insert(self, p): self.op, self.p = "insert", p; return self
    def upsert(self, p, **k): self.op, self.p = "upsert", p; return self
    def update(self, p): self.op, self.p = "update", p; return self
    def delete(self): self.op = "delete"; return self
    def execute(self):
        if self.op != "select":
            self.db.writes.append((self.name, self.op, self.p))
            return MagicMock(data=[self.p] if self.p else [])
        return MagicMock(data=self.db.rows.get(self.name, []))


class FakeDB:
    def __init__(self, **rows): self.rows, self.writes = rows, []
    def table(self, n): return Q(self, n)


def test_single_calendar_is_unchanged():
    with patch.object(bk, "get_settings", return_value={"calendar_mode": "single"}), \
         patch.object(bk, "_slots_for", return_value=[START]) as sf:
        assert bk.get_open_slots(FakeDB(), ORG, SVC, START.date(), START.date()) == [START]
    assert sf.call_args.kwargs.get("rep_id") is None


def test_per_staff_offers_a_time_when_any_one_person_is_free():
    later = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
    by_rep = {"a": [START], "b": [START, later], "c": []}
    with patch.object(bk, "get_settings", return_value={"calendar_mode": "per_staff"}), \
         patch.object(bk, "eligible_staff_ids", return_value=["a", "b", "c"]), \
         patch.object(bk, "_slots_for", side_effect=lambda db, org, svc, f, t, n=None, ex=None, rep_id=None: by_rep[rep_id]):
        assert bk.get_open_slots(FakeDB(), ORG, SVC, START.date(), START.date()) == [START, later]


def _rank(db, svc=SVC, free=("a", "b", "c")):
    with patch.object(bk, "eligible_staff_ids", return_value=["a", "b", "c"]), \
         patch.object(bk, "_slots_for", side_effect=lambda *a, rep_id=None, **k: [START] if rep_id in free else []):
        return bk.rank_reps(db, ORG, svc, "lead-1", START)


def test_rank_prefers_fewest_recent_bookings_then_least_recently_booked():
    db = FakeDB(lead_demos=[
        {"assigned_to": "a", "created_at": "2026-10-30T10:00:00+00:00", "status": "confirmed"},
        {"assigned_to": "a", "created_at": "2026-10-31T10:00:00+00:00", "status": "confirmed"},
        {"assigned_to": "b", "created_at": "2026-10-31T09:00:00+00:00", "status": "confirmed"},
        {"assigned_to": "c", "created_at": "2026-10-20T09:00:00+00:00", "status": "confirmed"},
        {"assigned_to": "c", "created_at": "2026-10-21T09:00:00+00:00", "status": "cancelled"},   # cancelled does not count
    ])
    assert _rank(db) == ["c", "b", "a"]


def test_rank_skips_busy_people_and_returns_empty_when_nobody_is_free():
    assert _rank(FakeDB(lead_demos=[]), free=("b",)) == ["b"]
    assert _rank(FakeDB(lead_demos=[]), free=()) == []


def test_lead_owner_first_beats_the_fairness_order():
    db = FakeDB(lead_demos=[{"assigned_to": "a", "created_at": "2026-10-31T10:00:00+00:00", "status": "confirmed"}],
                leads=[{"assigned_to": "a"}])
    assert _rank(db, svc={**SVC, "assignment_mode": "lead_owner_first"})[0] == "a"
    assert _rank(db)[0] != "a"        # same data, 'anyone' mode: the busier person is not first


def test_race_for_one_person_falls_to_the_next_free_person():
    calls = []
    def fake_insert(db, org_id, lead_id, service, start, end, source, tz, uid, notes, assigned_to=None, guard_scope="org"):
        calls.append(assigned_to)
        if assigned_to == "a":
            raise bk._err(409, "SLOT_TAKEN", "taken")
        return "demo-9"
    with patch.object(bk, "rank_reps", return_value=["a", "b"]), patch.object(bk, "_insert_booking_row", side_effect=fake_insert):
        assert bk._insert_for_best_rep(FakeDB(), ORG, SVC, "lead-1", START, START, "native", None, None, None) == ("demo-9", "b")
    assert calls == ["a", "b"]


def test_everyone_taken_is_slot_taken_not_a_crash():
    with patch.object(bk, "rank_reps", return_value=["a"]), \
         patch.object(bk, "_insert_booking_row", side_effect=bk._err(409, "SLOT_TAKEN", "x")):
        with pytest.raises(HTTPException) as e:
            bk._insert_for_best_rep(FakeDB(), ORG, SVC, "l", START, START, "native", None, None, None)
    assert e.value.detail["code"] == "SLOT_TAKEN"


def test_person_follows_business_hours_until_they_set_their_own():
    org_rules = [{"weekday": 0, "start_time": "09:00", "end_time": "17:00"}]
    own = [{"weekday": 1, "start_time": "10:00", "end_time": "12:00"}]
    assert bk._staff_rules(FakeDB(booking_staff=[{"uses_org_hours": True}]), "o", "u", org_rules) == org_rules
    assert bk._staff_rules(FakeDB(booking_staff=[]), "o", "u", org_rules) == org_rules
    assert bk._staff_rules(FakeDB(booking_staff=[{"uses_org_hours": False}], booking_staff_availability=own), "o", "u", org_rules) == own


def test_eligible_staff_respects_opt_in_and_specific_service_people():
    users = [{"id": "a", "is_active": True, "roles": {"template": "sales_agent"}},
             {"id": "b", "is_active": True, "roles": {"template": "sales_agent"}},
             {"id": "c", "is_active": True, "roles": {"template": "viewer"}}]
    db = FakeDB(users=users, booking_staff=[{"user_id": "a", "accepts_bookings": True}, {"user_id": "b", "accepts_bookings": False},
                                            {"user_id": "c", "accepts_bookings": True}],
                booking_service_staff=[{"user_id": "a"}])
    assert bk.eligible_staff_ids(db, "o", SVC) == ["a"]                      # b opted out, c has a role that cannot take bookings
    assert bk.eligible_staff_ids(db, "o", {**SVC, "assignment_mode": "specific"}) == ["a"]
    db.rows["booking_service_staff"] = []
    assert bk.eligible_staff_ids(db, "o", {**SVC, "assignment_mode": "specific"}) == []


def test_calendar_mode_must_be_known():
    with pytest.raises(HTTPException):
        bk.save_settings(FakeDB(), "o", {"calendar_mode": "weird"})


def test_reassign_refuses_a_clash_with_the_new_persons_own_booking():
    class Boom(FakeDB):
        def table(self, n):
            q = Q(self, n)
            if n == "lead_demos":
                orig = q.execute
                def ex():
                    if q.op == "update":
                        raise Exception("conflicting key value violates exclusion constraint lead_demos_rep_no_overlap 23P01")
                    return orig()
                q.execute = ex
            return q
    with patch.object(bk, "_get_live_booking", return_value={"id": "d", "lead_id": "l", "assigned_to": "a", "scheduled_at": START.isoformat()}), \
         patch.object(bk, "_require_staff_user", return_value={"id": "b"}):
        with pytest.raises(HTTPException) as e:
            bk.reassign_booking(Boom(), "o", "d", "b")
    assert e.value.status_code == 409 and e.value.detail["code"] == "SLOT_TAKEN"
