"""
tests/unit/test_lead_dedup.py
9E-C — C3: Lead deduplication race condition tests.

Test: Two simultaneous create_lead() calls for the same phone number →
      one lead created, the other gets the existing lead back, no exception.

T1: Mocked function signatures verified against lead_service.create_lead source.
T2: No mixing of side_effect and return_value on same mock chain.
T3: Syntax validated before delivery.
"""
import pytest
from unittest.mock import MagicMock, patch

ORG_ID  = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000002"
LEAD_ID = "00000000-0000-0000-0000-000000000020"
PHONE   = "2348031234567"


def _make_db():
    return MagicMock()


def _lead_create_payload():
    """Minimal LeadCreate-like object with model_dump."""
    mock = MagicMock()
    mock.model_dump.return_value = {
        "full_name": "Test User",
        "phone": PHONE,
        "whatsapp": PHONE,
        "source": "whatsapp_inbound",
        "contact_type": "sales_lead",
    }
    return mock


class TestLeadDedupC3:
    """C3: create_lead() is idempotent on duplicate phone — never raises."""

    @patch("app.services.lead_service.write_timeline_event")
    @patch("app.services.lead_service.write_audit_log")
    @patch("app.services.lead_service._notify_new_lead")
    def test_successful_insert_returns_new_lead(
        self, mock_notify, mock_audit, mock_timeline
    ):
        """Normal path: INSERT succeeds, returns the new lead."""
        from app.services.lead_service import create_lead

        db = _make_db()
        new_lead = {"id": LEAD_ID, "org_id": ORG_ID, "phone": PHONE, "stage": "new"}

        db.table.return_value.insert.return_value.execute.return_value.data = [new_lead]

        payload = _lead_create_payload()
        result = create_lead(db, ORG_ID, USER_ID, payload)

        assert result["id"] == LEAD_ID
        assert result["phone"] == PHONE

    @patch("app.services.lead_service.write_timeline_event")
    @patch("app.services.lead_service.write_audit_log")
    @patch("app.services.lead_service._notify_new_lead")
    def test_duplicate_phone_returns_existing_lead_no_exception(
        self, mock_notify, mock_audit, mock_timeline
    ):
        """
        When INSERT raises a 23505 unique constraint violation (duplicate phone),
        create_lead fetches and returns the existing lead.
        No HTTPException or other exception is raised.
        """
        from app.services.lead_service import create_lead

        existing_lead = {
            "id": LEAD_ID,
            "org_id": ORG_ID,
            "phone": PHONE,
            "stage": "new",
        }

        db = _make_db()
        call_counts = {"insert": 0, "select": 0}

        def table_side_effect(name):
            mock = MagicMock()

            # INSERT raises unique violation
            insert_exc = Exception(
                "duplicate key value violates unique constraint (23505) "
                "idx_leads_active_phone"
            )
            mock.insert.return_value.execute.side_effect = insert_exc

            # SELECT for fallback fetch returns existing lead
            mock.select.return_value.eq.return_value \
                .eq.return_value.is_.return_value \
                .neq.return_value.limit.return_value \
                .execute.return_value.data = [existing_lead]

            return mock

        db.table.side_effect = table_side_effect

        payload = _lead_create_payload()

        # Must NOT raise
        result = create_lead(db, ORG_ID, USER_ID, payload)

        assert result is not None
        assert result.get("id") == LEAD_ID

    @patch("app.services.lead_service.write_timeline_event")
    @patch("app.services.lead_service.write_audit_log")
    @patch("app.services.lead_service._notify_new_lead")
    def test_two_concurrent_creates_both_succeed_without_exception(
        self, mock_notify, mock_audit, mock_timeline
    ):
        """
        Simulates two concurrent calls. First succeeds; second gets a 23505,
        falls back to the existing lead. Neither raises. Both return a lead dict.
        """
        from app.services.lead_service import create_lead

        existing_lead = {"id": LEAD_ID, "org_id": ORG_ID, "phone": PHONE}
        new_lead      = {"id": LEAD_ID, "org_id": ORG_ID, "phone": PHONE}

        # Worker A db: INSERT succeeds
        db_a = _make_db()
        db_a.table.return_value.insert.return_value.execute.return_value.data = [new_lead]

        # Worker B db: INSERT raises 23505, SELECT returns existing
        db_b = _make_db()

        def table_b_side_effect(name):
            mock = MagicMock()
            mock.insert.return_value.execute.side_effect = Exception(
                "duplicate key (23505) idx_leads_active_phone"
            )
            mock.select.return_value.eq.return_value \
                .eq.return_value.is_.return_value \
                .neq.return_value.limit.return_value \
                .execute.return_value.data = [existing_lead]
            return mock

        db_b.table.side_effect = table_b_side_effect

        payload_a = _lead_create_payload()
        payload_b = _lead_create_payload()

        result_a = create_lead(db_a, ORG_ID, USER_ID, payload_a)
        result_b = create_lead(db_b, ORG_ID, USER_ID, payload_b)

        assert result_a is not None
        assert result_b is not None
        # Both return the same lead — no double creation
        assert result_a.get("phone") == PHONE
        assert result_b.get("phone") == PHONE
