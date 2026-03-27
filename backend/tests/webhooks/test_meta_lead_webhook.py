"""
tests/webhooks/test_meta_lead_webhook.py

Webhook tests for:
  GET  /webhooks/meta/verify
  POST /webhooks/meta/lead-ads
  POST /webhooks/meta/whatsapp  (stub — returns 200)

Security tests:
  - Bad X-Hub-Signature-256 is rejected with 403
  - Missing signature is rejected with 403
  - Valid signature is accepted

Graph API mock:
  - respx mocks GET https://graph.facebook.com/v18.0/{leadgen_id}
  - Returns field_data matching Section 6.1 schema

Per Build Status Phase 1 critical patterns:
  - get_supabase ALWAYS overridden, even for signature rejection tests
  - Class-scoped fixtures: restore after per-test overrides, never .clear()
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pytest
import respx
import httpx
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _chain(data=None):
    data = data if data is not None else []
    result = MagicMock()
    result.data = data if isinstance(data, list) else [data] if data else []
    result.count = len(result.data)
    m = MagicMock()
    m.execute.return_value = result
    for method in ("select", "insert", "update", "eq", "is_",
                   "order", "range", "maybe_single", "single"):
        getattr(m, method).return_value = m
    return m


def _build_db(org_row=None, lead_row=None):
    """Build a mock Supabase client for webhook handler tests."""
    db = MagicMock()
    org_data = [org_row] if org_row else []
    lead_data = [lead_row] if lead_row else []

    org_chain       = _chain(data=org_data)
    integrations    = _chain(data=[])             # no stored token → falls back to settings
    leads_chain     = _chain(data=lead_data)
    timeline_chain  = _chain(data=[])
    audit_chain     = _chain(data=[])
    customers_chain = _chain(data=[{"id": "cust-001"}])
    subs_chain      = _chain(data=[{"id": "sub-001"}])

    _map = {
        "organisations": org_chain,
        "integrations":  integrations,
        "leads":         leads_chain,
        "lead_timeline": timeline_chain,
        "audit_logs":    audit_chain,
        "customers":     customers_chain,
        "subscriptions": subs_chain,
    }
    db.table.side_effect = lambda name: _map.get(name, _chain())
    return db


# Standard org row that matches the page_id in test payloads
_ORG_ROW = {
    "id": "org-1",
    "meta_page_id": "PAGE-001",
    "whatsapp_phone_id": None,
}

# Valid Graph API response — Section 6.1
_GRAPH_RESPONSE = {
    "id": "leadgen-001",
    "created_time": "2026-03-25T10:00:00+0000",
    "field_data": [
        {"name": "full_name",     "values": ["Emeka Obi"]},
        {"name": "phone_number",  "values": ["+2348031456789"]},
        {"name": "email",         "values": ["emeka@emekamart.com"]},
        {"name": "business_name", "values": ["Emeka's Supermart"]},
        {"name": "business_type", "values": ["Supermarket"]},
        {"name": "problem_stated","values": ["We lose track of stock."]},
    ],
}

# Meta Lead Ads webhook payload — Section 6.1
def _lead_ad_payload(page_id="PAGE-001", leadgen_id="leadgen-001") -> dict:
    return {
        "object": "page",
        "entry": [{
            "id": page_id,
            "changes": [{
                "field": "leadgen",
                "value": {
                    "leadgen_id": leadgen_id,
                    "page_id": page_id,
                    "form_id": "FORM-001",
                    "ad_id": "AD-001",
                    "adgroup_id": "ADGROUP-001",
                    "campaign_id": "CAMPAIGN-001",
                    "created_time": 1711360920,
                },
            }],
        }],
    }


# ---------------------------------------------------------------------------
# Fixtures — override settings so tests never need real env vars
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    """Inject test values for settings used by webhooks."""
    import app.config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "META_VERIFY_TOKEN", "test-verify-token", raising=False)
    monkeypatch.setattr(cfg_module.settings, "META_APP_SECRET",   "test-app-secret",   raising=False)
    monkeypatch.setattr(cfg_module.settings, "META_WHATSAPP_TOKEN","test-wa-token",     raising=False)


@pytest.fixture
def client_factory():
    """
    Return a callable that builds a TestClient with get_supabase overridden.
    Cleans up dependency_overrides after each test (restores to empty).
    """
    from app.main import app
    from app.database import get_supabase

    overrides_set = []

    def _make(db_mock):
        app.dependency_overrides[get_supabase] = lambda: db_mock
        overrides_set.append(get_supabase)
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    # Cleanup — remove only what we set (never .clear())
    for dep in overrides_set:
        app.dependency_overrides.pop(dep, None)


# ===========================================================================
# GET /webhooks/meta/verify
# ===========================================================================

class TestMetaVerifyWebhook:

    def test_valid_token_returns_challenge(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        resp = client.get(
            "/webhooks/meta/verify",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "12345",
            },
        )
        assert resp.status_code == 200
        # Challenge value returned as body
        assert "12345" in resp.text

    def test_wrong_token_returns_403(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        resp = client.get(
            "/webhooks/meta/verify",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "WRONG-TOKEN",
                "hub.challenge": "12345",
            },
        )
        assert resp.status_code == 403

    def test_missing_mode_returns_403(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        resp = client.get(
            "/webhooks/meta/verify",
            params={
                "hub.verify_token": "test-verify-token",
                "hub.challenge": "99999",
            },
        )
        assert resp.status_code == 403

    def test_missing_challenge_returns_200(self, client_factory):
        """No challenge in params — still 200 if token is correct."""
        db = _build_db()
        client = client_factory(db)
        resp = client.get(
            "/webhooks/meta/verify",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify-token",
            },
        )
        assert resp.status_code == 200


# ===========================================================================
# POST /webhooks/meta/lead-ads — signature verification
# ===========================================================================

class TestMetaLeadAdsSignature:

    def test_missing_signature_returns_403(self, client_factory):
        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        body = json.dumps(_lead_ad_payload()).encode()
        resp = client.post(
            "/webhooks/meta/lead-ads",
            content=body,
            headers={"Content-Type": "application/json"},
            # No X-Hub-Signature-256
        )
        assert resp.status_code == 403

    def test_wrong_signature_returns_403(self, client_factory):
        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        body = json.dumps(_lead_ad_payload()).encode()
        resp = client.post(
            "/webhooks/meta/lead-ads",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeefdeadbeef",
            },
        )
        assert resp.status_code == 403

    def test_tampered_body_signature_mismatch_returns_403(self, client_factory):
        """Sign one payload but send a different one."""
        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        original = json.dumps(_lead_ad_payload()).encode()
        tampered = original + b"extra"
        sig = _compute_sig("test-app-secret", original)
        resp = client.post(
            "/webhooks/meta/lead-ads",
            content=tampered,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 403


# ===========================================================================
# POST /webhooks/meta/lead-ads — valid payload + Graph API mock
# ===========================================================================

class TestMetaLeadAdsProcessing:

    def _post(self, client, payload_dict: dict):
        body = json.dumps(payload_dict).encode()
        sig = _compute_sig("test-app-secret", body)
        return client.post(
            "/webhooks/meta/lead-ads",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )

    @respx.mock
    def test_valid_payload_creates_lead_returns_200(self, client_factory):
        """Happy path: valid signature + Graph API mocked → lead created → 200."""
        respx.get(
            "https://graph.facebook.com/v18.0/leadgen-001",
        ).mock(return_value=httpx.Response(200, json=_GRAPH_RESPONSE))

        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        resp = self._post(client, _lead_ad_payload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["processed"] == 1
        assert body["errors"] == []

    @respx.mock
    def test_duplicate_lead_returns_200_not_500(self, client_factory):
        """
        Duplicate detection returns DUPLICATE_DETECTED 409.
        Webhook must absorb it (return 200) and log — Meta expects 200 always.
        """
        respx.get(
            "https://graph.facebook.com/v18.0/leadgen-001",
        ).mock(return_value=httpx.Response(200, json=_GRAPH_RESPONSE))

        db = _build_db(_ORG_ROW)
        # Patch duplicate detection to always return True
        from unittest.mock import patch
        with patch("app.services.lead_service.check_duplicate", return_value=True):
            client = client_factory(db)
            resp = self._post(client, _lead_ad_payload())

        assert resp.status_code == 200
        # processed is 0 because duplicate — but still 200
        assert resp.json()["status"] == "ok"

    @respx.mock
    def test_non_page_object_ignored_returns_200(self, client_factory):
        """Non-page object type is ignored — returns 200 with status='ignored'."""
        db = _build_db(_ORG_ROW)
        client = client_factory(db)

        payload = {"object": "whatsapp_business_account", "entry": []}
        body = json.dumps(payload).encode()
        sig = _compute_sig("test-app-secret", body)
        resp = client.post(
            "/webhooks/meta/lead-ads",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @respx.mock
    def test_unknown_page_id_skipped(self, client_factory):
        """
        If page_id doesn't match any org, the entry is skipped.
        Returns 200 with processed=0.
        """
        respx.get(
            "https://graph.facebook.com/v18.0/leadgen-001",
        ).mock(return_value=httpx.Response(200, json=_GRAPH_RESPONSE))

        # DB returns no org for this page_id
        db = _build_db(org_row=None)
        client = client_factory(db)
        resp = self._post(client, _lead_ad_payload(page_id="UNKNOWN-PAGE"))

        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    @respx.mock
    def test_graph_api_field_data_parsed_correctly(self, client_factory):
        """
        Verify that the correct fields are extracted from field_data and saved.
        We inspect the insert call on the leads chain.
        """
        respx.get(
            "https://graph.facebook.com/v18.0/leadgen-002",
        ).mock(return_value=httpx.Response(200, json={
            **_GRAPH_RESPONSE,
            "id": "leadgen-002",
            "field_data": [
                {"name": "full_name",     "values": ["Ngozi Eze"]},
                {"name": "phone_number",  "values": ["+2348011111111"]},
                {"name": "email",         "values": ["ngozi@test.com"]},
                {"name": "business_name", "values": ["Ngozi Stores"]},
            ],
        }))

        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        payload = _lead_ad_payload(leadgen_id="leadgen-002")
        payload["entry"][0]["changes"][0]["value"]["leadgen_id"] = "leadgen-002"

        resp = self._post(client, payload)
        assert resp.status_code == 200

        # Inspect leads.insert call to verify correct data
        insert_calls = db.table("leads").insert.call_args_list
        assert len(insert_calls) >= 1
        inserted = insert_calls[0].args[0]
        assert inserted["full_name"] == "Ngozi Eze"
        assert inserted.get("source") in ("facebook_ad", "instagram_ad")

    @respx.mock
    def test_graph_api_error_handled_gracefully(self, client_factory):
        """If Graph API returns 500, the webhook still returns 200 (logged as error)."""
        respx.get(
            "https://graph.facebook.com/v18.0/leadgen-001",
        ).mock(return_value=httpx.Response(500, json={"error": "Internal error"}))

        db = _build_db(_ORG_ROW)
        client = client_factory(db)
        resp = self._post(client, _lead_ad_payload())

        # Always 200 to Meta — errors are logged internally
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 0
        assert len(data["errors"]) >= 1

    @respx.mock
    def test_multiple_changes_in_one_entry(self, client_factory):
        """Multiple leadgen changes in one payload are all processed."""
        respx.get("https://graph.facebook.com/v18.0/leadgen-A").mock(
            return_value=httpx.Response(200, json={**_GRAPH_RESPONSE, "id": "leadgen-A"})
        )
        respx.get("https://graph.facebook.com/v18.0/leadgen-B").mock(
            return_value=httpx.Response(200, json={**_GRAPH_RESPONSE, "id": "leadgen-B"})
        )

        db = _build_db(_ORG_ROW)
        client = client_factory(db)

        payload = {
            "object": "page",
            "entry": [{
                "id": "PAGE-001",
                "changes": [
                    {"field": "leadgen", "value": {
                        "leadgen_id": "leadgen-A", "page_id": "PAGE-001",
                        "ad_id": "AD-1", "campaign_id": "CAM-1",
                    }},
                    {"field": "leadgen", "value": {
                        "leadgen_id": "leadgen-B", "page_id": "PAGE-001",
                        "ad_id": "AD-2", "campaign_id": "CAM-1",
                    }},
                ],
            }],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        assert resp.json()["processed"] == 2


# ===========================================================================
# POST /webhooks/meta/whatsapp  (stub)
# ===========================================================================

class TestMetaWhatsappWebhookStub:

    def test_valid_signature_returns_200(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
        sig = _compute_sig("test-app-secret", body)
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert resp.status_code == 200

    def test_bad_signature_returns_403(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        body = json.dumps({"object": "whatsapp_business_account"}).encode()
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={"Content-Type": "application/json",
                     "X-Hub-Signature-256": "sha256=badbad"},
        )
        assert resp.status_code == 403

    def test_missing_signature_returns_403(self, client_factory):
        db = _build_db()
        client = client_factory(db)
        body = json.dumps({"object": "whatsapp_business_account"}).encode()
        resp = client.post(
            "/webhooks/meta/whatsapp",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403