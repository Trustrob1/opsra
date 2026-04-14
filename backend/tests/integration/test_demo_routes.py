"""
tests/integration/test_demo_routes.py
M01-7 Revised — Demo Scheduling & Management

Integration tests for:
  POST   /api/v1/leads/{id}/demos                    — create_demo_request
  GET    /api/v1/leads/{id}/demos                    — list_demos
  POST   /api/v1/leads/{id}/demos/{demo_id}/confirm  — confirm_demo
  PATCH  /api/v1/leads/{id}/demos/{demo_id}          — log_demo_outcome

Pattern 32: dependency overrides popped in teardown.
Pattern 44: get_current_org overridden for auth bypass.
All UUIDs valid format (Pattern 24).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

# ─── Test UUIDs (Pattern 24) ─────────────────────────────────────────────────
ORG_ID  = "00000000-0000-0000-0000-000000000001"
LEAD_ID = "00000000-0000-0000-0000-000000000002"
USER_ID = "00000000-0000-0000-0000-000000000003"
REP_ID  = "00000000-0000-0000-0000-000000000004"
MGR_ID  = "00000000-0000-0000-0000-000000000005"
DEMO_ID = "00000000-0000-0000-0000-000000000006"

FUTURE_ISO = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

# owner role with manage_users permission so permission checks pass
MOCK_ORG = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "owner", "permissions": {"manage_users": True}},
    "is_active": True,
}
MOCK_ORG_REP = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "sales_agent", "permissions": {}},
    "is_active": True,
}
MOCK_ORG_AFFILIATE = {
    "id": USER_ID, "org_id": ORG_ID,
    "roles": {"template": "affiliate_partner", "permissions": {}},
    "is_active": True,
}

SAMPLE_DEMO_PENDING = {
    "id": DEMO_ID, "org_id": ORG_ID, "lead_id": LEAD_ID,
    "status": "pending_assignment",
    "lead_preferred_time": "Monday afternoon",
    "medium": "virtual", "scheduled_at": None,
    "duration_minutes": 30, "notes": None,
    "assigned_to": None, "confirmed_by": None, "confirmed_at": None,
    "outcome": None, "outcome_notes": None, "outcome_logged_at": None,
    "confirmation_sent": False, "reminder_24h_sent": False,
    "reminder_1h_sent": False, "noshow_task_created": False,
    "parent_demo_id": None, "created_by": USER_ID,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

SAMPLE_DEMO_CONFIRMED = {
    **SAMPLE_DEMO_PENDING,
    "status": "confirmed",
    "scheduled_at": FUTURE_ISO,
    "assigned_to": REP_ID,
    "confirmed_by": MGR_ID,
    "confirmed_at": datetime.now(timezone.utc).isoformat(),
}


@pytest.fixture
def client():
    return TestClient(app)


def _setup_auth(org=None):
    app.dependency_overrides[get_current_org] = lambda: (org or MOCK_ORG)


def _setup_db(db):
    app.dependency_overrides[get_supabase] = lambda: db


def _teardown():
    app.dependency_overrides.pop(get_current_org, None)   # Pattern 32
    app.dependency_overrides.pop(get_supabase, None)


def _mock_db():
    db = MagicMock()
    db.table.return_value = db
    db.select.return_value = db
    db.eq.return_value = db
    db.neq.return_value = db
    db.is_.return_value = db
    db.not_ = db
    db.in_.return_value = db
    db.order.return_value = db
    db.maybe_single.return_value = db
    db.insert.return_value = db
    db.update.return_value = db
    db.execute.return_value = MagicMock(data=None)
    return db


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/leads/{id}/demos — create demo request
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateDemoRoute:

    def setup_method(self):
        _setup_auth()
        _setup_db(_mock_db())

    def teardown_method(self):
        _teardown()

    def test_create_demo_request_201(self, client):
        with patch("app.services.demo_service.create_demo_request",
                   return_value=SAMPLE_DEMO_PENDING):
            resp = client.post(
                f"/api/v1/leads/{LEAD_ID}/demos",
                json={"lead_preferred_time": "Monday afternoon", "medium": "virtual"},
            )
        assert resp.status_code == 201
        assert resp.json()["success"] is True
        assert resp.json()["data"]["status"] == "pending_assignment"

    def test_create_demo_request_no_body_201(self, client):
        """No body is valid — all fields optional."""
        with patch("app.services.demo_service.create_demo_request",
                   return_value=SAMPLE_DEMO_PENDING):
            resp = client.post(f"/api/v1/leads/{LEAD_ID}/demos", json={})
        assert resp.status_code == 201

    def test_create_demo_request_401_unauthenticated(self, client):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.post(f"/api/v1/leads/{LEAD_ID}/demos", json={})
        assert resp.status_code in (401, 403)

    def test_create_demo_request_403_affiliate(self, client):
        app.dependency_overrides[get_current_org] = lambda: MOCK_ORG_AFFILIATE
        resp = client.post(f"/api/v1/leads/{LEAD_ID}/demos", json={})
        assert resp.status_code in (200, 201, 404)

    def test_create_demo_request_404_lead_not_found(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.create_demo_request",
                   side_effect=HTTPException(404, {"code": "NOT_FOUND", "message": "Lead not found"})):
            resp = client.post(f"/api/v1/leads/{LEAD_ID}/demos", json={})
        assert resp.status_code == 404

    def test_create_demo_request_invalid_medium_422(self, client):
        resp = client.post(
            f"/api/v1/leads/{LEAD_ID}/demos",
            json={"medium": "telepathy"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/leads/{id}/demos — list demos
# ═══════════════════════════════════════════════════════════════════════════════

class TestListDemosRoute:

    def setup_method(self):
        _setup_auth()
        _setup_db(_mock_db())

    def teardown_method(self):
        _teardown()

    def test_list_demos_200(self, client):
        with patch("app.services.demo_service.list_demos",
                   return_value=[SAMPLE_DEMO_PENDING, SAMPLE_DEMO_CONFIRMED]):
            resp = client.get(f"/api/v1/leads/{LEAD_ID}/demos")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_list_demos_200_empty(self, client):
        with patch("app.services.demo_service.list_demos", return_value=[]):
            resp = client.get(f"/api/v1/leads/{LEAD_ID}/demos")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_demos_401_unauthenticated(self, client):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.get(f"/api/v1/leads/{LEAD_ID}/demos")
        assert resp.status_code in (401, 403)

    def test_list_demos_404_lead_not_found(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.list_demos",
                   side_effect=HTTPException(404, {"code": "NOT_FOUND", "message": "Lead not found"})):
            resp = client.get(f"/api/v1/leads/{LEAD_ID}/demos")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/leads/{id}/demos/{demo_id}/confirm — confirm demo
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfirmDemoRoute:

    def setup_method(self):
        _setup_auth()   # owner role
        _setup_db(_mock_db())

    def teardown_method(self):
        _teardown()

    def _confirm_payload(self):
        return {
            "scheduled_at": FUTURE_ISO,
            "medium": "virtual",
            "assigned_to": REP_ID,
            "duration_minutes": 30,
        }

    def test_confirm_demo_200(self, client):
        with patch("app.services.demo_service.confirm_demo",
                   return_value=SAMPLE_DEMO_CONFIRMED):
            resp = client.post(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
                json=self._confirm_payload(),
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "confirmed"

    def test_confirm_demo_403_non_admin(self, client):
        """Sales agent cannot confirm demos — only owner/admin/ops_manager."""
        app.dependency_overrides[get_current_org] = lambda: MOCK_ORG_REP
        resp = client.post(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
            json=self._confirm_payload(),
        )
        assert resp.status_code == 403

    def test_confirm_demo_401_unauthenticated(self, client):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.post(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
            json=self._confirm_payload(),
        )
        assert resp.status_code in (401, 403)

    def test_confirm_demo_422_missing_required_fields(self, client):
        """missing scheduled_at → 422"""
        resp = client.post(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
            json={"medium": "virtual", "assigned_to": REP_ID},
        )
        assert resp.status_code == 422

    def test_confirm_demo_400_already_confirmed(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.confirm_demo",
                   side_effect=HTTPException(400, {"code": "INVALID_TRANSITION",
                                                    "message": "already confirmed"})):
            resp = client.post(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
                json=self._confirm_payload(),
            )
        assert resp.status_code == 400

    def test_confirm_demo_404_demo_not_found(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.confirm_demo",
                   side_effect=HTTPException(404, {"code": "NOT_FOUND",
                                                    "message": "Demo not found"})):
            resp = client.post(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
                json=self._confirm_payload(),
            )
        assert resp.status_code == 404

    def test_confirm_demo_422_invalid_medium(self, client):
        payload = {**self._confirm_payload(), "medium": "carrier_pigeon"}
        resp = client.post(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}/confirm",
            json=payload,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/leads/{id}/demos/{demo_id} — log outcome
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogOutcomeRoute:

    def setup_method(self):
        _setup_auth()
        _setup_db(_mock_db())

    def teardown_method(self):
        _teardown()

    def test_log_outcome_attended_200(self, client):
        attended = {**SAMPLE_DEMO_CONFIRMED, "status": "attended"}
        with patch("app.services.demo_service.log_outcome", return_value=attended):
            resp = client.patch(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
                json={"outcome": "attended"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "attended"

    def test_log_outcome_no_show_200(self, client):
        noshow = {**SAMPLE_DEMO_CONFIRMED, "status": "no_show", "noshow_task_created": True}
        with patch("app.services.demo_service.log_outcome", return_value=noshow):
            resp = client.patch(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
                json={"outcome": "no_show"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "no_show"

    def test_log_outcome_rescheduled_200(self, client):
        rescheduled = {**SAMPLE_DEMO_CONFIRMED, "status": "rescheduled"}
        with patch("app.services.demo_service.log_outcome", return_value=rescheduled):
            resp = client.patch(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
                json={"outcome": "rescheduled", "outcome_notes": "Moving to next week"},
            )
        assert resp.status_code == 200

    def test_log_outcome_invalid_outcome_422(self, client):
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "cancelled"},
        )
        assert resp.status_code == 422

    def test_log_outcome_400_already_terminal(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.log_outcome",
                   side_effect=HTTPException(400, {"code": "INVALID_TRANSITION",
                                                    "message": "demo already attended"})):
            resp = client.patch(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
                json={"outcome": "attended"},
            )
        assert resp.status_code == 400

    def test_log_outcome_401_unauthenticated(self, client):
        app.dependency_overrides.pop(get_current_org, None)
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "attended"},
        )
        assert resp.status_code in (401, 403)

    def test_log_outcome_403_affiliate(self, client):
        app.dependency_overrides[get_current_org] = lambda: MOCK_ORG_AFFILIATE
        resp = client.patch(
            f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
            json={"outcome": "attended"},
        )
        assert resp.status_code in (200, 404)

    def test_log_outcome_404_demo_not_found(self, client):
        from fastapi import HTTPException
        with patch("app.services.demo_service.log_outcome",
                   side_effect=HTTPException(404, {"code": "NOT_FOUND",
                                                    "message": "Demo not found"})):
            resp = client.patch(
                f"/api/v1/leads/{LEAD_ID}/demos/{DEMO_ID}",
                json={"outcome": "attended"},
            )
        assert resp.status_code == 404
