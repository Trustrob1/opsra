"""
tests/unit/test_9e_additions.py
Phase 9E unit tests:
  - TestStorageUpload       (tickets.py — storage stub replaced)
  - TestNewDeviceAlert      (auth.py   — _check_new_device helper)
  - TestGetCustomerWindowOpen (customers.py — window_open field)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase
from app.dependencies import get_current_org

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
ORG_ID      = "00000000-0000-0000-0000-000000000001"
USER_ID     = "00000000-0000-0000-0000-000000000002"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000003"


# ══════════════════════════════════════════════════════════════════════════════
# TestStorageUpload — 9E-2
# ══════════════════════════════════════════════════════════════════════════════

def _org_member():
    return {
        "id": USER_ID, "org_id": ORG_ID,
        "roles": {"template": "ops_manager", "permissions": {}},
    }


class TestStorageUpload:
    """Phase 9E: attachment upload now writes bytes to Supabase Storage."""

    def setup_method(self):
        self.mock_db = MagicMock()
        # storage chain
        self.storage_chain = MagicMock()
        self.storage_chain.upload.return_value = MagicMock()
        self.mock_db.storage.from_.return_value = self.storage_chain

        # ticket_messages / audit chain — any table call succeeds
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[{
            "id": "00000000-0000-0000-0000-000000000010",
            "ticket_id": "00000000-0000-0000-0000-000000000011",
            "file_name": "test.jpg", "storage_path": "tickets/x/y/z.jpg",
            "file_type": "image/jpeg", "file_size_bytes": 100,
        }])
        chain.select.return_value = chain
        chain.eq.return_value     = chain
        chain.is_.return_value    = chain
        chain.maybe_single.return_value = chain
        chain.insert.return_value = chain

        def tbl(name):
            if name == "ticket_attachments": return chain
            if name == "tickets":            return chain
            if name == "audit_logs":         return chain
            return MagicMock()

        self.mock_db.table.side_effect = tbl
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_upload_calls_storage_with_correct_bucket(self):
        """Phase 9E: storage.from_('ticket-attachments').upload() must be called."""
        jpg = b'\xff\xd8\xff\xe0' + b'\x00' * 100   # minimal JPEG magic bytes
        with patch("app.routers.tickets._FILETYPE_AVAILABLE", False):
            self.client.post(
                "/api/v1/tickets/00000000-0000-0000-0000-000000000011/attachments",
                files={"file": ("photo.jpg", jpg, "image/jpeg")},
            )
        self.mock_db.storage.from_.assert_called_with("ticket-attachments")
        self.storage_chain.upload.assert_called_once()

    def test_upload_storage_failure_returns_502(self):
        """If storage upload fails, 502 is returned and no DB row is inserted."""
        self.storage_chain.upload.side_effect = Exception("Storage unavailable")
        jpg = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        with patch("app.routers.tickets._FILETYPE_AVAILABLE", False):
            resp = self.client.post(
                "/api/v1/tickets/00000000-0000-0000-0000-000000000011/attachments",
                files={"file": ("photo.jpg", jpg, "image/jpeg")},
            )
        assert resp.status_code == 502
        # Attachment DB insert must NOT have been called
        self.mock_db.table.return_value.insert.assert_not_called()

    def test_upload_storage_called_before_db_insert(self):
        """Storage upload precedes DB insert — verifiable via call order."""
        call_order = []
        self.storage_chain.upload.side_effect = lambda **kw: call_order.append("storage") or MagicMock()

        orig_tbl = self.mock_db.table.side_effect
        def tbl_spy(name):
            chain = orig_tbl(name)
            if name == "ticket_attachments":
                orig_insert = chain.insert
                def insert_spy(row):
                    call_order.append("db_insert")
                    return orig_insert(row)
                chain.insert = insert_spy
            return chain
        self.mock_db.table.side_effect = tbl_spy

        jpg = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        with patch("app.routers.tickets._FILETYPE_AVAILABLE", False):
            self.client.post(
                "/api/v1/tickets/00000000-0000-0000-0000-000000000011/attachments",
                files={"file": ("photo.jpg", jpg, "image/jpeg")},
            )
        # storage must come before db_insert in call order
        assert call_order.index("storage") < call_order.index("db_insert")


# ══════════════════════════════════════════════════════════════════════════════
# TestNewDeviceAlert — 9E-4
# ══════════════════════════════════════════════════════════════════════════════

class TestNewDeviceAlert:
    """Phase 9E: _check_new_device inserts row and sends alerts on new IP."""

    def _make_db(self, existing_device=None, org_phone_id="phone_id_123"):
        """Build a multi-table mock for device check tests."""
        db = MagicMock()

        device_chain = MagicMock()
        device_chain.select.return_value       = device_chain
        device_chain.eq.return_value           = device_chain
        device_chain.maybe_single.return_value = device_chain
        device_chain.update.return_value       = device_chain
        device_chain.insert.return_value       = device_chain
        device_chain.execute.return_value      = MagicMock(data=existing_device)

        notif_chain = MagicMock()
        notif_chain.insert.return_value  = notif_chain
        notif_chain.execute.return_value = MagicMock(data=[])

        org_chain = MagicMock()
        org_chain.select.return_value       = org_chain
        org_chain.eq.return_value           = org_chain
        org_chain.maybe_single.return_value = org_chain
        org_chain.execute.return_value      = MagicMock(
            data={"whatsapp_phone_id": org_phone_id} if org_phone_id else None
        )

        def tbl(name):
            if name == "user_devices":    return device_chain
            if name == "notifications":   return notif_chain
            if name == "organisations":   return org_chain
            return MagicMock()

        db.table.side_effect = tbl
        self._device_chain = device_chain
        self._notif_chain  = notif_chain
        return db

    def test_new_ip_inserts_device_row(self):
        from app.routers.auth import _check_new_device
        db = self._make_db(existing_device=None)
        _check_new_device(db, USER_ID, ORG_ID, "Tunde", None, "1.2.3.4", "Mozilla/5.0")
        self._device_chain.insert.assert_called_once()
        inserted = self._device_chain.insert.call_args[0][0]
        assert inserted["user_id"]    == USER_ID
        assert inserted["ip_address"] == "1.2.3.4"

    def test_new_ip_creates_notification(self):
        from app.routers.auth import _check_new_device
        db = self._make_db(existing_device=None)
        _check_new_device(db, USER_ID, ORG_ID, "Tunde", None, "1.2.3.4", "")
        self._notif_chain.insert.assert_called_once()
        notif = self._notif_chain.insert.call_args[0][0]
        assert notif["type"] == "security_alert"
        assert notif["user_id"] == USER_ID

    def test_known_ip_updates_last_seen_not_insert(self):
        from app.routers.auth import _check_new_device
        existing = {"id": "00000000-0000-0000-0000-000000000099"}
        db = self._make_db(existing_device=existing)
        _check_new_device(db, USER_ID, ORG_ID, "Tunde", None, "1.2.3.4", "")
        # update called, insert NOT called
        self._device_chain.update.assert_called_once()
        self._device_chain.insert.assert_not_called()
        # notification NOT created for known device
        self._notif_chain.insert.assert_not_called()

    def test_no_whatsapp_skips_wa_send(self):
        """If user has no whatsapp_number, no WhatsApp call is made."""
        from app.routers.auth import _check_new_device
        db = self._make_db(existing_device=None)
        with patch("app.routers.auth._META_WA_TOKEN", "sometoken"), \
             patch("app.routers.auth.httpx") as mock_httpx:
            _check_new_device(db, USER_ID, ORG_ID, "Tunde",
                              whatsapp_number=None,  # no number
                              ip_address="5.5.5.5", user_agent="")
            mock_httpx.post.assert_not_called()

    def test_device_check_failure_does_not_raise(self):
        """S14: _check_new_device must never raise even if DB is broken."""
        from app.routers.auth import _check_new_device
        db = MagicMock()
        db.table.side_effect = RuntimeError("DB is down")
        # Must not raise
        _check_new_device(db, USER_ID, ORG_ID, "Tunde", None, "1.2.3.4", "")


# ══════════════════════════════════════════════════════════════════════════════
# TestGetCustomerWindowOpen — 9E-5
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCustomerWindowOpen:
    """Phase 9E: GET /customers/{id} includes server-computed window_open field."""

    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = _org_member
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_window_open_true_when_is_window_open_returns_true(self):
        customer_data = {
            "id": CUSTOMER_ID, "org_id": ORG_ID,
            "full_name": "Amaka", "assigned_to": None,
        }
        with patch("app.routers.customers.whatsapp_service.get_customer",
                   return_value=customer_data), \
             patch("app.routers.customers.whatsapp_service._is_window_open",
                   return_value=True):
            resp = self.client.get(f"/api/v1/customers/{CUSTOMER_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["window_open"] is True

    def test_window_open_false_when_is_window_open_returns_false(self):
        customer_data = {
            "id": CUSTOMER_ID, "org_id": ORG_ID,
            "full_name": "Emeka", "assigned_to": None,
        }
        with patch("app.routers.customers.whatsapp_service.get_customer",
                   return_value=customer_data), \
             patch("app.routers.customers.whatsapp_service._is_window_open",
                   return_value=False):
            resp = self.client.get(f"/api/v1/customers/{CUSTOMER_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["window_open"] is False

    def test_window_open_defaults_false_on_error(self):
        """S14: if _is_window_open raises, window_open = False (safe default)."""
        customer_data = {
            "id": CUSTOMER_ID, "org_id": ORG_ID,
            "full_name": "Tunde", "assigned_to": None,
        }
        with patch("app.routers.customers.whatsapp_service.get_customer",
                   return_value=customer_data), \
             patch("app.routers.customers.whatsapp_service._is_window_open",
                   side_effect=Exception("DB error")):
            resp = self.client.get(f"/api/v1/customers/{CUSTOMER_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["window_open"] is False
