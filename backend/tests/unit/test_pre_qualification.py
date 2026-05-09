"""
tests/unit/test_pre_qualification.py
PRE-QUAL — Unit tests for _is_lead_pre_qualified and _handle_pre_qualified_lead

Run:
    pytest tests/unit/test_pre_qualification.py -v

Patterns:
  T2  — side_effect only on db.table, each chain has its own return_value
  T3  — dry-run validated before presenting
  Pattern 63 — patch at source module for lazy imports
"""
import uuid
from unittest.mock import MagicMock, patch
import pytest

from app.routers.webhooks import _is_lead_pre_qualified, _handle_pre_qualified_lead

ORG_ID  = str(uuid.uuid4())
LEAD_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
PHONE   = "+2348012345678"
NOW_TS  = "2026-05-08T00:00:00Z"


# ── DB factory ────────────────────────────────────────────────────────────────

def _make_db(table_data: dict = None, capture_inserts: dict = None):
    """
    Build a DB mock where db.table(name) returns a chain specific to that table.
    table_data:      dict of table_name -> data returned by execute()
    capture_inserts: dict of table_name -> list to append insert payloads to
    T2: side_effect only on db.table — each chain has its own return_value.
    """
    table_data      = table_data or {}
    capture_inserts = capture_inserts or {}
    db = MagicMock()

    def _table(name):
        chain = MagicMock()
        chain.select.return_value       = chain
        chain.eq.return_value           = chain
        chain.update.return_value       = chain
        chain.limit.return_value        = chain
        chain.order.return_value        = chain
        chain.maybe_single.return_value = chain
        chain.in_.return_value          = chain
        chain.neq.return_value          = chain
        chain.gt.return_value           = chain
        chain.execute.return_value      = MagicMock(data=table_data.get(name, {}))

        if name in capture_inserts:
            target = capture_inserts[name]
            def _capture(data, _t=target):
                _t.append(data)
                return chain
            chain.insert.side_effect = _capture
        else:
            chain.insert.return_value = chain

        return chain

    db.table.side_effect = _table
    return db


# ── _is_lead_pre_qualified ────────────────────────────────────────────────────

class TestIsLeadPreQualified:

    def test_returns_true_when_no_qualification_flow_configured(self):
        """Org has no qualification_flow → skip bot (nothing to collect)."""
        db = _make_db({
            "organisations": {"qualification_flow": None},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True

    def test_returns_true_when_flow_has_no_questions(self):
        db = _make_db({
            "organisations": {"qualification_flow": {"questions": []}},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True

    def test_returns_true_when_no_questions_have_mapped_fields(self):
        """Questions exist but none map to a lead field → nothing to collect."""
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "text": "Tell us about yourself", "map_to_lead_field": None},
                    ]
                }
            },
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True

    def test_returns_true_when_one_mapped_field_is_populated(self):
        """Any one populated mapped field → pre-qualified."""
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "problem_stated"},
                        {"id": "q2", "map_to_lead_field": "business_type"},
                    ]
                }
            },
            "leads": {"problem_stated": "Need mattresses for my hotel", "business_type": None},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True

    def test_returns_true_when_all_mapped_fields_are_populated(self):
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "problem_stated"},
                        {"id": "q2", "map_to_lead_field": "business_type"},
                    ]
                }
            },
            "leads": {"problem_stated": "Need beds", "business_type": "Hotel"},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True

    def test_returns_false_when_no_mapped_fields_are_populated(self):
        """None of the mapped fields are populated → run qualification bot."""
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "problem_stated"},
                        {"id": "q2", "map_to_lead_field": "business_type"},
                    ]
                }
            },
            "leads": {"problem_stated": None, "business_type": None},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is False

    def test_returns_false_when_mapped_fields_are_whitespace(self):
        """Whitespace-only values are not considered populated."""
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "problem_stated"},
                    ]
                }
            },
            "leads": {"problem_stated": "   "},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is False

    def test_returns_false_safely_on_db_error(self):
        """S14: DB error → return False (safe default is to run normal qualification)."""
        db = MagicMock()
        db.table.side_effect = Exception("DB connection lost")
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is False

    def test_works_with_any_configured_field_not_just_legacy_fields(self):
        """Works with any org-configured field — not hardcoded to B2B field names."""
        db = _make_db({
            "organisations": {
                "qualification_flow": {
                    "questions": [
                        {"id": "q1", "map_to_lead_field": "location"},
                        {"id": "q2", "map_to_lead_field": "branches"},
                    ]
                }
            },
            "leads": {"location": "Lagos Island", "branches": None},
        })
        assert _is_lead_pre_qualified(db, ORG_ID, LEAD_ID) is True


# ── _handle_pre_qualified_lead ────────────────────────────────────────────────

class TestHandlePreQualifiedLead:

    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_sends_personalised_greeting_using_first_name(self, mock_creds, mock_send):
        """Greeting uses first name only — not full name."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        db = _make_db({
            "organisations": {"whatsapp_sales_mode": "human", "shopify_connected": False},
            "leads":         {"full_name": "John Adeyemi"},
        })

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John Adeyemi",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        mock_send.assert_called()
        body = mock_send.call_args[0][1]["text"]["body"]
        assert "John" in body
        assert "Adeyemi" not in body

    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_notifies_assigned_rep(self, mock_creds, mock_send):
        """Assigned rep receives a notification about the re-engaging lead."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        inserted_notifications = []
        db = _make_db(
            table_data={
                "organisations": {"whatsapp_sales_mode": "human", "shopify_connected": False},
                "leads":         {"full_name": "Jane"},
            },
            capture_inserts={"notifications": inserted_notifications},
        )

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="Jane",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        assert any(n.get("user_id") == USER_ID for n in inserted_notifications)
        assert any(n.get("resource_id") == LEAD_ID for n in inserted_notifications)

    @patch("app.services.whatsapp_service.send_product_list")
    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_no_product_list_in_human_mode(self, mock_creds, mock_send, mock_products):
        """Human mode: greeting sent, no product list."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        db = _make_db({
            "organisations": {"whatsapp_sales_mode": "human", "shopify_connected": True},
            "leads":         {"full_name": "John"},
        })

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        mock_products.assert_not_called()

    @patch("app.services.whatsapp_service.send_product_list")
    @patch("app.services.commerce_service.get_or_create_commerce_session")
    @patch("app.routers.webhooks.triage_service.get_or_create_session")
    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_sends_product_list_in_bot_mode_with_shopify(
        self, mock_creds, mock_send, mock_session, mock_commerce, mock_products
    ):
        """Bot mode + Shopify connected: greeting AND product list sent."""
        mock_creds.return_value   = ("phone_id_123", "token_abc", None)
        mock_session.return_value = {"id": str(uuid.uuid4())}
        mock_commerce.return_value = {"id": str(uuid.uuid4())}
        db = _make_db({
            "organisations": {"whatsapp_sales_mode": "bot", "shopify_connected": True},
            "leads":         {"full_name": "John"},
            "products":      [{"id": str(uuid.uuid4()), "title": "Royal Rest King", "is_active": True}],
        })

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        mock_products.assert_called_once()

    @patch("app.services.whatsapp_service.send_product_list")
    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_no_product_list_in_bot_mode_without_shopify(
        self, mock_creds, mock_send, mock_products
    ):
        """Bot mode but Shopify not connected: greeting only, no product list."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        db = _make_db({
            "organisations": {"whatsapp_sales_mode": "bot", "shopify_connected": False},
            "leads":         {"full_name": "John"},
        })

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        mock_products.assert_not_called()

    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_creates_handed_off_qualification_session(self, mock_creds, mock_send):
        """Must insert a handed_off session to prevent repeat greetings on future messages."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        inserted_sessions = []
        db = _make_db(
            table_data={
                "organisations": {"whatsapp_sales_mode": "human", "shopify_connected": False},
                "leads":         {"full_name": "John"},
            },
            capture_inserts={"lead_qualification_sessions": inserted_sessions},
        )

        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )

        assert len(inserted_sessions) == 1
        sess = inserted_sessions[0]
        assert sess["stage"]    == "handed_off"
        assert sess["ai_active"] is False
        assert sess["lead_id"]  == LEAD_ID
        assert sess["org_id"]   == ORG_ID

    @patch("app.services.whatsapp_service._call_meta_send")
    @patch("app.services.whatsapp_service._get_org_wa_credentials")
    def test_never_raises_on_db_error(self, mock_creds, mock_send):
        """S14: must never raise even if DB completely fails."""
        mock_creds.return_value = ("phone_id_123", "token_abc", None)
        db = MagicMock()
        db.table.side_effect = Exception("DB gone")

        # Must not raise
        _handle_pre_qualified_lead(
            db=db, org_id=ORG_ID, lead_id=LEAD_ID,
            phone_number=PHONE, contact_name="John",
            assigned_to=USER_ID, now_ts=NOW_TS,
        )