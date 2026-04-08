"""
tests/webhooks/test_payment_webhooks.py
Integration tests for Phase 9D payment webhook routes.

Routes under test:
  POST /webhooks/payment/paystack     — Paystack charge.success
  POST /webhooks/payment/flutterwave  — Flutterwave charge.completed

Security:
  Paystack:    HMAC-SHA512 of raw body vs PAYSTACK_SECRET_KEY → X-Paystack-Signature
  Flutterwave: direct compare FLUTTERWAVE_SECRET_HASH vs verif-hash header
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_supabase

# ── Test constants ─────────────────────────────────────────────────────────────
PAYSTACK_SECRET  = "test_paystack_secret_key"
FLUTTER_HASH     = "test_flutterwave_secret_hash"

ORG_ID = "00000000-0000-0000-0000-000000000001"
SUB_ID = "00000000-0000-0000-0000-000000000050"

client = TestClient(app)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _paystack_sig(body: bytes, secret: str = PAYSTACK_SECRET) -> str:
    """Compute valid X-Paystack-Signature for a raw body."""
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def _paystack_body(
    sub_id: str = SUB_ID,
    org_id: str = ORG_ID,
    event: str = "charge.success",
) -> bytes:
    payload = {
        "event": event,
        "data": {
            "reference": "TXN_test_001",
            "amount": 4500000,
            "paid_at": "2026-04-07T10:00:00.000Z",
            "metadata": {"subscription_id": sub_id, "org_id": org_id},
        },
    }
    return json.dumps(payload).encode()


def _flutter_body(
    sub_id: str = SUB_ID,
    org_id: str = ORG_ID,
    event: str = "charge.completed",
    status: str = "successful",
) -> bytes:
    payload = {
        "event": event,
        "data": {
            "tx_ref": "FLW_test_001",
            "amount": 45000.0,
            "currency": "NGN",
            "status": status,
            "created_at": "2026-04-07T10:00:00.000Z",
            "meta": {"subscription_id": sub_id, "org_id": org_id},
        },
    }
    return json.dumps(payload).encode()


# ── Paystack webhook tests ─────────────────────────────────────────────────────

class TestPaystackWebhook:
    """POST /webhooks/payment/paystack"""

    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)

    def test_valid_signature_accepted_returns_200(self):
        body = _paystack_body()
        sig  = _paystack_sig(body)
        with patch("app.routers.webhooks.process_paystack_webhook") as mock_proc, \
             patch.dict("os.environ", {"PAYSTACK_SECRET_KEY": PAYSTACK_SECRET}):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"X-Paystack-Signature": sig, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_proc.assert_called_once()

    def test_invalid_signature_rejected_with_403(self):
        body = _paystack_body()
        with patch.dict("os.environ", {"PAYSTACK_SECRET_KEY": PAYSTACK_SECRET}):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"X-Paystack-Signature": "deadbeef", "Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_missing_signature_header_rejected_with_403(self):
        body = _paystack_body()
        with patch.dict("os.environ", {"PAYSTACK_SECRET_KEY": PAYSTACK_SECRET}):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_unconfigured_secret_rejects_all_requests(self):
        """If PAYSTACK_SECRET_KEY is absent, every request must be rejected."""
        body = _paystack_body()
        sig  = _paystack_sig(body)
        with patch.dict("os.environ", {}, clear=True):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"X-Paystack-Signature": sig, "Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_processing_error_still_returns_200(self):
        """S14: internal processing failure must not return 5xx to Paystack."""
        body = _paystack_body()
        sig  = _paystack_sig(body)
        with patch(
            "app.routers.webhooks.process_paystack_webhook",
            side_effect=RuntimeError("db connection lost"),
        ), patch.dict("os.environ", {"PAYSTACK_SECRET_KEY": PAYSTACK_SECRET}):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"X-Paystack-Signature": sig, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200

    def test_non_charge_event_passes_through_returns_200(self):
        """Unhandled event types are ignored by the service — route still returns 200."""
        body = _paystack_body(event="transfer.success")
        sig  = _paystack_sig(body)
        with patch("app.routers.webhooks.process_paystack_webhook") as mock_proc, \
             patch.dict("os.environ", {"PAYSTACK_SECRET_KEY": PAYSTACK_SECRET}):
            resp = client.post(
                "/webhooks/payment/paystack",
                content=body,
                headers={"X-Paystack-Signature": sig, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        mock_proc.assert_called_once()   # route still calls service; service ignores it


# ── Flutterwave webhook tests ──────────────────────────────────────────────────

class TestFlutterwaveWebhook:
    """POST /webhooks/payment/flutterwave"""

    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_db

    def teardown_method(self):
        app.dependency_overrides.pop(get_supabase, None)

    def test_valid_hash_accepted_returns_200(self):
        body = _flutter_body()
        with patch("app.routers.webhooks.process_flutterwave_webhook") as mock_proc, \
             patch.dict("os.environ", {"FLUTTERWAVE_SECRET_HASH": FLUTTER_HASH}):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"verif-hash": FLUTTER_HASH, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_proc.assert_called_once()

    def test_wrong_hash_rejected_with_403(self):
        body = _flutter_body()
        with patch.dict("os.environ", {"FLUTTERWAVE_SECRET_HASH": FLUTTER_HASH}):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"verif-hash": "not_the_right_hash", "Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_missing_verif_hash_header_rejected_with_403(self):
        body = _flutter_body()
        with patch.dict("os.environ", {"FLUTTERWAVE_SECRET_HASH": FLUTTER_HASH}):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_unconfigured_secret_rejects_all_requests(self):
        """If FLUTTERWAVE_SECRET_HASH is absent, every request must be rejected."""
        body = _flutter_body()
        with patch.dict("os.environ", {}, clear=True):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"verif-hash": FLUTTER_HASH, "Content-Type": "application/json"},
            )
        assert resp.status_code == 403

    def test_processing_error_still_returns_200(self):
        """S14: internal processing failure must not return 5xx to Flutterwave."""
        body = _flutter_body()
        with patch(
            "app.routers.webhooks.process_flutterwave_webhook",
            side_effect=RuntimeError("downstream failure"),
        ), patch.dict("os.environ", {"FLUTTERWAVE_SECRET_HASH": FLUTTER_HASH}):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"verif-hash": FLUTTER_HASH, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200

    def test_non_successful_charge_passes_through_returns_200(self):
        """Failed charges are ignored by the service — route still returns 200."""
        body = _flutter_body(status="failed")
        with patch("app.routers.webhooks.process_flutterwave_webhook") as mock_proc, \
             patch.dict("os.environ", {"FLUTTERWAVE_SECRET_HASH": FLUTTER_HASH}):
            resp = client.post(
                "/webhooks/payment/flutterwave",
                content=body,
                headers={"verif-hash": FLUTTER_HASH, "Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        mock_proc.assert_called_once()
