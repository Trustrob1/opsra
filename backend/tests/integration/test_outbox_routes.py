"""
backend/tests/integration/test_outbox_routes.py
-------------------------------------------------
Integration tests for M01-4 outbox HTTP routes:

  GET  /api/v1/outbox
  POST /api/v1/outbox
  POST /api/v1/outbox/{id}/approve
  POST /api/v1/outbox/{id}/cancel

Patterns applied:
  Pattern 28: org["org_id"] = org's ID, org["id"] = user's ID
  Pattern 32: autouse fixture pops overrides on teardown — never .clear()
  Pattern 34: auth rejections assert != 200 or in (401, 403)
  Pattern 6:  error paths assert status_code only — never resp.json()["success"]

Test classes:
  TestListOutboxRoute    (4 tests)
  TestQueueOutboxRoute   (4 tests)
  TestApproveOutboxRoute (5 tests)
  TestCancelOutboxRoute  (5 tests)

Total: 18 integration tests
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

ORG_ID    = "00000000-0000-0000-0001-000000000001"
LEAD_ID   = "00000000-0000-0000-0001-000000000002"
USER_ID   = "00000000-0000-0000-0001-000000000003"
OUTBOX_ID = "00000000-0000-0000-0001-000000000004"

client = TestClient(app)


def _org_member():
    """
    Standard authenticated user fixture.
    Pattern 28: org_id = org["org_id"], user_id = org["id"]
    Pattern 37: role is at org["roles"]["template"]
    """
    return {
        "org_id": ORG_ID,        # used by routes as org["org_id"]
        "id": USER_ID,           # used by routes as org["id"]
        "roles": {"template": "sales_agent"},
        "permissions": {},
    }


def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    db.table.return_value = chain
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.is_.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.maybe_single.return_value = chain
    res = MagicMock()
    res.data = []
    res.count = 0
    chain.execute.return_value = res
    return db


# ===========================================================================
# TestListOutboxRoute
# ===========================================================================

class TestListOutboxRoute:

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_supabase]    = _mock_db
        app.dependency_overrides[get_current_org] = _org_member
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_list_outbox_returns_200(self):
        with patch(
            "app.routers.whatsapp.list_outbox",
            return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
        ):
            resp = client.get("/api/v1/outbox")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "items" in body["data"]

    def test_list_outbox_passes_org_id_to_service(self):
        with patch(
            "app.routers.whatsapp.list_outbox",
            return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
        ) as mock_list:
            client.get("/api/v1/outbox")
        kwargs = mock_list.call_args.kwargs
        assert kwargs.get("org_id") == ORG_ID

    def test_list_outbox_passes_status_filter(self):
        with patch(
            "app.routers.whatsapp.list_outbox",
            return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
        ) as mock_list:
            client.get("/api/v1/outbox?status=pending")
        kwargs = mock_list.call_args.kwargs
        assert kwargs.get("status") == "pending"

    def test_list_outbox_unauthenticated_rejected(self):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.get("/api/v1/outbox")
        assert resp.status_code != 200
        app.dependency_overrides[get_current_org] = _org_member


# ===========================================================================
# TestQueueOutboxRoute
# ===========================================================================

class TestQueueOutboxRoute:

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_supabase]    = _mock_db
        app.dependency_overrides[get_current_org] = _org_member
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_queue_outbox_returns_201_pending(self):
        queued_row = {
            "id": OUTBOX_ID,
            "org_id": ORG_ID,
            "lead_id": LEAD_ID,
            "content": "Hi there",
            "status": "pending",
        }
        with patch(
            "app.routers.whatsapp.queue_outbox_message",
            return_value=queued_row,
        ):
            resp = client.post("/api/v1/outbox", json={
                "lead_id": LEAD_ID,
                "content": "Hi there",
                "source_type": "qualification_reply",
            })
        print(resp.json())
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "pending"

    def test_queue_outbox_passes_org_id_and_user_id_to_service(self):
        with patch(
            "app.routers.whatsapp.queue_outbox_message",
            return_value={"id": OUTBOX_ID, "status": "pending"},
        ) as mock_queue:
            client.post("/api/v1/outbox", json={
                "lead_id": LEAD_ID,
                "content": "Hi",
                "source_type": "first_touch",
            })
        kwargs = mock_queue.call_args.kwargs
        assert kwargs.get("org_id")     == ORG_ID    # org["org_id"]
        assert kwargs.get("queued_by")  == USER_ID   # org["id"]

    def test_queue_outbox_auto_send_returns_sent_status(self):
        sent_row = {
            "id": OUTBOX_ID,
            "org_id": ORG_ID,
            "status": "sent",
        }
        with patch(
            "app.routers.whatsapp.queue_outbox_message",
            return_value=sent_row,
        ):
            resp = client.post("/api/v1/outbox", json={
                "lead_id": LEAD_ID,
                "content": "Auto sent",
                "source_type": "first_touch",
            })
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] == "sent"

    def test_queue_outbox_missing_source_type_returns_422(self):
        resp = client.post("/api/v1/outbox", json={
            "lead_id": LEAD_ID,
            "content": "Hi",
            # source_type omitted — required field
        })
        assert resp.status_code == 422


# ===========================================================================
# TestApproveOutboxRoute
# ===========================================================================

class TestApproveOutboxRoute:

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_supabase]    = _mock_db
        app.dependency_overrides[get_current_org] = _org_member
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_approve_pending_returns_200_and_sent(self):
        sent_row = {"id": OUTBOX_ID, "org_id": ORG_ID, "status": "sent"}
        with patch(
            "app.routers.whatsapp.approve_outbox_message",
            return_value=sent_row,
        ):
            resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/approve")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "sent"

    def test_approve_passes_correct_org_id_and_user_id(self):
        with patch(
            "app.routers.whatsapp.approve_outbox_message",
            return_value={"id": OUTBOX_ID, "status": "sent"},
        ) as mock_approve:
            client.post(f"/api/v1/outbox/{OUTBOX_ID}/approve")
        kwargs = mock_approve.call_args.kwargs
        assert kwargs.get("org_id")    == ORG_ID     # org["org_id"]
        assert kwargs.get("user_id")   == USER_ID    # org["id"]
        assert kwargs.get("outbox_id") == OUTBOX_ID

    def test_approve_nonexistent_returns_404(self):
        from fastapi import HTTPException
        with patch(
            "app.routers.whatsapp.approve_outbox_message",
            side_effect=HTTPException(status_code=404, detail="NOT_FOUND"),
        ):
            resp = client.post("/api/v1/outbox/nonexistent/approve")
        assert resp.status_code == 404

    def test_approve_already_sent_returns_400(self):
        from fastapi import HTTPException
        with patch(
            "app.routers.whatsapp.approve_outbox_message",
            side_effect=HTTPException(
                status_code=400,
                detail="Cannot approve a message with status 'sent'",
            ),
        ):
            resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/approve")
        assert resp.status_code == 400

    def test_approve_unauthenticated_rejected(self):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/approve")
        assert resp.status_code != 200
        app.dependency_overrides[get_current_org] = _org_member


# ===========================================================================
# TestCancelOutboxRoute
# ===========================================================================

class TestCancelOutboxRoute:

    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_supabase]    = _mock_db
        app.dependency_overrides[get_current_org] = _org_member
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_cancel_pending_returns_200_and_cancelled(self):
        cancelled_row = {"id": OUTBOX_ID, "org_id": ORG_ID, "status": "cancelled"}
        with patch(
            "app.routers.whatsapp.cancel_outbox_message",
            return_value=cancelled_row,
        ):
            resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/cancel")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelled"

    def test_cancel_passes_correct_org_id_and_user_id(self):
        with patch(
            "app.routers.whatsapp.cancel_outbox_message",
            return_value={"id": OUTBOX_ID, "status": "cancelled"},
        ) as mock_cancel:
            client.post(f"/api/v1/outbox/{OUTBOX_ID}/cancel")
        kwargs = mock_cancel.call_args.kwargs
        assert kwargs.get("org_id")    == ORG_ID     # org["org_id"]
        assert kwargs.get("user_id")   == USER_ID    # org["id"]
        assert kwargs.get("outbox_id") == OUTBOX_ID

    def test_cancel_already_sent_returns_400(self):
        from fastapi import HTTPException
        with patch(
            "app.routers.whatsapp.cancel_outbox_message",
            side_effect=HTTPException(
                status_code=400,
                detail="Cannot cancel a message with status 'sent'",
            ),
        ):
            resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/cancel")
        assert resp.status_code == 400

    def test_cancel_nonexistent_returns_404(self):
        from fastapi import HTTPException
        with patch(
            "app.routers.whatsapp.cancel_outbox_message",
            side_effect=HTTPException(status_code=404, detail="NOT_FOUND"),
        ):
            resp = client.post("/api/v1/outbox/nonexistent/cancel")
        assert resp.status_code == 404

    def test_cancel_unauthenticated_rejected(self):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.post(f"/api/v1/outbox/{OUTBOX_ID}/cancel")
        assert resp.status_code != 200
        app.dependency_overrides[get_current_org] = _org_member

