"""
tests/webhooks/test_whatsapp_inbound.py

Tests for the fully-implemented POST /webhooks/meta/whatsapp handler
and supporting unit tests for:
  - whatsapp_service.get_lead_messages
  - GET /api/v1/leads/{id}/messages route

Replaces / extends TestMetaWhatsappWebhookStub in test_meta_lead_webhook.py.
The stub tests (valid sig → 200, bad sig → 403) remain in test_meta_lead_webhook.py
and are still valid since the route still returns 200 on valid sig.

Patterns followed:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 8  : separate insert chain
  - Pattern 9  : normalise list vs dict
  - Pattern 32 : pop() teardown in class fixtures
  - Pattern 33 : no ILIKE — phone matching is Python-side
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Shared helpers  (mirrors test_meta_lead_webhook.py style)
# ---------------------------------------------------------------------------

APP_SECRET = "test-app-secret"

def _sig(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _chain(data=None, count=None):
    """Chainable Supabase table mock — mirrors test_whatsapp_service._chain."""
    chain = MagicMock()
    result = MagicMock()
    result.data  = data if data is not None else []
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 0
    )
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "order", "range", "limit",
              "maybe_single", "update", "insert", "neq", "gt", "gte", "in_"):
        getattr(chain, m).return_value = chain
    return chain


def _post_wa(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={
            "Content-Type":       "application/json",
            "X-Hub-Signature-256": _sig(body),
        },
    )


def _inbound_payload(from_number="2348001234567", content="Hello there",
                     msg_id="wa-msg-001") -> dict:
    """Build a minimal inbound WhatsApp message payload — Tech Spec §6.2."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata":  {"phone_number_id": "phone-id-1"},
                    "contacts":  [{"profile": {"name": "Emeka Obi"}, "wa_id": from_number}],
                    "messages":  [{
                        "id":        msg_id,
                        "from":      from_number,
                        "timestamp": "1711360920",
                        "type":      "text",
                        "text":      {"body": content},
                    }],
                    "statuses":  [],
                },
            }],
        }],
    }


def _status_payload(meta_msg_id="wa-msg-001", new_status="delivered") -> dict:
    """Build a delivery status update payload — Tech Spec §6.2."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-id-1"},
                    "messages": [],
                    "statuses": [{
                        "id":           meta_msg_id,
                        "status":       new_status,
                        "timestamp":    "1711360950",
                        "recipient_id": "2348001234567",
                    }],
                },
            }],
        }],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "META_APP_SECRET",    APP_SECRET,     raising=False)
    monkeypatch.setattr(cfg.settings, "META_VERIFY_TOKEN",  "test-token",   raising=False)
    monkeypatch.setattr(cfg.settings, "META_WHATSAPP_TOKEN","test-wa-token", raising=False)


@pytest.fixture
def client_factory():
    from app.main import app
    from app.database import get_supabase
    deps = []

    def _make(db_mock):
        app.dependency_overrides[get_supabase] = lambda: db_mock
        deps.append(get_supabase)
        return TestClient(app, raise_server_exceptions=False)

    yield _make
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# Helper: build a DB mock that matches a customer by phone
# ---------------------------------------------------------------------------

def _db_with_customer(phone="2348001234567", customer_id="cust-001",
                      org_id="org-001", assigned_to="user-abc"):
    db = MagicMock()
    customer_row = {
        "id": customer_id, "org_id": org_id,
        "whatsapp": phone, "phone": phone,
        "assigned_to": assigned_to, "deleted_at": None,
    }
    customers_chain = _chain([customer_row])
    leads_chain     = _chain([])        # no lead match needed
    wa_insert       = _chain([{"id": "wa-row-001"}])
    notif_insert    = _chain([])
    audit_chain     = _chain([])

    call_counts = {"n": 0}

    def _tbl(name):
        if name == "customers":   return customers_chain
        if name == "leads":       return leads_chain
        if name == "whatsapp_messages":
            call_counts["n"] += 1
            return wa_insert
        if name == "notifications": return notif_insert
        if name == "audit_logs":    return audit_chain
        # WH-2: organisations query must return empty data (not a bare MagicMock)
        # so the customer triage menu branch evaluates to falsy and falls through.
        if name == "organisations": return _chain([])
        return _chain([])

    db.table.side_effect = _tbl
    return db


def _db_with_lead(phone="2348001234567", lead_id="lead-001",
                  org_id="org-001", assigned_to="user-abc"):
    db = MagicMock()
    lead_row = {
        "id": lead_id, "org_id": org_id,
        "whatsapp": phone, "phone": phone,
        "assigned_to": assigned_to, "deleted_at": None,
    }
    customers_chain = _chain([])   # no customer match
    leads_chain     = _chain([lead_row])
    wa_insert       = _chain([{"id": "wa-row-002"}])
    notif_insert    = _chain([])
    audit_chain     = _chain([])

    def _tbl(name):
        if name == "customers":         return customers_chain
        if name == "leads":             return leads_chain
        if name == "whatsapp_messages": return wa_insert
        if name == "notifications":     return notif_insert
        if name == "audit_logs":        return audit_chain
        return _chain([])

    db.table.side_effect = _tbl
    return db


def _db_unknown_number():
    """DB that matches no customer or lead."""
    db = MagicMock()
    db.table.side_effect = lambda name: _chain([])
    return db


# ===========================================================================
# POST /webhooks/meta/whatsapp — signature verification
# (These extend the stub tests — both should still pass)
# ===========================================================================

class TestWhatsAppWebhookSignature:

    def test_valid_signature_returns_200(self, client_factory):
        db = _db_with_customer()
        client = client_factory(db)
        resp = _post_wa(client, _inbound_payload())
        assert resp.status_code == 200

    def test_bad_signature_returns_403(self, client_factory):
        db = _db_unknown_number()
        client = client_factory(db)
        body = json.dumps(_inbound_payload()).encode()
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={"Content-Type": "application/json",
                     "X-Hub-Signature-256": "sha256=badbad"},
        )
        assert resp.status_code == 403

    def test_missing_signature_returns_403(self, client_factory):
        db = _db_unknown_number()
        client = client_factory(db)
        body = json.dumps(_inbound_payload()).encode()
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    def test_non_whatsapp_object_ignored(self, client_factory):
        db = _db_unknown_number()
        client = client_factory(db)
        payload = {"object": "page", "entry": []}
        resp = _post_wa(client, payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


# ===========================================================================
# POST /webhooks/meta/whatsapp — inbound message processing
# ===========================================================================

class TestWhatsAppInboundMessage:

    def test_message_saved_when_customer_matched(self, client_factory):
        """Happy path: phone matches customer → message inserted to whatsapp_messages."""
        db = _db_with_customer(phone="2348001234567", customer_id="cust-001")
        client = client_factory(db)
        resp = _post_wa(client, _inbound_payload(from_number="2348001234567"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # whatsapp_messages.insert must have been called
        db.table("whatsapp_messages").insert.assert_called()

    def test_message_saved_when_lead_matched(self, client_factory):
        """Phone matches a lead (no customer) → message inserted with lead_id."""
        db = _db_with_lead(phone="2348009999999", lead_id="lead-001")
        client = client_factory(db)
        resp = _post_wa(client, _inbound_payload(from_number="2348009999999"))
        assert resp.status_code == 200
        insert_args = db.table("whatsapp_messages").insert.call_args
        row = insert_args[0][0]
        assert row.get("lead_id") == "lead-001"
        assert row.get("customer_id") is None

    def test_notification_sent_to_assigned_rep(self, client_factory):
        """Assigned rep receives in-app notification when message arrives."""
        db = _db_with_customer(assigned_to="user-abc")
        client = client_factory(db)
        _post_wa(client, _inbound_payload())
        notif_insert = db.table("notifications").insert
        notif_insert.assert_called()
        notif_row = notif_insert.call_args[0][0]
        assert notif_row["user_id"] == "user-abc"
        assert notif_row["type"]    == "whatsapp_reply"

    def test_unknown_number_returns_200_no_insert(self, client_factory):
        """Unknown phone number — no match → no insert, still returns 200."""
        db = _db_unknown_number()
        client = client_factory(db)
        resp = _post_wa(client, _inbound_payload(from_number="0000000000"))
        assert resp.status_code == 200
        # whatsapp_messages.insert should NOT have been called
        db.table("whatsapp_messages").insert.assert_not_called()

    def test_message_content_saved_correctly(self, client_factory):
        """Message content and direction are saved correctly."""
        db = _db_with_customer()
        client = client_factory(db)
        _post_wa(client, _inbound_payload(content="I need help with my POS"))
        row = db.table("whatsapp_messages").insert.call_args[0][0]
        assert row["content"]   == "I need help with my POS"
        assert row["direction"] == "inbound"
        assert row["window_open"] is True

    def test_processing_error_still_returns_200(self, client_factory):
        """S14 — processing error must never cause a non-200 response to Meta."""
        db = MagicMock()
        db.table.side_effect = Exception("DB connection lost")
        client = client_factory(db)
        resp = _post_wa(client, _inbound_payload())
        assert resp.status_code == 200

    def test_empty_entry_list_returns_200(self, client_factory):
        """Empty entries — nothing to process, but always 200."""
        db = _db_unknown_number()
        client = client_factory(db)
        payload = {"object": "whatsapp_business_account", "entry": []}
        resp = _post_wa(client, payload)
        assert resp.status_code == 200


# ===========================================================================
# POST /webhooks/meta/whatsapp — status updates
# ===========================================================================

class TestWhatsAppStatusUpdate:

    def test_delivered_status_updates_message_row(self, client_factory):
        """delivered status → whatsapp_messages row updated with delivered_at."""
        db = MagicMock()
        update_chain = _chain([])
        db.table.side_effect = lambda name: update_chain
        client = client_factory(db)
        resp = _post_wa(client, _status_payload(new_status="delivered"))
        assert resp.status_code == 200
        update_chain.update.assert_called()
        update_args = update_chain.update.call_args[0][0]
        assert update_args["status"] == "delivered"
        assert "delivered_at" in update_args

    def test_read_status_updates_message_row(self, client_factory):
        """read status → whatsapp_messages row updated with read_at."""
        db = MagicMock()
        update_chain = _chain([])
        db.table.side_effect = lambda name: update_chain
        client = client_factory(db)
        resp = _post_wa(client, _status_payload(new_status="read"))
        assert resp.status_code == 200
        update_args = update_chain.update.call_args[0][0]
        assert update_args["status"] == "read"
        assert "read_at" in update_args

    def test_status_update_failure_still_returns_200(self, client_factory):
        """S14 — status update DB failure must not affect the 200 response."""
        db = MagicMock()
        db.table.side_effect = Exception("timeout")
        client = client_factory(db)
        resp = _post_wa(client, _status_payload())
        assert resp.status_code == 200

    def test_sent_status_no_timestamp_added(self, client_factory):
        """sent status only updates status field — no delivered_at or read_at."""
        db = MagicMock()
        update_chain = _chain([])
        db.table.side_effect = lambda name: update_chain
        client = client_factory(db)
        _post_wa(client, _status_payload(new_status="sent"))
        update_args = update_chain.update.call_args[0][0]
        assert update_args["status"] == "sent"
        assert "delivered_at" not in update_args
        assert "read_at"      not in update_args


# ===========================================================================
# whatsapp_service.get_lead_messages (unit tests)
# ===========================================================================

class TestGetLeadMessages:

    ORG_ID  = "org-001"
    LEAD_ID = "00000000-0000-0000-0000-000000000001"

    def _make_db(self, lead_exists=True, messages=None):
        db = MagicMock()
        messages = messages or []

        lead_chain = _chain([{"id": self.LEAD_ID}] if lead_exists else [])
        msg_chain  = _chain(messages, count=len(messages))

        call_n = {"n": 0}

        def _tbl(name):
            if name == "leads":
                return lead_chain
            if name == "whatsapp_messages":
                call_n["n"] += 1
                return msg_chain
            return _chain()

        db.table.side_effect = _tbl
        return db

    def test_returns_paginated_messages(self):
        from app.services.whatsapp_service import get_lead_messages
        msgs = [
            {"id": "m1", "lead_id": self.LEAD_ID, "content": "Hello", "direction": "inbound"},
            {"id": "m2", "lead_id": self.LEAD_ID, "content": "Hi back", "direction": "outbound"},
        ]
        db = self._make_db(messages=msgs)
        result = get_lead_messages(db, self.ORG_ID, self.LEAD_ID)
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_raises_404_when_lead_not_found(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(lead_exists=False)
        with pytest.raises(HTTPException) as exc_info:
            get_lead_messages(db, self.ORG_ID, self.LEAD_ID)
        assert exc_info.value.status_code == 404

    def test_returns_empty_when_no_messages(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(lead_exists=True, messages=[])
        result = get_lead_messages(db, self.ORG_ID, self.LEAD_ID)
        assert result["total"] == 0
        assert result["items"] == []

    def test_filters_by_lead_id(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(messages=[{"id": "m1", "content": "Hi"}])
        get_lead_messages(db, self.ORG_ID, self.LEAD_ID)
        # The messages query must have filtered by lead_id
        msg_chain = db.table("whatsapp_messages")
        eq_calls = [str(c) for c in msg_chain.eq.call_args_list]
        assert any(self.LEAD_ID in c for c in eq_calls)


# ===========================================================================
# GET /api/v1/leads/{id}/messages (integration route tests)
# ===========================================================================

class TestGetLeadMessagesRoute:

    ORG_ID  = "org-001"
    LEAD_ID = "00000000-0000-0000-0000-000000000001"

    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._org = {
            "id": "user-001", "org_id": self.ORG_ID,
            "roles": {"template": "ops_manager", "permissions": {}},
        }
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: self._org
        yield
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def _configure_db(self, lead_exists=True, messages=None):
        messages = messages or []
        lead_chain = _chain([{"id": self.LEAD_ID}] if lead_exists else [])
        msg_chain  = _chain(messages, count=len(messages))

        def _tbl(name):
            if name == "leads":             return lead_chain
            if name == "whatsapp_messages": return msg_chain
            return _chain()

        self.mock_db.table.side_effect = _tbl

    def test_returns_200_with_messages(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._configure_db(messages=[
            {"id": "m1", "lead_id": self.LEAD_ID, "content": "Hello", "direction": "inbound"},
        ])
        client = TestClient(app)
        resp = client.get(f"/api/v1/leads/{self.LEAD_ID}/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total"] == 1

    def test_returns_200_with_empty_list(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._configure_db(messages=[])
        client = TestClient(app)
        resp = client.get(f"/api/v1/leads/{self.LEAD_ID}/messages")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0

    def test_returns_404_when_lead_not_found(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._configure_db(lead_exists=False)
        client = TestClient(app)
        resp = client.get(f"/api/v1/leads/{self.LEAD_ID}/messages")
        assert resp.status_code == 404
