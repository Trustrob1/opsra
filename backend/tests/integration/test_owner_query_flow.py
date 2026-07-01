"""
tests/integration/test_owner_query_flow.py
INTEGRATIONS-1 — Integration tests for the owner query routing
through the WhatsApp webhook.

Tests confirm:
- Owner number routes to handle_owner_query, not triage/lead paths
- Non-owner numbers are not routed to owner handler
- _is_org_owner exact-match logic

Pattern 32: pop overrides in teardown, never clear().
Pattern 42: patch at source module where name is USED.
Pattern 63: patch at import location in webhooks, not at service module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

ORG_ID       = "33333333-3333-3333-3333-333333333333"
PHONE_NUM_ID = "99999999999"
OWNER_PHONE  = "+2348055551234"
OTHER_PHONE  = "+2348099990000"
APP_SECRET   = "test_secret_value"


# ── _is_org_owner unit tests ─────────────────────────────────────────────────

class TestIsOrgOwner:
    """Unit-level tests for the _is_org_owner helper."""

    def test_exact_match_returns_true(self):
        from app.routers.webhooks import _is_org_owner
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
          .maybe_single.return_value.execute.return_value.data = {
              "org_business_contact_number": "+2348055551234"
          }
        assert _is_org_owner(db, ORG_ID, "+2348055551234") is True

    def test_normalises_without_plus(self):
        from app.routers.webhooks import _is_org_owner
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
          .maybe_single.return_value.execute.return_value.data = {
              "org_business_contact_number": "+2348055551234"
          }
        assert _is_org_owner(db, ORG_ID, "2348055551234") is True

    def test_different_number_returns_false(self):
        from app.routers.webhooks import _is_org_owner
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
          .maybe_single.return_value.execute.return_value.data = {
              "org_business_contact_number": "+2348055551234"
          }
        assert _is_org_owner(db, ORG_ID, "+2348099990000") is False

    def test_empty_stored_number_returns_false(self):
        from app.routers.webhooks import _is_org_owner
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
          .maybe_single.return_value.execute.return_value.data = {
              "org_business_contact_number": ""
          }
        assert _is_org_owner(db, ORG_ID, "+2348055551234") is False

    def test_db_failure_returns_false(self):
        from app.routers.webhooks import _is_org_owner
        db = MagicMock()
        db.table.side_effect = Exception("DB error")
        assert _is_org_owner(db, ORG_ID, "+2348055551234") is False


# ── Webhook routing tests ─────────────────────────────────────────────────────

class TestOwnerRoutingWebhook:
    """
    Confirms handle_owner_query is called for owner messages and NOT
    called for non-owner messages.

    Patches handle_owner_query at the import location inside webhooks.py
    (app.routers.webhooks) — not at the service module — because the
    function is imported with a local `from ... import` inside the handler.
    """

    def test_owner_message_routes_to_owner_handler(self):
        """Owner number → _is_org_owner returns True → handler called.
        _is_org_owner is patched with return_value=True because normalize_phone()
        transforms the sender number before it reaches _is_org_owner, making
        an exact string comparison against OWNER_PHONE unreliable in tests.
        The unit tests for _is_org_owner itself cover the matching logic."""
        from app.routers import webhooks as wh

        db = MagicMock()
        # dedup check — no duplicate
        db.table.return_value.select.return_value.eq.return_value \
          .limit.return_value.execute.return_value.data = []

        with patch.object(wh, "_lookup_record_by_phone",
                          return_value=(None, None, None, None)), \
             patch.object(wh, "_lookup_org_by_phone_number_id",
                          return_value=ORG_ID), \
             patch.object(wh, "_is_org_owner", return_value=True), \
             patch("app.services.owner_query_service.handle_owner_query") as mock_handler:

            message = {
                "from": OWNER_PHONE,
                "id": "msg_owner_001",
                "type": "text",
                "text": {"body": "revenue this month"},
            }
            wh._handle_inbound_message(db, message, "Test Owner", PHONE_NUM_ID)
            mock_handler.assert_called_once()

    def test_non_owner_message_does_not_route_to_owner_handler(self):
        """Non-owner number → _is_org_owner returns False → handler not called."""
        from app.routers import webhooks as wh

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
          .limit.return_value.execute.return_value.data = []

        with patch.object(wh, "_lookup_record_by_phone",
                          return_value=(None, None, None, None)), \
             patch.object(wh, "_lookup_org_by_phone_number_id",
                          return_value=ORG_ID), \
             patch.object(wh, "_is_org_owner", return_value=False), \
             patch.object(wh, "triage_service") as mock_triage, \
             patch("app.services.owner_query_service.handle_owner_query") as mock_handler:

            mock_triage.get_active_session.return_value = None
            mock_triage.get_or_create_session.return_value = {"id": "sess-001"}

            # Org behaviour fetch
            db.table.return_value.select.return_value.eq.return_value \
              .maybe_single.return_value.execute.return_value.data = {
                  "unknown_contact_behavior": "triage_first",
                  "whatsapp_phone_id": PHONE_NUM_ID,
                  "sales_mode": "consultative",
                  "whatsapp_sales_mode": "human",
                  "shopify_connected": False,
                  "whatsapp_triage_config": None,
              }

            message = {
                "from": OTHER_PHONE,
                "id": "msg_other_001",
                "type": "text",
                "text": {"body": "hello"},
            }
            wh._handle_inbound_message(db, message, "Unknown", PHONE_NUM_ID)
            mock_handler.assert_not_called()
