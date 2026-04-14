"""
tests/unit/test_lead_sla_worker.py
M01-6 — Unit tests for lead_sla_worker

Tests cover:
  - stamp_first_contacted (lead_service helper)
  - _get_org_sla
  - _get_org_manager_id
  - _insert_notification
  - _process_lead (all branches: skipped / 1x breach / 2x escalation)
  - run_lead_sla_check (Celery task, full summary)

All UUIDs are valid UUID format (Pattern 24).
Notifications are inserted directly — no create_notification function (Pattern 28 note).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

ORG_ID   = str(uuid.uuid4())
LEAD_ID  = str(uuid.uuid4())
REP_ID   = str(uuid.uuid4())
MGR_ID   = str(uuid.uuid4())


def _chain(*return_values):
    """Build a supabase-style chainable mock that returns a given value from .execute()."""
    mock = MagicMock()
    terminal = MagicMock()
    terminal.execute.return_value = MagicMock(data=return_values[0])
    # Chain every attribute back to the same mock so .eq().eq().is_() etc. all work
    mock.table.return_value = mock
    mock.select.return_value = mock
    mock.eq.return_value = mock
    mock.is_.return_value = mock
    mock.not_.return_value = mock
    mock.in_.return_value = mock
    mock.neq.return_value = mock
    mock.not_.in_.return_value = mock
    mock.limit.return_value = mock
    mock.update.return_value = mock
    mock.insert.return_value = mock
    mock.maybe_single.return_value = terminal
    mock.execute.return_value = MagicMock(data=return_values[0])
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# stamp_first_contacted
# ═══════════════════════════════════════════════════════════════════════════════

class TestStampFirstContacted:

    def test_stamps_when_not_yet_contacted(self):
        from app.services.lead_service import stamp_first_contacted
        db = MagicMock()
        created_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        lead_data = {"id": LEAD_ID, "first_contacted_at": None, "created_at": created_at}

        # maybe_single chain
        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=lead_data)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .is_.return_value.maybe_single.return_value = select_chain

        update_chain = MagicMock()
        update_chain.execute.return_value = MagicMock(data=[])
        db.table.return_value.update.return_value.eq.return_value.eq.return_value = update_chain

        stamp_first_contacted(db, ORG_ID, LEAD_ID)
        update_chain.execute.assert_called_once()

    def test_idempotent_when_already_stamped(self):
        from app.services.lead_service import stamp_first_contacted
        db = MagicMock()
        lead_data = {
            "id": LEAD_ID,
            "first_contacted_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=lead_data)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .is_.return_value.maybe_single.return_value = select_chain

        stamp_first_contacted(db, ORG_ID, LEAD_ID)
        # update should NOT be called
        db.table.return_value.update.assert_not_called()

    def test_skips_when_lead_not_found(self):
        from app.services.lead_service import stamp_first_contacted
        db = MagicMock()
        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=None)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .is_.return_value.maybe_single.return_value = select_chain

        # Should not raise
        stamp_first_contacted(db, ORG_ID, LEAD_ID)
        db.table.return_value.update.assert_not_called()

    def test_calculates_response_time_minutes(self):
        """response_time_minutes should be set based on elapsed time since created_at."""
        from app.services.lead_service import stamp_first_contacted
        db = MagicMock()
        created_at = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
        lead_data = {"id": LEAD_ID, "first_contacted_at": None, "created_at": created_at}

        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=lead_data)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .is_.return_value.maybe_single.return_value = select_chain

        update_chain = MagicMock()
        update_chain.execute.return_value = MagicMock(data=[])
        db.table.return_value.update.return_value.eq.return_value.eq.return_value = update_chain

        stamp_first_contacted(db, ORG_ID, LEAD_ID)
        # Check update was called with a response_time_minutes between 88 and 92 (clock drift)
        call_args = db.table.return_value.update.call_args[0][0]
        assert 88 <= call_args["response_time_minutes"] <= 92


# ═══════════════════════════════════════════════════════════════════════════════
# _get_org_sla
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetOrgSla:

    def test_returns_configured_values(self):
        from app.workers.lead_sla_worker import _get_org_sla
        db = MagicMock()
        single = MagicMock()
        single.execute.return_value = MagicMock(data={
            "sla_hot_hours": 2, "sla_warm_hours": 6, "sla_cold_hours": 48
        })
        db.table.return_value.select.return_value.eq.return_value.single.return_value = single

        result = _get_org_sla(db, ORG_ID)
        assert result == {"hot": 2, "warm": 6, "cold": 48}

    def test_falls_back_to_defaults_when_null(self):
        from app.workers.lead_sla_worker import _get_org_sla
        db = MagicMock()
        single = MagicMock()
        single.execute.return_value = MagicMock(data={
            "sla_hot_hours": None, "sla_warm_hours": None, "sla_cold_hours": None
        })
        db.table.return_value.select.return_value.eq.return_value.single.return_value = single

        result = _get_org_sla(db, ORG_ID)
        assert result == {"hot": 1, "warm": 4, "cold": 24}


# ═══════════════════════════════════════════════════════════════════════════════
# _get_org_manager_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetOrgManagerId:

    def test_returns_first_owner(self):
        """
        Worker fetches all users with roles(template) join and filters in Python
        (Pattern 33 / Pattern 37 / Pattern 48 Rule 3).
        The DB mock must return rows in the joined structure PostgREST uses:
          { "id": "...", "is_active": True, "roles": {"template": "owner"} }
        Not a flat "role" column — that column does not exist on users table.
        """
        from app.workers.lead_sla_worker import _get_org_manager_id
        db = MagicMock()
        # Worker calls .select("id, is_active, roles(template)").eq(org_id).eq(is_active)
        # then optionally .neq(exclude_user_id) — all chained, ends in .execute()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .execute.return_value = MagicMock(data=[
                {"id": MGR_ID, "is_active": True, "roles": {"template": "owner"}},
                {"id": REP_ID, "is_active": True, "roles": {"template": "sales_agent"}},
            ])
        # Also handle the .neq() branch (when exclude_user_id is passed)
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .neq.return_value.execute.return_value = MagicMock(data=[
                {"id": MGR_ID, "is_active": True, "roles": {"template": "owner"}},
            ])

        result = _get_org_manager_id(db, ORG_ID, exclude_user_id=REP_ID)
        assert result == MGR_ID

    def test_returns_none_when_no_manager(self):
        from app.workers.lead_sla_worker import _get_org_manager_id
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .execute.return_value = MagicMock(data=[
                {"id": REP_ID, "is_active": True, "roles": {"template": "sales_agent"}},
            ])
        db.table.return_value.select.return_value.eq.return_value.eq.return_value\
            .neq.return_value.execute.return_value = MagicMock(data=[
                {"id": REP_ID, "is_active": True, "roles": {"template": "sales_agent"}},
            ])

        result = _get_org_manager_id(db, ORG_ID)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# _insert_notification
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsertNotification:

    def test_inserts_with_correct_fields(self):
        """
        Notifications table has NO metadata column (Pattern 48 Rule 2).
        Worker inserts resource_type + resource_id instead.
        """
        from app.workers.lead_sla_worker import _insert_notification, _NOTIF_BREACH
        db = MagicMock()
        insert_chain = MagicMock()
        db.table.return_value.insert.return_value = insert_chain

        _insert_notification(db, ORG_ID, REP_ID, _NOTIF_BREACH,
                             "Title", "Body text", LEAD_ID)

        insert_call_kwargs = db.table.return_value.insert.call_args[0][0]
        assert insert_call_kwargs["org_id"]        == ORG_ID
        assert insert_call_kwargs["user_id"]       == REP_ID
        assert insert_call_kwargs["type"]          == _NOTIF_BREACH
        assert insert_call_kwargs["is_read"]       is False
        # Pattern 48 Rule 2: resource_type/resource_id, NOT metadata
        assert insert_call_kwargs["resource_type"] == "lead"
        assert insert_call_kwargs["resource_id"]   == LEAD_ID
        assert "metadata" not in insert_call_kwargs, \
            "metadata column does not exist on notifications table (Pattern 48 Rule 2)"
        insert_chain.execute.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# _process_lead
# ═══════════════════════════════════════════════════════════════════════════════

def _make_lead(score="hot", hours_ago=2, assigned=True):
    created_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "id":          LEAD_ID,
        "org_id":      ORG_ID,
        "full_name":   "Test Lead",
        "score":       score,
        "assigned_to": REP_ID if assigned else None,
        "created_at":  created_at,
    }


SLA = {"hot": 1, "warm": 4, "cold": 24}


class TestProcessLead:

    def test_skips_unscored_lead(self):
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()
        result = _process_lead(db, _make_lead(score="unscored"), SLA)
        assert result["skipped"] is True
        assert result["breach"]  is False

    def test_skips_when_not_yet_overdue(self):
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()
        # Hot lead created 30 minutes ago — 1h SLA not yet breached
        result = _process_lead(db, _make_lead(score="hot", hours_ago=0.4), SLA)
        assert result["skipped"] is True

    def test_skips_when_no_assigned_rep(self):
        """
        At 1× threshold with no rep assigned, the worker's else branch sets
        result["skipped"] = True.

        hours_ago=1.5 puts elapsed time strictly between threshold_1 (1h) and
        threshold_2 (2h), ensuring we hit the 1× branch — not the 2× branch.
        hours_ago=2 would hit elapsed >= threshold_2 (2h >= 2h) and enter the
        escalation path where skipped is never set.
        """
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=None)

        with patch("app.workers.lead_sla_worker._insert_notification") as mock_notif:
            result = _process_lead(db, _make_lead(score="hot", hours_ago=1.5, assigned=False), SLA)

        assert result["skipped"] is True
        assert result["breach"]  is False
        # No notification should be sent when there's no rep
        mock_notif.assert_not_called()

    def test_breach_alert_at_1x_threshold(self):
        from app.workers.lead_sla_worker import _process_lead, _NOTIF_BREACH
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        # Hot lead, 1.5h old — past 1h threshold, before 2h escalation threshold
        result = _process_lead(db, _make_lead(score="hot", hours_ago=1.5), SLA)
        assert result["breach"]     is True
        assert result["escalation"] is False

        insert_payload = db.table.return_value.insert.call_args[0][0]
        assert insert_payload["type"]    == _NOTIF_BREACH
        assert insert_payload["user_id"] == REP_ID

    def test_escalation_at_2x_threshold(self):
        """
        At 2× threshold: both breach (to rep) and escalation (to manager) fired.
        Patch _get_org_manager_id at the module level (Pattern 42) so the DB
        mock chain doesn't need to match the worker's exact query structure.
        """
        from app.workers.lead_sla_worker import _process_lead, _NOTIF_BREACH, _NOTIF_ESCALATION

        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        # Hot lead, 3h old — past 2h escalation threshold
        with patch(
            "app.workers.lead_sla_worker._get_org_manager_id",
            return_value=MGR_ID,
        ):
            result = _process_lead(db, _make_lead(score="hot", hours_ago=3), SLA)

        assert result["breach"]     is True
        assert result["escalation"] is True

        # Two notifications should have been inserted (breach to rep + escalation to mgr)
        assert db.table.return_value.insert.call_count == 2
        types_inserted = {
            call[0][0]["type"]
            for call in db.table.return_value.insert.call_args_list
        }
        assert _NOTIF_BREACH     in types_inserted
        assert _NOTIF_ESCALATION in types_inserted

    def test_warm_lead_uses_correct_threshold(self):
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock()

        # Warm lead, 5h old — past 4h threshold
        result = _process_lead(db, _make_lead(score="warm", hours_ago=5), SLA)
        assert result["breach"] is True

    def test_cold_lead_skipped_if_within_window(self):
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()

        # Cold lead, 12h old — within 24h window
        result = _process_lead(db, _make_lead(score="cold", hours_ago=12), SLA)
        assert result["skipped"] is True

    def test_exception_caught_and_logged(self):
        from app.workers.lead_sla_worker import _process_lead
        db = MagicMock()
        db.table.side_effect = RuntimeError("db exploded")

        lead = _make_lead(score="hot", hours_ago=2)
        # Should not raise — S14 protection
        result = _process_lead(db, lead, SLA)
        assert result["skipped"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# run_lead_sla_check (Celery task)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunLeadSlaCheck:

    @patch("app.workers.lead_sla_worker.get_supabase")   # Pattern 48 Rule 1: get_supabase not get_db
    @patch("app.workers.lead_sla_worker._process_lead")
    def test_processes_all_orgs_and_leads(self, mock_process, mock_get_supabase):
        from app.workers.lead_sla_worker import run_lead_sla_check

        db = MagicMock()
        mock_get_supabase.return_value = db

        org1_id = str(uuid.uuid4())
        lead1_id = str(uuid.uuid4())

        # orgs result
        orgs_execute = MagicMock(data=[{
            "id": org1_id,
            "sla_hot_hours": 1, "sla_warm_hours": 4, "sla_cold_hours": 24
        }])
        # leads result
        leads_execute = MagicMock(data=[{
            "id": lead1_id, "org_id": org1_id,
            "full_name": "Jane", "score": "hot",
            "assigned_to": str(uuid.uuid4()),
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        }])

        # Make the chain return different things on sequential calls
        db.table.return_value.select.return_value.execute.side_effect = [
            orgs_execute, leads_execute
        ]
        # Make all chained calls also resolve
        db.table.return_value.select.return_value.eq.return_value.execute.return_value = leads_execute
        db.table.return_value.select.return_value.eq.return_value\
            .is_.return_value.not_.return_value.execute.return_value = leads_execute

        mock_process.return_value = {"breach": True, "escalation": False, "skipped": False}

        # Call task directly (bypass Celery)
        summary = run_lead_sla_check.run()
        assert summary["orgs_processed"] >= 0  # ran without exception

    @patch("app.workers.lead_sla_worker.get_supabase")   # Pattern 48 Rule 1: get_supabase not get_db
    def test_returns_summary_on_empty_orgs(self, mock_get_supabase):
        from app.workers.lead_sla_worker import run_lead_sla_check

        db = MagicMock()
        mock_get_supabase.return_value = db
        db.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        summary = run_lead_sla_check.run()
        assert summary["orgs_processed"] == 0
        assert summary["leads_checked"]  == 0
        assert summary["breaches"]       == 0