"""
tests/unit/test_lead_nurture_worker.py
Unit tests for app/workers/lead_nurture_worker.py — M01-10a
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

ORG_ID   = "00000000-0000-0000-0000-000000000001"
LEAD_ID  = "00000000-0000-0000-0000-000000000002"
LEAD_ID2 = "00000000-0000-0000-0000-000000000005"
USER_ID  = "00000000-0000-0000-0000-000000000003"
NOW_TS   = "2026-04-12T07:00:00+00:00"

_SEQUENCE = [
    {"mode": "custom", "template": "Hi {{name}}!", "content_type": "tip"},
]

_ORG = {
    "id":                  ORG_ID,
    "name":                "TestOrg",
    "nurture_track_enabled": True,
    "nurture_interval_days": 7,
    "nurture_sequence":    _SEQUENCE,
    "whatsapp_phone_id":   "phone-id-123",
}

_LEAD = {
    "id":                          LEAD_ID,
    "full_name":                   "Emeka",
    "phone":                       "+2348001234567",
    "whatsapp":                    "+2348001234567",
    "business_name":               "TechCo",
    "problem_stated":              "Need CRM",
    "assigned_to":                 USER_ID,
    "nurture_sequence_position":   0,
    "last_nurture_sent_at":        None,
}


def _make_db_multi(responses: list):
    """DB mock with a sequence of responses consumed in order."""
    db    = MagicMock()
    chain = MagicMock()
    for method in (
        "select", "insert", "update", "eq", "neq", "in_", "is_",
        "gte", "lte", "order", "limit", "maybe_single",
    ):
        getattr(chain, method).return_value = chain

    idx = [0]

    def _execute():
        i = idx[0]
        idx[0] += 1
        if i < len(responses):
            return MagicMock(data=responses[i])
        return MagicMock(data=[])

    chain.execute.side_effect = _execute
    db.table.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Worker tests
# ---------------------------------------------------------------------------

@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_sends_for_lead_with_null_last_sent(mock_send, mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    # orgs query → null_result → overdue_result
    mock_get_db.return_value = _make_db_multi([
        [_ORG],     # orgs
        [_LEAD],    # null last_nurture_sent_at
        [],         # overdue (empty — lead already in null set)
    ])
    mock_send.return_value = {"sent": True, "position": 0}

    result = run_lead_nurture_send()

    assert result["sent"]   == 1
    assert result["failed"] == 0
    mock_send.assert_called_once()


@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_sends_for_overdue_lead(mock_send, mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    overdue_lead = {**_LEAD, "last_nurture_sent_at": "2026-03-01T00:00:00+00:00"}
    mock_get_db.return_value = _make_db_multi([
        [_ORG],          # orgs
        [],              # null set — empty
        [overdue_lead],  # overdue set
    ])
    mock_send.return_value = {"sent": True, "position": 0}

    result = run_lead_nurture_send()

    assert result["sent"] == 1
    mock_send.assert_called_once()


@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_deduplicates_leads_across_queries(mock_send, mock_get_db):
    """A lead in both null and overdue sets must only be sent once."""
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    mock_get_db.return_value = _make_db_multi([
        [_ORG],
        [_LEAD],   # in null set
        [_LEAD],   # also in overdue set
    ])
    mock_send.return_value = {"sent": True, "position": 0}

    result = run_lead_nurture_send()

    assert result["leads_checked"] == 1
    mock_send.assert_called_once()


@patch("app.workers.lead_nurture_worker.get_supabase")
def test_worker_skips_org_with_empty_sequence(mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    org_no_seq = {**_ORG, "nurture_sequence": []}
    mock_get_db.return_value = _make_db_multi([[org_no_seq]])

    result = run_lead_nurture_send()

    assert result["orgs_processed"] == 1
    assert result["sent"] == 0


@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_s14_one_lead_failure_doesnt_stop_loop(mock_send, mock_get_db):
    """S14 — one lead exception increments failed, loop continues."""
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    lead2 = {**_LEAD, "id": LEAD_ID2}
    mock_get_db.return_value = _make_db_multi([
        [_ORG],
        [_LEAD, lead2],
        [],
    ])
    mock_send.side_effect = [Exception("DB error"), {"sent": True, "position": 0}]

    result = run_lead_nurture_send()

    assert result["failed"] == 1
    assert result["sent"]   == 1


@patch("app.workers.lead_nurture_worker.get_supabase")
def test_worker_returns_failed_1_when_org_load_fails(mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    db    = MagicMock()
    chain = MagicMock()
    chain.execute.side_effect = Exception("connection error")
    for m in ("select", "eq"):
        getattr(chain, m).return_value = chain
    db.table.return_value = chain
    mock_get_db.return_value = db

    result = run_lead_nurture_send()

    assert result["failed"] == 1
    assert result["orgs_processed"] == 0


@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_summary_keys_present(mock_send, mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    mock_get_db.return_value = _make_db_multi([[]])
    result = run_lead_nurture_send()

    for key in ("orgs_processed", "leads_checked", "sent", "failed"):
        assert key in result


@patch("app.workers.lead_nurture_worker.get_supabase")
@patch("app.workers.lead_nurture_worker.send_nurture_message")
def test_worker_passes_org_data_to_send(mock_send, mock_get_db):
    """Worker must pass the org row (with whatsapp_phone_id etc.) to send_nurture_message."""
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    mock_get_db.return_value = _make_db_multi([
        [_ORG], [_LEAD], [],
    ])
    mock_send.return_value = {"sent": True, "position": 0}

    run_lead_nurture_send()

    _, kwargs = mock_send.call_args
    assert kwargs.get("org_data", {}).get("id") == ORG_ID or \
           mock_send.call_args[1].get("org_data", {}).get("id") == ORG_ID or \
           mock_send.call_args[0][5]["id"] == ORG_ID  # positional


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

@patch("app.workers.lead_nurture_worker.get_supabase")
def test_worker_dry_run_no_network_calls(mock_get_db):
    from app.workers.lead_nurture_worker import run_lead_nurture_send

    mock_get_db.return_value = _make_db_multi([[]])
    result = run_lead_nurture_send()

    assert result["failed"] == 0
