"""
tests/integration/test_customer_routes.py

Integration tests for /api/v1/customers/* routes.
All DB access is mocked via get_supabase override (Pattern 3).
get_current_org is also overridden — both must be set even for 422 tests.

Pattern compliance:
  - Pattern 3: always override get_supabase (even for 422 tests)
  - Pattern 4: restore class fixture after per-test override
  - Pattern 8: separate insert mock for write operations
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

ORG_ID = "org-test-cust"
USER_ID = "user-test-cust"
CUSTOMER_ID = "cust-abc-123"

_FAKE_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "email": "admin@test.com",
    "full_name": "Test Admin",
    "roles": {"template": "owner", "permissions": {}},
}

_CUSTOMER = {
    "id": CUSTOMER_ID,
    "org_id": ORG_ID,
    "full_name": "Emeka Obi",
    "whatsapp": "2348001234567",
    "phone": "2348001234567",
    "email": "emeka@test.com",
    "business_name": "Emeka Stores",
    "business_type": "supermarket",
    "location": "Lagos",
    "branches": "2-3",
    "assigned_to": None,
    "assigned_user": None,
    "whatsapp_opt_in": True,
    "whatsapp_opt_out_broadcasts": False,
    "onboarding_complete": False,
    "churn_risk": "low",
    "deleted_at": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def client():
    """TestClient with both dependencies overridden for the whole class."""
    mock_db = MagicMock()
    app.dependency_overrides[get_supabase] = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: _FAKE_ORG
    with TestClient(app) as c:
        c._mock_db = mock_db
        yield c
    app.dependency_overrides.pop(get_supabase, None)
    app.dependency_overrides.pop(get_current_org, None)


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
# GET /api/v1/customers
# ---------------------------------------------------------------------------

class TestListCustomers:
    def test_200_returns_paginated_envelope(self, client):
        chain, _ = _make_chain([_CUSTOMER], count=1)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"]
        assert body["data"]["total"] == 1

    def test_200_empty_list(self, client):
        chain, _ = _make_chain([], count=0)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers")
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    def test_filter_by_churn_risk(self, client):
        chain, _ = _make_chain([_CUSTOMER], count=1)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers?churn_risk=high")
        assert resp.status_code == 200

    def test_filter_by_onboarding_complete(self, client):
        chain, _ = _make_chain([], count=0)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers?onboarding_complete=false")
        assert resp.status_code == 200

    def test_pagination_params(self, client):
        chain, _ = _make_chain([], count=0)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers?page=2&page_size=10")
        body = resp.json()
        assert resp.status_code == 200
        assert body["data"]["page"] == 2
        assert body["data"]["page_size"] == 10


# ---------------------------------------------------------------------------
# GET /api/v1/customers/{customer_id}
# ---------------------------------------------------------------------------

class TestGetCustomer:
    def test_200_returns_customer(self, client):
        chain, _ = _make_chain(_CUSTOMER)
        client._mock_db.table.return_value = chain
        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == CUSTOMER_ID

    def test_404_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers/nonexistent")
        assert resp.status_code == 404

    def test_404_empty_list(self, client):
        """Pattern 9 — empty list is treated as not-found."""
        chain, _ = _make_chain([])
        client._mock_db.table.return_value = chain
        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/customers/{customer_id}
# ---------------------------------------------------------------------------

class TestUpdateCustomer:
    def test_200_updates_full_name(self, client):
        # First call: _customer_or_404  → returns existing customer
        # Second call: update  → returns updated customer
        # Third call: audit_logs insert → don't care
        existing_chain, _ = _make_chain(_CUSTOMER)
        updated_record = {**_CUSTOMER, "full_name": "Emeka Obi Updated"}
        update_chain, _ = _make_chain([updated_record])

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "customers":
                return existing_chain if call_count["n"] == 1 else update_chain
            return update_chain  # audit_logs
        client._mock_db.table.side_effect = tbl

        resp = client.patch(
            f"/api/v1/customers/{CUSTOMER_ID}",
            json={"full_name": "Emeka Obi Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Restore for subsequent tests (Pattern 4)
        client._mock_db.table.side_effect = None

    def test_404_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.patch(
            f"/api/v1/customers/nonexistent",
            json={"full_name": "X"},
        )
        assert resp.status_code == 404

    def test_422_missing_body(self, client):
        """Pattern 3 — 422 test still requires get_supabase override (already set)."""
        chain, _ = _make_chain(_CUSTOMER)
        client._mock_db.table.return_value = chain
        # Send invalid body that fails Pydantic validation
        resp = client.patch(
            f"/api/v1/customers/{CUSTOMER_ID}",
            json={"whatsapp_opt_in": "not-a-bool"},
        )
        assert resp.status_code == 422

    def test_200_update_opt_in(self, client):
        existing_chain, _ = _make_chain(_CUSTOMER)
        updated = {**_CUSTOMER, "whatsapp_opt_in": False}
        update_chain, _ = _make_chain([updated])

        call_count = {"n": 0}
        def tbl(name):
            call_count["n"] += 1
            if name == "customers":
                return existing_chain if call_count["n"] == 1 else update_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.patch(
            f"/api/v1/customers/{CUSTOMER_ID}",
            json={"whatsapp_opt_in": False},
        )
        assert resp.status_code == 200
        client._mock_db.table.side_effect = None


# ---------------------------------------------------------------------------
# GET /api/v1/customers/{customer_id}/messages
# ---------------------------------------------------------------------------

class TestGetCustomerMessages:
    def test_200_returns_message_history(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        msg = {"id": "m1", "direction": "outbound", "content": "Hello"}
        msg_chain, _ = _make_chain([msg], count=1)

        def tbl(name):
            if name == "customers":
                return cust_chain
            if name == "whatsapp_messages":
                return msg_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["items"] == [msg]
        client._mock_db.table.side_effect = None

    def test_404_customer_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers/bad-id/messages")
        assert resp.status_code == 404

    def test_pagination_defaults(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        msg_chain, _ = _make_chain([], count=0)

        def tbl(name):
            return cust_chain if name == "customers" else msg_chain
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/messages")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["page"] == 1
        assert body["page_size"] == 20
        client._mock_db.table.side_effect = None


# ---------------------------------------------------------------------------
# GET /api/v1/customers/{customer_id}/tasks
# ---------------------------------------------------------------------------

class TestGetCustomerTasks:
    def test_200_returns_tasks(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        task = {"id": "t1", "title": "Follow up call", "source_module": "whatsapp"}
        tasks_chain, _ = _make_chain([task])

        def tbl(name):
            if name == "customers":
                return cust_chain
            if name == "tasks":
                return tasks_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/tasks")
        assert resp.status_code == 200
        assert resp.json()["data"] == [task]
        client._mock_db.table.side_effect = None

    def test_200_empty_tasks(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        tasks_chain, _ = _make_chain([])

        def tbl(name):
            return cust_chain if name == "customers" else tasks_chain
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/tasks")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        client._mock_db.table.side_effect = None


# ---------------------------------------------------------------------------
# GET /api/v1/customers/{customer_id}/nps
# ---------------------------------------------------------------------------

class TestGetCustomerNps:
    def test_200_returns_nps_history(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        nps = {"id": "n1", "score": 5, "trigger_type": "quarterly"}
        nps_chain, _ = _make_chain([nps])

        def tbl(name):
            if name == "customers":
                return cust_chain
            if name == "nps_responses":
                return nps_chain
            return MagicMock()
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/nps")
        assert resp.status_code == 200
        assert resp.json()["data"] == [nps]
        client._mock_db.table.side_effect = None

    def test_200_empty_nps(self, client):
        cust_chain, _ = _make_chain(_CUSTOMER)
        nps_chain, _ = _make_chain([])

        def tbl(name):
            return cust_chain if name == "customers" else nps_chain
        client._mock_db.table.side_effect = tbl

        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/nps")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        client._mock_db.table.side_effect = None

    def test_404_customer_not_found(self, client):
        chain, _ = _make_chain(None)
        client._mock_db.table.return_value = chain
        resp = client.get("/api/v1/customers/bad-id/nps")
        assert resp.status_code == 404