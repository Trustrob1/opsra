"""
tests/integration/test_pre_qualification_routes.py
PRE-QUAL — Integration tests for the full routing decision in _handle_inbound_message.

Tests call _handle_inbound_message directly (not via HTTP) because the
WhatsApp webhook route dispatches to Celery (process_inbound_webhook.delay).
This is the correct integration boundary for this feature.

Run:
    pytest tests/integration/test_pre_qualification_routes.py -v
"""
import uuid
from unittest.mock import MagicMock, patch, call
import pytest

from app.routers.webhooks import _handle_inbound_message

ORG_ID   = str(uuid.uuid4())
LEAD_ID  = str(uuid.uuid4())
USER_ID  = str(uuid.uuid4())
PHONE    = "+2348012345678"
PHONE_ID = "phone_number_id_001"
NOW_TS   = "2026-05-08T00:00:00Z"


# ── DB factory ────────────────────────────────────────────────────────────────

def _make_db(
    lead_id=None,
    org_id=None,
    has_qual_session=False,
    is_pre_qualified=True,
    wa_sales_mode="human",
    shopify_connected=False,
):
    """
    Build a DB mock that simulates _handle_inbound_message's lookup path:
    - _lookup_record_by_phone returns (org_id, None, lead_id, user_id)
    - lead_qualification_sessions returns empty or a session row
    - organisations returns org config
    - leads returns lead data with/without populated mapped fields
    T2: side_effect only on db.table.
    """
    _lead_id = lead_id or LEAD_ID
    _org_id  = org_id  or ORG_ID
    db = MagicMock()

    def _table(name):
        chain = MagicMock()
        chain.select.return_value       = chain
        chain.eq.return_value           = chain
        chain.update.return_value       = chain
        chain.insert.return_value       = chain
        chain.limit.return_value        = chain
        chain.order.return_value        = chain
        chain.maybe_single.return_value = chain
        chain.in_.return_value          = chain
        chain.neq.return_value          = chain
        chain.gt.return_value           = chain
        chain.is_.return_value          = chain
        chain.execute.return_value      = MagicMock(data={})

        if name == "leads":
            chain.execute.return_value = MagicMock(data=[{
                "id":             _lead_id,
                "org_id":         _org_id,
                "whatsapp":       PHONE,
                "phone":          PHONE,
                "assigned_to":    USER_ID,
                "ai_paused":      False,
                "nurture_track":  False,
                "stage":          "new",
                "problem_stated": "Need mattresses" if is_pre_qualified else None,
                "business_type":  None,
                "full_name":      "John Doe",
                "deleted_at":     None,
            }])

        elif name == "customers":
            chain.execute.return_value = MagicMock(data=[])

        elif name == "customer_contacts":
            chain.execute.return_value = MagicMock(data=[])

        elif name == "organisations":
            chain.execute.return_value = MagicMock(data={
                "id":                    _org_id,
                "qualification_flow":    {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "problem_stated"},
                    ],
                    "opening_message": "Hi!",
                },
                "whatsapp_sales_mode":   wa_sales_mode,
                "shopify_connected":     shopify_connected,
                "unknown_contact_behavior": "qualify_immediately",
                "sales_mode":            "consultative",
                "whatsapp_triage_config": None,
                "whatsapp_phone_id":     PHONE_ID,
            })

        elif name == "lead_qualification_sessions":
            if has_qual_session:
                chain.execute.return_value = MagicMock(
                    data=[{"id": str(uuid.uuid4()), "ai_active": True}]
                )
            else:
                chain.execute.return_value = MagicMock(data=[])

        elif name == "whatsapp_messages":
            chain.execute.return_value = MagicMock(data=[])

        elif name == "whatsapp_sessions":
            chain.execute.return_value = MagicMock(data=None)

        return chain

    db.table.side_effect = _table
    return db


def _make_message(phone=PHONE, content="Hello"):
    return {
        "id":   str(uuid.uuid4()),
        "from": phone,
        "type": "text",
        "text": {"body": content},
    }


# ── Routing tests ─────────────────────────────────────────────────────────────

class TestPreQualRoutingDecision:

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=True)
    def test_pre_qualified_lead_routes_to_pre_qual_handler(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """
        Lead found by phone + pre-qualified + no existing qual session
        → _handle_pre_qualified_lead called, qualification bot NOT launched.
        """
        db = _make_db(is_pre_qualified=True, has_qual_session=False)

        with patch("app.routers.webhooks._handle_structured_qualification_turn") as mock_qual_turn:
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        mock_handle_pre_qual.assert_called_once()
        mock_qual_turn.assert_not_called()

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=False)
    def test_non_pre_qualified_lead_routes_to_qualification_bot(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """
        Lead found by phone + NOT pre-qualified + no existing qual session
        → qualification bot launched, _handle_pre_qualified_lead NOT called.
        """
        db = _make_db(is_pre_qualified=False, has_qual_session=False)

        with patch("app.routers.webhooks._handle_structured_qualification_turn") as mock_qual_turn:
            mock_qual_turn.return_value = None
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        mock_handle_pre_qual.assert_not_called()
        mock_qual_turn.assert_called_once()

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=True)
    def test_active_qualification_session_bypasses_pre_qual_check(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """
        Lead is pre-qualified BUT already has an active qualification session
        in progress → pre-qual check skipped, bot continues normally.
        """
        db = _make_db(is_pre_qualified=True, has_qual_session=True)

        with patch("app.routers.webhooks._handle_structured_qualification_turn") as mock_qual_turn:
            mock_qual_turn.return_value = None
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        mock_handle_pre_qual.assert_not_called()
        mock_qual_turn.assert_called_once()

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=True)
    def test_pre_qual_not_called_when_existing_session_present(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """
        Repeat message from pre-qualified lead: a handed_off session already exists
        (has_qual_session=True). Pre-qual handler must NOT fire again.
        """
        db = _make_db(is_pre_qualified=True, has_qual_session=True)

        with patch("app.routers.webhooks._handle_structured_qualification_turn") as mock_qual_turn:
            mock_qual_turn.return_value = None
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        mock_handle_pre_qual.assert_not_called()

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=True)
    def test_pre_qual_handler_receives_correct_arguments(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """_handle_pre_qualified_lead must be called with correct lead_id and org_id."""
        db = _make_db(is_pre_qualified=True, has_qual_session=False)

        with patch("app.routers.webhooks._handle_structured_qualification_turn"):
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        call_kwargs = mock_handle_pre_qual.call_args[1]
        assert call_kwargs["lead_id"]      == LEAD_ID
        assert call_kwargs["org_id"]       == ORG_ID
        assert call_kwargs["phone_number"] == PHONE.lstrip("+")

    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified", return_value=True)
    def test_pre_qual_returns_early_without_continuing_pipeline(
        self, mock_is_pre_qual, mock_handle_pre_qual
    ):
        """
        After pre-qual handler fires, the message pipeline must return early —
        no further handlers (post-handoff, customer inbound) should run.
        """
        db = _make_db(is_pre_qualified=True, has_qual_session=False)

        with patch("app.routers.webhooks._handle_structured_qualification_turn") as mock_qual, \
             patch("app.services.customer_inbound_service.handle_lead_post_handoff_inbound") as mock_post:
            _handle_inbound_message(db, _make_message(), "John Doe", PHONE_ID)

        mock_qual.assert_not_called()
        mock_post.assert_not_called()

    @patch("app.services.customer_inbound_service.handle_customer_inbound")
    @patch("app.routers.webhooks._handle_pre_qualified_lead")
    @patch("app.routers.webhooks._is_lead_pre_qualified")
    def test_is_pre_qual_not_called_when_customer_id_exists(
        self, mock_is_pre_qual, mock_handle_pre_qual, mock_customer_inbound
    ):
        """
        Pre-qual check only applies to leads, not existing customers.
        If customer_id is found, the check must not run.
        """
        db = _make_db(is_pre_qualified=True, has_qual_session=False)

        def _table(name):
            chain = MagicMock()
            chain.select.return_value       = chain
            chain.eq.return_value           = chain
            chain.update.return_value       = chain
            chain.insert.return_value       = chain
            chain.limit.return_value        = chain
            chain.order.return_value        = chain
            chain.maybe_single.return_value = chain
            chain.in_.return_value          = chain
            chain.neq.return_value          = chain
            chain.gt.return_value           = chain
            chain.is_.return_value          = chain
            if name == "customers":
                chain.execute.return_value = MagicMock(data=[{
                    "id": str(uuid.uuid4()), "org_id": ORG_ID,
                    "whatsapp": PHONE, "phone": PHONE,
                    "assigned_to": USER_ID,
                }])
            else:
                chain.execute.return_value = MagicMock(data={})
            return chain

        db2 = MagicMock()
        db2.table.side_effect = _table

        with patch("app.routers.webhooks._handle_structured_qualification_turn"):
            _handle_inbound_message(db2, _make_message(), "Customer", PHONE_ID)

        mock_is_pre_qual.assert_not_called()
        mock_handle_pre_qual.assert_not_called()