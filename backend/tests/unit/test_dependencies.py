"""
tests/unit/test_dependencies.py
--------------------------------
Unit tests for app/dependencies.py.

Strategy: call the async dependency functions directly with injected mock
arguments — no patching of module-level globals needed.

get_current_user(token, supabase)       — both params passed explicitly
get_current_org(current_user, supabase) — both params passed explicitly
has_permission(user, key)               — pure function, no mocks needed

Run with:
    pytest tests/unit/test_dependencies.py -v
"""

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _creds(token: str = "valid.mock.token") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _make_supabase(
    user_id: str = "user-001",
    org_id: str = "org-001",
    is_active: bool = True,
    permissions: dict = None,
    token_valid: bool = True,
):
    """Build a Supabase mock that simulates a user lookup."""
    mock = MagicMock()

    if token_valid:
        mock_auth_user = MagicMock()
        mock_auth_user.user = MagicMock(id=user_id)
        mock.auth.get_user = MagicMock(return_value=mock_auth_user)
    else:
        mock.auth.get_user = MagicMock(side_effect=Exception("Invalid JWT"))

    mock.table.return_value \
        .select.return_value \
        .eq.return_value \
        .single.return_value \
        .execute.return_value.data = {
            "id": user_id,
            "org_id": org_id,
            "email": "agent@acme.example",
            "full_name": "Test Agent",
            "is_active": is_active,
            "whatsapp_number": None,
            "notification_prefs": {},
            "roles": {
                "template": "sales_agent",
                "permissions": permissions or {"view_leads": True},
            },
        }

    return mock


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_token_calls_supabase_get_user(self):
        mock_db = _make_supabase(token_valid=True)
        from app.dependencies import get_current_user

        result = await get_current_user(
            token=_creds("valid.token"),
            supabase=mock_db,
        )
        mock_db.auth.get_user.assert_called_once_with("valid.token")
        assert result is not None

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        mock_db = _make_supabase(token_valid=False)
        from app.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=_creds("bad.token"), supabase=mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_none_user_response_raises_401(self):
        mock_db = MagicMock()
        mock_db.auth.get_user = MagicMock(return_value=MagicMock(user=None))
        from app.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=_creds("token"), supabase=mock_db)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_org
# ---------------------------------------------------------------------------

class TestGetCurrentOrg:
    @pytest.mark.asyncio
    async def test_active_user_returns_full_record(self):
        mock_db = _make_supabase(user_id="user-001", org_id="org-001", is_active=True)
        mock_auth_user = MagicMock(id="user-001")

        from app.dependencies import get_current_org
        result = await get_current_org(current_user=mock_auth_user, supabase=mock_db)

        assert result["org_id"] == "org-001"
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_deactivated_user_raises_401(self):
        mock_db = _make_supabase(is_active=False)
        mock_auth_user = MagicMock(id="user-002")

        from app.dependencies import get_current_org
        with pytest.raises(HTTPException) as exc_info:
            await get_current_org(current_user=mock_auth_user, supabase=mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_user_record_raises_401(self):
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value \
            .single.return_value.execute.side_effect = Exception("Record not found")

        mock_auth_user = MagicMock(id="ghost-user")
        from app.dependencies import get_current_org

        with pytest.raises(HTTPException) as exc_info:
            await get_current_org(current_user=mock_auth_user, supabase=mock_db)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# has_permission — pure function, no mocks needed
# ---------------------------------------------------------------------------

class TestHasPermission:
    def test_granted_permission_returns_true(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": {"view_leads": True}}}
        assert has_permission(user, "view_leads") is True

    def test_denied_permission_returns_false(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": {"view_leads": False}}}
        assert has_permission(user, "view_leads") is False

    def test_missing_permission_key_returns_false(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": {}}}
        assert has_permission(user, "export_data") is False

    def test_null_roles_returns_false(self):
        from app.dependencies import has_permission
        user = {"roles": None}
        assert has_permission(user, "view_leads") is False

    def test_missing_roles_key_returns_false(self):
        from app.dependencies import has_permission
        user = {}
        assert has_permission(user, "view_leads") is False

    def test_null_permissions_returns_false(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": None}}
        assert has_permission(user, "view_leads") is False

    def test_multiple_permissions_independent(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": {"view_leads": True, "delete_leads": False}}}
        assert has_permission(user, "view_leads") is True
        assert has_permission(user, "delete_leads") is False

    def test_non_boolean_true_not_granted(self):
        from app.dependencies import has_permission
        user = {"roles": {"permissions": {"view_leads": "yes"}}}
        assert has_permission(user, "view_leads") is False