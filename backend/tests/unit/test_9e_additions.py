"""
tests/unit/test_9e_additions.py
Phase 9E-E unit tests covering all security fixes:

  - TestLeadModelConstraints     (S3/S4 — LeadCreate + LeadUpdate field limits)
  - TestTicketModelConstraints   (S4/S5 — TicketCreate, AddMessageRequest,
                                          ResolveRequest, InteractionLogCreate)
  - TestSlaWorkerPattern48       (sla_worker — roles(template) join fix)
  - TestGrowthInsightsImport     (growth_insights_worker — import path fix)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


# ── Shared constants ──────────────────────────────────────────────────────────
ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000099"


# ══════════════════════════════════════════════════════════════════════════════
# S3 / S4 — app/models/leads.py
# ══════════════════════════════════════════════════════════════════════════════

class TestLeadModelConstraints:
    """S3/S4: Every str field on LeadCreate and LeadUpdate must have max_length."""

    # ── LeadCreate — required field ───────────────────────────────────────────

    def test_full_name_at_limit_passes(self):
        from app.models.leads import LeadCreate
        payload = LeadCreate(full_name="A" * 255, source="manual_phone")
        assert payload.full_name == "A" * 255

    def test_full_name_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="A" * 256, source="manual_phone")

    # ── LeadCreate — phone / whatsapp ─────────────────────────────────────────

    def test_phone_at_limit_passes(self):
        from app.models.leads import LeadCreate
        LeadCreate(full_name="Test", source="manual_phone", phone="1" * 20)

    def test_phone_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="Test", source="manual_phone", phone="1" * 21)

    def test_whatsapp_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="Test", source="manual_phone", whatsapp="1" * 21)

    # ── LeadCreate — S4 free text field ───────────────────────────────────────

    def test_problem_stated_at_limit_passes(self):
        from app.models.leads import LeadCreate
        LeadCreate(full_name="Test", source="manual_phone", problem_stated="x" * 5000)

    def test_problem_stated_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="Test", source="manual_phone", problem_stated="x" * 5001)

    # ── LeadCreate — utm / campaign fields ────────────────────────────────────

    def test_utm_source_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="Test", source="manual_phone", utm_source="x" * 256)

    def test_campaign_id_over_limit_raises(self):
        from app.models.leads import LeadCreate
        with pytest.raises(ValidationError):
            LeadCreate(full_name="Test", source="manual_phone", campaign_id="x" * 256)

    # ── LeadCreate — None values still accepted ───────────────────────────────

    def test_all_optional_fields_none_passes(self):
        from app.models.leads import LeadCreate
        payload = LeadCreate(full_name="Test", source="manual_phone")
        assert payload.phone is None
        assert payload.problem_stated is None

    # ── LeadUpdate — same constraints ─────────────────────────────────────────

    def test_lead_update_full_name_over_limit_raises(self):
        from app.models.leads import LeadUpdate
        with pytest.raises(ValidationError):
            LeadUpdate(full_name="A" * 256)

    def test_lead_update_problem_stated_over_limit_raises(self):
        from app.models.leads import LeadUpdate
        with pytest.raises(ValidationError):
            LeadUpdate(problem_stated="x" * 5001)

    def test_lead_update_problem_stated_at_limit_passes(self):
        from app.models.leads import LeadUpdate
        payload = LeadUpdate(problem_stated="x" * 5000)
        assert len(payload.problem_stated) == 5000

    def test_lead_update_all_none_passes(self):
        from app.models.leads import LeadUpdate
        payload = LeadUpdate()
        assert payload.full_name is None


# ══════════════════════════════════════════════════════════════════════════════
# S4 / S5 — app/models/tickets.py
# ══════════════════════════════════════════════════════════════════════════════

class TestTicketModelConstraints:
    """S4/S5: content/notes fields on ticket models must have max_length."""

    # ── TicketCreate — S5: content max 10,000 ────────────────────────────────

    def test_ticket_create_content_at_limit_passes(self):
        from app.models.tickets import TicketCreate
        t = TicketCreate(content="x" * 10000)
        assert len(t.content) == 10000

    def test_ticket_create_content_over_limit_raises(self):
        from app.models.tickets import TicketCreate
        with pytest.raises(ValidationError):
            TicketCreate(content="x" * 10001)

    def test_ticket_create_content_required(self):
        from app.models.tickets import TicketCreate
        with pytest.raises(ValidationError):
            TicketCreate()

    # ── AddMessageRequest — S4: content max 5,000 ────────────────────────────

    def test_add_message_content_at_limit_passes(self):
        from app.models.tickets import AddMessageRequest
        m = AddMessageRequest(message_type="agent_reply", content="x" * 5000)
        assert len(m.content) == 5000

    def test_add_message_content_over_limit_raises(self):
        from app.models.tickets import AddMessageRequest
        with pytest.raises(ValidationError):
            AddMessageRequest(message_type="agent_reply", content="x" * 5001)

    def test_add_message_invalid_message_type_raises(self):
        from app.models.tickets import AddMessageRequest
        with pytest.raises(ValidationError):
            AddMessageRequest(message_type="unknown_type", content="Hello")

    # ── ResolveRequest — S4: resolution_notes max 5,000 ─────────────────────

    def test_resolve_request_at_limit_passes(self):
        from app.models.tickets import ResolveRequest
        r = ResolveRequest(resolution_notes="x" * 5000)
        assert len(r.resolution_notes) == 5000

    def test_resolve_request_over_limit_raises(self):
        from app.models.tickets import ResolveRequest
        with pytest.raises(ValidationError):
            ResolveRequest(resolution_notes="x" * 5001)

    def test_resolve_request_notes_required(self):
        from app.models.tickets import ResolveRequest
        with pytest.raises(ValidationError):
            ResolveRequest()

    # ── InteractionLogCreate — S3/S4 ─────────────────────────────────────────

    def test_interaction_log_raw_notes_at_limit_passes(self):
        from app.models.tickets import InteractionLogCreate
        from datetime import datetime, timezone
        log = InteractionLogCreate(
            interaction_type="whatsapp",
            raw_notes="x" * 5000,
            interaction_date=datetime.now(timezone.utc),
        )
        assert len(log.raw_notes) == 5000

    def test_interaction_log_raw_notes_over_limit_raises(self):
        from app.models.tickets import InteractionLogCreate
        from datetime import datetime, timezone
        with pytest.raises(ValidationError):
            InteractionLogCreate(
                interaction_type="whatsapp",
                raw_notes="x" * 5001,
                interaction_date=datetime.now(timezone.utc),
            )

    def test_interaction_log_outcome_over_limit_raises(self):
        from app.models.tickets import InteractionLogCreate
        from datetime import datetime, timezone
        with pytest.raises(ValidationError):
            InteractionLogCreate(
                interaction_type="whatsapp",
                outcome="x" * 101,
                interaction_date=datetime.now(timezone.utc),
            )

    def test_interaction_log_outcome_at_limit_passes(self):
        from app.models.tickets import InteractionLogCreate
        from datetime import datetime, timezone
        log = InteractionLogCreate(
            interaction_type="whatsapp",
            outcome="x" * 100,
            interaction_date=datetime.now(timezone.utc),
        )
        assert len(log.outcome) == 100

    def test_interaction_log_none_notes_passes(self):
        from app.models.tickets import InteractionLogCreate
        from datetime import datetime, timezone
        log = InteractionLogCreate(
            interaction_type="in_person",
            interaction_date=datetime.now(timezone.utc),
        )
        assert log.raw_notes is None
        assert log.outcome is None


# ══════════════════════════════════════════════════════════════════════════════
# sla_worker — Pattern 48 fix
# ══════════════════════════════════════════════════════════════════════════════

class TestSlaWorkerPattern48:
    """
    sla_worker supervisor notification block must use roles(template) join
    (Pattern 48) and check for 'ops_manager' — not 'role' column / 'supervisor'.

    Mock chains mirror the worker's exact call sequences:
      organisations : .select("id").execute().data
      tickets       : .select(...).eq("org_id",...).in_("status",...).execute().data
      tickets update: .update({...}).eq("id",...).execute()
      users         : .select("id, roles(template)").eq("org_id",...).execute().data
      notifications : .insert({...}).execute()
      tasks         : .insert({...}).execute()
    """

    def _make_db(self, users_with_roles, tickets=None):
        """
        Build a db mock whose table() side_effect returns a dedicated chain
        per table name, wired to the exact call sequences in the worker.
        """
        # Per-table chain stores
        table_mocks = {}

        def _make_chain():
            c = MagicMock()
            # Wire every chaining method back to the same mock so any
            # sequence of .select().eq().in_().execute() etc. all resolve.
            for method in ("select", "eq", "in_", "is_", "order",
                           "limit", "neq", "update", "insert"):
                getattr(c, method).return_value = c
            c.execute.return_value = MagicMock(data=[])
            return c

        def _table(name):
            if name not in table_mocks:
                table_mocks[name] = _make_chain()
            return table_mocks[name]

        db = MagicMock()
        db.table.side_effect = _table

        # Trigger creation of each table mock so we can configure them
        _table("organisations")
        _table("tickets")
        _table("users")
        _table("notifications")
        _table("tasks")

        # organisations: .select("id").execute().data  →  [{"id": ORG_ID}]
        table_mocks["organisations"].execute.return_value = MagicMock(
            data=[{"id": ORG_ID}]
        )

        # tickets: .select(...).eq(...).in_(...).execute().data
        tickets_data = tickets or [{
            "id":                    "ticket-001",
            "org_id":                ORG_ID,
            "title":                 "Test ticket",
            "status":                "open",
            "assigned_to":           "user-rep-001",
            "sla_resolution_due_at": "2020-01-01T00:00:00+00:00",
            "sla_response_due_at":   "2020-01-01T00:00:00+00:00",
            "sla_breached":          False,
        }]
        table_mocks["tickets"].execute.return_value = MagicMock(data=tickets_data)

        # users: .select("id, roles(template)").eq(...).execute().data
        table_mocks["users"].execute.return_value = MagicMock(data=users_with_roles)

        return db, table_mocks

    # ── Notification capture helper ───────────────────────────────────────────

    def _capture_notifications(self, table_mocks):
        """
        Wire notifications.insert() to capture every row dict passed to it.
        Returns the list that will be populated during the run.
        """
        captured = []

        original_insert = table_mocks["notifications"].insert

        def _capture(row_dict):
            captured.append(row_dict)
            m = MagicMock()
            m.execute.return_value = MagicMock()
            return m

        table_mocks["notifications"].insert.side_effect = _capture
        return captured

    # ── Tests ─────────────────────────────────────────────────────────────────

    def test_owner_receives_supervisor_notification(self):
        """Users with roles.template='owner' must be notified of SLA breach."""
        users = [
            {"id": "user-owner-001", "roles": {"template": "owner"}},
            {"id": "user-rep-001",   "roles": {"template": "sales_agent"}},
        ]
        db, mocks = self._make_db(users)
        captured = self._capture_notifications(mocks)

        with patch("app.workers.sla_worker.get_supabase", return_value=db):
            from app.workers.sla_worker import run_sla_monitor
            run_sla_monitor.run()

        notified_ids = [n.get("user_id") for n in captured]
        assert "user-owner-001" in notified_ids

    def test_ops_manager_receives_supervisor_notification(self):
        """Users with roles.template='ops_manager' must be notified."""
        users = [
            {"id": "user-ops-001", "roles": {"template": "ops_manager"}},
            {"id": "user-rep-001", "roles": {"template": "sales_agent"}},
        ]
        db, mocks = self._make_db(users)
        captured = self._capture_notifications(mocks)

        with patch("app.workers.sla_worker.get_supabase", return_value=db):
            from app.workers.sla_worker import run_sla_monitor
            run_sla_monitor.run()

        notified_ids = [n.get("user_id") for n in captured]
        assert "user-ops-001" in notified_ids

    def test_sales_agent_does_not_receive_supervisor_notification(self):
        """sales_agent must NOT receive the supervisor escalation notification."""
        users = [
            {"id": "user-owner-001", "roles": {"template": "owner"}},
            {"id": "user-agent-001", "roles": {"template": "sales_agent"}},
        ]
        db, mocks = self._make_db(users)
        captured = self._capture_notifications(mocks)

        with patch("app.workers.sla_worker.get_supabase", return_value=db):
            from app.workers.sla_worker import run_sla_monitor
            run_sla_monitor.run()

        notified_ids = [n.get("user_id") for n in captured]
        assert "user-agent-001" not in notified_ids

    def test_users_query_uses_roles_template_join(self):
        """
        The select() call on users must request 'roles(template)' not 'role'.
        Confirms Pattern 48 compliance at the query level.
        """
        users = [{"id": "user-owner-001", "roles": {"template": "owner"}}]
        db, mocks = self._make_db(users)

        with patch("app.workers.sla_worker.get_supabase", return_value=db):
            from app.workers.sla_worker import run_sla_monitor
            run_sla_monitor.run()

        select_calls = [str(c) for c in mocks["users"].select.call_args_list]
        assert any("roles" in c for c in select_calls), (
            "users query must use roles(template) join per Pattern 48"
        )
        assert not any(c == "call('id, role')" for c in select_calls), (
            "users query must not select bare 'role' column — Pattern 48 violation"
        )

    def test_s14_per_org_exception_does_not_stop_loop(self):
        """
        S14: an exception inside one org's processing must be caught by the
        per-org try/except and must not propagate to the task level.
        Worker returns a result dict — not raises.
        """
        users = [{"id": "user-owner-001", "roles": {"template": "owner"}}]
        db, mocks = self._make_db(users)

        # Make tickets.execute() raise so the per-org block fails
        mocks["tickets"].execute.side_effect = Exception("DB timeout")

        with patch("app.workers.sla_worker.get_supabase", return_value=db):
            from app.workers.sla_worker import run_sla_monitor
            result = run_sla_monitor.run()

        assert isinstance(result, dict)
        assert "breaches" in result


# ══════════════════════════════════════════════════════════════════════════════
# growth_insights_worker — import fix
# ══════════════════════════════════════════════════════════════════════════════

class TestGrowthInsightsImport:
    """
    growth_insights_worker must import get_supabase from app.database,
    not app.dependencies. This was the bug that caused ImportError at startup.
    """

    def test_get_supabase_imported_from_app_database(self):
        """
        Verify the worker module resolves get_supabase from app.database.
        If the import is wrong, importing the worker itself will raise ImportError.
        """
        import importlib
        import app.workers.growth_insights_worker as worker_mod

        # The module must have loaded without error (import happened at collection time).
        # Now confirm the get_supabase reference points to app.database, not app.dependencies.
        import app.database as db_mod
        assert worker_mod.get_supabase is db_mod.get_supabase, (
            "growth_insights_worker.get_supabase must come from app.database, "
            "not app.dependencies"
        )

    def test_worker_module_importable_without_error(self):
        """Importing the worker module must not raise any ImportError."""
        try:
            import app.workers.growth_insights_worker  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"growth_insights_worker raised ImportError on import: {exc}")
