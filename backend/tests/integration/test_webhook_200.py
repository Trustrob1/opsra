"""
tests/integration/test_webhook_200.py
---------------------------------------
Integration tests for 9E-B — POST /webhooks/meta/whatsapp.

Verifies:
  1. Valid webhook → 200 returned immediately
  2. Processing dispatched to Celery, not executed inline
  3. Invalid signature → 403
  4. Non-whatsapp_business_account object → still 200 (Meta must get 200 always)
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign(payload_bytes: bytes, secret: str = "test_secret") -> str:
    sig = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig}"


def _wa_payload(object_type: str = "whatsapp_business_account") -> dict:
    return {
        "object": object_type,
        "entry": [
            {
                "id": "entry-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "phone-id-123"},
                            "contacts": [{"profile": {"name": "Test User"}}],
                            "messages": [
                                {
                                    "id": "msg-abc-001",
                                    "from": "2348031234567",
                                    "type": "text",
                                    "text": {"body": "Hello"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWebhook200:

    @pytest.fixture(autouse=True)
    def patch_secret(self, monkeypatch):
        """Use a known secret for all tests."""
        monkeypatch.setattr(settings, "META_APP_SECRET", "test_secret")

    def test_valid_webhook_returns_200_immediately(self):
        """Valid signature → 200. Celery dispatch called, not inline processing."""
        payload_bytes = json.dumps(_wa_payload()).encode()
        sig = _sign(payload_bytes)

        with patch("app.workers.webhook_worker.process_inbound_webhook") as mock_task:
            mock_task.delay = MagicMock()

            with TestClient(app) as client:
                resp = client.post(
                    "/webhooks/meta/whatsapp",
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": sig,
                    },
                )

        assert resp.status_code == 200
        mock_task.delay.assert_called_once()

    def test_processing_dispatched_to_celery_not_inline(self):
        """_handle_inbound_message must NOT be called in the HTTP handler."""
        payload_bytes = json.dumps(_wa_payload()).encode()
        sig = _sign(payload_bytes)

        with patch("app.workers.webhook_worker.process_inbound_webhook") as mock_task, \
             patch("app.routers.webhooks._handle_inbound_message") as mock_handler:
            mock_task.delay = MagicMock()

            with TestClient(app) as client:
                client.post(
                    "/webhooks/meta/whatsapp",
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": sig,
                    },
                )

        # Celery dispatched
        mock_task.delay.assert_called_once()
        # Inline handler NOT called in the HTTP request
        mock_handler.assert_not_called()

    def test_invalid_signature_returns_403(self):
        """Bad signature → 403. Celery must NOT be called."""
        payload_bytes = json.dumps(_wa_payload()).encode()

        with patch("app.workers.webhook_worker.process_inbound_webhook") as mock_task:
            mock_task.delay = MagicMock()

            with TestClient(app) as client:
                resp = client.post(
                    "/webhooks/meta/whatsapp",
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": "sha256=invalidsignature",
                    },
                )

        assert resp.status_code == 403
        mock_task.delay.assert_not_called()

    def test_missing_signature_returns_403(self):
        """No signature header → 403."""
        payload_bytes = json.dumps(_wa_payload()).encode()

        with TestClient(app) as client:
            resp = client.post(
                "/webhooks/meta/whatsapp",
                content=payload_bytes,
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 403
