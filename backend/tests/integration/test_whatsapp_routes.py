"""
tests/integration/test_whatsapp_routes.py

Integration tests for Module 02 WhatsApp routes:
  POST  /api/v1/messages/send
  GET/POST /api/v1/broadcasts, approve, cancel
  GET/POST/PATCH /api/v1/templates
  GET/PUT /api/v1/drip-sequences

Pattern compliance:
  - Pattern 3: always override get_supabase (even for 422 tests)
  - Pattern 4: restore class fixture after per-test override
  - Pattern 8: separate insert mock for write operations
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

ORG_ID = "org-wa-test"
USER_ID = "user-wa-test"
BROADCAST_ID = str(uuid.uuid4())
TEMPLATE_ID = str(uuid.uuid4())
CUSTOMER_ID = "00000000-0000-0000-0000-000000000001"

_FAKE_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "email": "admin@test.com",
    "full_name": "Test Admin",
    "roles": {"template": "owner", "permissions": {}},
}

_FAKE_ORG_SALES = {
    **_FAKE_ORG,
    "roles": {"template": "sales_agent", "permissions": {}},
}

_CUSTOMER = {
    "id": CUSTOMER_ID,
    "org_id": ORG_ID,
    "full_name": "Ada Okafor",
    "whatsapp": "2348001234567",
    "phone": "2348001234567",
    "deleted_at": None,
}

_BROADCAST = {
    "id": BROADCAST_ID,
    "org_id": ORG_ID,
    "name": "Feature launch",
    "template_id": TEMPLATE_ID,
    "status": "draft",
    "scheduled_at": None,
    "created_by": USER_ID,
}

_TEMPLATE = {
    "id": TEMPLATE_ID,
    "org_id": ORG_ID,
    "name": "renewal_reminder",
    "category": "utility",
    "body": "Hi {{customer_name}}",
    "variables": ["customer_name"],
    "meta_status": "pending",
}

_TEMPLATE_REJECTED = {**_TEMPLATE, "meta_status": "rejected"}

_META_RESPONSE = {"messages": [{"id": "meta-xyz-999"}]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chain(data, count=None):
    chain = MagicMock()
    result = MagicMock()
    result.data = data
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 0
    )
    chain.execute.return_value = result
    for m in ["select", "eq", "is_", "order", "range", "limit",
               "maybe_single", "update", "insert"]:
        getattr(chain, m).return_value = chain
    return chain, result


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def client():
    mock_db = MagicMock()
    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _FAKE_ORG
    with TestClient(app) as c:
        c._mock_db = mock_db
        yield c
    app.dependency_overrides.pop(get_supabase, None)
    app.dependency_overrides.pop(get_current_org, None)


# ---------------------------------------------------------------------------
# POST /api/v1/messages/send
# ---------------------------------------------------------------------------

class TestSendMessage:
    def _setup_send_db(self, mock_db, window_open=True):
        org_chain, _ = _make_chain({"whatsapp_phone_id": "phone123"})
        cust_chain, _ = _make_chain(_CUSTOMER)
        expires = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
        window_chain, _ = _make_chain(
            [{"window_open": True, "window_expires_at": expires}]
            if window_open else []
        )
        # Pattern 8: the service hits whatsapp_messages TWICE —
        #   call 1 → SELECT window check → window_chain
        #   call 2 → INSERT the message  → insert_chain
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [{"id": "msg-1", "status": "sent"}]
        insert_chain.execute.return_value = ir
        insert_chain.insert.return_value = insert_chain

        wa_calls = {"n": 0}

        def tbl(name):
            if name == "organisations":
                return org_chain
            if name == "customers":
                return cust_chain
            if name == "whatsapp_messages":
                wa_calls["n"] += 1
                return window_chain if wa_calls["n"] == 1 else insert_chain
            return insert_chain
        mock_db.table.side_effect = tbl

    def test_200_send_free_form_window_open(self, client):
        self._setup_send_db(client._mock_db, window_open=True)
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            resp = client.post(
                "/api/v1/messages/send",
                json={"customer_id": CUSTOMER_ID, "content": "Hello Ada!"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        client._mock_db.table.side_effect = None

    def test_200_send_template(self, client):
        self._setup_send_db(client._mock_db, window_open=False)
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            resp = client.post(
                "/api/v1/messages/send",
                json={
                    "customer_id": CUSTOMER_ID,
                    "template_name": "renewal_reminder",
                },
            )
        assert resp.status_code == 200
        client._mock_db.table.side_effect = None

    def test_400_free_form_window_closed(self, client):
        self._setup_send_db(client._mock_db, window_open=False)
        with patch(
            "app.services.whatsapp_service._call_meta_send",
            return_value=_META_RESPONSE,
        ):
            resp = client.post(
                "/api/v1/messages/send",
                json={"customer_id": CUSTOMER_ID, "content": "No template"},
            )
        assert resp.status_code == 400
        client._mock_db.table.side_effect = None

    def test_422_no_recipient(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post(
            "/api/v1/messages/send",
            json={"content": "Hi"},
        )
        assert resp.status_code == 422

    def test_422_no_content_or_template(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post(
            "/api/v1/messages/send",
            json={"customer_id": CUSTOMER_ID},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/broadcasts
# ---------------------------------------------------------------------------

class TestListBroadcasts:
    def test_200_returns_broadcasts(self, client):
        chain, _ = _make_chain([_BROADCAST], count=1)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/broadcasts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["name"] == "Feature launch"

    def test_200_empty(self, client):
        chain, _ = _make_chain([], count=0)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/broadcasts")
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/broadcasts
# ---------------------------------------------------------------------------

class TestCreateBroadcast:
    def test_201_creates_draft(self, client):
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [_BROADCAST]
        insert_chain.execute.return_value = ir
        insert_chain.insert.return_value = insert_chain
        client._mock_db.table.return_value = insert_chain

        resp = client.post(
            "/api/v1/broadcasts",
            json={
                "name": "Feature launch",
                "template_id": TEMPLATE_ID,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "draft"

    def test_422_missing_template_id(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post("/api/v1/broadcasts", json={"name": "No template"})
        assert resp.status_code == 422

    def test_422_missing_name(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post(
            "/api/v1/broadcasts",
            json={"template_id": TEMPLATE_ID},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/broadcasts/{broadcast_id}
# ---------------------------------------------------------------------------

class TestGetBroadcast:
    def test_200_returns_broadcast(self, client):
        chain, _ = _make_chain(_BROADCAST)
        client._mock_db.table.return_value = chain
        resp = client.get(f"/api/v1/broadcasts/{BROADCAST_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == BROADCAST_ID

    def test_404_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/broadcasts/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/broadcasts/{broadcast_id}/approve
# ---------------------------------------------------------------------------

class TestApproveBroadcast:
    def test_200_draft_becomes_sending(self, client):
        fetch_chain, _ = _make_chain(_BROADCAST)
        approved = {**_BROADCAST, "status": "sending"}
        update_chain, _ = _make_chain([approved])

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts":
                return fetch_chain if call_count["n"] == 1 else update_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.post(f"/api/v1/broadcasts/{BROADCAST_ID}/approve")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "sending"
        client._mock_db.table.side_effect = None

    def test_400_already_sent(self, client):
        sent = {**_BROADCAST, "status": "sent"}
        chain, _ = _make_chain(sent)
        client._mock_db.table.return_value = chain
        resp = client.post(f"/api/v1/broadcasts/{BROADCAST_ID}/approve")
        assert resp.status_code == 400

    def test_404_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post("/api/v1/broadcasts/bad-id/approve")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/broadcasts/{broadcast_id}/cancel
# ---------------------------------------------------------------------------

class TestCancelBroadcast:
    def test_200_draft_cancelled(self, client):
        fetch_chain, _ = _make_chain(_BROADCAST)
        cancelled = {**_BROADCAST, "status": "cancelled"}
        update_chain, _ = _make_chain([cancelled])

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "broadcasts":
                return fetch_chain if call_count["n"] == 1 else update_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.post(f"/api/v1/broadcasts/{BROADCAST_ID}/cancel")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelled"
        client._mock_db.table.side_effect = None

    def test_400_sent_cannot_cancel(self, client):
        sent = {**_BROADCAST, "status": "sent"}
        chain, _ = _make_chain(sent)
        client._mock_db.table.return_value = chain
        resp = client.post(f"/api/v1/broadcasts/{BROADCAST_ID}/cancel")
        assert resp.status_code == 400

    def test_400_sending_cannot_cancel(self, client):
        sending = {**_BROADCAST, "status": "sending"}
        chain, _ = _make_chain(sending)
        client._mock_db.table.return_value = chain
        resp = client.post(f"/api/v1/broadcasts/{BROADCAST_ID}/cancel")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/v1/templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_200_returns_templates(self, client):
        chain, _ = _make_chain([_TEMPLATE])
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/templates")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert body["data"][0]["name"] == "renewal_reminder"

    def test_200_empty_list(self, client):
        chain, _ = _make_chain([])
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/templates")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/templates
# ---------------------------------------------------------------------------

class TestCreateTemplate:
    def test_200_creates_pending_template(self, client):
        new_tmpl = {**_TEMPLATE, "id": str(uuid.uuid4())}
        insert_chain = MagicMock()
        ir = MagicMock()
        ir.data = [new_tmpl]
        insert_chain.execute.return_value = ir
        insert_chain.insert.return_value = insert_chain
        client._mock_db.table.return_value = insert_chain

        resp = client.post(
            "/api/v1/templates",
            json={
                "name": "renewal_reminder",
                "category": "utility",
                "body": "Hi {{customer_name}}",
                "variables": ["customer_name"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["meta_status"] == "pending"

    def test_422_invalid_category(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post(
            "/api/v1/templates",
            json={"name": "t", "category": "promotional", "body": "hi"},
        )
        assert resp.status_code in (400, 422)

    def test_422_missing_body(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.post(
            "/api/v1/templates",
            json={"name": "t", "category": "utility"},
        )
        assert resp.status_code == 422

    def test_200_valid_categories(self, client):
        for cat in ("marketing", "utility", "authentication"):
            new_tmpl = {**_TEMPLATE, "category": cat, "id": str(uuid.uuid4())}
            insert_chain = MagicMock()
            ir = MagicMock()
            ir.data = [new_tmpl]
            insert_chain.execute.return_value = ir
            insert_chain.insert.return_value = insert_chain
            client._mock_db.table.return_value = insert_chain

            resp = client.post(
                "/api/v1/templates",
                json={"name": "t", "category": cat, "body": "hello"},
            )
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /api/v1/templates/{template_id}
# ---------------------------------------------------------------------------

class TestUpdateTemplate:
    def test_200_updates_rejected_template(self, client):
        fetch_chain, _ = _make_chain(_TEMPLATE_REJECTED)
        updated = {**_TEMPLATE_REJECTED, "body": "New body", "meta_status": "pending"}
        update_chain, _ = _make_chain([updated])

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "whatsapp_templates":
                return fetch_chain if call_count["n"] == 1 else update_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.patch(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"body": "New body"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["meta_status"] == "pending"
        client._mock_db.table.side_effect = None

    def test_400_approved_template_not_editable(self, client):
        approved = {**_TEMPLATE, "meta_status": "approved"}
        chain, _ = _make_chain(approved)
        client._mock_db.table.return_value = chain
        resp = client.patch(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"body": "New body"},
        )
        assert resp.status_code == 400

    def test_400_pending_template_not_editable(self, client):
        chain, _ = _make_chain(_TEMPLATE)  # meta_status = "pending"
        client._mock_db.table.return_value = chain
        resp = client.patch(
            f"/api/v1/templates/{TEMPLATE_ID}",
            json={"body": "New body"},
        )
        assert resp.status_code == 400

    def test_404_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.patch(
            "/api/v1/templates/bad-id",
            json={"body": "New body"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/drip-sequences
# ---------------------------------------------------------------------------

class TestGetDripSequence:
    def test_200_returns_sequence(self, client):
        drip = {"id": "d1", "name": "Day 1 Welcome", "delay_days": 1, "is_active": True}
        chain, _ = _make_chain([drip])
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/drip-sequences")
        assert resp.status_code == 200
        assert resp.json()["data"] == [drip]

    def test_200_empty(self, client):
        chain, _ = _make_chain([])
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/drip-sequences")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# PUT /api/v1/drip-sequences (Admin only)
# ---------------------------------------------------------------------------

class TestUpdateDripSequence:
    def test_200_owner_can_update(self, client):
        # deactivate chain and insert chain
        deact_chain = MagicMock()
        dr = MagicMock()
        dr.data = []
        deact_chain.execute.return_value = dr
        for m in ["update", "eq"]:
            getattr(deact_chain, m).return_value = deact_chain

        drip_row = {"id": "d-new", "name": "Day 3", "is_active": True}
        ins_chain = MagicMock()
        ir = MagicMock()
        ir.data = [drip_row]
        ins_chain.execute.return_value = ir
        for m in ["insert", "update", "eq"]:
            getattr(ins_chain, m).return_value = ins_chain

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "drip_messages":
                return deact_chain if call_count["n"] <= 1 else ins_chain
            return MagicMock()  # audit_logs
        client._mock_db.table.side_effect = tbl

        resp = client.put(
            "/api/v1/drip-sequences",
            json={
                "messages": [
                    {
                        "name": "Day 3 Sales",
                        "template_id": str(uuid.uuid4()),
                        "delay_days": 3,
                        "sequence_order": 1,
                        "is_active": True,
                        "business_types": [],
                    }
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        client._mock_db.table.side_effect = None

    def test_403_non_owner_forbidden(self, client):
        # Temporarily override get_current_org to a non-owner
        app.dependency_overrides[get_current_org] = lambda: _FAKE_ORG_SALES
        chain, _ = _make_chain([])
        client._mock_db.table.return_value = chain

        resp = client.put(
            "/api/v1/drip-sequences",
            json={"messages": []},
        )
        assert resp.status_code == 403

        # Pattern 4: restore class fixture
        app.dependency_overrides[get_current_org] = lambda: _FAKE_ORG

    def test_422_missing_messages_field(self, client):
        chain, _ = _make_chain([])
        client._mock_db.table.return_value = chain
        resp = client.put("/api/v1/drip-sequences", json={})
        assert resp.status_code == 422

    def test_200_empty_messages_clears_sequence(self, client):
        deact_chain = MagicMock()
        dr = MagicMock()
        dr.data = []
        deact_chain.execute.return_value = dr
        for m in ["update", "eq"]:
            getattr(deact_chain, m).return_value = deact_chain

        client._mock_db.table.return_value = deact_chain

        resp = client.put("/api/v1/drip-sequences", json={"messages": []})
        assert resp.status_code == 200
        assert resp.json()["data"] == []