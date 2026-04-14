"""
tests/webhooks/test_whatsapp_auto_create_lead.py

Tests for M01-1 — auto-create lead when inbound WhatsApp arrives from
an unknown number (no existing lead or customer match).

Covers:
  - _lookup_org_by_phone_number_id() helper
  - _handle_inbound_message() auto-create path
  - Full route POST /webhooks/meta/whatsapp with unknown number

Patterns:
  - Pattern 3  : get_supabase ALWAYS overridden
  - Pattern 9  : normalise list vs dict
  - Pattern 33 : no ILIKE — phone matching is Python-side
  - Pattern 34 : auth tests use != 200 or in (401, 403)
  - S14        : lead creation failure never causes non-200 response
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_SECRET      = "test-app-secret"
ORG_ID          = "00000000-0000-0000-0000-000000000001"
LEAD_ID         = "00000000-0000-0000-0000-000000000010"
USER_ID         = "00000000-0000-0000-0000-000000000099"
PHONE_NUMBER_ID = "phone-id-001"
UNKNOWN_PHONE   = "2348055555555"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _chain(data=None, count=None):
    chain = MagicMock()
    result = MagicMock()
    result.data  = data if data is not None else []
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 0
    )
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "order", "limit", "maybe_single",
              "update", "insert", "neq", "in_", "gt"):
        getattr(chain, m).return_value = chain
    return chain


def _post_wa(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={
            "Content-Type":        "application/json",
            "X-Hub-Signature-256": _sig(body),
        },
    )


def _inbound_payload(
    phone=UNKNOWN_PHONE,
    contact_name="New Prospect",
    msg_content="Hello I need help",
    phone_number_id=PHONE_NUMBER_ID,
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata":  {"phone_number_id": phone_number_id},
                    "contacts":  [{"profile": {"name": contact_name}, "wa_id": phone}],
                    "messages":  [{
                        "id":   "msg-new-001",
                        "from": phone,
                        "type": "text",
                        "text": {"body": msg_content},
                    }],
                    "statuses": [],
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
    monkeypatch.setattr(cfg.settings, "META_APP_SECRET",     APP_SECRET,      raising=False)
    monkeypatch.setattr(cfg.settings, "META_VERIFY_TOKEN",   "test-token",    raising=False)
    monkeypatch.setattr(cfg.settings, "META_WHATSAPP_TOKEN", "test-wa-token", raising=False)


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


def _db_unknown_number(org_row=None, create_lead_result=None):
    """
    DB mock where phone lookup finds nothing (no customer, no lead),
    but org lookup by phone_number_id returns org_row if provided.
    lead_service.create_lead is patched separately in tests.
    """
    db = MagicMock()
    empty = _chain([])
    org_chain = _chain([org_row] if org_row else [])
    wa_chain  = _chain([{"id": "wa-new-001"}])
    notif_chain = _chain([])
    audit_chain = _chain([])

    def _tbl(name):
        if name == "customers":          return empty
        if name == "customer_contacts":  return empty   # WH-0: new lookup in _lookup_record_by_phone
        if name == "whatsapp_sessions":  return empty   # WH-0: triage session check
        if name == "leads":              return empty
        if name == "organisations":      return org_chain
        if name == "whatsapp_messages":  return wa_chain
        if name == "notifications":      return notif_chain
        if name == "audit_logs":         return audit_chain
        return _chain()

    db.table.side_effect = _tbl
    return db, notif_chain


# ===========================================================================
# Unit tests — _lookup_org_by_phone_number_id
# ===========================================================================

class TestLookupOrgByPhoneNumberId:

    def test_returns_org_id_when_matched(self):
        from app.routers.webhooks import _lookup_org_by_phone_number_id
        org_rows = [
            {"id": ORG_ID, "whatsapp_phone_id": PHONE_NUMBER_ID},
        ]
        db = MagicMock()
        db.table.return_value = _chain(org_rows)
        result = _lookup_org_by_phone_number_id(db, PHONE_NUMBER_ID)
        assert result == ORG_ID

    def test_returns_none_when_no_match(self):
        from app.routers.webhooks import _lookup_org_by_phone_number_id
        org_rows = [
            {"id": ORG_ID, "whatsapp_phone_id": "different-phone-id"},
        ]
        db = MagicMock()
        db.table.return_value = _chain(org_rows)
        result = _lookup_org_by_phone_number_id(db, PHONE_NUMBER_ID)
        assert result is None

    def test_returns_none_when_empty_phone_number_id(self):
        from app.routers.webhooks import _lookup_org_by_phone_number_id
        db = MagicMock()
        result = _lookup_org_by_phone_number_id(db, "")
        assert result is None
        db.table.assert_not_called()

    def test_returns_none_on_db_failure(self):
        """S14 — DB error returns None, never raises."""
        from app.routers.webhooks import _lookup_org_by_phone_number_id
        db = MagicMock()
        db.table.side_effect = Exception("timeout")
        result = _lookup_org_by_phone_number_id(db, PHONE_NUMBER_ID)
        assert result is None

    def test_handles_whitespace_in_phone_number_id(self):
        """phone_number_id values with surrounding whitespace still match."""
        from app.routers.webhooks import _lookup_org_by_phone_number_id
        org_rows = [{"id": ORG_ID, "whatsapp_phone_id": f"  {PHONE_NUMBER_ID}  "}]
        db = MagicMock()
        db.table.return_value = _chain(org_rows)
        result = _lookup_org_by_phone_number_id(db, PHONE_NUMBER_ID)
        assert result == ORG_ID


# ===========================================================================
# Integration tests — auto-create lead on inbound from unknown number
# ===========================================================================

class TestAutoCreateLeadOnInbound:

    _ORG_ROW = {
        "id":                       ORG_ID,
        "whatsapp_phone_id":        PHONE_NUMBER_ID,
        "unknown_contact_behavior": "qualify_immediately",  # WH-0: these tests cover legacy path
        "whatsapp_triage_config":   None,
    }
    _NEW_LEAD = {
        "id":          LEAD_ID,
        "org_id":      ORG_ID,
        "full_name":   "New Prospect",
        "phone":       UNKNOWN_PHONE,
        "whatsapp":    UNKNOWN_PHONE,
        "source":      "whatsapp_inbound",
        "assigned_to": USER_ID,
    }

    def test_unknown_number_creates_lead_returns_200(self, client_factory):
        """Happy path: unknown number → org found → lead created → 200."""
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD) as mock_create:
            resp = _post_wa(client, _inbound_payload())
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_create.assert_called_once()

    def test_lead_created_with_correct_fields(self, client_factory):
        """Lead is created with whatsapp_inbound source, phone, and problem_stated."""
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD) as mock_create:
            _post_wa(client, _inbound_payload(
                phone=UNKNOWN_PHONE,
                contact_name="Emeka",
                msg_content="I need POS software",
            ))

        _, kwargs = mock_create.call_args
        payload = kwargs["payload"]
        assert payload.full_name      == "Emeka"
        assert payload.phone          == UNKNOWN_PHONE
        assert payload.whatsapp       == UNKNOWN_PHONE
        assert payload.source         == "whatsapp_inbound"
        assert payload.problem_stated == "I need POS software"
        assert kwargs["org_id"]       == ORG_ID
        assert kwargs["user_id"]      == "system"

    def test_falls_back_to_phone_when_no_contact_name(self, client_factory):
        """When WhatsApp contact name is empty, phone number used as full_name."""
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD) as mock_create:
            _post_wa(client, _inbound_payload(contact_name=""))

        _, kwargs = mock_create.call_args
        assert kwargs["payload"].full_name == UNKNOWN_PHONE

    def test_message_saved_with_lead_id(self, client_factory):
        """After lead creation, whatsapp_messages row is saved with new lead_id."""
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD):
            _post_wa(client, _inbound_payload())

        wa_insert = db.table("whatsapp_messages").insert
        wa_insert.assert_called_once()
        row = wa_insert.call_args[0][0]
        assert row["lead_id"]   == LEAD_ID
        assert row["direction"] == "inbound"
        assert row["org_id"]    == ORG_ID

    def test_notification_uses_new_lead_title(self, client_factory):
        """Notification title says 'New lead via WhatsApp' not 'New WhatsApp reply'."""
        db, notif_chain = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD):
            _post_wa(client, _inbound_payload(contact_name="Emeka"))

        notif_chain.insert.assert_called()
        notif_row = notif_chain.insert.call_args[0][0]
        assert "New lead via WhatsApp" in notif_row["title"]
        assert notif_row["type"] == "whatsapp_new_lead"
        assert notif_row["resource_type"] == "lead"
        assert notif_row["resource_id"]   == LEAD_ID

    def test_no_org_match_returns_200_no_lead_created(self, client_factory):
        """If phone_number_id matches no org, return 200 and create no lead."""
        db, _ = _db_unknown_number(org_row=None)  # no org match
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead") as mock_create:
            resp = _post_wa(client, _inbound_payload())
        assert resp.status_code == 200
        mock_create.assert_not_called()

    def test_duplicate_lead_recovers_via_relookup(self, client_factory):
        """
        If create_lead raises DUPLICATE_DETECTED (race condition),
        the handler re-looks up the phone and continues — never crashes.
        """
        from fastapi import HTTPException
        from app.models.common import ErrorCode

        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)

        dup_exc = HTTPException(
            status_code=409,
            detail={"code": ErrorCode.DUPLICATE_DETECTED, "message": "Duplicate"},
        )
        # After duplicate, the re-lookup now finds the lead
        with patch("app.routers.webhooks.lead_service.create_lead",
                   side_effect=dup_exc), \
             patch("app.routers.webhooks._lookup_record_by_phone",
                   side_effect=[
                       (None, None, None, None),       # first call — unknown
                       (ORG_ID, None, LEAD_ID, USER_ID), # re-lookup after duplicate
                   ]):
            resp = _post_wa(client, _inbound_payload())

        assert resp.status_code == 200

    def test_lead_creation_failure_returns_200(self, client_factory):
        """S14 — lead creation DB error must not cause non-200 response."""
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   side_effect=Exception("DB error")):
            resp = _post_wa(client, _inbound_payload())
        assert resp.status_code == 200

    def test_existing_lead_not_duplicated(self, client_factory):
        """
        If the phone already exists as a lead, the existing flow runs —
        create_lead is NOT called again.
        """
        lead_row = {
            "id": LEAD_ID, "org_id": ORG_ID,
            "whatsapp": UNKNOWN_PHONE, "phone": UNKNOWN_PHONE,
            "assigned_to": USER_ID, "deleted_at": None,
        }
        db = MagicMock()
        wa_chain    = _chain([{"id": "wa-001"}])
        notif_chain = _chain([])
        audit_chain = _chain([])

        def _tbl(name):
            if name == "customers":         return _chain([])
            if name == "leads":             return _chain([lead_row])
            if name == "whatsapp_messages": return wa_chain
            if name == "notifications":     return notif_chain
            if name == "audit_logs":        return audit_chain
            return _chain()

        db.table.side_effect = _tbl
        client = client_factory(db)

        with patch("app.routers.webhooks.lead_service.create_lead") as mock_create:
            resp = _post_wa(client, _inbound_payload(phone=UNKNOWN_PHONE))

        assert resp.status_code == 200
        mock_create.assert_not_called()

    def test_non_text_message_creates_lead_without_problem_stated(self, client_factory):
        """Image messages still create a lead — problem_stated is None (not "[Image]")."""
        image_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata":  {"phone_number_id": PHONE_NUMBER_ID},
                        "contacts":  [{"profile": {"name": "Sender"}, "wa_id": UNKNOWN_PHONE}],
                        "messages":  [{
                            "id": "img-001", "from": UNKNOWN_PHONE,
                            "type": "image", "image": {"id": "img-id-1"},
                        }],
                        "statuses": [],
                    },
                }],
            }],
        }
        db, _ = _db_unknown_number(org_row=self._ORG_ROW)
        client = client_factory(db)
        with patch("app.routers.webhooks.lead_service.create_lead",
                   return_value=self._NEW_LEAD) as mock_create:
            resp = _post_wa(client, image_payload)

        assert resp.status_code == 200
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        # problem_stated should be None for non-text (image content = "[Image]" not useful)
        assert kwargs["payload"].problem_stated is None
