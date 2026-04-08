"""
tests/unit/test_unread_and_lead_messages.py

Tests for:
  1. whatsapp_service.get_lead_messages
  2. whatsapp_service.get_unread_counts
  3. webhooks._handle_inbound_message — notification uses real full_name
  4. GET /api/v1/messages/unread-counts route

Patterns followed:
  - Pattern 3  : get_supabase ALWAYS overridden in integration tests
  - Pattern 8  : separate insert chain
  - Pattern 9  : normalise list vs dict
  - Pattern 32 : pop() teardown, never .clear()
  - Pattern 45 : .maybe_single() returns None when 0 rows — guard before .data
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared helpers — mirrors test_whatsapp_service._chain pattern
# ---------------------------------------------------------------------------

ORG_ID      = "org-001"
LEAD_ID     = "00000000-0000-0000-0000-000000000001"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000002"
USER_ID     = "00000000-0000-0000-0000-000000000099"


def _chain(data=None, count=None):
    chain = MagicMock()
    result = MagicMock()
    result.data  = data if data is not None else []
    result.count = count if count is not None else (
        len(data) if isinstance(data, list) else 0
    )
    chain.execute.return_value = result
    for m in ("select", "eq", "is_", "order", "range", "limit",
              "maybe_single", "update", "insert", "neq", "in_"):
        getattr(chain, m).return_value = chain
    return chain


def _db_for_tables(table_map: dict):
    """Return a db mock where db.table(name) returns different chains per name."""
    db = MagicMock()
    db.table.side_effect = lambda name: table_map.get(name, _chain())
    return db


# ===========================================================================
# 1 — whatsapp_service.get_lead_messages
# ===========================================================================

class TestGetLeadMessages:

    def _make_db(self, lead_exists=True, messages=None, count=None):
        messages = messages or []
        count = count if count is not None else len(messages)
        lead_chain = _chain([{"id": LEAD_ID}] if lead_exists else [])
        msg_chain  = _chain(messages, count=count)
        return _db_for_tables({
            "leads":             lead_chain,
            "whatsapp_messages": msg_chain,
        })

    def test_returns_messages_and_total(self):
        from app.services.whatsapp_service import get_lead_messages
        msgs = [
            {"id": "m1", "lead_id": LEAD_ID, "content": "Hi",    "direction": "inbound"},
            {"id": "m2", "lead_id": LEAD_ID, "content": "Hello", "direction": "outbound"},
        ]
        db = self._make_db(messages=msgs, count=2)
        result = get_lead_messages(db, ORG_ID, LEAD_ID)
        assert result["total"]      == 2
        assert len(result["items"]) == 2
        assert result["page"]       == 1

    def test_raises_404_when_lead_not_found(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(lead_exists=False)
        with pytest.raises(HTTPException) as exc_info:
            get_lead_messages(db, ORG_ID, LEAD_ID)
        assert exc_info.value.status_code == 404

    def test_returns_empty_when_no_messages(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(lead_exists=True, messages=[], count=0)
        result = get_lead_messages(db, ORG_ID, LEAD_ID)
        assert result["total"]      == 0
        assert result["items"]      == []

    def test_query_filters_by_lead_id_and_org(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(messages=[{"id": "m1", "content": "test"}])
        get_lead_messages(db, ORG_ID, LEAD_ID)
        msg_chain = db.table("whatsapp_messages")
        eq_calls  = [str(c) for c in msg_chain.eq.call_args_list]
        assert any(LEAD_ID in c for c in eq_calls)
        assert any(ORG_ID  in c for c in eq_calls)

    def test_respects_page_and_page_size(self):
        from app.services.whatsapp_service import get_lead_messages
        db = self._make_db(messages=[])
        get_lead_messages(db, ORG_ID, LEAD_ID, page=2, page_size=10)
        msg_chain = db.table("whatsapp_messages")
        # range(10, 19) should have been called for page=2, page_size=10
        msg_chain.range.assert_called_with(10, 19)


# ===========================================================================
# 2 — whatsapp_service.get_unread_counts
# ===========================================================================

class TestGetUnreadCounts:

    def test_returns_lead_counts(self):
        from app.services.whatsapp_service import get_unread_counts
        rows = [
            {"lead_id": LEAD_ID,  "customer_id": None},
            {"lead_id": LEAD_ID,  "customer_id": None},
            {"lead_id": "lead-2", "customer_id": None},
        ]
        db = _db_for_tables({"whatsapp_messages": _chain(rows)})
        result = get_unread_counts(db, ORG_ID)
        assert result["leads"][LEAD_ID]  == 2
        assert result["leads"]["lead-2"] == 1
        assert result["customers"]       == {}

    def test_returns_customer_counts(self):
        from app.services.whatsapp_service import get_unread_counts
        rows = [
            {"lead_id": None, "customer_id": CUSTOMER_ID},
            {"lead_id": None, "customer_id": CUSTOMER_ID},
        ]
        db = _db_for_tables({"whatsapp_messages": _chain(rows)})
        result = get_unread_counts(db, ORG_ID)
        assert result["customers"][CUSTOMER_ID] == 2
        assert result["leads"]                  == {}

    def test_returns_empty_dicts_when_no_unread(self):
        from app.services.whatsapp_service import get_unread_counts
        db = _db_for_tables({"whatsapp_messages": _chain([])})
        result = get_unread_counts(db, ORG_ID)
        assert result == {"leads": {}, "customers": {}}

    def test_db_failure_returns_empty_dicts(self):
        """S14 — DB error must never crash the list views."""
        from app.services.whatsapp_service import get_unread_counts
        db = MagicMock()
        db.table.side_effect = Exception("DB connection lost")
        result = get_unread_counts(db, ORG_ID)
        assert result == {"leads": {}, "customers": {}}

    def test_filters_by_inbound_direction_and_unread(self):
        """Query must filter direction=inbound and read_at IS NULL."""
        from app.services.whatsapp_service import get_unread_counts
        db = _db_for_tables({"whatsapp_messages": _chain([])})
        get_unread_counts(db, ORG_ID)
        chain = db.table("whatsapp_messages")
        eq_calls = [str(c) for c in chain.eq.call_args_list]
        assert any("inbound" in c for c in eq_calls)
        chain.is_.assert_called()


# ===========================================================================
# 3 — webhooks._handle_inbound_message notification uses real full_name
# ===========================================================================

APP_SECRET = "test-app-secret"


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _inbound_payload(phone="2348001234567", contact_name="Test Sender") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata":  {"phone_number_id": "test"},
                    "contacts":  [{"profile": {"name": contact_name}, "wa_id": phone}],
                    "messages":  [{
                        "id": "msg-001", "from": phone,
                        "type": "text", "text": {"body": "Hello"},
                    }],
                    "statuses": [],
                },
            }],
        }],
    }


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


def _db_with_lead_name(phone="2348001234567", full_name="Amaka Johnson",
                        lead_id=LEAD_ID, org_id=ORG_ID, assigned_to=USER_ID):
    """DB mock that matches a lead by phone and returns its full_name."""
    lead_row = {
        "id": lead_id, "org_id": org_id,
        "whatsapp": phone, "phone": phone,
        "full_name": full_name,
        "assigned_to": assigned_to, "deleted_at": None,
    }
    customers_chain = _chain([])
    leads_chain     = _chain([lead_row])
    name_chain      = _chain({"id": lead_id, "full_name": full_name})
    wa_chain        = _chain([{"id": "wa-001"}])
    notif_chain     = _chain([])
    audit_chain     = _chain([])

    call_counts = {"leads": 0}

    def _tbl(name):
        if name == "customers":         return customers_chain
        if name == "leads":
            call_counts["leads"] += 1
            # First call = phone lookup, subsequent = name lookup
            return leads_chain
        if name == "whatsapp_messages": return wa_chain
        if name == "notifications":     return notif_chain
        if name == "audit_logs":        return audit_chain
        return _chain()

    db = MagicMock()
    db.table.side_effect = _tbl
    return db, notif_chain


class TestNotificationUsesRealName:

    def _post(self, client, payload):
        body = json.dumps(payload).encode()
        return client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={
                "Content-Type":        "application/json",
                "X-Hub-Signature-256": _sig(body),
            },
        )

    def test_notification_title_uses_lead_full_name(self, client_factory):
        """Notification title must use lead's full_name, not WhatsApp contact name."""
        db, notif_chain = _db_with_lead_name(
            phone="2348001234567",
            full_name="Amaka Johnson",
        )
        client = client_factory(db)
        self._post(client, _inbound_payload(
            phone="2348001234567",
            contact_name="Test Sender",   # WhatsApp contact name — should NOT be used
        ))
        notif_chain.insert.assert_called()
        notif_row = notif_chain.insert.call_args[0][0]
        assert "Amaka Johnson" in notif_row["title"]
        assert "Test Sender"   not in notif_row["title"]

    def test_notification_falls_back_to_contact_name_on_name_lookup_failure(
        self, client_factory
    ):
        """If name lookup fails, fall back to WhatsApp contact_name — never crash."""
        lead_row = {
            "id": LEAD_ID, "org_id": ORG_ID,
            "whatsapp": "2348001234567", "phone": "2348001234567",
            "assigned_to": USER_ID, "deleted_at": None,
        }

        call_n = {"n": 0}

        def _tbl(name):
            if name == "customers": return _chain([])
            if name == "leads":
                call_n["n"] += 1
                if call_n["n"] == 1:
                    return _chain([lead_row])   # phone lookup succeeds
                # name lookup fails
                c = MagicMock()
                c.select.return_value = c
                c.eq.return_value = c
                c.maybe_single.return_value = c
                c.execute.side_effect = Exception("timeout")
                return c
            if name == "whatsapp_messages": return _chain([{"id": "wa-001"}])
            if name == "notifications":     return _chain([])
            return _chain()

        db = MagicMock()
        db.table.side_effect = _tbl
        client = client_factory(db)

        # Should not raise — S14
        resp = self._post(client, _inbound_payload(
            phone="2348001234567",
            contact_name="Test Sender",
        ))
        assert resp.status_code == 200

    def test_notification_falls_back_to_phone_when_no_name_available(
        self, client_factory
    ):
        """If contact_name is empty and name lookup returns nothing, use phone."""
        lead_row = {
            "id": LEAD_ID, "org_id": ORG_ID,
            "whatsapp": "2348001234567", "phone": "2348001234567",
            "assigned_to": USER_ID, "deleted_at": None,
        }
        notif_chain = _chain([])

        def _tbl(name):
            if name == "customers":         return _chain([])
            if name == "leads":             return _chain([lead_row])
            if name == "whatsapp_messages": return _chain([{"id": "wa-001"}])
            if name == "notifications":     return notif_chain
            return _chain()

        db = MagicMock()
        db.table.side_effect = _tbl
        client = client_factory(db)
        self._post(client, _inbound_payload(
            phone="2348001234567",
            contact_name="",   # empty contact name
        ))
        notif_row = notif_chain.insert.call_args[0][0]
        # Title must contain something — either name or phone
        assert len(notif_row["title"]) > len("New WhatsApp reply from ")


# ===========================================================================
# 4 — GET /api/v1/messages/unread-counts route
# ===========================================================================

class TestUnreadCountsRoute:

    @pytest.fixture(autouse=True)
    def _setup(self):
        from app.main import app
        from app.database import get_supabase
        from app.dependencies import get_current_org

        self.mock_db = MagicMock()
        self._org = {
            "id": USER_ID, "org_id": ORG_ID,
            "roles": {"template": "ops_manager", "permissions": {}},
        }
        app.dependency_overrides[get_supabase]    = lambda: self.mock_db
        app.dependency_overrides[get_current_org] = lambda: self._org
        yield
        app.dependency_overrides.pop(get_supabase,    None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_with_counts(self):
        rows = [
            {"lead_id": LEAD_ID, "customer_id": None},
            {"lead_id": LEAD_ID, "customer_id": None},
        ]
        self.mock_db.table.return_value = _chain(rows)
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["leads"][LEAD_ID] == 2

    def test_returns_200_with_empty_when_no_unread(self):
        self.mock_db.table.return_value = _chain([])
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["leads"]     == {}
        assert data["customers"] == {}

    def test_db_failure_returns_200_with_empty(self):
        """S14 — DB failure must return empty counts, not 500."""
        self.mock_db.table.side_effect = Exception("DB down")
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        resp = client.get("/api/v1/messages/unread-counts")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"leads": {}, "customers": {}}
