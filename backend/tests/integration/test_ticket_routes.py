"""
tests/integration/test_ticket_routes.py
Integration tests for Module 03 — Support routes.
Pattern references:
  Pattern 1  : lazy get_supabase factory — never module-level
  Pattern 3  : every test class (including 422 classes) overrides get_supabase
  Pattern 4  : class-scoped fixtures restore only their own overrides
  Pattern 6  : 4xx tests assert status_code only, never resp.json()["success"]
  Pattern 7  : prefix="/api/v1" only — routes define own sub-paths
  Pattern 8  : insert chain.insert.return_value = insert_chain
  Pattern 24 : all UUID constants in valid UUID format
  Pattern 28 : tickets router uses get_current_org — every fixture must override it
  Pattern 32 : autouse fixture teardowns must pop overrides, not restore them
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org, get_current_user
from app.main import app
from app.services import ticket_service

# ---------------------------------------------------------------------------
# UUID constants — Pattern 24
# ---------------------------------------------------------------------------
ORG_ID      = "00000000-0000-0000-0000-000000000999"
USER_ID     = "00000000-0000-0000-0000-000000000777"
TICKET_ID   = "00000000-0000-0000-0000-000000000101"
ARTICLE_ID  = "00000000-0000-0000-0000-000000000201"
LOG_ID      = "00000000-0000-0000-0000-000000000301"
MSG_ID      = "00000000-0000-0000-0000-000000000401"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# Shared auth mocks
# ---------------------------------------------------------------------------
_FAKE_USER = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "email": "agent@example.com",
    "roles": {"template": "owner"},
}

# Pattern 28: get_current_org returns a plain dict with id, org_id, role.
# Includes both "role" and "roles" so it satisfies any role-check pattern
# in the tickets router regardless of which field it reads.
_FAKE_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "role": "owner",
    "roles": {"template": "owner"},
}

_TICKET = {
    "id": TICKET_ID,
    "org_id": ORG_ID,
    "reference": "TKT-0001",
    "status": "open",
    "category": "billing",
    "urgency": "medium",
    "title": "Billing issue",
    "ai_handling_mode": "draft_review",
    "sla_breached": False,
    "sla_pause_minutes": 0,
    "sla_paused_at": None,
    "deleted_at": None,
}

_ARTICLE = {
    "id": ARTICLE_ID,
    "org_id": ORG_ID,
    "category": "faq",
    "title": "How to reset",
    "content": "Go to settings.",
    "tags": [],
    "is_published": True,
    "version": 1,
    "usage_count": 0,
    "created_by": USER_ID,
}

_LOG = {
    "id": LOG_ID,
    "org_id": ORG_ID,
    "interaction_type": "outbound_call",
    "logged_by": USER_ID,
    "interaction_date": datetime.now(timezone.utc).isoformat(),
}


def _chain(data=None, count=None) -> MagicMock:
    """Pattern 8: fluent chain stub."""
    result = MagicMock()
    result.data = data if data is not None else []
    if count is not None:
        result.count = count
    m = MagicMock()
    for method in (
        "select", "insert", "update", "delete",
        "eq", "neq", "is_", "order", "range", "limit",
        "maybe_single", "filter", "in_",
    ):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db_mock(**kwargs) -> MagicMock:
    db = MagicMock()
    db.table.side_effect = lambda name: kwargs.get(name, _chain())
    return db


# ---------------------------------------------------------------------------
# Fixtures — Pattern 3 + Pattern 4 + Pattern 28 + Pattern 32
# ---------------------------------------------------------------------------
@pytest.fixture(scope="class")
def client_with_auth():
    """
    Class-scoped client with get_current_user overridden only.
    Each test class that also needs get_supabase must override it separately
    and restore only that override on teardown (Pattern 4).
    """
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    yield TestClient(app, raise_server_exceptions=False)
    # Restore — Pattern 4: never call .clear(), restore only what this fixture set
    app.dependency_overrides.pop(get_current_user, None)
    for k, v in original.items():
        app.dependency_overrides[k] = v


# ---------------------------------------------------------------------------
# TestListTickets
# ---------------------------------------------------------------------------
class TestListTickets:
    @pytest.fixture(autouse=True)
    def _setup(self):
        db = _db_mock(tickets=_chain(data=[_TICKET], count=1))
        app.dependency_overrides[get_supabase]    = lambda: db
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)

    def test_returns_200_and_paginated_list(self):
        with TestClient(app) as c:
            resp = c.get("/api/v1/tickets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"]["items"], list)

    def test_accepts_status_filter(self):
        with TestClient(app) as c:
            resp = c.get("/api/v1/tickets?status=open")
        assert resp.status_code == 200

    def test_accepts_sla_breached_filter(self):
        with TestClient(app) as c:
            resp = c.get("/api/v1/tickets?sla_breached=false")
        assert resp.status_code == 200

    def test_rejects_invalid_page(self):
        with TestClient(app) as c:
            resp = c.get("/api/v1/tickets?page=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestCreateTicket
# ---------------------------------------------------------------------------
class TestCreateTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "create_ticket", return_value=_TICKET)
    def test_returns_201_with_ticket(self, mock_create):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/tickets",
                json={"content": "My bill is wrong"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == TICKET_ID

    @patch.object(ticket_service, "create_ticket", return_value=_TICKET)
    def test_accepts_all_optional_fields(self, mock_create):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/tickets",
                json={
                    "content": "Issue",
                    "category": "hardware",
                    "urgency": "high",
                    "ai_handling_mode": "human_only",
                },
            )
        assert resp.status_code == 201

    def test_returns_422_when_content_missing(self):
        with TestClient(app) as c:
            resp = c.post("/api/v1/tickets", json={})
        assert resp.status_code == 422

    def test_returns_422_for_invalid_category(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/tickets",
                json={"content": "issue", "category": "INVALID"},
            )
        assert resp.status_code == 422

    def test_returns_422_for_invalid_urgency(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/tickets",
                json={"content": "issue", "urgency": "INVALID"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestGetTicket
# ---------------------------------------------------------------------------
class TestGetTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(
        ticket_service, "get_ticket",
        return_value={**_TICKET, "messages": [], "attachments": [], "interactions": []},
    )
    def test_returns_200_with_full_ticket(self, mock_get):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/tickets/{TICKET_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == TICKET_ID

    @patch.object(ticket_service, "get_ticket", side_effect=Exception("boom"))
    def test_returns_500_on_unexpected_error(self, _):
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get(f"/api/v1/tickets/{TICKET_ID}")
        assert resp.status_code == 500

    @patch.object(ticket_service, "get_ticket", side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Ticket not found"))
    def test_returns_404_for_missing_ticket(self, _):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/tickets/{TICKET_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestUpdateTicket
# ---------------------------------------------------------------------------
class TestUpdateTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "update_ticket", return_value=_TICKET)
    def test_returns_200_on_valid_patch(self, mock_update):
        with TestClient(app) as c:
            resp = c.patch(f"/api/v1/tickets/{TICKET_ID}", json={"urgency": "critical"})
        assert resp.status_code == 200

    def test_returns_422_for_invalid_category(self):
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/tickets/{TICKET_ID}",
                json={"category": "INVALID"},
            )
        assert resp.status_code == 422

    def test_returns_422_for_extra_field(self):
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/tickets/{TICKET_ID}",
                json={"status": "closed"},  # status not in TicketUpdate
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestAddMessage
# ---------------------------------------------------------------------------
class TestAddMessage:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(
        ticket_service, "add_message",
        return_value={"id": MSG_ID, "message_type": "agent_reply"},
    )
    def test_returns_201_on_valid_message(self, mock_msg):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/messages",
                json={"message_type": "agent_reply", "content": "We are on it."},
            )
        assert resp.status_code == 201

    def test_returns_422_when_message_type_missing(self):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/messages",
                json={"content": "Where is my reply?"},
            )
        assert resp.status_code == 422

    def test_returns_422_for_invalid_message_type(self):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/messages",
                json={"message_type": "INVALID", "content": "test"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestResolveTicket
# ---------------------------------------------------------------------------
class TestResolveTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "resolve_ticket", return_value={**_TICKET, "status": "resolved"})
    def test_returns_200_on_valid_resolution(self, mock_resolve):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/resolve",
                json={"resolution_notes": "Issue fixed by resetting the account."},
            )
        assert resp.status_code == 200

    def test_returns_422_when_resolution_notes_missing(self):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/resolve", json={})
        assert resp.status_code == 422

    @patch.object(
        ticket_service, "resolve_ticket",
        side_effect=__import__("fastapi").HTTPException(status_code=400, detail="wrong status"),
    )
    def test_returns_400_on_invalid_status_transition(self, _):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/resolve",
                json={"resolution_notes": "notes"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestCloseTicket
# ---------------------------------------------------------------------------
class TestCloseTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "close_ticket", return_value={**_TICKET, "status": "closed"})
    def test_returns_200_on_valid_close(self, mock_close):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/close")
        assert resp.status_code == 200

    @patch.object(
        ticket_service, "close_ticket",
        side_effect=__import__("fastapi").HTTPException(status_code=400, detail="not resolved"),
    )
    def test_returns_400_when_not_resolved(self, _):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/close")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestReopenTicket
# ---------------------------------------------------------------------------
class TestReopenTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "reopen_ticket", return_value={**_TICKET, "status": "open"})
    def test_returns_200_on_valid_reopen(self, mock_reopen):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/reopen")
        assert resp.status_code == 200

    @patch.object(
        ticket_service, "reopen_ticket",
        side_effect=__import__("fastapi").HTTPException(status_code=400, detail="not closed"),
    )
    def test_returns_400_when_not_closed(self, _):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/reopen")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestEscalateTicket
# ---------------------------------------------------------------------------
class TestEscalateTicket:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "escalate_ticket", return_value={**_TICKET, "urgency": "critical"})
    def test_returns_200_on_valid_escalation(self, mock_escalate):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/escalate")
        assert resp.status_code == 200

    @patch.object(
        ticket_service, "escalate_ticket",
        side_effect=__import__("fastapi").HTTPException(status_code=400, detail="resolved"),
    )
    def test_returns_400_for_resolved_ticket(self, _):
        with TestClient(app) as c:
            resp = c.post(f"/api/v1/tickets/{TICKET_ID}/escalate")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# TestListAttachments
# ---------------------------------------------------------------------------
class TestListAttachments:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(
        ticket_service, "list_attachments",
        return_value=[{"id": "att-1", "file_name": "screenshot.png"}],
    )
    def test_returns_200_with_list(self, mock_list):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/tickets/{TICKET_ID}/attachments")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    @patch.object(
        ticket_service, "list_attachments",
        side_effect=__import__("fastapi").HTTPException(status_code=404, detail="Ticket not found"),
    )
    def test_returns_404_for_missing_ticket(self, _):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/tickets/{TICKET_ID}/attachments")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestUploadAttachment
# ---------------------------------------------------------------------------
class TestUploadAttachment:
    @pytest.fixture(autouse=True)
    def _setup(self):
        # Phase 9E: db must be a MagicMock (not None) so db.storage.from_().upload()
        # can be called by the real storage upload added in Phase 9E.
        # create_attachment is still patched per-test, so no DB row is written.
        mock_db = MagicMock()
        mock_db.storage.from_.return_value.upload.return_value = MagicMock()
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: mock_db
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "create_attachment", return_value={"id": "att-1"})
    def test_returns_201_on_valid_pdf_upload(self, mock_create):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/attachments",
                files={"file": ("doc.pdf", b"PDF content", "application/pdf")},
            )
        assert resp.status_code == 201

    def test_returns_415_for_invalid_mime_type(self):
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/attachments",
                files={"file": ("evil.exe", b"MZ", "application/x-msdownload")},
            )
        assert resp.status_code == 415

    @patch.object(ticket_service, "create_attachment", return_value={"id": "att-1"})
    def test_returns_413_for_oversized_file(self, mock_create):
        big_content = b"A" * (26 * 1024 * 1024)  # 26 MB
        with TestClient(app) as c:
            resp = c.post(
                f"/api/v1/tickets/{TICKET_ID}/attachments",
                files={"file": ("big.pdf", big_content, "application/pdf")},
            )
        assert resp.status_code == 413

    @patch.object(ticket_service, "create_attachment", return_value={"id": "att-1"})
    def test_accepts_all_valid_mime_types(self, mock_create):
        valid_types = [
            ("img.jpg", b"data", "image/jpeg"),
            ("img.png", b"data", "image/png"),
            ("vid.mp4", b"data", "video/mp4"),
            ("audio.mp3", b"data", "audio/mpeg"),
            ("data.csv", b"data", "text/csv"),
        ]
        with TestClient(app) as c:
            for name, content, mime in valid_types:
                resp = c.post(
                    f"/api/v1/tickets/{TICKET_ID}/attachments",
                    files={"file": (name, content, mime)},
                )
                assert resp.status_code == 201, f"Expected 201 for {mime}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# TestKBList
# ---------------------------------------------------------------------------
class TestKBList:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(
        ticket_service, "list_kb_articles",
        return_value={"items": [_ARTICLE], "total": 1, "page": 1, "page_size": 20},
    )
    def test_returns_200_and_paginated_list(self, mock_list):
        with TestClient(app) as c:
            resp = c.get("/api/v1/knowledge-base")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    @patch.object(
        ticket_service, "list_kb_articles",
        return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
    )
    def test_accepts_category_filter(self, mock_list):
        with TestClient(app) as c:
            resp = c.get("/api/v1/knowledge-base?category=faq")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestKBCreate
# ---------------------------------------------------------------------------
class TestKBCreate:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "create_kb_article", return_value=_ARTICLE)
    def test_returns_201_on_valid_article(self, mock_create):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/knowledge-base",
                json={
                    "category": "faq",
                    "title": "How to reset your password",
                    "content": "Go to settings and click reset.",
                },
            )
        assert resp.status_code == 201

    def test_returns_422_when_category_missing(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/knowledge-base",
                json={"title": "T", "content": "C"},
            )
        assert resp.status_code == 422

    def test_returns_422_for_invalid_category(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/knowledge-base",
                json={"category": "INVALID", "title": "T", "content": "C"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestKBGet
# ---------------------------------------------------------------------------
class TestKBGet:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "get_kb_article", return_value=_ARTICLE)
    def test_returns_200_with_article(self, mock_get):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/knowledge-base/{ARTICLE_ID}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == ARTICLE_ID

    @patch.object(
        ticket_service, "get_kb_article",
        side_effect=__import__("fastapi").HTTPException(status_code=404, detail="not found"),
    )
    def test_returns_404_for_missing_article(self, _):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/knowledge-base/{ARTICLE_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestKBUpdate
# ---------------------------------------------------------------------------
class TestKBUpdate:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "update_kb_article", return_value={**_ARTICLE, "version": 2})
    def test_returns_200_on_valid_update(self, mock_update):
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/knowledge-base/{ARTICLE_ID}",
                json={"content": "Updated content."},
            )
        assert resp.status_code == 200

    def test_returns_422_for_invalid_category(self):
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/knowledge-base/{ARTICLE_ID}",
                json={"category": "INVALID"},
            )
        assert resp.status_code == 422

    def test_returns_422_for_extra_field(self):
        with TestClient(app) as c:
            resp = c.patch(
                f"/api/v1/knowledge-base/{ARTICLE_ID}",
                json={"usage_count": 99},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TestKBDelete (unpublish — Admin only)
# ---------------------------------------------------------------------------
class TestKBDelete:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_supabase] = lambda: None
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)

    @patch.object(ticket_service, "unpublish_kb_article", return_value={**_ARTICLE, "is_published": False})
    def test_returns_200_for_owner(self, mock_unpublish):
        app.dependency_overrides[get_current_user] = lambda: {**_FAKE_USER, "roles": {"template": "owner"}}
        app.dependency_overrides[get_current_org]  = lambda: {**_FAKE_ORG, "role": "owner"}
        with TestClient(app) as c:
            resp = c.delete(f"/api/v1/knowledge-base/{ARTICLE_ID}")
        assert resp.status_code == 200

    def test_returns_403_for_non_admin(self):
        app.dependency_overrides[get_current_user] = lambda: {**_FAKE_USER, "roles": {"template": "sales_rep"}}
        app.dependency_overrides[get_current_org]  = lambda: {**_FAKE_ORG, "role": "sales_rep", "roles": {"template": "sales_rep"}}
        with TestClient(app) as c:
            resp = c.delete(f"/api/v1/knowledge-base/{ARTICLE_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# TestCreateInteractionLog
# ---------------------------------------------------------------------------
class TestCreateInteractionLog:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(ticket_service, "create_interaction_log", return_value=_LOG)
    def test_returns_201_on_valid_log(self, mock_create):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/interaction-logs",
                json={
                    "interaction_type": "outbound_call",
                    "raw_notes": "Called, no answer. Left voicemail.",
                    "interaction_date": datetime.now(timezone.utc).isoformat(),
                },
            )
        assert resp.status_code == 201

    def test_returns_422_when_interaction_type_missing(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/interaction-logs",
                json={"interaction_date": datetime.now(timezone.utc).isoformat()},
            )
        assert resp.status_code == 422

    def test_returns_422_for_invalid_interaction_type(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/interaction-logs",
                json={
                    "interaction_type": "INVALID",
                    "interaction_date": datetime.now(timezone.utc).isoformat(),
                },
            )
        assert resp.status_code == 422

    def test_returns_422_when_interaction_date_missing(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/v1/interaction-logs",
                json={"interaction_type": "email"},
            )
        assert resp.status_code == 422

    @patch.object(ticket_service, "create_interaction_log", return_value=_LOG)
    def test_accepts_all_valid_interaction_types(self, mock_create):
        valid_types = [
            "outbound_call", "inbound_call", "whatsapp", "in_person", "email"
        ]
        with TestClient(app) as c:
            for itype in valid_types:
                resp = c.post(
                    "/api/v1/interaction-logs",
                    json={
                        "interaction_type": itype,
                        "interaction_date": datetime.now(timezone.utc).isoformat(),
                    },
                )
                assert resp.status_code == 201, f"Expected 201 for {itype}"


# ---------------------------------------------------------------------------
# TestListInteractionLogs
# ---------------------------------------------------------------------------
class TestListInteractionLogs:
    @pytest.fixture(autouse=True)
    def _setup(self):
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
        app.dependency_overrides[get_current_org]  = lambda: _FAKE_ORG
        app.dependency_overrides[get_supabase]     = lambda: None
        yield
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_org, None)
        app.dependency_overrides.pop(get_supabase, None)

    @patch.object(
        ticket_service, "list_interaction_logs",
        return_value={"items": [_LOG], "total": 1, "page": 1, "page_size": 20},
    )
    def test_returns_200_with_logs(self, mock_list):
        with TestClient(app) as c:
            resp = c.get("/api/v1/interaction-logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1

    @patch.object(
        ticket_service, "list_interaction_logs",
        return_value={"items": [], "total": 0, "page": 1, "page_size": 20},
    )
    def test_accepts_customer_id_filter(self, mock_list):
        with TestClient(app) as c:
            resp = c.get(f"/api/v1/interaction-logs?customer_id={CUSTOMER_ID}")
        assert resp.status_code == 200

    def test_rejects_invalid_page(self):
        with TestClient(app) as c:
            resp = c.get("/api/v1/interaction-logs?page=0")
        assert resp.status_code == 422