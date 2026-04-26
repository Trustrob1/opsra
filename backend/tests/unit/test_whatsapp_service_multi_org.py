# tests/unit/test_whatsapp_service_multi_org.py
# MULTI-ORG-WA-1 — Unit tests for per-org WhatsApp credentials
#
# Tests:
#   1. _get_org_wa_credentials returns DB values when both columns are set
#   2. _get_org_wa_credentials falls back to settings when DB phone_id is null
#   3. _get_org_wa_credentials falls back to settings when DB token is null
#   4. _get_org_wa_credentials returns (None,None,None) on DB exception — S14
#   5. Two orgs get different credentials — core multi-org assertion
#   6. _call_meta_send uses passed token in Authorization header
#   7. _call_meta_send falls back to settings.META_WHATSAPP_TOKEN when token=None

import pytest
from unittest.mock import MagicMock, patch


ORG_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ORG_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _mock_db_returning(phone_id, token, waba_id=None):
    db = MagicMock()
    row = {}
    if phone_id is not None:
        row["whatsapp_phone_id"] = phone_id
    if token is not None:
        row["whatsapp_access_token"] = token
    if waba_id is not None:
        row["whatsapp_waba_id"] = waba_id
    (
        db.table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
        .data
    ) = row
    return db


class TestGetOrgWaCredentials:

    def test_returns_db_values_when_both_set(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = _mock_db_returning("phone-ovaloop", "token-ovaloop", "waba-ovaloop")
        phone_id, token, waba_id = _get_org_wa_credentials(db, ORG_A)
        assert phone_id == "phone-ovaloop"
        assert token == "token-ovaloop"
        assert waba_id == "waba-ovaloop"

    def test_falls_back_to_settings_when_phone_id_null(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = _mock_db_returning(None, "token-from-db")
        with patch("app.services.whatsapp_service.settings") as mock_settings:
            mock_settings.META_WHATSAPP_PHONE_ID = "settings-phone-id"
            mock_settings.META_WHATSAPP_TOKEN = None
            mock_settings.META_WABA_ID = None
            phone_id, token, _ = _get_org_wa_credentials(db, ORG_A)
        assert phone_id == "settings-phone-id"
        assert token == "token-from-db"

    def test_falls_back_to_settings_when_token_null(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = _mock_db_returning("phone-from-db", None)
        with patch("app.services.whatsapp_service.settings") as mock_settings:
            mock_settings.META_WHATSAPP_PHONE_ID = None
            mock_settings.META_WHATSAPP_TOKEN = "settings-token"
            mock_settings.META_WABA_ID = None
            _, token, _ = _get_org_wa_credentials(db, ORG_A)
        assert token == "settings-token"

    def test_returns_none_tuple_on_db_exception_s14(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = MagicMock()
        db.table.side_effect = Exception("DB failure")
        with patch("app.services.whatsapp_service.settings") as mock_settings:
            mock_settings.META_WHATSAPP_PHONE_ID = None
            mock_settings.META_WHATSAPP_TOKEN = None
            mock_settings.META_WABA_ID = None
            result = _get_org_wa_credentials(db, ORG_A)
        assert result == (None, None, None)

    def test_two_orgs_get_different_credentials(self):
        """Core multi-org assertion — Royal Rest and Ovaloop stay separate."""
        from app.services.whatsapp_service import _get_org_wa_credentials

        db_ovaloop   = _mock_db_returning("phone-ovaloop",   "token-ovaloop",   "waba-ovaloop")
        db_royalrest = _mock_db_returning("phone-royalrest", "token-royalrest", "waba-royalrest")

        phone_a, token_a, waba_a = _get_org_wa_credentials(db_ovaloop, ORG_A)
        phone_b, token_b, waba_b = _get_org_wa_credentials(db_royalrest, ORG_B)

        assert phone_a == "phone-ovaloop"
        assert phone_b == "phone-royalrest"
        assert token_a != token_b
        assert waba_a != waba_b

    def test_returns_none_waba_when_column_absent_from_row(self):
        """waba_id gracefully None when column not yet populated."""
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = _mock_db_returning("phone-x", "token-x", waba_id=None)
        with patch("app.services.whatsapp_service.settings") as mock_settings:
            mock_settings.META_WHATSAPP_PHONE_ID = None
            mock_settings.META_WHATSAPP_TOKEN = None
            mock_settings.META_WABA_ID = None
            _, _, waba_id = _get_org_wa_credentials(db, ORG_A)
        assert waba_id is None


class TestCallMetaSendTokenParam:

    def test_uses_passed_token_in_auth_header(self):
        """When token is passed, it appears in Authorization header."""
        from app.services.whatsapp_service import _call_meta_send
        phone_id = "phone-123"
        payload = {"messaging_product": "whatsapp", "to": "2348000000001", "type": "text"}

        captured = {}

        def fake_post(url, json=None, headers=None):
            captured["auth"] = headers.get("Authorization")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"messages": [{"id": "wamid.abc"}]}
            return resp

        with patch("app.services.whatsapp_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = fake_post
            mock_client_cls.return_value = mock_client

            _call_meta_send(phone_id, payload, token="org-specific-token")

        assert captured["auth"] == "Bearer org-specific-token"

    def test_falls_back_to_settings_token_when_none_passed(self):
        """When token=None, falls back to settings.META_WHATSAPP_TOKEN."""
        from app.services.whatsapp_service import _call_meta_send
        phone_id = "phone-123"
        payload = {"messaging_product": "whatsapp", "to": "2348000000001", "type": "text"}

        captured = {}

        def fake_post(url, json=None, headers=None):
            captured["auth"] = headers.get("Authorization")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"messages": [{"id": "wamid.abc"}]}
            return resp

        with patch("app.services.whatsapp_service.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = fake_post
            mock_client_cls.return_value = mock_client

            with patch("app.services.whatsapp_service.settings") as mock_settings:
                mock_settings.META_WHATSAPP_TOKEN = "fallback-settings-token"
                _call_meta_send(phone_id, payload, token=None)

        assert captured["auth"] == "Bearer fallback-settings-token"
