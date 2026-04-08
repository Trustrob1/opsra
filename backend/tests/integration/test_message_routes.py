"""
tests/integration/test_message_routes.py

Integration tests for:
  GET  /api/v1/messages/unread-counts   (whatsapp.py router)
  GET  /api/v1/leads/{id}/messages      (leads.py router)

These tests verify the full HTTP flow:
  - Route is correctly registered in main.py
  - Auth dependency fires (401 without token)
  - Response envelope shape is correct
  - DB results are correctly returned
  - S14: DB failure returns safe fallback, not 500

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 28 : get_current_org overridden (not get_current_user)
  - Pattern 32 : pop() teardown — never .clear()
  - Pattern 45 : .maybe_single() returns None when 0 rows
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID      = "00000000-0000-0000-0000-000000000001"
LEAD_ID     = "00000000-0000-0000-0000-000000000010"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000020"
USER_ID     = "00000000-0000-0000-0000-000000000099"

# ---------------------------------------------------------------------------
# Shared chain helper — mirrors existing integration test patterns
# ---------------------------------------------------------------------------

def _chain(data=None, count=None):
    chain = MagicMock()
    result = MagicMock()
    result.data  = data if data is not None else []
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 0
    )
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "neq", "in_", "order",
              "range", "limit", "maybe_single", "update", "insert"):
        getattr(chain, m).return_value = chain
    return chain


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_and_db():
    """
    Yield (client, mock_db) with both get_supabase and get_current_org
    overridden. Tears down via pop() — Pattern 32.
    """
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    mock_db = MagicMock()
    org     = {
        "id":    USER_ID,
        "org_id": ORG_ID,
        "roles": {"template": "ops_manager", "permissions": {}},
    }

    app.dependency_overrides[get_supabase]    = lambda: mock_db
    app.dependency_overrides[get_current_org] = lambda: org

    client = TestClient(app, raise_server_exceptions=False)
    yield client, mock_db

    app.dependency_overrides.pop(get_supabase,    None)
    app.dependency_overrides.pop(get_current_org, None)


@pytest.fixture
def unauthenticated_client():
    """Client with NO dependency overrides — auth middleware fires normally."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# GET /api/v1/messages/unread-counts
# ===========================================================================

class TestUnreadCountsIntegration:

    def test_route_exists_returns_200(self, client_and_db):
        """Route is registered and returns 200 with correct envelope."""
        client, mock_db = client_and_db
        mock_db.table.return_value = _chain([])
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "data" in body

    def test_response_has_leads_and_customers_keys(self, client_and_db):
        """Response data always has both 'leads' and 'customers' keys."""
        client, mock_db = client_and_db
        mock_db.table.return_value = _chain([])
        resp = client.get("/api/v1/messages/unread-counts")
        data = resp.json()["data"]
        assert "leads"     in data
        assert "customers" in data

    def test_returns_correct_lead_unread_count(self, client_and_db):
        """Two unread messages for a lead → count of 2 returned."""
        client, mock_db = client_and_db
        rows = [
            {"lead_id": LEAD_ID, "customer_id": None},
            {"lead_id": LEAD_ID, "customer_id": None},
        ]
        mock_db.table.return_value = _chain(rows)
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["leads"].get(LEAD_ID) == 2

    def test_returns_correct_customer_unread_count(self, client_and_db):
        """One unread message for a customer → count of 1 returned."""
        client, mock_db = client_and_db
        rows = [{"lead_id": None, "customer_id": CUSTOMER_ID}]
        mock_db.table.return_value = _chain(rows)
        resp = client.get("/api/v1/messages/unread-counts")
        data = resp.json()["data"]
        assert data["customers"].get(CUSTOMER_ID) == 1

    def test_db_failure_returns_200_with_empty_counts(self, client_and_db):
        """S14: DB error must return empty counts, not 500."""
        client, mock_db = client_and_db
        mock_db.table.side_effect = Exception("Connection refused")
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"leads": {}, "customers": {}}

    def test_requires_authentication(self, unauthenticated_client):
        """Route rejects requests with no JWT — returns 4xx or 5xx (not 200)."""
        resp = unauthenticated_client.get("/api/v1/messages/unread-counts")
        assert resp.status_code != 200

    def test_empty_org_returns_empty_counts(self, client_and_db):
        """No unread messages in org → both dicts are empty."""
        client, mock_db = client_and_db
        mock_db.table.return_value = _chain([])
        resp = client.get("/api/v1/messages/unread-counts")
        data = resp.json()["data"]
        assert data["leads"]     == {}
        assert data["customers"] == {}


# ===========================================================================
# GET /api/v1/leads/{id}/messages
# ===========================================================================

class TestLeadMessagesRouteIntegration:

    def _configure_db(self, mock_db, lead_exists=True, messages=None, count=None):
        messages = messages or []
        count    = count if count is not None else len(messages)
        lead_chain = _chain([{"id": LEAD_ID}] if lead_exists else [])
        msg_chain  = _chain(messages, count=count)

        def _tbl(name):
            if name == "leads":             return lead_chain
            if name == "whatsapp_messages": return msg_chain
            return _chain()

        mock_db.table.side_effect = _tbl

    def test_returns_200_with_messages(self, client_and_db):
        """Happy path: lead exists with messages → 200 + paginated envelope."""
        client, mock_db = client_and_db
        messages = [
            {"id": "m1", "lead_id": LEAD_ID, "content": "Hi",    "direction": "inbound",  "status": "delivered"},
            {"id": "m2", "lead_id": LEAD_ID, "content": "Hello", "direction": "outbound", "status": "read"},
        ]
        self._configure_db(mock_db, messages=messages, count=2)
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"]        is True
        assert body["data"]["total"]  == 2
        assert len(body["data"]["items"]) == 2

    def test_returns_200_with_empty_list(self, client_and_db):
        """Lead exists but has no messages → 200 with total=0."""
        client, mock_db = client_and_db
        self._configure_db(mock_db, messages=[], count=0)
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"]      == 0
        assert body["data"]["items"]      == []

    def test_returns_404_when_lead_not_found(self, client_and_db):
        """Lead does not exist in org → 404."""
        client, mock_db = client_and_db
        self._configure_db(mock_db, lead_exists=False)
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        assert resp.status_code == 404

    def test_pagination_params_accepted(self, client_and_db):
        """page and page_size query params are accepted without error."""
        client, mock_db = client_and_db
        self._configure_db(mock_db, messages=[])
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages?page=2&page_size=10")
        assert resp.status_code == 200

    def test_response_envelope_shape(self, client_and_db):
        """Response has the standard paginated envelope fields."""
        client, mock_db = client_and_db
        self._configure_db(mock_db, messages=[])
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        body = resp.json()
        assert "success"   in body
        assert "data"      in body
        data = body["data"]
        assert "items"     in data
        assert "total"     in data
        assert "page"      in data
        assert "page_size" in data

    def test_requires_authentication(self, unauthenticated_client):
        """Route rejects requests with no JWT — returns 4xx (not 200)."""
        resp = unauthenticated_client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        assert resp.status_code in (401, 403)

    def test_message_fields_returned(self, client_and_db):
        """Each message row includes key fields used by the frontend."""
        client, mock_db = client_and_db
        messages = [{
            "id":        "m1",
            "lead_id":   LEAD_ID,
            "content":   "Hello I need help",
            "direction": "inbound",
            "status":    "delivered",
            "read_at":   None,
            "created_at": "2026-04-08T10:00:00+00:00",
        }]
        self._configure_db(mock_db, messages=messages, count=1)
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/messages")
        item = resp.json()["data"]["items"][0]
        assert item["direction"] == "inbound"
        assert item["content"]   == "Hello I need help"
        assert item["status"]    == "delivered"
