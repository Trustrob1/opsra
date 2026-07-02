"""
app/services/mock_provider_service.py
TESTING ONLY — Mock data provider for owner query flow testing.

Returns realistic fake data so the full owner query flow can be tested
end-to-end without real Paystack credentials or subscriptions table data.

IMPORTANT: Remove this provider from the registry before going live
with real data. It is for development/testing only.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.integrations.base import IntegrationProvider

logger = logging.getLogger(__name__)


class MockRevenueProvider(IntegrationProvider):
    """
    Returns realistic fake revenue data for testing purposes.
    Mimics the PaystackProvider interface exactly.
    """

    name = "mock_revenue"

    def capabilities(self) -> dict:
        return {
            "label": "Revenue & Payments (Test)",
            "emoji": "💰",
            "examples": [
                "What's my revenue this month?",
                "How many conversions this week?",
                "Payment summary for last quarter",
            ],
        }

    def get_summary(
        self,
        db: Any,
        org_id: str,
        date_from: date,
        date_to: date,
    ) -> dict:
        """Returns realistic fake revenue data."""
        days = (date_to - date_from).days + 1
        return {
            "available":            True,
            "provider":             self.name,
            "data_source":          "mock_data_for_testing",
            "date_from":            str(date_from),
            "date_to":              str(date_to),
            "total_revenue_ngn":    days * 45000.0,
            "total_payments":       days * 3,
            "active_subscriptions": 47,
            "payment_methods": {
                "card":     days * 2,
                "transfer": days * 1,
            },
        }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Returns fake transaction records."""
        return [
            {
                "reference":   f"mock_ref_{i:03d}",
                "amount_ngn":  45000.0,
                "status":      "success",
                "channel":     "card" if i % 2 == 0 else "transfer",
                "created_at":  str(date.today()),
                "customer":    f"customer{i}@example.com",
            }
            for i in range(1, min(limit + 1, 6))
        ]


class MockLeadsProvider(IntegrationProvider):
    """
    Returns realistic fake leads data for testing purposes.
    """

    name = "mock_leads"

    def capabilities(self) -> dict:
        return {
            "label": "Leads & Pipeline (Test)",
            "emoji": "📊",
            "examples": [
                "How many leads came in yesterday?",
                "Which lead source is converting best?",
                "Show me leads by stage",
            ],
        }

    def get_summary(
        self,
        db: Any,
        org_id: str,
        date_from: date,
        date_to: date,
    ) -> dict:
        """Returns realistic fake leads data."""
        days = (date_to - date_from).days + 1
        return {
            "available":          True,
            "provider":           self.name,
            "data_source":        "mock_data_for_testing",
            "date_from":          str(date_from),
            "date_to":            str(date_to),
            "total_leads":        days * 8,
            "converted":          days * 2,
            "conversion_rate_pct": 25.0,
            "by_source": {
                "facebook_ad":     days * 4,
                "instagram_ad":    days * 2,
                "whatsapp_inbound": days * 2,
            },
            "by_stage": {
                "new":           days * 3,
                "contacted":     days * 2,
                "converted":     days * 2,
                "lost":          days * 1,
            },
        }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Returns fake lead records."""
        return [
            {
                "name":       f"Test Lead {i}",
                "source":     "facebook_ad" if i % 2 == 0 else "instagram_ad",
                "stage":      "new",
                "created_at": str(date.today()),
            }
            for i in range(1, min(limit + 1, 6))
        ]
