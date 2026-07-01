"""
app/services/payment_service.py
INTEGRATIONS-1 — Paystack/Flutterwave integration provider (proof migration).

Reads from Opsra's own subscriptions/customers tables populated by the
existing Paystack and Flutterwave webhooks. No live external API call
is made — the webhook already writes what we need.

Existing webhook handlers (POST /webhooks/payment/paystack and
/webhooks/payment/flutterwave) are NOT modified — they continue writing
to subscriptions exactly as before. This file is read-only.

S14: all methods return error/empty shape on failure, never raise.
Pattern 29: load_dotenv() at module level.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from dotenv import load_dotenv

from app.integrations.base import IntegrationProvider

load_dotenv()

logger = logging.getLogger(__name__)


class PaystackProvider(IntegrationProvider):
    """
    Reads subscription/payment data already stored in Opsra by the
    Paystack webhook handler.
    """

    name = "paystack"

    def capabilities(self) -> dict:
        return {
            "label": "Revenue & Payments",
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
        """
        Returns revenue and subscription counts from the subscriptions
        table for the given period.
        S14: returns {'available': False, 'reason': ...} on any failure.
        """
        try:
            from_iso = date_from.isoformat()
            to_iso   = date_to.isoformat() + "T23:59:59"

            # Fetch subscriptions active or renewed in the period
            result = (
                db.table("subscriptions")
                .select(
                    "id, amount, status, plan_name, "
                    "payment_method, created_at, renewed_at"
                )
                .eq("org_id", org_id)
                .gte("created_at", from_iso)
                .lte("created_at", to_iso)
                .execute()
            )
            rows = result.data or []

            total_revenue    = sum(float(r.get("amount") or 0) for r in rows)
            total_count      = len(rows)
            active_count     = sum(1 for r in rows if r.get("status") == "active")
            payment_methods: dict = {}
            for r in rows:
                pm = r.get("payment_method") or "unknown"
                payment_methods[pm] = payment_methods.get(pm, 0) + 1

            return {
                "available":         True,
                "provider":          self.name,
                "date_from":         str(date_from),
                "date_to":           str(date_to),
                "total_revenue_ngn": total_revenue,
                "total_payments":    total_count,
                "active_subscriptions": active_count,
                "payment_methods":   payment_methods,
            }
        except Exception as exc:
            logger.warning(
                "PaystackProvider.get_summary failed org=%s: %s", org_id, exc
            )
            return {
                "available": False,
                "reason": "Could not retrieve payment data right now.",
            }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Simple keyword search over subscription plan names and statuses.
        S14: returns [] on any failure.
        """
        try:
            result = (
                db.table("subscriptions")
                .select(
                    "id, amount, status, plan_name, "
                    "payment_method, created_at"
                )
                .eq("org_id", org_id)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            rows = result.data or []
            query_lower = query.lower()
            matches = [
                {
                    "id":             r.get("id"),
                    "plan":           r.get("plan_name") or "—",
                    "amount_ngn":     float(r.get("amount") or 0),
                    "status":         r.get("status") or "—",
                    "payment_method": r.get("payment_method") or "—",
                    "created_at":     r.get("created_at") or "—",
                }
                for r in rows
                if (
                    query_lower in (r.get("plan_name") or "").lower()
                    or query_lower in (r.get("status") or "").lower()
                    or query_lower in (r.get("payment_method") or "").lower()
                )
            ]
            return matches[:limit]
        except Exception as exc:
            logger.warning(
                "PaystackProvider.search failed org=%s: %s", org_id, exc
            )
            return []
