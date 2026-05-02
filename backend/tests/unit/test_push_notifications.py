"""
tests/unit/test_push_notifications.py
PWA-1 — push notification unit tests (Supabase client version)

Tests:
    1. POST /push-token saves token to DB
    2. Push send failure does not block caller (S14)
    3. Invalid token (empty) rejected with 422
    4. Token exceeding max length rejected with 422
    5. No push sent when user has no token
"""

import json
import pytest
from unittest.mock import patch, MagicMock


VALID_SUBSCRIPTION = json.dumps({
    "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint",
    "keys": {
        "p256dh": "fake-p256dh-key",
        "auth":   "fake-auth-key",
    },
})

# Simulate the Pydantic user object your app returns (attribute access, not dict)
class MockUser:
    id        = "user-uuid-123"
    email     = "agent@opsra.io"
    org_id    = "org-uuid-456"
    full_name = "Test Agent"


# ── Test 1: POST /push-token saves token ─────────────────────────────────────

def test_save_push_token_success():
    from app.routers.push_notifications import save_push_token, PushTokenRequest

    mock_db = MagicMock()
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        save_push_token(
            body=PushTokenRequest(token=VALID_SUBSCRIPTION, platform="web"),
            db=mock_db,
            current_user=MockUser(),
        )
    )

    assert result["success"] is True
    mock_db.table.assert_called_with("users")
    mock_db.table.return_value.update.assert_called_once_with(
        {"push_token": VALID_SUBSCRIPTION}
    )


# ── Test 2: S14 — push send failure does not block caller ────────────────────

def test_push_send_failure_non_blocking():
    from app.routers.push_notifications import send_push_notification

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "push_token": VALID_SUBSCRIPTION
    }

    with patch("app.routers.push_notifications.VAPID_PUBLIC_KEY", "fake-pub"):
        with patch("app.routers.push_notifications.VAPID_PRIVATE_KEY", "fake-priv"):
            with patch("pywebpush.webpush", side_effect=Exception("Network error")):
                result = send_push_notification(
                    db=mock_db,
                    user_id="user-uuid-123",
                    title="New lead assigned",
                    body="A hot lead is waiting for you.",
                )

    assert result is None



# ── Test 3: Empty token rejected with 422 ────────────────────────────────────

def test_empty_token_rejected():
    from app.routers.push_notifications import save_push_token, PushTokenRequest
    from fastapi import HTTPException

    mock_db = MagicMock()

    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            save_push_token(
                body=PushTokenRequest(token="   ", platform="web"),
                db=mock_db,
                current_user=MockUser(),
            )
        )

    assert exc_info.value.status_code == 422


# ── Test 4: Oversized token rejected with 422 ────────────────────────────────

def test_oversized_token_rejected():
    from app.routers.push_notifications import save_push_token, PushTokenRequest
    from fastapi import HTTPException

    mock_db = MagicMock()
    oversized = "x" * 600

    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            save_push_token(
                body=PushTokenRequest(token=oversized, platform="web"),
                db=mock_db,
                current_user=MockUser(),
            )
        )

    assert exc_info.value.status_code == 422


# ── Test 5: No push sent when user has no token ──────────────────────────────

def test_no_push_when_no_token():
    from app.routers.push_notifications import send_push_notification

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "push_token": None
    }

    with patch("app.routers.push_notifications.VAPID_PUBLIC_KEY", "fake-pub"):
        with patch("app.routers.push_notifications.VAPID_PRIVATE_KEY", "fake-priv"):
            with patch("pywebpush.webpush") as mock_webpush:
                send_push_notification(mock_db, "user-uuid-123", "Test", "Body")
                mock_webpush.assert_not_called()
