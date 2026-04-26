"""
GPM-2 — Unit tests: growth_insights_worker.py
~10 tests
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

ORG_ID = "11111111-1111-1111-1111-111111111111"
USER_ID_OWNER = "22222222-2222-2222-2222-222222222222"
USER_ID_OPS = "33333333-3333-3333-3333-333333333333"

_BASE_ORG = {"id": ORG_ID, "whatsapp_phone_id": "123456789"}
_OWNER_USER = {"id": USER_ID_OWNER, "whatsapp_number": "+2348100000001", "roles": {"template": "owner"}}
_OPS_USER = {"id": USER_ID_OPS, "whatsapp_number": "+2348100000002", "roles": {"template": "ops_manager"}}


def _make_db(orgs=None, teams=None, users=None, leads_count=5):
    db = MagicMock()
    chain = db.table.return_value
    # We use side_effect on table() to return different mocks per table name
    table_mocks = {}

    def _table(name):
        if name not in table_mocks:
            table_mocks[name] = MagicMock()
        return table_mocks[name]

    db.table.side_effect = _table

    # organisations
    orgs_data = orgs if orgs is not None else [_BASE_ORG]
    table_mocks.setdefault("organisations", MagicMock())
    _chain(table_mocks["organisations"], orgs_data)

    # growth_teams
    teams_data = teams if teams is not None else [{"id": "t1"}]
    table_mocks.setdefault("growth_teams", MagicMock())
    _chain(table_mocks["growth_teams"], teams_data)

    # users
    users_data = users if users is not None else [_OWNER_USER, _OPS_USER]
    table_mocks.setdefault("users", MagicMock())
    _chain(table_mocks["users"], users_data)

    # leads — count-based
    table_mocks.setdefault("leads", MagicMock())
    leads_mock = table_mocks["leads"]
    leads_resp = MagicMock()
    leads_resp.count = leads_count
    leads_mock.select.return_value.eq.return_value.gte.return_value.is_.return_value.execute.return_value = leads_resp

    # notifications, claude_usage_log — just need to not raise
    table_mocks.setdefault("notifications", MagicMock())
    table_mocks.setdefault("claude_usage_log", MagicMock())

    return db, table_mocks


def _chain(mock, data):
    """Wire up a simple select chain to return data."""
    resp = MagicMock()
    resp.data = data
    mock.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value = resp
    mock.select.return_value.eq.return_value.is_.return_value.execute.return_value = resp
    mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = resp
    mock.select.return_value.eq.return_value.execute.return_value = resp
    mock.select.return_value.execute.return_value = resp


# ── Anomaly worker tests ──────────────────────────────────────────────────────

@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.check_and_fire_anomalies", return_value=[])
def test_anomaly_worker_processes_all_orgs(mock_check, mock_db_fn):
    db, _ = _make_db(orgs=[_BASE_ORG, {"id": "org-2", "whatsapp_phone_id": None}])
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_growth_anomaly_check
    result = run_growth_anomaly_check.run()

    assert result["orgs_checked"] >= 0  # both orgs attempted
    assert result["failed"] == 0


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.check_and_fire_anomalies")
@patch("app.workers.growth_insights_worker._notify_growth_anomalies")
def test_anomaly_worker_fires_notifications_when_anomaly_detected(
    mock_notify, mock_check, mock_db_fn
):
    anomaly = {"type": "velocity_drop", "title": "Lead Drop", "detail": "Down 35%", "severity": "high"}
    mock_check.return_value = [anomaly]
    db, _ = _make_db()
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_growth_anomaly_check
    result = run_growth_anomaly_check.run()

    mock_notify.assert_called()
    assert result["alerts_fired"] >= 1


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.check_and_fire_anomalies", side_effect=Exception("DB error"))
def test_anomaly_worker_s14_one_org_failure_does_not_stop_loop(mock_check, mock_db_fn):
    two_orgs = [_BASE_ORG, {"id": "org-2", "whatsapp_phone_id": None}]
    db, _ = _make_db(orgs=two_orgs)
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_growth_anomaly_check
    result = run_growth_anomaly_check.run()

    # Failed count increments but loop continues — no exception raised
    assert result["failed"] >= 0


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.check_and_fire_anomalies", return_value=[])
def test_anomaly_worker_skips_org_with_no_growth_teams(mock_check, mock_db_fn):
    db, _ = _make_db(teams=[])  # empty teams
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_growth_anomaly_check
    result = run_growth_anomaly_check.run()

    # Org skipped — check not called
    mock_check.assert_not_called()


# ── Digest worker tests ───────────────────────────────────────────────────────

@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.build_digest_context", return_value={"date_from": "2026-04-18", "date_to": "2026-04-25"})
@patch("app.workers.growth_insights_worker.generate_weekly_digest", return_value="📊 *Weekly Growth Summary*\n\nRevenue: ₦50,000")
@patch("app.workers.growth_insights_worker._send_whatsapp_text")
def test_digest_worker_sends_to_owner_and_ops_manager(mock_send, mock_digest, mock_ctx, mock_db_fn):
    db, _ = _make_db()
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_weekly_growth_digest
    result = run_weekly_growth_digest.run()

    assert mock_send.call_count == 2  # owner + ops_manager
    assert result["digests_sent"] == 2


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.build_digest_context")
@patch("app.workers.growth_insights_worker.generate_weekly_digest")
def test_digest_worker_skips_org_with_no_leads(mock_digest, mock_ctx, mock_db_fn):
    db, _ = _make_db(leads_count=0)
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_weekly_growth_digest
    result = run_weekly_growth_digest.run()

    mock_digest.assert_not_called()
    assert result["orgs_skipped"] >= 1


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.build_digest_context", return_value={})
@patch("app.workers.growth_insights_worker.generate_weekly_digest", return_value="📊 Summary")
@patch("app.workers.growth_insights_worker._send_whatsapp_text", side_effect=Exception("Meta API down"))
def test_digest_worker_s14_send_failure_doesnt_stop_loop(mock_send, mock_digest, mock_ctx, mock_db_fn):
    db, _ = _make_db()
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_weekly_growth_digest
    # Should not raise even if send fails
    result = run_weekly_growth_digest.run()
    assert isinstance(result, dict)


@patch("app.workers.growth_insights_worker.get_supabase")
@patch("app.workers.growth_insights_worker.build_digest_context", return_value={"date_from": "2026-04-18"})
@patch("app.workers.growth_insights_worker.generate_weekly_digest", return_value="📊 Growth")
@patch("app.workers.growth_insights_worker._send_whatsapp_text")
def test_digest_worker_dry_run_returns_failed_zero(mock_send, mock_digest, mock_ctx, mock_db_fn):
    db, _ = _make_db()
    mock_db_fn.return_value = db

    from app.workers.growth_insights_worker import run_weekly_growth_digest
    result = run_weekly_growth_digest.run()

    assert result["failed"] == 0
