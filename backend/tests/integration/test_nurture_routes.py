"""
tests/integration/test_nurture_routes.py
Integration tests for GET/PATCH /api/v1/admin/nurture-config — M01-10a

Patterns applied:
  Pattern 32 — dependency_overrides teardown via pop(), never clear()
  Pattern 44 — override get_current_org directly
  Pattern 24 — valid UUID format for all test constants
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

ORG_ID = "00000000-0000-0000-0000-000000000001"
USER_ID = "00000000-0000-0000-0000-000000000003"

_ORG_PAYLOAD = {
    "id":     USER_ID,
    "org_id": ORG_ID,
    "roles":  {
        "template": "owner",
        "permissions": {"manage_users": True},
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def auth_db(client):
    """
    Override get_current_org + get_supabase for nurture config tests.
    Pattern 32 — pop() teardown.
    Pattern 44 — override get_current_org directly.
    """
    from app.main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    mock_db    = MagicMock()
    chain      = MagicMock()
    chain.execute.return_value = MagicMock(data={
        "nurture_track_enabled":   False,
        "conversion_attempt_days": 14,
        "nurture_interval_days":   7,
        "nurture_sequence":        [],
    })
    for method in (
        "select", "insert", "update", "eq", "neq", "in_", "is_",
        "gte", "lte", "order", "limit", "maybe_single",
    ):
        getattr(chain, method).return_value = chain
    mock_db.table.return_value = chain

    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: mock_db

    yield client, mock_db

    # Pattern 32 — pop(), never clear()
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/nurture-config
# ---------------------------------------------------------------------------

def test_get_nurture_config_returns_200(auth_db):
    client, _ = auth_db
    resp = client.get(
        "/api/v1/admin/nurture-config",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "data" in body


def test_get_nurture_config_includes_all_fields(auth_db):
    client, _ = auth_db
    resp = client.get(
        "/api/v1/admin/nurture-config",
        headers={"Authorization": "Bearer fake-token"},
    )
    data = resp.json()["data"]
    for field in (
        "nurture_track_enabled",
        "conversion_attempt_days",
        "nurture_interval_days",
        "nurture_sequence",
    ):
        assert field in data, f"Missing field: {field}"


def test_get_nurture_config_returns_defaults_when_db_returns_empty(client):
    from app.main import app
    from app.dependencies import get_current_org
    from app.database import get_supabase

    mock_db = MagicMock()
    chain   = MagicMock()
    chain.execute.return_value = MagicMock(data=None)
    for m in ("select", "eq", "maybe_single"):
        getattr(chain, m).return_value = chain
    mock_db.table.return_value = chain

    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: mock_db

    try:
        resp = client.get(
            "/api/v1/admin/nurture-config",
            headers={"Authorization": "Bearer fake-token"},
        )
        data = resp.json()["data"]
        assert data["nurture_track_enabled"]   is False
        assert data["conversion_attempt_days"] == 14
        assert data["nurture_interval_days"]   == 7
        assert data["nurture_sequence"]        == []
    finally:
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)


def test_get_nurture_config_requires_auth(client):
    resp = client.get("/api/v1/admin/nurture-config")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/nurture-config
# ---------------------------------------------------------------------------

def test_patch_nurture_config_returns_200(auth_db):
    client, mock_db = auth_db
    mock_db.table.return_value.execute.return_value = MagicMock(data=[{
        "nurture_track_enabled": True,
        "conversion_attempt_days": 21,
        "nurture_interval_days": 7,
        "nurture_sequence": [],
    }])

    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_track_enabled": True, "conversion_attempt_days": 21},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_patch_nurture_config_no_fields_returns_ok(auth_db):
    """Empty payload (no fields set) returns 200 with 'No changes' message."""
    client, _ = auth_db
    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200


def test_patch_nurture_config_validates_conversion_attempt_days(auth_db):
    """conversion_attempt_days < 1 fails Pydantic validation → 422."""
    client, _ = auth_db
    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"conversion_attempt_days": 0},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 422


def test_patch_nurture_config_validates_nurture_interval_days(auth_db):
    """nurture_interval_days > 365 fails validation → 422."""
    client, _ = auth_db
    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_interval_days": 999},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 422


def test_patch_nurture_config_accepts_false_toggle(auth_db):
    """nurture_track_enabled=False must be accepted (not filtered as falsy)."""
    client, mock_db = auth_db
    mock_db.table.return_value.execute.return_value = MagicMock(data=[{
        "nurture_track_enabled": False,
    }])

    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_track_enabled": False},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200


def test_patch_nurture_config_accepts_empty_sequence(auth_db):
    """nurture_sequence=[] (clearing the sequence) must be accepted."""
    client, mock_db = auth_db
    mock_db.table.return_value.execute.return_value = MagicMock(data=[{
        "nurture_sequence": [],
    }])

    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_sequence": []},
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200


def test_patch_nurture_config_requires_auth(client):
    resp = client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_track_enabled": True},
    )
    assert resp.status_code in (401, 403)


def test_patch_nurture_config_writes_audit_log(auth_db):
    """Update must write an audit log entry."""
    client, mock_db = auth_db
    mock_db.table.return_value.execute.return_value = MagicMock(data=[{}])

    client.patch(
        "/api/v1/admin/nurture-config",
        json={"nurture_track_enabled": True},
        headers={"Authorization": "Bearer fake-token"},
    )

    audit_inserts = [
        c[0][0] for c in mock_db.table.return_value.insert.call_args_list
        if c[0][0].get("action") == "nurture_config.updated"
    ]
    assert len(audit_inserts) >= 1