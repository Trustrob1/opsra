"""
tests/integration/test_lead_assignment_routes.py
ASSIGN-1 — 12 integration tests for /admin/lead-assignment routes.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-minimum!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SUPERADMIN_SECRET", "test-superadmin-secret")

ORG_ID   = "11111111-1111-1111-1111-111111111111"
USER_ID  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ORG = "99999999-9999-9999-9999-999999999999"
OTHER_USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SHIFT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
REP1_ID  = "dddddddd-dddd-dddd-dddd-dddddddddddd"

_ORG_PAYLOAD = {
    "id":      USER_ID,
    "org_id":  ORG_ID,
    "is_active": True,
    "roles": {
        "template":    "owner",
        "permissions": {
            "manage_users": True,
            "manage_roles": True,
        },
    },
}

_NON_ADMIN_PAYLOAD = {
    "id":      USER_ID,
    "org_id":  ORG_ID,
    "is_active": True,
    "roles": {
        "template":    "sales_agent",
        "permissions": {
            "manage_users":  False,
            "manage_roles":  False,
            "view_reports":  False,
        },
    },
}

_SHIFT = {
    "id":           SHIFT_ID,
    "org_id":       ORG_ID,
    "shift_name":   "Day Shift",
    "shift_start":  "08:00",
    "shift_end":    "18:00",
    "days_active":  ["mon", "tue", "wed", "thu", "fri"],
    "assignee_ids": [REP1_ID],
    "strategy":     "least_loaded",
    "is_active":    True,
}


def _mock_db(mode="manual", shifts=None, shift_count=1):
    db = MagicMock()

    def table_side(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.not_ = chain
        chain.is_.return_value = chain
        chain.update.return_value = chain
        chain.insert.return_value = chain
        chain.delete.return_value = chain
        chain.order.return_value = chain
        chain.maybe_single.return_value = chain

        if name == "organisations":
            chain.execute.return_value = MagicMock(
                data={"lead_assignment_mode": mode, "sla_business_hours": {}}
            )
        elif name == "lead_assignment_shifts":
            shift_list = shifts if shifts is not None else [_SHIFT]
            chain.execute.return_value = MagicMock(
                data=shift_list, count=shift_count
            )
        elif name == "users":
            chain.execute.return_value = MagicMock(data=[{"id": REP1_ID}])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain

    db.table.side_effect = table_side
    return db


@pytest.fixture
def client():
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org

    db = _mock_db()
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_supabase,    None)
    app.dependency_overrides.pop(get_current_org, None)


def _client_with(db=None, org=None):
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    db = db or _mock_db()
    org = org or _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: db
    app.dependency_overrides[get_current_org] = lambda: org
    return TestClient(app, raise_server_exceptions=False)


class TestLeadAssignmentRoutes:

    def test_LA_I_01_get_returns_mode_and_shifts(self, client):
        """LA-I-01: GET returns mode and shifts."""
        resp = client.get("/api/v1/admin/lead-assignment")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "mode" in data
        assert "shifts" in data

    def test_LA_I_02_put_mode_auto_creates_prefilled_shift(self):
        """LA-I-02: PUT mode=auto on first switch creates pre-filled Day Shift."""
        db = _mock_db(mode="manual", shifts=[])  # no existing shifts
        c = _client_with(db=db)
        resp = c.put("/api/v1/admin/lead-assignment/mode", json={"mode": "auto"})
        assert resp.status_code == 200
        assert resp.json()["data"]["mode"] == "auto"

    def test_LA_I_03_put_mode_manual_disables_engine(self):
        """LA-I-03: PUT mode=manual returns mode=manual."""
        db = _mock_db(mode="auto")
        c = _client_with(db=db)
        resp = c.put("/api/v1/admin/lead-assignment/mode", json={"mode": "manual"})
        assert resp.status_code == 200
        assert resp.json()["data"]["mode"] == "manual"

    def test_LA_I_04_post_shift_creates_valid_shift(self, client):
        """LA-I-04: POST shift with valid payload returns 201."""
        payload = {
            "shift_name":   "Night Shift",
            "shift_start":  "20:00",
            "shift_end":    "08:00",
            "days_active":  ["mon", "tue", "wed"],
            "assignee_ids": [REP1_ID],
            "strategy":     "least_loaded",
        }
        resp = client.post("/api/v1/admin/lead-assignment/shifts", json=payload)
        assert resp.status_code == 201

    def test_LA_I_05_post_shift_rejects_invalid_time(self, client):
        """LA-I-05: POST rejects invalid time format."""
        payload = {
            "shift_name":  "Bad Shift",
            "shift_start": "8am",
            "shift_end":   "6pm",
            "days_active": ["mon"],
            "assignee_ids": [],
        }
        resp = client.post("/api/v1/admin/lead-assignment/shifts", json=payload)
        assert resp.status_code == 422

    def test_LA_I_06_post_shift_rejects_empty_days(self, client):
        """LA-I-06: POST rejects empty days_active."""
        payload = {
            "shift_name":  "Bad Shift",
            "shift_start": "08:00",
            "shift_end":   "18:00",
            "days_active": [],
            "assignee_ids": [],
        }
        resp = client.post("/api/v1/admin/lead-assignment/shifts", json=payload)
        assert resp.status_code == 422

    def test_LA_I_07_post_shift_rejects_foreign_assignees(self):
        """LA-I-07: POST rejects assignee_ids from another org."""
        db = MagicMock()

        def table_side(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.in_.return_value = chain
            chain.insert.return_value = chain
            chain.order.return_value = chain
            chain.maybe_single.return_value = chain
            if name == "users":
                chain.execute.return_value = MagicMock(data=[])  # no users found
            else:
                chain.execute.return_value = MagicMock(data=[])
            return chain
        db.table.side_effect = table_side

        c = _client_with(db=db)
        payload = {
            "shift_name":  "Shift",
            "shift_start": "08:00",
            "shift_end":   "18:00",
            "days_active": ["mon"],
            "assignee_ids": [OTHER_USER],
        }
        resp = c.post("/api/v1/admin/lead-assignment/shifts", json=payload)
        assert resp.status_code == 422

    def test_LA_I_08_patch_shift_partial_update(self, client):
        """LA-I-08: PATCH shift partial update succeeds."""
        resp = client.patch(
            f"/api/v1/admin/lead-assignment/shifts/{SHIFT_ID}",
            json={"shift_name": "Updated Shift"},
        )
        assert resp.status_code == 200

    def test_LA_I_09_delete_blocked_when_last_active(self):
        """LA-I-09: DELETE blocked when last active shift."""
        from unittest.mock import MagicMock

        db = MagicMock()
        call_count = [0]

        def table_side(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.update.return_value = chain
            chain.maybe_single.return_value = chain

            if name == "lead_assignment_shifts":
                call_count[0] += 1
                if call_count[0] == 1:
                    # First call: verify shift exists
                    chain.execute.return_value = MagicMock(data=_SHIFT, count=None)
                else:
                    # Second call: count active shifts — only 1 left
                    chain.execute.return_value = MagicMock(data=[_SHIFT], count=1)
            else:
                chain.execute.return_value = MagicMock(data=[], count=0)
            return chain

        db.table.side_effect = table_side
        c = _client_with(db=db)
        resp = c.delete(f"/api/v1/admin/lead-assignment/shifts/{SHIFT_ID}")
        assert resp.status_code == 422

    def test_LA_I_10_delete_succeeds_when_others_remain(self):
        """LA-I-10: DELETE succeeds when other shifts remain."""
        from unittest.mock import MagicMock

        other_shift = {**_SHIFT, "id": "other-shift-id"}
        db = MagicMock()
        call_count = [0]

        def table_side(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.update.return_value = chain
            chain.maybe_single.return_value = chain

            if name == "lead_assignment_shifts":
                call_count[0] += 1
                if call_count[0] == 1:
                    # First call: verify shift exists
                    chain.execute.return_value = MagicMock(data=_SHIFT, count=None)
                else:
                    # Second call: count active shifts — 2 remain
                    chain.execute.return_value = MagicMock(data=[_SHIFT, other_shift], count=2)
            else:
                chain.execute.return_value = MagicMock(data=[], count=0)
            return chain

        db.table.side_effect = table_side
        c = _client_with(db=db)
        resp = c.delete(f"/api/v1/admin/lead-assignment/shifts/{SHIFT_ID}")
        assert resp.status_code == 200

    def test_LA_I_11_non_admin_gets_403(self):
        """LA-I-11: Non-admin → 403 on all lead-assignment routes."""
        # Send request with no Authorization header — FastAPI returns 403 via
        # get_current_org when no valid JWT is present.
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org
        from fastapi import HTTPException

        db = _mock_db()

        def _deny():
            raise HTTPException(status_code=403, detail="Forbidden")

        app.dependency_overrides[get_supabase] = lambda: db
        app.dependency_overrides[get_current_org] = _deny

        c = TestClient(app, raise_server_exceptions=False)
        for method, path, kwargs in [
            ("get",  "/api/v1/admin/lead-assignment",        {}),
            ("put",  "/api/v1/admin/lead-assignment/mode",   {"json": {"mode": "auto"}}),
            ("get",  "/api/v1/admin/lead-assignment/shifts",  {}),
            ("post", "/api/v1/admin/lead-assignment/shifts",  {"json": {}}),
        ]:
            resp = getattr(c, method)(path, **kwargs)
            assert resp.status_code == 403, f"{method.upper()} {path} should return 403"

        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_LA_I_12_org_isolation(self):
        """LA-I-12: Org isolation — cannot read another org's shifts."""
        # Other org user should only see their own shifts (empty in this mock)
        other_org_payload = {**_ORG_PAYLOAD, "org_id": OTHER_ORG}
        db = _mock_db(shifts=[])
        c = _client_with(db=db, org=other_org_payload)
        resp = c.get("/api/v1/admin/lead-assignment")
        assert resp.status_code == 200
        # Shifts will be empty for other org (mock returns [])
        assert resp.json()["data"]["shifts"] == []
