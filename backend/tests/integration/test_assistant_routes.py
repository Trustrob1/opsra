"""
tests/integration/test_assistant_routes.py
-------------------------------------------
Integration tests for Aria AI Assistant routes (M01-10b).

Routes tested:
  GET  /api/v1/briefing
  POST /api/v1/briefing/seen
  POST /api/v1/assistant/message   (SSE streaming — body collected as full text)
  GET  /api/v1/assistant/history

Security:
  S1  — org_id from JWT (never request body)
  S2  — get_current_org dependency (Pattern 28)
  Pattern 32 — dependency overrides use pop() not clear()
  Pattern 44 — override get_current_org directly
  Pattern 58 — _ORG_PAYLOAD with permissions nested inside roles
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org
from app.database import get_supabase

# ─── Constants ───────────────────────────────────────────────────────────────

ORG_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID  = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TODAY    = date.today().isoformat()

# Pattern 58 — shape matches real get_current_org return value (id, not user_id)
_ORG_PAYLOAD = {
    "id":      USER_ID,    # ← get_current_org returns "id"
    "org_id":  ORG_ID,
    "roles": {
        "template":    "owner",
        "permissions": {
            "is_admin":      True,
            "can_view_leads": True,
        },
    },
}


# ─── Mock DB ─────────────────────────────────────────────────────────────────

def _mock_db():
    db = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    db.table.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value     = chain
    chain.in_.return_value    = chain
    chain.order.return_value  = chain
    chain.limit.return_value  = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.single.return_value = chain
    chain.lt.return_value     = chain
    chain.delete.return_value = chain
    return db


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _override(db=None):
    """Apply dependency overrides. Returns the db mock."""
    if db is None:
        db = _mock_db()
    app.dependency_overrides[get_current_org] = lambda: _ORG_PAYLOAD
    app.dependency_overrides[get_supabase]    = lambda: db
    return db


def _teardown():
    """Pattern 32 — pop overrides, never clear()."""
    app.dependency_overrides.pop(get_current_org, None)
    app.dependency_overrides.pop(get_supabase, None)


# ─── GET /api/v1/briefing ─────────────────────────────────────────────────────

class TestGetBriefing:

    def test_returns_show_true_when_briefing_ready(self):
        db = _mock_db()
        db.table.return_value.single.return_value.execute.return_value = MagicMock(data={
            "briefing_content":       "Good morning! You have 3 hot leads.",
            "briefing_generated_at":  TODAY,
            "last_briefing_shown_at": None,
        })
        _override(db)
        try:
            client = TestClient(app)
            res = client.get("/api/v1/briefing")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["show"] is True
            assert "Good morning" in data["content"]
        finally:
            _teardown()

    def test_returns_show_false_when_no_briefing(self):
        db = _mock_db()
        db.table.return_value.single.return_value.execute.return_value = MagicMock(data={
            "briefing_content":       None,
            "briefing_generated_at":  None,
            "last_briefing_shown_at": None,
        })
        _override(db)
        try:
            client = TestClient(app)
            res = client.get("/api/v1/briefing")
            assert res.status_code == 200
            assert res.json()["data"]["show"] is False
        finally:
            _teardown()

    def test_requires_auth(self):
        client = TestClient(app)
        res = client.get("/api/v1/briefing")
        assert res.status_code in (401, 403, 422)

    def test_success_flag_true(self):
        db = _mock_db()
        db.table.return_value.single.return_value.execute.return_value = MagicMock(data={
            "briefing_content":       None,
            "briefing_generated_at":  None,
            "last_briefing_shown_at": None,
        })
        _override(db)
        try:
            client = TestClient(app)
            res = client.get("/api/v1/briefing")
            assert res.json()["success"] is True
        finally:
            _teardown()


# ─── POST /api/v1/briefing/seen ───────────────────────────────────────────────

class TestBriefingSeen:

    def test_seen_updates_user_and_returns_success(self):
        db = _override()
        try:
            client = TestClient(app)
            res = client.post("/api/v1/briefing/seen")
            assert res.status_code == 200
            assert res.json()["success"] is True
        finally:
            _teardown()

    def test_seen_calls_mark_briefing_seen(self):
        db = _override()
        try:
            with patch("app.routers.assistant.mark_briefing_seen") as mock_seen:
                client = TestClient(app)
                client.post("/api/v1/briefing/seen")
            mock_seen.assert_called_once_with(db, USER_ID)   # "id" key
        finally:
            _teardown()

    def test_requires_auth(self):
        client = TestClient(app)
        res = client.post("/api/v1/briefing/seen")
        assert res.status_code in (401, 403, 422)


# ─── POST /api/v1/assistant/message ──────────────────────────────────────────

class TestPostMessage:

    def _stream_patch(self, text="Hello from Aria"):
        """Return an async generator mock that yields one chunk then DONE."""
        async def _gen():
            yield text

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
        mock_stream_ctx.__aexit__  = AsyncMock(return_value=None)
        mock_stream_ctx.text_stream = _gen()
        return mock_stream_ctx

    def test_returns_200_with_streaming_response(self):
        db = _mock_db()
        db.table.return_value.execute.return_value = MagicMock(data=[])
        _override(db)
        try:
            stream_ctx = self._stream_patch()
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.messages.stream.return_value = stream_ctx

            with patch("app.routers.assistant.anthropic.AsyncAnthropic", return_value=mock_client):
                with patch("app.services.assistant_service.get_role_context", return_value={}):
                    client = TestClient(app)
                    res = client.post(
                        "/api/v1/assistant/message",
                        json={"message": "How many leads today?"},
                    )
            assert res.status_code == 200
        finally:
            _teardown()

    def test_stores_user_message_before_streaming(self):
        db = _mock_db()
        db.table.return_value.execute.return_value = MagicMock(data=[])
        _override(db)
        try:
            stream_ctx = self._stream_patch()
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.messages.stream.return_value = stream_ctx

            with patch("app.routers.assistant.anthropic.AsyncAnthropic", return_value=mock_client):
                with patch("app.services.assistant_service.get_role_context", return_value={}):
                    with patch("app.routers.assistant.store_message") as mock_store:
                        client = TestClient(app)
                        client.post(
                            "/api/v1/assistant/message",
                            json={"message": "test query"},
                        )
            # At minimum, user message was stored
            assert mock_store.called
            calls = [c[0] for c in mock_store.call_args_list]
            user_call = next((c for c in calls if c[3] == "user"), None)
            assert user_call is not None
        finally:
            _teardown()

    def test_rejects_empty_message(self):
        _override()
        try:
            client = TestClient(app)
            res = client.post("/api/v1/assistant/message", json={"message": ""})
            assert res.status_code == 422
        finally:
            _teardown()

    def test_rejects_message_over_5000_chars(self):
        _override()
        try:
            client = TestClient(app)
            res = client.post(
                "/api/v1/assistant/message",
                json={"message": "x" * 5_001},
            )
            assert res.status_code == 422
        finally:
            _teardown()

    def test_requires_auth(self):
        client = TestClient(app)
        res = client.post("/api/v1/assistant/message", json={"message": "hi"})
        assert res.status_code in (401, 403, 422)

    def test_sse_response_content_type(self):
        db = _mock_db()
        db.table.return_value.execute.return_value = MagicMock(data=[])
        _override(db)
        try:
            stream_ctx = self._stream_patch("Hi there")
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.messages.stream.return_value = stream_ctx

            with patch("app.routers.assistant.anthropic.AsyncAnthropic", return_value=mock_client):
                with patch("app.services.assistant_service.get_role_context", return_value={}):
                    client = TestClient(app)
                    res = client.post(
                        "/api/v1/assistant/message",
                        json={"message": "Hello"},
                    )
            assert "text/event-stream" in res.headers.get("content-type", "")
        finally:
            _teardown()


# ─── GET /api/v1/assistant/history ───────────────────────────────────────────

class TestGetHistory:

    def test_returns_message_list(self):
        db = _mock_db()
        history_rows = [
            {"role": "user",      "content": "Hi",    "created_at": "2026-01-01T12:00:00Z"},
            {"role": "assistant", "content": "Hello", "created_at": "2026-01-01T12:01:00Z"},
        ]
        db.table.return_value.execute.return_value = MagicMock(data=list(reversed(history_rows)))
        _override(db)
        try:
            client = TestClient(app)
            res = client.get("/api/v1/assistant/history")
            assert res.status_code == 200
            data = res.json()["data"]
            assert isinstance(data, list)
            assert len(data) == 2
        finally:
            _teardown()

    def test_returns_empty_list_when_no_history(self):
        db = _override()
        try:
            client = TestClient(app)
            res = client.get("/api/v1/assistant/history")
            assert res.status_code == 200
            assert res.json()["data"] == []
        finally:
            _teardown()

    def test_success_flag_true(self):
        db = _override()
        try:
            client = TestClient(app)
            res = client.get("/api/v1/assistant/history")
            assert res.json()["success"] is True
        finally:
            _teardown()

    def test_requires_auth(self):
        client = TestClient(app)
        res = client.get("/api/v1/assistant/history")
        assert res.status_code in (401, 403, 422)

    def test_org_id_from_jwt_not_query_param(self):
        """S1 — org_id must come from JWT, not the request."""
        db = _override()
        try:
            client = TestClient(app)
            # Even if caller tries to inject a different org_id in query, it's ignored
            res = client.get(
                "/api/v1/assistant/history",
                params={"org_id": "ffffffff-ffff-ffff-ffff-ffffffffffff"},
            )
            # Should succeed using the JWT org_id, not the query param
            assert res.status_code == 200
        finally:
            _teardown()
