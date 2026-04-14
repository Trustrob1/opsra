"""
tests/unit/test_lead_graduation_worker.py
Unit tests for app/workers/lead_graduation_worker.py — M01-10a
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

ORG_ID   = "00000000-0000-0000-0000-000000000001"
LEAD_ID  = "00000000-0000-0000-0000-000000000002"
LEAD_ID2 = "00000000-0000-0000-0000-000000000005"
USER_ID  = "00000000-0000-0000-0000-000000000003"


def _make_db(orgs=None, leads=None):
    """Factory for a mock DB that returns specified orgs + leads."""
    db     = MagicMock()
    chain  = MagicMock()
    chain.execute.return_value = MagicMock(data=[])

    for method in (
        "select", "insert", "update", "eq", "neq", "in_", "is_",
        "gte", "lte", "order", "limit", "maybe_single",
    ):
        getattr(chain, method).return_value = chain

    call_count = [0]
    responses  = []
    if orgs  is not None: responses.append(MagicMock(data=orgs))
    if leads is not None: responses.append(MagicMock(data=leads))

    def _execute():
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return responses[idx]
        return MagicMock(data=[])

    chain.execute.side_effect = _execute
    db.table.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Worker tests
# ---------------------------------------------------------------------------

@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_graduates_stale_lead(mock_activity, mock_graduate, mock_get_db):
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 14,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [{"id": LEAD_ID, "stage": "contacted", "assigned_to": USER_ID,
              "nurture_track": False, "first_contacted_at": "2026-03-01T00:00:00+00:00"}]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = False
    mock_graduate.return_value = {"graduated": True, "reason": "lead_unresponsive"}

    result = run_lead_graduation_check()

    assert result["graduated"] == 1
    assert result["failed"] == 0
    # Verify reason was computed and passed
    call_kwargs = mock_graduate.call_args[1]
    assert call_kwargs["graduation_reason"] == "lead_unresponsive"


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_reason_no_contact_when_never_contacted(mock_activity, mock_graduate, mock_get_db):
    """assigned but first_contacted_at is NULL → reason should be no_contact."""
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 14,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [{"id": LEAD_ID, "stage": "new", "assigned_to": USER_ID,
              "nurture_track": False, "first_contacted_at": None}]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = False
    mock_graduate.return_value = {"graduated": True, "reason": "no_contact"}

    run_lead_graduation_check()

    call_kwargs = mock_graduate.call_args[1]
    assert call_kwargs["graduation_reason"] == "no_contact"


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_reason_unassigned_when_no_rep(mock_activity, mock_graduate, mock_get_db):
    """assigned_to is NULL → reason should be unassigned."""
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 14,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [{"id": LEAD_ID, "stage": "new", "assigned_to": None,
              "nurture_track": False, "first_contacted_at": None}]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = False
    mock_graduate.return_value = {"graduated": True, "reason": "unassigned"}

    run_lead_graduation_check()

    call_kwargs = mock_graduate.call_args[1]
    assert call_kwargs["graduation_reason"] == "unassigned"


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_skips_lead_with_recent_human_activity(mock_activity, mock_graduate, mock_get_db):
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 14,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [{"id": LEAD_ID, "stage": "new", "assigned_to": None, "nurture_track": False, "first_contacted_at": None}]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = True  # recent activity → not stale

    result = run_lead_graduation_check()

    assert result["graduated"] == 0
    mock_graduate.assert_not_called()


@patch("app.workers.lead_graduation_worker.get_supabase")
def test_worker_skips_orgs_with_nurture_disabled(mock_get_db):
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    # DB returns empty orgs (nurture_track_enabled filter excluded them all)
    mock_get_db.return_value = _make_db(orgs=[], leads=[])

    result = run_lead_graduation_check()

    assert result["orgs_processed"] == 0
    assert result["graduated"] == 0


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_s14_one_lead_failure_doesnt_stop_loop(mock_activity, mock_graduate, mock_get_db):
    """S14 — failed lead increments failed count but loop continues."""
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 14,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [
        {"id": LEAD_ID,  "stage": "new", "assigned_to": None, "nurture_track": False, "first_contacted_at": None},
        {"id": LEAD_ID2, "stage": "new", "assigned_to": None, "nurture_track": False, "first_contacted_at": None},
    ]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = False
    mock_graduate.side_effect = [Exception("DB error"), {"graduated": True}]

    result = run_lead_graduation_check()

    assert result["failed"]    == 1
    assert result["graduated"] == 1


@patch("app.workers.lead_graduation_worker.get_supabase")
def test_worker_returns_failed_1_when_org_load_fails(mock_get_db):
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    db    = MagicMock()
    chain = MagicMock()
    chain.execute.side_effect = Exception("connection error")
    for m in ("select", "eq"):
        getattr(chain, m).return_value = chain
    db.table.return_value = chain
    mock_get_db.return_value = db

    result = run_lead_graduation_check()

    assert result["failed"] == 1
    assert result["orgs_processed"] == 0


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_uses_org_conversion_attempt_days(mock_activity, mock_graduate, mock_get_db):
    """Worker passes the org's conversion_attempt_days to the activity check."""
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    orgs  = [{"id": ORG_ID, "nurture_track_enabled": True, "conversion_attempt_days": 21,
              "nurture_sequence": [{"mode": "custom", "template": "Hi {{name}}"}]}]
    leads = [{"id": LEAD_ID, "stage": "demo_done", "assigned_to": None, "nurture_track": False, "first_contacted_at": None}]

    mock_get_db.return_value = _make_db(orgs=orgs, leads=leads)
    mock_activity.return_value = False
    mock_graduate.return_value = {"graduated": True, "reason": "lead_unresponsive"}

    run_lead_graduation_check()

    _, args, kwargs = mock_activity.mock_calls[0]
    days_arg = args[2] if len(args) > 2 else kwargs.get("days")
    assert days_arg == 21


@patch("app.workers.lead_graduation_worker.get_supabase")
@patch("app.workers.lead_graduation_worker.graduate_stale_lead")
@patch("app.workers.lead_graduation_worker.check_human_activity_since")
def test_worker_summary_keys_present(mock_activity, mock_graduate, mock_get_db):
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    mock_get_db.return_value = _make_db(orgs=[], leads=[])

    result = run_lead_graduation_check()

    for key in ("orgs_processed", "leads_checked", "graduated", "failed"):
        assert key in result


# ---------------------------------------------------------------------------
# Worker dry-run (pattern — no real DB / network)
# ---------------------------------------------------------------------------

@patch("app.workers.lead_graduation_worker.get_supabase")
def test_worker_dry_run_no_network_calls(mock_get_db):
    """Ensure worker can run with empty data without hitting real DB."""
    from app.workers.lead_graduation_worker import run_lead_graduation_check

    mock_get_db.return_value = _make_db(orgs=[], leads=[])
    result = run_lead_graduation_check()

    assert result["failed"] == 0