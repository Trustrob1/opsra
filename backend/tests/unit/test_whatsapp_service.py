"""
tests/unit/test_whatsapp_service.py

Unit tests for app.services.whatsapp_service.
All Supabase calls are mocked — no real DB connections.
Meta Cloud API (_call_meta_send) is patched in tests that exercise send_whatsapp_message.

Mock patterns follow Build Status CRITICAL PATTERNS:
  - Pattern 8  : separate insert mock to avoid overwriting SELECT result
  - Pattern 9  : _normalise_data tested via list AND dict return paths
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.customers import CustomerUpdate
from app.models.whatsapp import (
    BroadcastCreate,
    DripMessageConfig,
    SendMessageRequest,
    TemplateCreate,
    TemplateUpdate,
)
from app.services.whatsapp_service import (
    BROADCAST_APPROVE_FROM,
    BROADCAST_CANCEL_FROM,
    _broadcast_or_404,
    _customer_or_404,
    _is_window_open,
    _normalise_data,
    approve_broadcast,
    cancel_broadcast,
    create_broadcast,
    create_template,
    get_broadcast,
    get_customer,
    get_customer_messages,
    get_customer_nps,
    get_customer_tasks,
    get_drip_sequence,
    list_broadcasts,
    list_customers,
    list_templates,
    send_whatsapp_message,
    update_customer,
    update_drip_sequence,
    update_template,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = "org-111"
USER_ID = "user-222"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000333"
BROADCAST_ID = "bc-444"
TEMPLATE_ID = "tmpl-555"

_CUSTOMER = {
    "id": CUSTOMER_ID,
    "org_id": ORG_ID,
    "full_name": "Ada Okafor",
    "whatsapp": "2348001234567",
    "phone": "2348001234567",
    "business_name": "Ada Stores",
    "deleted_at": None,
}

_BROADCAST_DRAFT = {
    "id": BROADCAST_ID,
    "org_id": ORG_ID,
    "name": "Welcome blast",
    "template_id": "tmpl-abc",
    "status": "draft",
    "scheduled_at": None,
}

_BROADCAST_SCHEDULED = {
    **_BROADCAST_DRAFT,
    "status": "scheduled",
    "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
}

_TEMPLATE_REJECTED = {
    "id": TEMPLATE_ID,
    "org_id": ORG_ID,
    "name": "renewal_reminder",
    "category": "utility",
    "body": "Hi {{customer_name}}",
    "meta_status": "rejected",
    "rejection_reason": "content policy",
}

_TEMPLATE_PENDING = {**_TEMPLATE_REJECTED, "meta_status": "pending"}


def _chain(data, count=None):
    """
    Build a chainable Supabase table mock.
    All query-builder methods return the same mock (the chain).
    .execute() returns a result object with .data and .count.
    """
    chain = MagicMock()
    result = MagicMock()
    result.data = data
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 1
    )
    chain.execute.return_value = result
    for method in [
        "select", "eq", "is_", "order", "range", "limit",
        "maybe_single", "update", "delete",
    ]:
        getattr(chain, method).return_value = chain
    return chain, result


def _db_for_table(table_returns: dict):
    """
    Build a db mock where db.table(name) returns different chains per name.
    table_returns: {"customers": chain_obj, ...}
    """
    db = MagicMock()
    db.table.side_effect = lambda name: table_returns.get(name, MagicMock())
    return db


# ---------------------------------------------------------------------------
# _normalise_data
# ---------------------------------------------------------------------------

class TestNormaliseData:
    def test_dict_passthrough(self):
        assert _normalise_data({"id": "1"}) == {"id": "1"}

    def test_list_returns_first(self):
        assert _normalise_data([{"id": "1"}, {"id": "2"}]) == {"id": "1"}

    def test_empty_list_returns_none(self):
        assert _normalise_data([]) is None

    def test_none_passthrough(self):
        assert _normalise_data(None) is None


# ---------------------------------------------------------------------------
# _customer_or_404
# ---------------------------------------------------------------------------

class TestCustomerOr404:
    def test_found_returns_dict(self):
        chain, _ = _chain(_CUSTOMER)
        db = MagicMock()
        db.table.return_value = chain
        result = _customer_or_404(db, ORG_ID, CUSTOMER_ID)
        assert result["id"] == CUSTOMER_ID

    def test_found_as_list(self):
        chain, _ = _chain([_CUSTOMER])
        db = MagicMock()
        db.table.return_value = chain
        result = _customer_or_404(db, ORG_ID, CUSTOMER_ID)
        assert result["id"] == CUSTOMER_ID

    def test_not_found_raises_404(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            _customer_or_404(db, ORG_ID, "nonexistent")
        assert exc_info.value.status_code == 404

    def test_empty_list_raises_404(self):
        chain, _ = _chain([])
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            _customer_or_404(db, ORG_ID, CUSTOMER_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _is_window_open
# ---------------------------------------------------------------------------

class TestIsWindowOpen:
    def test_no_messages_returns_false(self):
        chain, _ = _chain([])
        db = MagicMock()
        db.table.return_value = chain
        assert _is_window_open(db, ORG_ID, CUSTOMER_ID) is False

    def test_window_open_returns_true(self):
        expires = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
        chain, _ = _chain([{"window_open": True, "window_expires_at": expires}])
        db = MagicMock()
        db.table.return_value = chain
        assert _is_window_open(db, ORG_ID, CUSTOMER_ID) is True

    def test_window_expired_returns_false(self):
        expires = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        chain, _ = _chain([{"window_open": True, "window_expires_at": expires}])
        db = MagicMock()
        db.table.return_value = chain
        assert _is_window_open(db, ORG_ID, CUSTOMER_ID) is False

    def test_window_open_false_returns_false(self):
        expires = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
        chain, _ = _chain([{"window_open": False, "window_expires_at": expires}])
        db = MagicMock()
        db.table.return_value = chain
        assert _is_window_open(db, ORG_ID, CUSTOMER_ID) is False

    def test_none_data_returns_false(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        assert _is_window_open(db, ORG_ID, CUSTOMER_ID) is False


# ---------------------------------------------------------------------------
# list_customers
# ---------------------------------------------------------------------------

class TestListCustomers:
    def test_returns_items_and_total(self):
        chain, res = _chain([_CUSTOMER], count=1)
        db = MagicMock()
        db.table.return_value = chain
        result = list_customers(db, ORG_ID)
        assert result["items"] == [_CUSTOMER]
        assert result["total"] == 1

    def test_empty_list(self):
        chain, res = _chain([], count=0)
        db = MagicMock()
        db.table.return_value = chain
        result = list_customers(db, ORG_ID)
        assert result["items"] == []
        assert result["total"] == 0

    def test_pagination_params_passed(self):
        chain, _ = _chain([], count=0)
        db = MagicMock()
        db.table.return_value = chain
        result = list_customers(db, ORG_ID, page=2, page_size=10)
        assert result["page"] == 2
        assert result["page_size"] == 10


# ---------------------------------------------------------------------------
# get_customer
# ---------------------------------------------------------------------------

class TestGetCustomer:
    def test_found(self):
        chain, _ = _chain(_CUSTOMER)
        db = MagicMock()
        db.table.return_value = chain
        result = get_customer(db, ORG_ID, CUSTOMER_ID)
        assert result["id"] == CUSTOMER_ID

    def test_not_found_raises_404(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            get_customer(db, ORG_ID, "missing")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# update_customer
# ---------------------------------------------------------------------------

class TestUpdateCustomer:
    def test_updates_field(self):
        # First call (_customer_or_404) → returns existing customer
        # Second call (update) → returns updated record
        existing_chain, _ = _chain(_CUSTOMER)
        updated_record = {**_CUSTOMER, "full_name": "Ada Okafor Updated"}

        # Separate insert mock per Pattern 8 (for update chain)
        update_chain = MagicMock()
        update_result = MagicMock()
        update_result.data = [updated_record]
        update_chain.execute.return_value = update_result
        for m in ["eq", "update", "is_", "select", "maybe_single"]:
            getattr(update_chain, m).return_value = update_chain

        # db.table side effect: first "customers" call → existing, subsequent → update
        call_count = {"n": 0}
        def table_side(name):
            if name == "customers":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return existing_chain
                return update_chain
            return MagicMock()

        db = MagicMock()
        db.table.side_effect = table_side

        # Audit log goes to audit_logs table — just needs to not raise
        payload = CustomerUpdate(full_name="Ada Okafor Updated")
        result = update_customer(db, ORG_ID, CUSTOMER_ID, USER_ID, payload)
        assert result["full_name"] == "Ada Okafor Updated"

    def test_404_if_customer_missing(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        payload = CustomerUpdate(full_name="X")
        with pytest.raises(HTTPException) as exc_info:
            update_customer(db, ORG_ID, "bad-id", USER_ID, payload)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_customer_messages
# ---------------------------------------------------------------------------

class TestGetCustomerMessages:
    def test_returns_messages(self):
        msg = {"id": "m1", "direction": "outbound", "content": "Hello"}
        # First call: _customer_or_404 (customers table)
        cust_chain, _ = _chain(_CUSTOMER)
        msg_chain, _ = _chain([msg], count=1)
        db = _db_for_table({"customers": cust_chain, "whatsapp_messages": msg_chain})
        result = get_customer_messages(db, ORG_ID, CUSTOMER_ID)
        assert result["items"] == [msg]
        assert result["total"] == 1

    def test_404_if_customer_missing(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException):
            get_customer_messages(db, ORG_ID, "bad-id")


# ---------------------------------------------------------------------------
# get_customer_tasks
# ---------------------------------------------------------------------------

class TestGetCustomerTasks:
    def test_returns_tasks(self):
        task = {"id": "t1", "title": "Follow up", "source_module": "whatsapp"}
        cust_chain, _ = _chain(_CUSTOMER)
        tasks_chain, _ = _chain([task])
        db = _db_for_table({"customers": cust_chain, "tasks": tasks_chain})
        result = get_customer_tasks(db, ORG_ID, CUSTOMER_ID)
        assert result == [task]

    def test_empty(self):
        cust_chain, _ = _chain(_CUSTOMER)
        tasks_chain, _ = _chain([])
        db = _db_for_table({"customers": cust_chain, "tasks": tasks_chain})
        result = get_customer_tasks(db, ORG_ID, CUSTOMER_ID)
        assert result == []


# ---------------------------------------------------------------------------
# get_customer_nps
# ---------------------------------------------------------------------------

class TestGetCustomerNps:
    def test_returns_nps_history(self):
        nps = {"id": "n1", "score": 5, "trigger_type": "quarterly"}
        cust_chain, _ = _chain(_CUSTOMER)
        nps_chain, _ = _chain([nps])
        db = _db_for_table({"customers": cust_chain, "nps_responses": nps_chain})
        result = get_customer_nps(db, ORG_ID, CUSTOMER_ID)
        assert result == [nps]


# ---------------------------------------------------------------------------
# list_broadcasts
# ---------------------------------------------------------------------------

class TestListBroadcasts:
    def test_returns_broadcasts(self):
        chain, _ = _chain([_BROADCAST_DRAFT], count=1)
        db = MagicMock()
        db.table.return_value = chain
        result = list_broadcasts(db, ORG_ID)
        assert result["items"] == [_BROADCAST_DRAFT]

    def test_empty(self):
        chain, _ = _chain([], count=0)
        db = MagicMock()
        db.table.return_value = chain
        result = list_broadcasts(db, ORG_ID)
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# create_broadcast
# ---------------------------------------------------------------------------

class TestCreateBroadcast:
    def test_creates_draft(self):
        import uuid
        tid = str(uuid.uuid4())
        new_row = {**_BROADCAST_DRAFT, "template_id": tid}

        # Separate insert chain (Pattern 8)
        insert_chain = MagicMock()
        insert_result = MagicMock()
        insert_result.data = [new_row]
        insert_chain.execute.return_value = insert_result
        insert_chain.insert.return_value = insert_chain   # chain .insert(row) → itself
        db = MagicMock()
        db.table.return_value = insert_chain

        payload = BroadcastCreate(name="Welcome blast", template_id=tid)
        result = create_broadcast(db, ORG_ID, USER_ID, payload)
        assert result["status"] == "draft"
        assert result["name"] == "Welcome blast"


# ---------------------------------------------------------------------------
# get_broadcast
# ---------------------------------------------------------------------------

class TestGetBroadcast:
    def test_found(self):
        chain, _ = _chain(_BROADCAST_DRAFT)
        db = MagicMock()
        db.table.return_value = chain
        result = get_broadcast(db, ORG_ID, BROADCAST_ID)
        assert result["id"] == BROADCAST_ID

    def test_not_found_raises_404(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            get_broadcast(db, ORG_ID, "bad")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# approve_broadcast
# ---------------------------------------------------------------------------

class TestApproveBroadcast:
    def test_draft_no_schedule_becomes_sending(self):
        fetch_chain, _ = _chain(_BROADCAST_DRAFT)
        updated = {**_BROADCAST_DRAFT, "status": "sending"}
        update_chain = MagicMock()
        ur = MagicMock()
        ur.data = [updated]
        update_chain.execute.return_value = ur
        for m in ["eq", "update"]:
            getattr(update_chain, m).return_value = update_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts" and call_count["n"] == 1:
                return fetch_chain
            return update_chain
        db = MagicMock()
        db.table.side_effect = tbl

        result = approve_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert result["status"] == "sending"

    def test_draft_future_schedule_becomes_scheduled(self):
        future_ts = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        scheduled_bc = {**_BROADCAST_DRAFT, "scheduled_at": future_ts}
        fetch_chain, _ = _chain(scheduled_bc)
        updated = {**scheduled_bc, "status": "scheduled"}
        update_chain = MagicMock()
        ur = MagicMock()
        ur.data = [updated]
        update_chain.execute.return_value = ur
        for m in ["eq", "update"]:
            getattr(update_chain, m).return_value = update_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts" and call_count["n"] == 1:
                return fetch_chain
            return update_chain
        db = MagicMock()
        db.table.side_effect = tbl

        result = approve_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert result["status"] == "scheduled"

    def test_non_draft_raises_400(self):
        sent_bc = {**_BROADCAST_DRAFT, "status": "sent"}
        chain, _ = _chain(sent_bc)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            approve_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert exc_info.value.status_code == 400

    def test_approve_from_states(self):
        assert "draft" in BROADCAST_APPROVE_FROM
        assert "scheduled" not in BROADCAST_APPROVE_FROM
        assert "sent" not in BROADCAST_APPROVE_FROM


# ---------------------------------------------------------------------------
# cancel_broadcast
# ---------------------------------------------------------------------------

class TestCancelBroadcast:
    def test_draft_can_be_cancelled(self):
        fetch_chain, _ = _chain(_BROADCAST_DRAFT)
        cancelled = {**_BROADCAST_DRAFT, "status": "cancelled"}
        update_chain = MagicMock()
        ur = MagicMock()
        ur.data = [cancelled]
        update_chain.execute.return_value = ur
        for m in ["eq", "update"]:
            getattr(update_chain, m).return_value = update_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts" and call_count["n"] == 1:
                return fetch_chain
            return update_chain
        db = MagicMock()
        db.table.side_effect = tbl

        result = cancel_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert result["status"] == "cancelled"

    def test_scheduled_can_be_cancelled(self):
        fetch_chain, _ = _chain(_BROADCAST_SCHEDULED)
        cancelled = {**_BROADCAST_SCHEDULED, "status": "cancelled"}
        update_chain = MagicMock()
        ur = MagicMock()
        ur.data = [cancelled]
        update_chain.execute.return_value = ur
        for m in ["eq", "update"]:
            getattr(update_chain, m).return_value = update_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts" and call_count["n"] == 1:
                return fetch_chain
            return update_chain
        db = MagicMock()
        db.table.side_effect = tbl

        result = cancel_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert result["status"] == "cancelled"

    def test_sent_cannot_be_cancelled(self):
        sent = {**_BROADCAST_DRAFT, "status": "sent"}
        chain, _ = _chain(sent)
        db = MagicMock()
        db.table.return_value = chain
        with pytest.raises(HTTPException) as exc_info:
            cancel_broadcast(db, ORG_ID, BROADCAST_ID, USER_ID)
        assert exc_info.value.status_code == 400

    def test_cancel_from_states(self):
        assert "draft" in BROADCAST_CANCEL_FROM
        assert "scheduled" in BROADCAST_CANCEL_FROM
        assert "sending" not in BROADCAST_CANCEL_FROM
        assert "sent" not in BROADCAST_CANCEL_FROM


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_returns_list(self):
        chain, _ = _chain([_TEMPLATE_REJECTED])
        db = MagicMock()
        db.table.return_value = chain
        result = list_templates(db, ORG_ID)
        assert result == [_TEMPLATE_REJECTED]


# ---------------------------------------------------------------------------
# create_template
# ---------------------------------------------------------------------------

class TestCreateTemplate:
    def test_creates_with_pending_status(self):
        new_tmpl = {**_TEMPLATE_PENDING, "id": "new-tmpl"}
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [new_tmpl]
        insert_chain.execute.return_value = ir
        insert_chain.insert.return_value = insert_chain   # chain .insert(row) → itself
        db = MagicMock()
        db.table.return_value = insert_chain

        payload = TemplateCreate(
            name="renewal_reminder",
            category="utility",
            body="Hi {{customer_name}}",
            variables=["customer_name"],
        )
        result = create_template(db, ORG_ID, USER_ID, payload)
        assert result["meta_status"] == "pending"

    def test_invalid_category_raises_422(self):
        db = MagicMock()
        payload = TemplateCreate(
            name="bad_cat",
            category="promotional",  # Not a valid category
            body="Hi",
        )
        with pytest.raises(HTTPException) as exc_info:
            create_template(db, ORG_ID, USER_ID, payload)
        assert exc_info.value.status_code == 422

    def test_valid_categories(self):
        for cat in ("marketing", "utility", "authentication"):
            new_tmpl = {**_TEMPLATE_PENDING, "category": cat, "id": f"t-{cat}"}
            insert_chain = MagicMock()
            ir = MagicMock()
            ir.data = [new_tmpl]
            insert_chain.execute.return_value = ir
            insert_chain.insert.return_value = insert_chain   # chain .insert(row) → itself
            db = MagicMock()
            db.table.return_value = insert_chain
            payload = TemplateCreate(name="t", category=cat, body="hello")
            result = create_template(db, ORG_ID, USER_ID, payload)
            assert result["category"] == cat


# ---------------------------------------------------------------------------
# update_template
# ---------------------------------------------------------------------------

class TestUpdateTemplate:
    def test_rejected_template_can_be_updated(self):
        fetch_chain, _ = _chain(_TEMPLATE_REJECTED)
        updated = {**_TEMPLATE_REJECTED, "body": "New body", "meta_status": "pending"}
        update_chain = MagicMock()
        ur = MagicMock()
        ur.data = [updated]
        update_chain.execute.return_value = ur
        for m in ["eq", "update", "maybe_single", "select"]:
            getattr(update_chain, m).return_value = update_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "whatsapp_templates" and call_count["n"] == 1:
                return fetch_chain
            return update_chain
        db = MagicMock()
        db.table.side_effect = tbl

        payload = TemplateUpdate(body="New body")
        result = update_template(db, ORG_ID, TEMPLATE_ID, USER_ID, payload)
        assert result["meta_status"] == "pending"

    def test_non_rejected_raises_400(self):
        approved = {**_TEMPLATE_REJECTED, "meta_status": "approved"}
        chain, _ = _chain(approved)
        db = MagicMock()
        db.table.return_value = chain
        payload = TemplateUpdate(body="new")
        with pytest.raises(HTTPException) as exc_info:
            update_template(db, ORG_ID, TEMPLATE_ID, USER_ID, payload)
        assert exc_info.value.status_code == 400

    def test_missing_template_raises_404(self):
        chain, _ = _chain(None)
        db = MagicMock()
        db.table.return_value = chain
        payload = TemplateUpdate(body="new")
        with pytest.raises(HTTPException) as exc_info:
            update_template(db, ORG_ID, "bad-id", USER_ID, payload)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_drip_sequence
# ---------------------------------------------------------------------------

class TestGetDripSequence:
    def test_returns_active_messages(self):
        drip = {"id": "d1", "name": "Day 1 Welcome", "delay_days": 1, "is_active": True}
        chain, _ = _chain([drip])
        db = MagicMock()
        db.table.return_value = chain
        result = get_drip_sequence(db, ORG_ID)
        assert result == [drip]

    def test_empty(self):
        chain, _ = _chain([])
        db = MagicMock()
        db.table.return_value = chain
        result = get_drip_sequence(db, ORG_ID)
        assert result == []


# ---------------------------------------------------------------------------
# update_drip_sequence
# ---------------------------------------------------------------------------

class TestUpdateDripSequence:
    def test_deactivates_existing_and_inserts_new(self):
        import uuid
        tid = str(uuid.uuid4())
        new_drip = {"id": "d2", "name": "Day 3 Sales", "is_active": True}

        # deactivate call and insert call use same mock table (drip_messages)
        deactivate_chain = MagicMock()
        dr = MagicMock()
        dr.data = []
        deactivate_chain.execute.return_value = dr
        for m in ["update", "eq"]:
            getattr(deactivate_chain, m).return_value = deactivate_chain

        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [new_drip]
        insert_chain.execute.return_value = ir
        for m in ["insert", "update", "eq"]:
            getattr(insert_chain, m).return_value = insert_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            # First call: deactivate (update chain)
            # Second call: insert (insert chain)
            # Audit log: audit_logs (don't care)
            if name == "drip_messages":
                if call_count["n"] <= 1:
                    return deactivate_chain
                return insert_chain
            return MagicMock()
        db = MagicMock()
        db.table.side_effect = tbl

        messages = [
            DripMessageConfig(
                name="Day 3 Sales",
                template_id=tid,
                delay_days=3,
                sequence_order=1,
            )
        ]
        result = update_drip_sequence(db, ORG_ID, USER_ID, messages)
        assert result == [new_drip]

    def test_empty_messages_returns_empty_list(self):
        deactivate_chain = MagicMock()
        dr = MagicMock()
        dr.data = []
        deactivate_chain.execute.return_value = dr
        for m in ["update", "eq"]:
            getattr(deactivate_chain, m).return_value = deactivate_chain

        db = MagicMock()
        db.table.return_value = deactivate_chain
        result = update_drip_sequence(db, ORG_ID, USER_ID, [])
        assert result == []


# ---------------------------------------------------------------------------
# send_whatsapp_message
# ---------------------------------------------------------------------------

_META_RESPONSE = {"messages": [{"id": "meta-msg-id-999"}]}
_ORG_ROW = {"whatsapp_phone_id": "phone123"}
_LEAD_ROW = {"whatsapp": "2348009876543", "phone": "2348009876543"}
_MSG_ROW = {
    "id": "wamsg-1",
    "org_id": ORG_ID,
    "direction": "outbound",
    "status": "sent",
}


class TestSendWhatsAppMessage:
    def _make_send_db(self, window_open: bool = True, use_lead: bool = False):
        """Build a db that satisfies all queries in send_whatsapp_message."""
        org_chain, _ = _chain(_ORG_ROW)
        cust_chain, _ = _chain(_CUSTOMER)
        lead_chain, _ = _chain(_LEAD_ROW)
        expires = (
            datetime.now(timezone.utc) + timedelta(hours=20)
        ).isoformat()
        window_chain, _ = _chain(
            [{"window_open": window_open, "window_expires_at": expires}]
            if window_open
            else []
        )
        # Separate insert chain (Pattern 8).
        # The service hits db.table("whatsapp_messages") TWICE:
        #   call 1 → SELECT for window check  → window_chain
        #   call 2 → INSERT the message       → insert_chain
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [_MSG_ROW]
        insert_chain.execute.return_value = ir
        insert_chain.insert.return_value = insert_chain

        wa_calls = {"n": 0}

        def tbl(name):
            if name == "organisations":
                return org_chain
            if name == "customers":
                return cust_chain
            if name == "leads":
                return lead_chain
            if name == "whatsapp_messages":
                wa_calls["n"] += 1
                return window_chain if wa_calls["n"] == 1 else insert_chain
            return insert_chain
        db = MagicMock()
        db.table.side_effect = tbl
        return db

    def test_send_free_form_window_open(self):
        db = self._make_send_db(window_open=True)
        payload = SendMessageRequest(
            customer_id=CUSTOMER_ID, content="Hello Ada!"
        )
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            result = send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert result["status"] == "sent"

    def test_send_template_window_closed(self):
        db = self._make_send_db(window_open=False)
        payload = SendMessageRequest(
            customer_id=CUSTOMER_ID,
            template_name="renewal_reminder",
        )
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            result = send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert result["status"] == "sent"

    def test_free_form_window_closed_raises_400(self):
        db = self._make_send_db(window_open=False)
        payload = SendMessageRequest(
            customer_id=CUSTOMER_ID, content="Hi without template"
        )
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            with pytest.raises(HTTPException) as exc_info:
                send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert exc_info.value.status_code == 400

    def test_missing_recipient_raises_422(self):
        db = MagicMock()
        payload = SendMessageRequest(content="Hi")  # No customer_id or lead_id
        with pytest.raises(HTTPException) as exc_info:
            send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert exc_info.value.status_code == 422

    def test_missing_content_and_template_raises_422(self):
        db = MagicMock()
        payload = SendMessageRequest(customer_id=CUSTOMER_ID)  # No content or template
        with pytest.raises(HTTPException) as exc_info:
            send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert exc_info.value.status_code == 422

    def test_meta_error_raises_503(self):
        db = self._make_send_db(window_open=True)
        payload = SendMessageRequest(customer_id=CUSTOMER_ID, content="Hi")
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            side_effect=HTTPException(status_code=503, detail="INTEGRATION_ERROR"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert exc_info.value.status_code == 503

    def test_send_to_lead(self):
        """Test sending to a lead (no customer_id, uses lead_id path)."""
        import uuid
        lead_id = str(uuid.uuid4())
        org_chain, _ = _chain(_ORG_ROW)
        lead_chain, _ = _chain(_LEAD_ROW)
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [_MSG_ROW]
        insert_chain.execute.return_value = ir
        for m in ["insert"]:
            getattr(insert_chain, m).return_value = insert_chain

        def tbl(name):
            if name == "organisations":
                return org_chain
            if name == "leads":
                return lead_chain
            return insert_chain
        db = MagicMock()
        db.table.side_effect = tbl

        payload = SendMessageRequest(
            lead_id=lead_id,
            template_name="welcome_lead",
        )
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            result = send_whatsapp_message(db, ORG_ID, USER_ID, payload)
        assert result["status"] == "sent"