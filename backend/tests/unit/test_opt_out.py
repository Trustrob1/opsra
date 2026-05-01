"""
tests/unit/test_opt_out.py
---------------------------
9E-I — Unit tests for WhatsApp opt-out / opt-in keyword handling.

Imports from app.utils.opt_out (standalone module) so tests run
independently of whether the webhooks.py patches have been applied.
"""
from __future__ import annotations

import ast
import os
import pytest
from unittest.mock import MagicMock, patch

with open(__file__) as _f:
    ast.parse(_f.read())


def _make_db_with_update_capture(updates_list: list):
    db = MagicMock()

    def capture_update(data):
        updates_list.append(data)
        m = MagicMock()
        m.eq.return_value = m
        m.execute.return_value.data = []
        return m

    db.table.return_value.update.side_effect = capture_update
    return db


class TestHandleOptKeywords:

    def _fn(self):
        from app.utils.opt_out import handle_opt_keywords
        return handle_opt_keywords

    def test_stop_sets_customer_opted_out_true(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="STOP", sender_phone="+2348001234567",
                                org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is True
        assert updates and updates[0] == {"whatsapp_opted_out": True}

    def test_stop_whitespace_and_case_insensitive(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="  Stop  ", sender_phone="+2348001234567",
                                org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is True
        assert updates[0] == {"whatsapp_opted_out": True}

    def test_unsubscribe_keyword_also_opts_out(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="unsubscribe", sender_phone="+2348001234567",
                                org_id="org-1", customer_id=None, lead_id="lead-1")
        assert result is True
        assert updates[0] == {"whatsapp_opted_out": True}

    def test_stop_on_lead_when_no_customer(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="quit", sender_phone="+2348001234567",
                                org_id="org-1", customer_id=None, lead_id="lead-99")
        assert result is True
        assert updates[0] == {"whatsapp_opted_out": True}

    def test_start_sets_opted_out_false(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="start", sender_phone="+2348001234567",
                                org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is True
        assert updates[0] == {"whatsapp_opted_out": False}

    def test_subscribe_keyword_opts_in(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="subscribe", sender_phone="+2348001234567",
                                org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is True
        assert updates[0] == {"whatsapp_opted_out": False}

    def test_normal_message_returns_false_no_db_write(self):
        db = MagicMock()
        result = self._fn()(db=db, content="Hello, I need help with my order",
                            sender_phone="+2348001234567",
                            org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is False
        db.table.assert_not_called()

    def test_opt_out_reply_sent_to_sender_phone(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        sent_payloads = []

        def capture_send(phone_id, payload, token=None):
            sent_payloads.append(payload)
            return {"messages": [{"id": "meta-123"}]}

        with patch("app.utils.opt_out._get_org_wa_credentials",
                   return_value=("phone-id-1", "token-abc", "waba-1")):
            with patch("app.utils.opt_out._call_meta_send", side_effect=capture_send):
                self._fn()(db=db, content="STOP", sender_phone="+2348001234567",
                           org_id="org-1", customer_id="cust-1", lead_id=None)

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["to"] == "+2348001234567"
        body = sent_payloads[0]["text"]["body"].lower()
        assert "unsubscribed" in body or "stop" in body or "opted" in body

    def test_opt_in_reply_sent_to_sender(self):
        updates = []
        db = _make_db_with_update_capture(updates)
        sent_payloads = []

        def capture_send(phone_id, payload, token=None):
            sent_payloads.append(payload)
            return {"messages": [{"id": "meta-456"}]}

        with patch("app.utils.opt_out._get_org_wa_credentials",
                   return_value=("phone-id-1", "token-abc", "waba-1")):
            with patch("app.utils.opt_out._call_meta_send", side_effect=capture_send):
                self._fn()(db=db, content="start", sender_phone="+2348001234567",
                           org_id="org-1", customer_id="cust-1", lead_id=None)

        assert len(sent_payloads) == 1
        body = sent_payloads[0]["text"]["body"].lower()
        assert "subscribed" in body or "welcome" in body or "back" in body

    def test_s14_db_exception_returns_false_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("Supabase connection lost")
        result = self._fn()(db=db, content="stop", sender_phone="+2348001234567",
                            org_id="org-1", customer_id="cust-1", lead_id=None)
        assert result is False

    def test_no_record_does_not_raise(self):
        db = MagicMock()
        with patch("app.utils.opt_out._get_org_wa_credentials", return_value=(None, None, None)):
            result = self._fn()(db=db, content="stop", sender_phone="+2348001234567",
                                org_id="org-1", customer_id=None, lead_id=None)
        assert result is True
        db.table.assert_not_called()


class TestTokenAuditI0:

    def test_no_access_token_returns_none_tuple(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id": "phone-123", "whatsapp_access_token": None,
                "whatsapp_waba_id": "waba-123", "whatsapp_connected": False,
            }
        with patch.dict(os.environ, {"META_WHATSAPP_TOKEN": "env-token-must-not-be-used"}):
            _, access_token, _ = _get_org_wa_credentials(db, "org-1")
        assert access_token is None
        assert access_token != "env-token-must-not-be-used"

    def test_no_token_with_connected_true_logs_warning(self, caplog):
        import logging
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id": "phone-123", "whatsapp_access_token": None,
                "whatsapp_waba_id": "waba-123", "whatsapp_connected": True,
            }
        with caplog.at_level(logging.WARNING, logger="app.services.whatsapp_service"):
            _get_org_wa_credentials(db, "org-bad")
        assert any(
            "whatsapp_connected=True" in r.message and "null" in r.message.lower()
            for r in caplog.records
        )

    def test_valid_token_returned_correctly(self):
        from app.services.whatsapp_service import _get_org_wa_credentials
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value.data = {
                "whatsapp_phone_id": "phone-abc", "whatsapp_access_token": "EAAxxxDBtoken",
                "whatsapp_waba_id": "waba-abc", "whatsapp_connected": True,
            }
        phone_id, access_token, waba_id = _get_org_wa_credentials(db, "org-ok")
        assert phone_id == "phone-abc"
        assert access_token == "EAAxxxDBtoken"
        assert waba_id == "waba-abc"

    def test_call_meta_send_raises_if_no_token(self):
        from fastapi import HTTPException
        from app.services.whatsapp_service import _call_meta_send
        with pytest.raises(HTTPException) as exc_info:
            _call_meta_send(phone_id="phone-123", meta_payload={}, token=None)
        assert exc_info.value.status_code == 503
