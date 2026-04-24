"""
tests/unit/test_lead_service_utm_ad.py
GPM-1D — 4 unit tests for utm_ad param in create_lead().
"""
from unittest.mock import MagicMock, patch
import pytest

from app.models.leads import LeadCreate
from app.services import lead_service


def _make_db(existing_lead=None):
    """Build a minimal Supabase mock that passes duplicate check and inserts cleanly."""
    db = MagicMock()

    # Duplicate check — no existing leads
    dup_query = MagicMock()
    dup_query.select.return_value = dup_query
    dup_query.eq.return_value = dup_query
    dup_query.is_.return_value = dup_query
    dup_query.execute.return_value = MagicMock(data=[])

    # Insert — return a fake lead row
    insert_result = MagicMock()
    inserted_row = {
        "id": "lead-001", "org_id": "org-1", "full_name": "Test Lead",
        "stage": "new", "score": "unscored", "assigned_to": "user-1",
    }
    insert_result.data = [inserted_row]

    insert_chain = MagicMock()
    insert_chain.execute.return_value = insert_result
    db.table.return_value.insert.return_value = insert_chain

    # Queries that return empty (audit_log, timeline, notifications, users)
    generic_chain = MagicMock()
    generic_chain.select.return_value = generic_chain
    generic_chain.eq.return_value = generic_chain
    generic_chain.is_.return_value = generic_chain
    generic_chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = generic_chain
    db.table.return_value.insert.return_value = insert_chain

    return db, inserted_row


def _payload(**kwargs):
    defaults = dict(full_name="Test Lead", source="manual_referral")
    defaults.update(kwargs)
    return LeadCreate(**defaults)


# ---------------------------------------------------------------------------
# Test 1: utm_ad stored when provided
# ---------------------------------------------------------------------------

def test_utm_ad_stored_when_provided():
    db, _ = _make_db()
    inserted_data = {}

    def capture_insert(data):
        inserted_data.update(data)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{**data, "id": "lead-001", "stage": "new", "score": "unscored"}])
        return m

    db.table.return_value.insert.side_effect = capture_insert

    with patch.object(lead_service, "check_duplicate", return_value=False), \
         patch.object(lead_service, "_notify_new_lead"):
        lead_service.create_lead(
            db=db, org_id="org-1", user_id="user-1",
            payload=_payload(),
            utm_ad="ad_creative_001",
        )

    assert inserted_data.get("utm_ad") == "ad_creative_001"


# ---------------------------------------------------------------------------
# Test 2: utm_ad=None stored as null — no error
# ---------------------------------------------------------------------------

def test_utm_ad_none_stored_as_null():
    db, _ = _make_db()
    inserted_data = {}

    def capture_insert(data):
        inserted_data.update(data)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{**data, "id": "lead-002", "stage": "new", "score": "unscored"}])
        return m

    db.table.return_value.insert.side_effect = capture_insert

    with patch.object(lead_service, "check_duplicate", return_value=False), \
         patch.object(lead_service, "_notify_new_lead"):
        lead_service.create_lead(
            db=db, org_id="org-1", user_id="user-1",
            payload=_payload(),
            utm_ad=None,
        )

    # utm_ad should simply not be in the inserted data when None
    assert inserted_data.get("utm_ad") is None


# ---------------------------------------------------------------------------
# Test 3: existing callers passing no utm_ad kwarg → no regression
# ---------------------------------------------------------------------------

def test_existing_callers_no_utm_ad_kwarg_no_regression():
    """
    Callers that don't pass utm_ad at all should still work without error.
    utm_ad must not appear in the insert payload.
    """
    db, _ = _make_db()
    inserted_data = {}

    def capture_insert(data):
        inserted_data.update(data)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{**data, "id": "lead-003", "stage": "new", "score": "unscored"}])
        return m

    db.table.return_value.insert.side_effect = capture_insert

    with patch.object(lead_service, "check_duplicate", return_value=False), \
         patch.object(lead_service, "_notify_new_lead"):
        # Old-style call — no utm_ad kwarg
        result = lead_service.create_lead(
            db=db, org_id="org-1", user_id="user-1",
            payload=_payload(),
        )

    assert result is not None
    assert "utm_ad" not in inserted_data


# ---------------------------------------------------------------------------
# Test 4: first_touch_team immutability still works when utm_ad is present
# ---------------------------------------------------------------------------

def test_first_touch_team_immutable_when_utm_ad_present():
    db, _ = _make_db()
    inserted_data = {}

    def capture_insert(data):
        inserted_data.update(data)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{**data, "id": "lead-004", "stage": "new", "score": "unscored"}])
        return m

    db.table.return_value.insert.side_effect = capture_insert

    with patch.object(lead_service, "check_duplicate", return_value=False), \
         patch.object(lead_service, "_notify_new_lead"):
        lead_service.create_lead(
            db=db, org_id="org-1", user_id="user-1",
            payload=_payload(),
            source_team="team_a",
            utm_ad="ad_creative_xyz",
        )

    # Both fields written on first creation
    assert inserted_data.get("source_team") == "team_a"
    assert inserted_data.get("first_touch_team") == "team_a"
    assert inserted_data.get("utm_ad") == "ad_creative_xyz"
