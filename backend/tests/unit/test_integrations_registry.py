"""
tests/unit/test_integrations_registry.py
INTEGRATIONS-1 — Unit tests for registry and payment_service.
Pattern 24: all UUIDs are valid format.
Pattern 42: patch at source module where name is USED.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

ORG_ID = "11111111-1111-1111-1111-111111111111"


# ── Registry: get_connected_providers ───────────────────────────────────────

class TestGetConnectedProviders:
    def _db(self, rows):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = rows
        return db

    def test_returns_connected_registered_providers(self):
        from app.integrations.registry import get_connected_providers
        db = self._db([{"provider": "paystack"}])
        result = get_connected_providers(db, ORG_ID)
        assert "paystack" in result

    def test_excludes_unregistered_providers(self):
        from app.integrations.registry import get_connected_providers
        db = self._db([{"provider": "unknown_future_provider"}])
        result = get_connected_providers(db, ORG_ID)
        assert "unknown_future_provider" not in result

    def test_returns_empty_on_db_failure(self):
        from app.integrations.registry import get_connected_providers
        db = MagicMock()
        db.table.side_effect = Exception("DB error")
        result = get_connected_providers(db, ORG_ID)
        assert result == []

    def test_returns_empty_when_no_rows(self):
        from app.integrations.registry import get_connected_providers
        db = self._db([])
        result = get_connected_providers(db, ORG_ID)
        assert result == []


# ── Registry: get_provider ───────────────────────────────────────────────────

class TestGetProvider:
    def test_returns_paystack_provider(self):
        from app.integrations.registry import get_provider
        provider = get_provider("paystack")
        assert provider is not None
        assert provider.name == "paystack"

    def test_returns_none_for_unknown(self):
        from app.integrations.registry import get_provider
        result = get_provider("nonexistent_provider")
        assert result is None


# ── Registry: build_help_message ─────────────────────────────────────────────

class TestBuildHelpMessage:
    def test_includes_connected_provider_label(self):
        from app.integrations import registry
        with patch.object(registry, "get_connected_providers", return_value=["paystack"]):
            db = MagicMock()
            msg = registry.build_help_message(db, ORG_ID, "https://example.com/dash")
            assert "Revenue" in msg or "Payment" in msg

    def test_includes_dashboard_link(self):
        from app.integrations import registry
        with patch.object(registry, "get_connected_providers", return_value=[]):
            db = MagicMock()
            msg = registry.build_help_message(db, ORG_ID, "https://example.com/dash")
            assert "example.com/dash" in msg

    def test_graceful_on_failure(self):
        from app.integrations import registry
        with patch.object(registry, "get_connected_providers", side_effect=Exception("fail")):
            db = MagicMock()
            msg = registry.build_help_message(db, ORG_ID, "")
            assert isinstance(msg, str)
            assert len(msg) > 0


# ── PaystackProvider: get_summary ────────────────────────────────────────────

class TestPaystackProviderGetSummary:
    def _db(self, rows):
        db = MagicMock()
        db.table.return_value.select.return_value \
          .eq.return_value.gte.return_value.lte.return_value \
          .execute.return_value.data = rows
        return db

    def test_returns_correct_totals(self):
        from app.services.payment_service import PaystackProvider
        rows = [
            {"amount": "5000", "status": "active",  "payment_method": "card"},
            {"amount": "3000", "status": "active",  "payment_method": "transfer"},
            {"amount": "2000", "status": "expired", "payment_method": "card"},
        ]
        db = self._db(rows)
        result = PaystackProvider().get_summary(
            db, ORG_ID, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result["available"] is True
        assert result["total_revenue_ngn"] == 10000.0
        assert result["total_payments"] == 3
        assert result["active_subscriptions"] == 2

    def test_returns_error_shape_on_db_failure(self):
        from app.services.payment_service import PaystackProvider
        db = MagicMock()
        db.table.side_effect = Exception("DB error")
        result = PaystackProvider().get_summary(
            db, ORG_ID, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result["available"] is False
        assert "reason" in result

    def test_returns_zero_totals_for_empty(self):
        from app.services.payment_service import PaystackProvider
        db = self._db([])
        result = PaystackProvider().get_summary(
            db, ORG_ID, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result["available"] is True
        assert result["total_revenue_ngn"] == 0.0
        assert result["total_payments"] == 0


# ── PaystackProvider: search ─────────────────────────────────────────────────

class TestPaystackProviderSearch:
    def _db(self, rows):
        db = MagicMock()
        db.table.return_value.select.return_value \
          .eq.return_value.order.return_value.limit.return_value \
          .execute.return_value.data = rows
        return db

    def test_returns_matching_rows(self):
        from app.services.payment_service import PaystackProvider
        rows = [
            {"id": "a", "plan_name": "Basic Plan", "amount": "5000",
             "status": "active", "payment_method": "card", "created_at": "2026-06-01"},
            {"id": "b", "plan_name": "Pro Plan", "amount": "10000",
             "status": "active", "payment_method": "transfer", "created_at": "2026-06-02"},
        ]
        db = self._db(rows)
        result = PaystackProvider().search(db, ORG_ID, "basic")
        assert len(result) == 1
        assert result[0]["plan"] == "Basic Plan"

    def test_returns_empty_list_on_failure(self):
        from app.services.payment_service import PaystackProvider
        db = MagicMock()
        db.table.side_effect = Exception("fail")
        result = PaystackProvider().search(db, ORG_ID, "anything")
        assert result == []
