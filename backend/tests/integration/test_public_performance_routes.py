"""
tests/integration/test_public_performance_routes.py
------------------------------------------------------
Integration tests for PERF-1A public PIN-gated routes.
No JWT — auth is PIN session token only.
All UUIDs valid format (Pattern 24).
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase

ORG_ID    = "aaaa1001-0000-0000-0000-000000000000"
LOG_ID    = "bbbb2002-0000-0000-0000-000000000000"
DASH_TOKEN = "test_dashboard_token_xyz"


def _make_db(org_row=None, log_row=None):
    db = MagicMock()
    db.table.return_value = db
    db.select.return_value = db
    db.update.return_value = db
    db.insert.return_value = db
    db.eq.return_value = db
    db.limit.return_value = db
    if org_row is not None:
        db.execute.return_value = MagicMock(data=[org_row])
    else:
        db.execute.return_value = MagicMock(data=[])
    return db


@pytest.fixture
def client():
    return TestClient(app)


def _valid_session_token():
    import app.services.performance_service as svc
    return svc.generate_owner_session_token(ORG_ID, DASH_TOKEN)


# ---------------------------------------------------------------------------
# POST /public/owner-dashboard/{token}/verify
# ---------------------------------------------------------------------------

def test_verify_pin_success(client):
    org_row = {
        "id": ORG_ID,
        "name": "Test Org",
        "owner_dashboard_pin": None,
        "health_score_weights": {"sales": 35, "staff": 25, "tasks": 20, "support": 20},
    }
    with patch("app.services.performance_service.verify_owner_dashboard_pin",
               return_value=org_row), \
         patch("app.routers.public_performance._check_lockout"), \
         patch("app.routers.public_performance._clear_lockout"), \
         patch("app.routers.public_performance._record_failed_attempt"):
        db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: db
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/verify",
                        json={"pin": "1234"})
        app.dependency_overrides.pop(get_supabase, None)

    assert r.status_code == 200
    data = r.json()
    assert "session_token" in data
    assert data["org_id"] == ORG_ID


def test_verify_pin_wrong_pin(client):
    with patch("app.services.performance_service.verify_owner_dashboard_pin", return_value=None), \
         patch("app.routers.public_performance._check_lockout"), \
         patch("app.routers.public_performance._record_failed_attempt"):
        db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: db
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/verify",
                        json={"pin": "0000"})
        app.dependency_overrides.pop(get_supabase, None)

    assert r.status_code == 401


def test_verify_pin_locked_out(client):
    from fastapi import HTTPException as FastAPIHTTPException
    with patch("app.routers.public_performance._check_lockout",
               side_effect=FastAPIHTTPException(status_code=429, detail="Too many failed attempts")):
        db = _make_db()
        app.dependency_overrides[get_supabase] = lambda: db
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/verify",
                        json={"pin": "1234"})
        app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 429


def test_verify_pin_invalid_format(client):
    """Non-digit PIN rejected by Pydantic validation."""
    db = _make_db()
    app.dependency_overrides[get_supabase] = lambda: db
    r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/verify",
                    json={"pin": "abcd"})
    app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /public/owner-dashboard/{token}/approve
# ---------------------------------------------------------------------------

def test_approve_log_valid_session(client):
    org_row = {"id": ORG_ID}
    with patch("app.services.performance_service.verify_owner_session_token", return_value=True), \
         patch("app.services.performance_service.approve_log", return_value=True):
        db = _make_db(org_row=org_row)
        app.dependency_overrides[get_supabase] = lambda: db
        session = _valid_session_token()
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/approve",
                        json={"log_id": LOG_ID},
                        headers={"Authorization": f"Bearer {session}"})
        app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 200


def test_approve_log_missing_token(client):
    org_row = {"id": ORG_ID}
    db = _make_db(org_row=org_row)
    app.dependency_overrides[get_supabase] = lambda: db
    r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/approve",
                    json={"log_id": LOG_ID})
    app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 401


def test_approve_log_invalid_token(client):
    org_row = {"id": ORG_ID}
    with patch("app.services.performance_service.verify_owner_session_token", return_value=False):
        db = _make_db(org_row=org_row)
        app.dependency_overrides[get_supabase] = lambda: db
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/approve",
                        json={"log_id": LOG_ID},
                        headers={"Authorization": "Bearer bad_token"})
        app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 401


def test_approve_log_unknown_token(client):
    """Token not found in DB → 404."""
    db = _make_db(org_row=None)
    db.execute.return_value = MagicMock(data=[])
    app.dependency_overrides[get_supabase] = lambda: db
    r = client.post(f"/api/v1/public/owner-dashboard/unknown_token/approve",
                    json={"log_id": LOG_ID},
                    headers={"Authorization": "Bearer sometoken"})
    app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /public/owner-dashboard/{token}/flag
# ---------------------------------------------------------------------------

def test_flag_log_valid_session(client):
    org_row = {"id": ORG_ID}
    with patch("app.services.performance_service.verify_owner_session_token", return_value=True), \
         patch("app.services.performance_service.flag_log", return_value=True):
        db = _make_db(org_row=org_row)
        # Users query for notification recipients
        db.execute.side_effect = [
            MagicMock(data=[org_row]),   # org lookup
            MagicMock(data=[{"id": ORG_ID, "roles": {"template": "owner"}}]),  # users lookup
        ]
        app.dependency_overrides[get_supabase] = lambda: db
        session = _valid_session_token()
        r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/flag",
                        json={"log_id": LOG_ID, "note": "Looks low"},
                        headers={"Authorization": f"Bearer {session}"})
        app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 200


def test_flag_log_note_too_long(client):
    """Note > 500 chars rejected by Pydantic."""
    db = _make_db()
    app.dependency_overrides[get_supabase] = lambda: db
    r = client.post(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}/flag",
                    json={"log_id": LOG_ID, "note": "x" * 501},
                    headers={"Authorization": "Bearer tok"})
    app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /public/owner-dashboard/{token}
# ---------------------------------------------------------------------------

def test_get_owner_dashboard_valid_session(client):
    org_row = {"id": ORG_ID, "name": "Test Org",
               "health_score_weights": {"sales": 35, "staff": 25, "tasks": 20, "support": 20}}
    dummy_panels = {"panel_staff": {}, "panel_tasks": {}, "panel_support": {}, "panel_approvals": [], "refreshed_at": ""}
    dummy_health = {"health_score": 78.0, "colour": "green", "components": {}, "weights": {}}
    with patch("app.services.performance_service.verify_owner_session_token", return_value=True), \
         patch("app.services.performance_service.get_owner_dashboard_panels",
               new_callable=AsyncMock, return_value=dummy_panels), \
         patch("app.services.performance_service.get_health_score",
               new_callable=AsyncMock, return_value=dummy_health):
        db = _make_db(org_row=org_row)
        app.dependency_overrides[get_supabase] = lambda: db
        session = _valid_session_token()
        r = client.get(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}",
                       headers={"Authorization": f"Bearer {session}"})
        app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 200
    assert r.json()["org_name"] == "Test Org"


def test_get_owner_dashboard_no_auth(client):
    org_row = {"id": ORG_ID, "name": "Test Org", "health_score_weights": {}}
    db = _make_db(org_row=org_row)
    app.dependency_overrides[get_supabase] = lambda: db
    r = client.get(f"/api/v1/public/owner-dashboard/{DASH_TOKEN}")
    app.dependency_overrides.pop(get_supabase, None)
    assert r.status_code == 401
