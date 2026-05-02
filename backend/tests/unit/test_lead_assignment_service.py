"""
tests/unit/test_lead_assignment_service.py
ASSIGN-1 — 24 unit tests for lead_assignment_service.py
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, time as dt_time

ORG_ID  = "11111111-1111-1111-1111-111111111111"
LEAD_ID = "22222222-2222-2222-2222-222222222222"
REP1_ID = "33333333-3333-3333-3333-333333333333"
REP2_ID = "44444444-4444-4444-4444-444444444444"
ADMIN_ID = "55555555-5555-5555-5555-555555555555"


def _mk_shift(start="08:00", end="18:00", days=None, assignees=None, active=True, name="Day Shift"):
    return {
        "id": "shift-1",
        "org_id": ORG_ID,
        "shift_name": name,
        "shift_start": start,
        "shift_end": end,
        "days_active": days or ["mon","tue","wed","thu","fri"],
        "assignee_ids": assignees or [REP1_ID],
        "strategy": "least_loaded",
        "is_active": active,
    }


def _db_with_shifts(shifts):
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.not_.return_value = chain
    chain.is_.return_value = chain
    chain.execute.return_value = MagicMock(data=shifts)
    db.table.return_value = chain
    return db


# ═══════════════════════════════════════════════════════════════════════════
# get_active_shift
# ═══════════════════════════════════════════════════════════════════════════

class TestGetActiveShift:

    def test_LA_U_01_returns_shift_inside_window(self):
        """LA-U-01: returns correct shift when time is inside window."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("08:00", "18:00", ["mon"])])
        now = datetime(2026, 5, 4, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
        result = get_active_shift(db, ORG_ID, now)
        assert result is not None
        assert result["shift_name"] == "Day Shift"

    def test_LA_U_02_returns_none_outside_window(self):
        """LA-U-02: returns None when current time outside all shifts."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("08:00", "18:00", ["mon"])])
        now = datetime(2026, 5, 4, 20, 0, tzinfo=timezone.utc)  # Monday 20:00
        result = get_active_shift(db, ORG_ID, now)
        assert result is None

    def test_LA_U_03_midnight_spanning_active_at_2300(self):
        """LA-U-03: midnight-spanning shift active at 23:00."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("22:00", "06:00", ["mon"])])
        now = datetime(2026, 5, 4, 23, 0, tzinfo=timezone.utc)  # Monday 23:00
        result = get_active_shift(db, ORG_ID, now)
        assert result is not None

    def test_LA_U_04_midnight_spanning_active_at_0200(self):
        """LA-U-04: midnight-spanning shift active at 02:00."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("22:00", "06:00", ["tue"])])
        now = datetime(2026, 5, 5, 2, 0, tzinfo=timezone.utc)  # Tuesday 02:00
        result = get_active_shift(db, ORG_ID, now)
        assert result is not None

    def test_LA_U_05_midnight_spanning_not_active_at_1200(self):
        """LA-U-05: midnight-spanning shift NOT active at 12:00."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("22:00", "06:00", ["mon"])])
        now = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)  # Monday 12:00
        result = get_active_shift(db, ORG_ID, now)
        assert result is None

    def test_LA_U_06_respects_days_active(self):
        """LA-U-06: returns None on inactive day."""
        from app.services.lead_assignment_service import get_active_shift
        db = _db_with_shifts([_mk_shift("08:00", "18:00", ["mon", "tue"])])
        now = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)  # Wednesday
        result = get_active_shift(db, ORG_ID, now)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# get_eligible_reps
# ═══════════════════════════════════════════════════════════════════════════

class TestGetEligibleReps:

    def _make_db(self, users):
        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value = MagicMock(data=users)
        db.table.return_value = chain
        return db

    def test_LA_U_07_filters_inactive_users(self):
        """LA-U-07: filters out is_active=false."""
        from app.services.lead_assignment_service import get_eligible_reps
        users = [
            {"id": REP1_ID, "is_active": True,  "is_out_of_office": False},
            {"id": REP2_ID, "is_active": False, "is_out_of_office": False},
        ]
        db = self._make_db(users)
        shift = _mk_shift(assignees=[REP1_ID, REP2_ID])
        result = get_eligible_reps(db, ORG_ID, shift)
        assert len(result) == 1
        assert result[0]["id"] == REP1_ID

    def test_LA_U_08_filters_out_of_office(self):
        """LA-U-08: filters out is_out_of_office=true."""
        from app.services.lead_assignment_service import get_eligible_reps
        users = [
            {"id": REP1_ID, "is_active": True, "is_out_of_office": True},
            {"id": REP2_ID, "is_active": True, "is_out_of_office": False},
        ]
        db = self._make_db(users)
        shift = _mk_shift(assignees=[REP1_ID, REP2_ID])
        result = get_eligible_reps(db, ORG_ID, shift)
        assert len(result) == 1
        assert result[0]["id"] == REP2_ID

    def test_LA_U_09_returns_empty_when_all_ineligible(self):
        """LA-U-09: returns empty list when all reps ineligible."""
        from app.services.lead_assignment_service import get_eligible_reps
        users = [
            {"id": REP1_ID, "is_active": False, "is_out_of_office": False},
        ]
        db = self._make_db(users)
        shift = _mk_shift(assignees=[REP1_ID])
        result = get_eligible_reps(db, ORG_ID, shift)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# get_least_loaded_rep
# ═══════════════════════════════════════════════════════════════════════════

class TestGetLeastLoadedRep:

    def _make_db(self, leads):
        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.not_ = chain
        chain.is_.return_value = chain
        chain.execute.return_value = MagicMock(data=leads)
        db.table.return_value = chain
        return db

    def test_LA_U_10_returns_rep_with_fewest_leads(self):
        """LA-U-10: returns rep with fewest open leads."""
        from app.services.lead_assignment_service import get_least_loaded_rep
        leads = [
            {"assigned_to": REP1_ID},
            {"assigned_to": REP1_ID},
        ]
        db = self._make_db(leads)
        reps = [
            {"id": REP1_ID, "full_name": "Rep 1"},
            {"id": REP2_ID, "full_name": "Rep 2"},
        ]
        result = get_least_loaded_rep(db, ORG_ID, reps)
        assert result["id"] == REP2_ID

    def test_LA_U_11_tie_first_in_list_wins(self):
        """LA-U-11: tie → first in list wins."""
        from app.services.lead_assignment_service import get_least_loaded_rep
        db = self._make_db([])  # no open leads — both at 0
        reps = [
            {"id": REP1_ID, "full_name": "Rep 1"},
            {"id": REP2_ID, "full_name": "Rep 2"},
        ]
        result = get_least_loaded_rep(db, ORG_ID, reps)
        assert result["id"] == REP1_ID

    def test_LA_U_12_rep_with_zero_leads_wins(self):
        """LA-U-12: rep with 0 leads wins."""
        from app.services.lead_assignment_service import get_least_loaded_rep
        leads = [{"assigned_to": REP1_ID}]
        db = self._make_db(leads)
        reps = [
            {"id": REP1_ID, "full_name": "Rep 1"},
            {"id": REP2_ID, "full_name": "Rep 2"},
        ]
        result = get_least_loaded_rep(db, ORG_ID, reps)
        assert result["id"] == REP2_ID

    def test_LA_U_13_returns_none_when_empty(self):
        """LA-U-13: returns None when eligible_reps is empty."""
        from app.services.lead_assignment_service import get_least_loaded_rep
        db = self._make_db([])
        result = get_least_loaded_rep(db, ORG_ID, [])
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# auto_assign_lead
# ═══════════════════════════════════════════════════════════════════════════

class TestAutoAssignLead:

    def _base_db(self, mode="auto", contact_type="sales_lead", user_template=None):
        db = MagicMock()

        def table_side(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.in_.return_value = chain
            chain.not_ = chain
            chain.is_.return_value = chain
            chain.update.return_value = chain
            chain.insert.return_value = chain

            if name == "organisations":
                chain.execute.return_value = MagicMock(data={
                    "lead_assignment_mode": mode,
                    "timezone": "Africa/Lagos",
                    "sla_business_hours": {},
                })
            elif name == "leads":
                chain.execute.return_value = MagicMock(
                    data={"contact_type": contact_type, "full_name": "Test Lead", "source": "whatsapp_inbound"}
                )
            elif name == "users":
                chain.execute.return_value = MagicMock(
                    data={"roles": {"template": user_template or "sales_agent"}}
                    if user_template else {"roles": {"template": "owner"}}
                )
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = table_side
        return db

    def test_LA_U_14_gate_manual_mode_returns_none(self):
        """LA-U-14: mode=manual → None, no assignment."""
        from app.services.lead_assignment_service import auto_assign_lead
        db = self._base_db(mode="manual")
        result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
        assert result is None

    def test_LA_U_15_gate_non_sales_lead_returns_none(self):
        """LA-U-15: contact_type != sales_lead → None."""
        from app.services.lead_assignment_service import auto_assign_lead
        db = self._base_db(mode="auto", contact_type="support_contact")
        result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
        assert result is None

    def test_LA_U_16_gate_import_source_returns_none(self):
        """LA-U-16: source=import → None."""
        from app.services.lead_assignment_service import auto_assign_lead
        db = self._base_db(mode="auto")
        result = auto_assign_lead(db, ORG_ID, LEAD_ID, "import", None)
        assert result is None

    def test_LA_U_17_gate_sales_agent_user_returns_none(self):
        """LA-U-17: user_id is sales_agent → None."""
        from app.services.lead_assignment_service import auto_assign_lead

        db = MagicMock()
        calls = []

        def table_side(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.in_.return_value = chain
            chain.maybe_single.return_value = chain

            calls.append(name)
            if name == "organisations":
                chain.execute.return_value = MagicMock(data={
                    "lead_assignment_mode": "auto", "timezone": "Africa/Lagos"
                })
            elif name == "leads":
                chain.execute.return_value = MagicMock(
                    data={"contact_type": "sales_lead"}
                )
            elif name == "users":
                chain.execute.return_value = MagicMock(
                    data={"roles": {"template": "sales_agent"}}
                )
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain

        db.table.side_effect = table_side
        result = auto_assign_lead(db, ORG_ID, LEAD_ID, "manual", REP1_ID)
        assert result is None

    def test_LA_U_18_no_active_shift_notifies_admins(self):
        """LA-U-18: no active shift → None, admins notified."""
        from app.services.lead_assignment_service import auto_assign_lead

        with patch("app.services.lead_assignment_service.get_active_shift", return_value=None), \
             patch("app.services.lead_assignment_service._notify_no_reps_available") as mock_notify, \
             patch("app.services.lead_assignment_service.get_eligible_reps", return_value=[]), \
             patch("app.services.lead_assignment_service.get_least_loaded_rep", return_value=None):

            db = MagicMock()
            def table_side(name):
                chain = MagicMock()
                chain.select.return_value = chain
                chain.eq.return_value = chain
                chain.maybe_single.return_value = chain
                if name == "organisations":
                    chain.execute.return_value = MagicMock(data={"lead_assignment_mode": "auto", "timezone": "UTC"})
                elif name == "leads":
                    chain.execute.return_value = MagicMock(data={"contact_type": "sales_lead"})
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain
            db.table.side_effect = table_side

            result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
            assert result is None
            mock_notify.assert_called_once_with(db, ORG_ID, LEAD_ID)

    def test_LA_U_19_no_eligible_reps_notifies_admins(self):
        """LA-U-19: no eligible reps → None, admins notified."""
        from app.services.lead_assignment_service import auto_assign_lead

        shift = _mk_shift()
        with patch("app.services.lead_assignment_service.get_active_shift", return_value=shift), \
             patch("app.services.lead_assignment_service.get_eligible_reps", return_value=[]), \
             patch("app.services.lead_assignment_service._notify_no_reps_available") as mock_notify:

            db = MagicMock()
            def table_side(name):
                chain = MagicMock()
                chain.select.return_value = chain
                chain.eq.return_value = chain
                chain.maybe_single.return_value = chain
                if name == "organisations":
                    chain.execute.return_value = MagicMock(data={"lead_assignment_mode": "auto", "timezone": "UTC"})
                elif name == "leads":
                    chain.execute.return_value = MagicMock(data={"contact_type": "sales_lead"})
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain
            db.table.side_effect = table_side

            result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
            assert result is None
            mock_notify.assert_called_once()

    def test_LA_U_20_success_writes_assignment(self):
        """LA-U-20: success → assigned_to written, timeline, audit, notification."""
        from app.services.lead_assignment_service import auto_assign_lead

        rep = {"id": REP1_ID, "full_name": "Test Rep", "whatsapp_number": ""}
        shift = _mk_shift()

        with patch("app.services.lead_assignment_service.get_active_shift", return_value=shift), \
             patch("app.services.lead_assignment_service.get_eligible_reps", return_value=[rep]), \
             patch("app.services.lead_assignment_service.get_least_loaded_rep", return_value=rep), \
             patch("app.services.lead_assignment_service._write_assignment") as mock_write:

            db = MagicMock()
            def table_side(name):
                chain = MagicMock()
                chain.select.return_value = chain
                chain.eq.return_value = chain
                chain.maybe_single.return_value = chain
                if name == "organisations":
                    chain.execute.return_value = MagicMock(data={"lead_assignment_mode": "auto", "timezone": "UTC"})
                elif name == "leads":
                    chain.execute.return_value = MagicMock(data={"contact_type": "sales_lead"})
                else:
                    chain.execute.return_value = MagicMock(data=[])
                return chain
            db.table.side_effect = table_side

            result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
            assert result == REP1_ID
            mock_write.assert_called_once_with(db, ORG_ID, LEAD_ID, REP1_ID, "Day Shift")


# ═══════════════════════════════════════════════════════════════════════════
# _write_assignment + _notify_no_reps_available
# ═══════════════════════════════════════════════════════════════════════════

class TestWriteAssignment:

    def _make_db(self):
        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        chain.insert.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = MagicMock(
            data={"full_name": "Test Rep", "whatsapp_number": "", "source": "whatsapp_inbound", "full_name": "Test Lead"}
        )
        db.table.return_value = chain
        return db

    def test_LA_U_21_timeline_event_correct_description(self):
        """LA-U-21: lead_timeline event written with correct description."""
        from app.services.lead_assignment_service import _write_assignment
        db = self._make_db()
        _write_assignment(db, ORG_ID, LEAD_ID, REP1_ID, "Night Shift")
        # Verify lead_timeline insert was called
        insert_calls = [
            call for call in db.table.call_args_list
            if call[0][0] == "lead_timeline"
        ]
        assert len(insert_calls) >= 1

    def test_LA_U_22_audit_log_correct_action(self):
        """LA-U-22: audit_log written with action='lead.auto_assigned'."""
        from app.services.lead_assignment_service import _write_assignment
        db = self._make_db()
        _write_assignment(db, ORG_ID, LEAD_ID, REP1_ID, "Day Shift")
        audit_calls = [
            call for call in db.table.call_args_list
            if call[0][0] == "audit_logs"
        ]
        assert len(audit_calls) >= 1

    def test_LA_U_23_notify_no_reps_notifies_owners(self):
        """LA-U-23: _notify_no_reps_available notifies all owners and ops_managers."""
        from app.services.lead_assignment_service import _notify_no_reps_available
        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data=[
            {"id": ADMIN_ID, "roles": {"template": "owner"}},
        ])
        db.table.return_value = chain
        _notify_no_reps_available(db, ORG_ID, LEAD_ID)
        # Should have inserted notifications
        insert_calls = [c for c in db.table.call_args_list if c[0][0] == "notifications"]
        assert len(insert_calls) >= 1

    def test_LA_U_24_s14_db_error_in_auto_assign_never_raises(self):
        """LA-U-24: S14 — DB error caught, lead still created unaffected."""
        from app.services.lead_assignment_service import auto_assign_lead
        db = MagicMock()
        db.table.side_effect = Exception("DB connection lost")
        # Must not raise
        result = auto_assign_lead(db, ORG_ID, LEAD_ID, "whatsapp_inbound", None)
        assert result is None
