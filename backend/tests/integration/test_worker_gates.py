# tests/integration/test_worker_gates.py
# 9E-D — Integration tests for business logic gates applied in workers.
#
# D1 (subscription gating): tested via renewal_worker.send_renewal_reminders
#     — simplest worker with a direct return dict and no bind=True.
# D2 (quiet hours): tested via nps_worker.run_nps_scheduler
# D3 (daily limit): tested via nps_worker.run_nps_scheduler
#
# Pattern: direct function call (not .apply()) for non-bind tasks.
# Pattern 33: Python-side filtering — mocks return full data, worker filters.
# T2: db.table.side_effect used throughout — never mix with return_value.
# S14: gate failures never raise — they skip/hold and continue.

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ── Shared constants ──────────────────────────────────────────────────────────

ORG_ID      = "org-gate-test-001"
CUSTOMER_ID = "cust-gate-test-001"
USER_ID     = "user-gate-test-001"

_ACTIVE_ORG = {
    "id":                           ORG_ID,
    "subscription_status":          "active",
    "quiet_hours_start":            None,
    "quiet_hours_end":              None,
    "timezone":                     "Africa/Lagos",
    "daily_customer_message_limit": 3,
}

_SUSPENDED_ORG = {
    **_ACTIVE_ORG,
    "subscription_status": "suspended",
}

_GRACE_ORG = {
    **_ACTIVE_ORG,
    "subscription_status": "grace",
}

_QUIET_ORG = {
    **_ACTIVE_ORG,
    "quiet_hours_start": "22:00:00",
    "quiet_hours_end":   "06:00:00",
    "timezone":          "Africa/Lagos",
}

_CUSTOMER = {
    "id":               CUSTOMER_ID,
    "full_name":        "Test Customer",
    "whatsapp":         "+2348012345678",
    "phone":            "+2348012345678",
    "last_nps_sent_at": None,
    "nps_event_sent_at": None,
}


# ── DB mock helpers ───────────────────────────────────────────────────────────

def _make_nps_db(org_row, customers=None, message_count=0):
    """
    Build a Supabase mock for nps_worker.run_nps_scheduler.
    Tracks whatsapp_messages inserts in a shared list.
    """
    inserts    = []
    customers  = customers if customers is not None else [_CUSTOMER]

    db = MagicMock()

    def table_side(name):
        tbl = MagicMock()

        sel = MagicMock()
        sel.select        = MagicMock(return_value=sel)
        sel.eq            = MagicMock(return_value=sel)
        sel.gte           = MagicMock(return_value=sel)
        sel.maybe_single  = MagicMock(return_value=sel)

        if name == "organisations":
            sel.execute = MagicMock(
                return_value=MagicMock(data=[org_row])
            )
        elif name == "customers":
            sel.execute = MagicMock(
                return_value=MagicMock(data=customers)
            )
        elif name == "whatsapp_messages":
            # D3: count query for has_exceeded_daily_limit
            mock_result       = MagicMock()
            mock_result.count = message_count
            mock_result.data  = []
            sel.execute       = MagicMock(return_value=mock_result)
        else:
            sel.execute = MagicMock(return_value=MagicMock(data=[]))

        tbl.select.return_value = sel

        # Capture inserts (whatsapp_messages + customers update)
        def capture_insert(data):
            ins = MagicMock()
            ins.execute.return_value = None
            inserts.append({"table": name, "data": data})
            return ins
        tbl.insert.side_effect = capture_insert

        upd = MagicMock()
        upd.eq.return_value      = upd
        upd.execute.return_value = MagicMock(data={})
        tbl.update.return_value  = upd

        return tbl

    db.table.side_effect = table_side
    db._inserts = inserts   # expose for assertions
    return db


def _make_renewal_db(org_rows):
    """Build a minimal Supabase mock for renewal_worker.send_renewal_reminders."""
    db = MagicMock()

    def table_side(name):
        tbl = MagicMock()
        sel = MagicMock()
        sel.select        = MagicMock(return_value=sel)
        sel.eq            = MagicMock(return_value=sel)
        sel.in_           = MagicMock(return_value=sel)
        sel.lt            = MagicMock(return_value=sel)
        sel.maybe_single  = MagicMock(return_value=sel)

        if name == "organisations":
            sel.execute = MagicMock(return_value=MagicMock(data=org_rows))
        elif name == "subscriptions":
            sel.execute = MagicMock(return_value=MagicMock(data=[]))
        elif name == "org_settings":
            sel.execute = MagicMock(return_value=MagicMock(data=None))
        else:
            sel.execute = MagicMock(return_value=MagicMock(data=[]))

        tbl.select.return_value  = sel
        tbl.update.return_value  = MagicMock(
            eq=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=None)
            ))
        )
        return tbl

    db.table.side_effect = table_side
    return db


# ═══════════════════════════════════════════════════════════════════════════════
# D1 — Subscription gating
# ═══════════════════════════════════════════════════════════════════════════════

class TestD1SubscriptionGating:

    def test_suspended_org_skipped_by_renewal_worker(self):
        """D1: suspended org must be skipped — skipped_inactive incremented."""
        db = _make_renewal_db(org_rows=[_SUSPENDED_ORG])

        with patch("app.workers.renewal_worker.get_supabase", return_value=db):
            from app.workers.renewal_worker import send_renewal_reminders
            result = send_renewal_reminders()

        assert result["skipped_inactive"] == 1
        assert result["processed"] == 0
        assert result["reminded"] == 0

    def test_read_only_org_skipped_by_renewal_worker(self):
        """D1: read_only org must also be skipped."""
        read_only_org = {**_ACTIVE_ORG, "subscription_status": "read_only"}
        db = _make_renewal_db(org_rows=[read_only_org])

        with patch("app.workers.renewal_worker.get_supabase", return_value=db):
            from app.workers.renewal_worker import send_renewal_reminders
            result = send_renewal_reminders()

        assert result["skipped_inactive"] == 1

    def test_grace_org_proceeds_in_renewal_worker(self):
        """D1: grace period org must proceed (is_org_active returns True for grace)."""
        db = _make_renewal_db(org_rows=[_GRACE_ORG])

        with patch("app.workers.renewal_worker.get_supabase", return_value=db):
            from app.workers.renewal_worker import send_renewal_reminders
            result = send_renewal_reminders()

        assert result["skipped_inactive"] == 0

    def test_active_org_proceeds_in_renewal_worker(self):
        """D1: active org must not be skipped."""
        db = _make_renewal_db(org_rows=[_ACTIVE_ORG])

        with patch("app.workers.renewal_worker.get_supabase", return_value=db):
            from app.workers.renewal_worker import send_renewal_reminders
            result = send_renewal_reminders()

        assert result["skipped_inactive"] == 0

    def test_suspended_org_skipped_by_nps_worker(self):
        """D1: suspended org skipped in nps_worker — no whatsapp_messages insert."""
        db = _make_nps_db(org_row=_SUSPENDED_ORG)

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts == [], (
            f"Expected no whatsapp_messages inserts for suspended org, got: {wa_inserts}"
        )

    def test_multiple_orgs_only_suspended_skipped(self):
        """D1: with mixed orgs, only suspended is skipped."""
        db = _make_renewal_db(org_rows=[_SUSPENDED_ORG, _ACTIVE_ORG])

        with patch("app.workers.renewal_worker.get_supabase", return_value=db):
            from app.workers.renewal_worker import send_renewal_reminders
            result = send_renewal_reminders()

        assert result["skipped_inactive"] == 1  # only the suspended one


# ═══════════════════════════════════════════════════════════════════════════════
# D2 — Quiet hours enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestD2QuietHours:

    def test_message_held_during_quiet_hours(self):
        """
        D2: when quiet hours are active, whatsapp_messages insert must have
        quiet_hours_held=True and send_after set.
        """
        db = _make_nps_db(org_row=_QUIET_ORG)

        # 23:00 UTC = 00:00 Lagos (UTC+1) — inside 22:00–06:00 window
        now_inside = datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc)

        with (
            patch("app.workers.nps_worker.get_supabase", return_value=db),
            patch("app.workers.nps_worker.datetime") as mock_dt,
        ):
            mock_dt.now.return_value     = now_inside
            mock_dt.now.side_effect      = None
            mock_dt.utcnow               = datetime.utcnow
            mock_dt.fromisoformat        = datetime.fromisoformat
            mock_dt.side_effect          = lambda *a, **kw: datetime(*a, **kw)

            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts, "Expected at least one whatsapp_messages insert"
        insert_data = wa_inserts[0]["data"]
        assert insert_data.get("quiet_hours_held") is True, (
            f"Expected quiet_hours_held=True, got: {insert_data}"
        )
        assert insert_data.get("send_after") is not None, (
            f"Expected send_after to be set, got: {insert_data}"
        )

    def test_message_sent_outside_quiet_hours(self):
        """
        D2: outside quiet hours, message must be sent immediately —
        quiet_hours_held must be absent or False, send_after must be None.
        """
        db = _make_nps_db(org_row=_QUIET_ORG)

        # 10:00 UTC = 11:00 Lagos — outside 22:00–06:00 window
        now_outside = datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc)

        with (
            patch("app.workers.nps_worker.get_supabase", return_value=db),
            patch("app.workers.nps_worker.datetime") as mock_dt,
        ):
            mock_dt.now.return_value  = now_outside
            mock_dt.now.side_effect   = None
            mock_dt.utcnow            = datetime.utcnow
            mock_dt.fromisoformat     = datetime.fromisoformat
            mock_dt.side_effect       = lambda *a, **kw: datetime(*a, **kw)

            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts, "Expected at least one whatsapp_messages insert"
        insert_data = wa_inserts[0]["data"]
        assert not insert_data.get("quiet_hours_held"), (
            f"Expected quiet_hours_held to be falsy outside quiet hours, got: {insert_data}"
        )
        assert insert_data.get("send_after") is None, (
            f"Expected send_after=None outside quiet hours, got: {insert_data}"
        )

    def test_no_quiet_hours_configured_sends_immediately(self):
        """D2: org with no quiet hours configured must send immediately."""
        db = _make_nps_db(org_row=_ACTIVE_ORG)  # no quiet_hours_start/end

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts, "Expected whatsapp_messages insert"
        assert not wa_inserts[0]["data"].get("quiet_hours_held")
        assert wa_inserts[0]["data"].get("send_after") is None


# ═══════════════════════════════════════════════════════════════════════════════
# D3 — Daily customer message limit
# ═══════════════════════════════════════════════════════════════════════════════

class TestD3DailyLimit:

    def test_customer_skipped_when_daily_limit_reached(self):
        """
        D3: customer who has already hit the daily limit must be skipped —
        no whatsapp_messages insert.
        """
        # message_count=3 means customer has already hit the default limit of 3
        db = _make_nps_db(org_row=_ACTIVE_ORG, message_count=3)

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts == [], (
            f"Expected no inserts when daily limit reached, got: {wa_inserts}"
        )

    def test_customer_sent_when_under_daily_limit(self):
        """D3: customer under daily limit must receive the message."""
        # message_count=2 — under default limit of 3
        db = _make_nps_db(org_row=_ACTIVE_ORG, message_count=2)

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts, "Expected whatsapp_messages insert when under limit"

    def test_org_configured_limit_respected(self):
        """D3: org-configured limit of 1 must be enforced — skip after 1 message."""
        org_with_limit_1 = {**_ACTIVE_ORG, "daily_customer_message_limit": 1}
        # message_count=1 means already at the org limit
        db = _make_nps_db(org_row=org_with_limit_1, message_count=1)

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts == [], (
            f"Expected no inserts when org limit of 1 reached, got: {wa_inserts}"
        )

    def test_system_ceiling_enforced(self):
        """D3: org configured limit above 20 must be clamped to ceiling of 20."""
        org_above_ceiling = {**_ACTIVE_ORG, "daily_customer_message_limit": 99}
        # message_count=20 — at system ceiling
        db = _make_nps_db(org_row=org_above_ceiling, message_count=20)

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts == [], (
            f"Expected no inserts — system ceiling of 20 must be enforced, "
            f"got: {wa_inserts}"
        )

    def test_db_error_in_limit_check_allows_send(self):
        """
        D3 S14: if has_exceeded_daily_limit raises, message must still be sent.
        A config/DB error must never silently block customers.
        """
        db = _make_nps_db(org_row=_ACTIVE_ORG)

        # Make the whatsapp_messages count query raise
        original_side = db.table.side_effect

        def table_side_with_error(name):
            tbl = original_side(name)
            if name == "whatsapp_messages":
                sel = MagicMock()
                sel.select       = MagicMock(return_value=sel)
                sel.eq           = MagicMock(return_value=sel)
                sel.gte          = MagicMock(return_value=sel)
                sel.execute      = MagicMock(side_effect=Exception("DB error"))
                tbl.select.return_value = sel
            return tbl

        db.table.side_effect = table_side_with_error

        with patch("app.workers.nps_worker.get_supabase", return_value=db):
            from app.workers.nps_worker import run_nps_scheduler
            run_nps_scheduler.apply()

        wa_inserts = [
            i for i in db._inserts
            if i["table"] == "whatsapp_messages"
        ]
        assert wa_inserts, (
            "S14: DB error in limit check must not block send — "
            f"expected insert, got none. Inserts: {db._inserts}"
        )
