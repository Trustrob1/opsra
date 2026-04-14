"""
tests/unit/test_demo_queue_service.py
M01-7a — Unit tests for:
  - demo_service.list_pending_demos_org_wide()
  - demo_service.get_lead_attention_summary()
  - demo_service.get_customer_attention_summary()

Pattern 24: all UUIDs valid format.
S14: signal query failures must not raise.

NOTE on mocking strategy:
  Each attention summary function makes 3 separate db.table() calls for
  different tables (whatsapp_messages, lead_demos/tickets, customers).
  We use a table_mock factory keyed by table name so each call gets its
  own mock chain with its own execute().data — avoiding cross-contamination.
"""
import pytest
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

ORG_ID   = str(uuid4())
LEAD_A   = str(uuid4())
LEAD_B   = str(uuid4())
CUST_A   = str(uuid4())
CUST_B   = str(uuid4())
DEMO_1   = str(uuid4())
USER_1   = str(uuid4())


def _chain(rows):
    """Build a mock Supabase chain that returns rows at .execute().data"""
    m = MagicMock()
    # Every chained attribute returns self so any combination works
    m.select.return_value = m
    m.eq.return_value = m
    m.neq.return_value = m
    m.in_.return_value = m
    m.is_.return_value = m
    m.not_ = m
    m.order.return_value = m
    m.limit.return_value = m
    m.execute.return_value = MagicMock(data=rows)
    return m


def _db_by_table(table_data: dict):
    """
    Returns a db mock where db.table(name) returns a distinct chain
    per table name.  table_data = { 'table_name': [row, ...] }
    Any table not listed returns an empty chain.
    """
    db = MagicMock()
    chains = {name: _chain(rows) for name, rows in table_data.items()}
    default = _chain([])

    def _table(name):
        return chains.get(name, default)

    db.table.side_effect = _table
    return db


# ─────────────────────────────────────────────────────────────────────────────
# list_pending_demos_org_wide
# ─────────────────────────────────────────────────────────────────────────────

class TestListPendingDemosOrgWide:

    def test_returns_flattened_rows(self):
        from app.services.demo_service import list_pending_demos_org_wide
        db = _db_by_table({
            "lead_demos": [
                {
                    "id": DEMO_1,
                    "lead_id": LEAD_A,
                    "status": "pending_assignment",
                    "lead_preferred_time": "Monday afternoon",
                    "medium": "virtual",
                    "notes": None,
                    "created_by": USER_1,
                    "created_at": "2026-04-10T10:00:00Z",
                    "updated_at": "2026-04-10T10:00:00Z",
                    "leads": {
                        "full_name": "Amara Osei",
                        "phone": "+2348012345678",
                        "whatsapp": "+2348012345678",
                        "assigned_to": USER_1,
                    },
                }
            ]
        })
        result = list_pending_demos_org_wide(db, ORG_ID)
        assert len(result) == 1
        row = result[0]
        assert row["id"] == DEMO_1
        assert row["lead_full_name"] == "Amara Osei"
        assert row["lead_phone"] == "+2348012345678"
        assert row["lead_assigned_to"] == USER_1
        assert "leads" not in row

    def test_returns_empty_list_when_none(self):
        from app.services.demo_service import list_pending_demos_org_wide
        db = _db_by_table({"lead_demos": []})
        assert list_pending_demos_org_wide(db, ORG_ID) == []

    def test_null_data_returns_empty(self):
        from app.services.demo_service import list_pending_demos_org_wide
        db = MagicMock()
        chain = _chain(None)
        db.table.return_value = chain
        assert list_pending_demos_org_wide(db, ORG_ID) == []

    def test_missing_leads_join_uses_defaults(self):
        from app.services.demo_service import list_pending_demos_org_wide
        db = _db_by_table({
            "lead_demos": [
                {
                    "id": DEMO_1,
                    "lead_id": LEAD_A,
                    "status": "pending_assignment",
                    "lead_preferred_time": None,
                    "medium": None,
                    "notes": None,
                    "created_by": None,
                    "created_at": "2026-04-10T10:00:00Z",
                    "updated_at": "2026-04-10T10:00:00Z",
                    "leads": None,
                }
            ]
        })
        result = list_pending_demos_org_wide(db, ORG_ID)
        assert result[0]["lead_full_name"] == "Unknown Lead"
        assert result[0]["lead_phone"] == ""
        assert result[0]["lead_assigned_to"] is None


# ─────────────────────────────────────────────────────────────────────────────
# get_lead_attention_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestGetLeadAttentionSummary:

    def test_no_signals_returns_empty(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "lead_demos": [],
            "tickets": [],
        })
        assert get_lead_attention_summary(db, ORG_ID) == {}

    def test_unread_messages_sets_has_attention(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"lead_id": LEAD_A}, {"lead_id": LEAD_A}],
            "lead_demos": [],
            "tickets": [],
        })
        result = get_lead_attention_summary(db, ORG_ID)
        assert LEAD_A in result
        assert result[LEAD_A]["has_attention"] is True
        assert result[LEAD_A]["unread_messages"] == 2
        assert "2 unread messages" in result[LEAD_A]["reasons"]

    def test_pending_demo_sets_has_attention(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "lead_demos": [{"lead_id": LEAD_B}],
            "tickets": [],
        })
        result = get_lead_attention_summary(db, ORG_ID)
        assert result[LEAD_B]["has_attention"] is True
        assert result[LEAD_B]["pending_demos"] == 1
        assert "Demo awaiting confirmation" in result[LEAD_B]["reasons"]

    def test_open_ticket_sets_has_attention(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "lead_demos": [],
            "tickets": [{"lead_id": LEAD_A}],
        })
        result = get_lead_attention_summary(db, ORG_ID)
        assert result[LEAD_A]["open_tickets"] == 1
        assert result[LEAD_A]["has_attention"] is True
        assert "1 open ticket" in result[LEAD_A]["reasons"]

    def test_multiple_signals_same_lead(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"lead_id": LEAD_A}],
            "lead_demos": [{"lead_id": LEAD_A}],
            "tickets": [{"lead_id": LEAD_A}],
        })
        result = get_lead_attention_summary(db, ORG_ID)
        assert result[LEAD_A]["unread_messages"] == 1
        assert result[LEAD_A]["pending_demos"] == 1
        assert result[LEAD_A]["open_tickets"] == 1
        assert len(result[LEAD_A]["reasons"]) == 3

    def test_scoped_lead_ids_filters_out_others(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"lead_id": LEAD_A}, {"lead_id": LEAD_B}],
            "lead_demos": [],
            "tickets": [],
        })
        result = get_lead_attention_summary(db, ORG_ID, lead_ids=[LEAD_A])
        assert LEAD_A in result
        assert LEAD_B not in result

    def test_signal_failure_does_not_raise(self):
        """S14: individual query failures must never propagate."""
        from app.services.demo_service import get_lead_attention_summary
        db = MagicMock()
        db.table.side_effect = Exception("DB totally broken")
        # Must not raise — returns empty dict
        result = get_lead_attention_summary(db, ORG_ID)
        assert isinstance(result, dict)

    def test_null_lead_id_rows_skipped(self):
        from app.services.demo_service import get_lead_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"lead_id": None}, {"lead_id": LEAD_A}],
            "lead_demos": [],
            "tickets": [],
        })
        result = get_lead_attention_summary(db, ORG_ID)
        assert None not in result
        assert LEAD_A in result


# ─────────────────────────────────────────────────────────────────────────────
# get_customer_attention_summary
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCustomerAttentionSummary:

    def test_no_signals_returns_empty(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "tickets": [],
            "customers": [],
        })
        assert get_customer_attention_summary(db, ORG_ID) == {}

    def test_unread_messages_for_customer(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"customer_id": CUST_B}],
            "tickets": [],
            "customers": [],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert CUST_B in result
        assert result[CUST_B]["unread_messages"] == 1
        assert result[CUST_B]["has_attention"] is True

    def test_open_ticket_sets_has_attention(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "tickets": [{"customer_id": CUST_A}],
            "customers": [],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert result[CUST_A]["open_tickets"] == 1
        assert result[CUST_A]["has_attention"] is True

    def test_churn_risk_sets_has_attention(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "tickets": [],
            "customers": [{"id": CUST_A, "churn_risk": "critical"}],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert CUST_A in result
        assert result[CUST_A]["has_attention"] is True
        assert result[CUST_A]["churn_risk"] == "critical"
        assert "Critical churn risk" in result[CUST_A]["reasons"]

    def test_high_churn_risk_also_sets_attention(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [],
            "tickets": [],
            "customers": [{"id": CUST_B, "churn_risk": "high"}],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert result[CUST_B]["has_attention"] is True
        assert "High churn risk" in result[CUST_B]["reasons"]

    def test_low_churn_risk_alone_no_attention(self):
        from app.services.demo_service import get_customer_attention_summary
        # customers table only returns high/critical — low risk customers
        # won't appear in that query, so they won't be in the summary at all
        db = _db_by_table({
            "whatsapp_messages": [],
            "tickets": [],
            "customers": [],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert CUST_A not in result

    def test_scoped_customer_ids_filters_out_others(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"customer_id": CUST_A}, {"customer_id": CUST_B}],
            "tickets": [],
            "customers": [],
        })
        result = get_customer_attention_summary(db, ORG_ID, customer_ids=[CUST_A])
        assert CUST_A in result
        assert CUST_B not in result

    def test_signal_failure_does_not_raise(self):
        """S14: individual query failures must never propagate."""
        from app.services.demo_service import get_customer_attention_summary
        db = MagicMock()
        db.table.side_effect = Exception("DB totally broken")
        result = get_customer_attention_summary(db, ORG_ID)
        assert isinstance(result, dict)

    def test_null_customer_id_rows_skipped(self):
        from app.services.demo_service import get_customer_attention_summary
        db = _db_by_table({
            "whatsapp_messages": [{"customer_id": None}, {"customer_id": CUST_A}],
            "tickets": [],
            "customers": [],
        })
        result = get_customer_attention_summary(db, ORG_ID)
        assert None not in result
        assert CUST_A in result
