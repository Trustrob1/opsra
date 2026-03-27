"""
tests/unit/test_auth_service.py
--------------------------------
Unit tests for app/services/auth_service.py.

Covers:
  - _validate_new_password() boundary conditions
  - request_password_reset() — calls Supabase, never raises on unknown email
  - update_user_password() — happy path, password errors, Supabase errors,
    audit log write, audit log failure is non-fatal

All Supabase calls are mocked using unittest.mock — no network required.

Run with:
    pytest tests/unit/test_auth_service.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.services.auth_service import (
    _validate_new_password,
    request_password_reset,
    update_user_password,
)


# ---------------------------------------------------------------------------
# _validate_new_password
# ---------------------------------------------------------------------------

class TestValidateNewPassword:
    def test_valid_8_chars(self):
        assert _validate_new_password("Abc12345") is None

    def test_valid_long_password(self):
        assert _validate_new_password("A" + "b1" * 63) is None  # 127 chars

    def test_too_short_returns_message(self):
        result = _validate_new_password("Abc123")  # 6 chars
        assert result is not None
        assert "8" in result

    def test_minimum_boundary_7_chars_fails(self):
        assert _validate_new_password("Abc1234") is not None

    def test_minimum_boundary_8_chars_passes(self):
        assert _validate_new_password("Abc12345") is None

    def test_too_long_returns_message(self):
        result = _validate_new_password("A" * 129)
        assert result is not None
        assert "128" in result

    def test_exactly_128_chars_passes(self):
        assert _validate_new_password("A" * 128) is None

    def test_empty_string_fails(self):
        assert _validate_new_password("") is not None


# ---------------------------------------------------------------------------
# request_password_reset
# ---------------------------------------------------------------------------

class TestRequestPasswordReset:
    @pytest.fixture
    def mock_supabase(self):
        client = MagicMock()
        client.auth.reset_password_for_email = MagicMock(return_value=None)
        return client

    @pytest.mark.asyncio
    async def test_returns_sent_true(self, mock_supabase):
        result = await request_password_reset(
            supabase=mock_supabase,
            email="user@example.com",
            redirect_url="https://app.example.com/auth/update-password",
        )
        assert result == {"sent": True}

    @pytest.mark.asyncio
    async def test_lowercases_email_before_calling_supabase(self, mock_supabase):
        await request_password_reset(
            supabase=mock_supabase,
            email="USER@EXAMPLE.COM",
            redirect_url="https://app.example.com/auth/update-password",
        )
        call_args = mock_supabase.auth.reset_password_for_email.call_args
        assert call_args[0][0] == "user@example.com"

    @pytest.mark.asyncio
    async def test_passes_redirect_url_to_supabase(self, mock_supabase):
        redirect = "https://app.example.com/auth/update-password"
        await request_password_reset(
            supabase=mock_supabase,
            email="user@example.com",
            redirect_url=redirect,
        )
        call_kwargs = mock_supabase.auth.reset_password_for_email.call_args[1]
        assert call_kwargs["options"]["redirect_to"] == redirect

    @pytest.mark.asyncio
    async def test_still_returns_sent_true_on_supabase_error(self, mock_supabase):
        """
        Must NOT raise — prevents email enumeration.
        If Supabase returns an error (e.g. unknown email) we silently succeed.
        """
        mock_supabase.auth.reset_password_for_email.side_effect = Exception("Unknown email")
        result = await request_password_reset(
            supabase=mock_supabase,
            email="notreal@example.com",
            redirect_url="https://app.example.com/auth/update-password",
        )
        assert result == {"sent": True}

    @pytest.mark.asyncio
    async def test_still_returns_sent_true_on_unknown_email(self, mock_supabase):
        """Alias of above — critical security contract."""
        mock_supabase.auth.reset_password_for_email.side_effect = Exception("not found")
        result = await request_password_reset(
            supabase=mock_supabase,
            email="ghost@nowhere.com",
            redirect_url="https://app.example.com/auth/update-password",
        )
        assert result == {"sent": True}


# ---------------------------------------------------------------------------
# update_user_password
# ---------------------------------------------------------------------------

class TestUpdateUserPassword:
    @pytest.fixture
    def mock_supabase(self):
        client = MagicMock()
        client.auth.update_user = MagicMock(return_value=MagicMock())
        # Audit log chain: .table().insert().execute()
        client.table.return_value.insert.return_value.execute.return_value = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_happy_path_returns_updated_true(self, mock_supabase):
        result = await update_user_password(
            supabase=mock_supabase,
            access_token="token123",
            new_password="NewPassword1",
            org_id="org-uuid",
            user_id="user-uuid",
        )
        assert result == {"updated": True}

    @pytest.mark.asyncio
    async def test_calls_supabase_update_user(self, mock_supabase):
        await update_user_password(
            supabase=mock_supabase,
            access_token="token123",
            new_password="NewPassword1",
            org_id="org-uuid",
            user_id="user-uuid",
        )
        mock_supabase.auth.update_user.assert_called_once_with(
            {"password": "NewPassword1"}
        )

    @pytest.mark.asyncio
    async def test_writes_audit_log(self, mock_supabase):
        await update_user_password(
            supabase=mock_supabase,
            access_token="token123",
            new_password="NewPassword1",
            org_id="org-uuid",
            user_id="user-uuid",
        )
        mock_supabase.table.assert_called_with("audit_logs")
        insert_call = mock_supabase.table.return_value.insert.call_args[0][0]
        assert insert_call["action"] == "auth.password_updated"
        assert insert_call["org_id"] == "org-uuid"
        assert insert_call["user_id"] == "user-uuid"
        assert "password" in str(insert_call["new_value"])

    @pytest.mark.asyncio
    async def test_audit_log_redacts_password(self, mock_supabase):
        """Password must never appear in the audit log in plaintext."""
        await update_user_password(
            supabase=mock_supabase,
            access_token="token123",
            new_password="SuperSecret1",
            org_id="org-uuid",
            user_id="user-uuid",
        )
        insert_call = mock_supabase.table.return_value.insert.call_args[0][0]
        assert "SuperSecret1" not in str(insert_call)
        assert "***REDACTED***" in str(insert_call["new_value"])

    @pytest.mark.asyncio
    async def test_raises_value_error_for_short_password(self, mock_supabase):
        with pytest.raises(ValueError, match="8"):
            await update_user_password(
                supabase=mock_supabase,
                access_token="token123",
                new_password="Short1",  # 6 chars
                org_id="org-uuid",
                user_id="user-uuid",
            )

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_supabase_failure(self, mock_supabase):
        mock_supabase.auth.update_user.side_effect = Exception("Token expired")
        with pytest.raises(RuntimeError, match="reset link"):
            await update_user_password(
                supabase=mock_supabase,
                access_token="expired_token",
                new_password="NewPassword1",
                org_id="org-uuid",
                user_id="user-uuid",
            )

    @pytest.mark.asyncio
    async def test_audit_log_failure_is_non_fatal(self, mock_supabase):
        """Audit log failure must NOT prevent the password from being updated."""
        mock_supabase.table.return_value.insert.return_value.execute.side_effect = (
            Exception("DB error")
        )
        # Should NOT raise — audit failure is logged but not surfaced
        result = await update_user_password(
            supabase=mock_supabase,
            access_token="token123",
            new_password="NewPassword1",
            org_id="org-uuid",
            user_id="user-uuid",
        )
        assert result == {"updated": True}

    @pytest.mark.asyncio
    async def test_password_not_sent_to_supabase_if_validation_fails(self, mock_supabase):
        """Supabase must not be called if local validation fails."""
        with pytest.raises(ValueError):
            await update_user_password(
                supabase=mock_supabase,
                access_token="token123",
                new_password="short",
                org_id="org-uuid",
                user_id="user-uuid",
            )
        mock_supabase.auth.update_user.assert_not_called()