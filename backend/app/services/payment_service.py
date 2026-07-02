"""
app/services/payment_service.py
INTEGRATIONS-1 — Paystack/Flutterwave integration provider (proof migration).

Reads from Opsra's own subscriptions/customers tables populated by the
existing Paystack and Flutterwave webhooks. Tries live Paystack API first if secret_key is set in integrations.credentials.
Falls back to Opsra's subscriptions table if no API key is configured.

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

import httpx as _httpx
 
from app.integrations.base import IntegrationProvider
 
_PAYSTACK_API_BASE = "https://api.paystack.co"
 
 
def _get_paystack_secret_key(db, org_id: str) -> str:
    """
    Read Paystack secret key from integrations table credentials JSONB.
    Returns '' if not set — caller falls back to subscriptions table.
    S14: never raises.
    """
    try:
        result = (
            db.table("integrations")
            .select("credentials")
            .eq("org_id", org_id)
            .eq("provider", "paystack")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        creds = (data or {}).get("credentials") or {}
        return creds.get("secret_key") or ""
    except Exception:
        return ""
 
 
def _call_paystack_totals(
    secret_key: str,
    date_from: str,
    date_to: str,
) -> dict | None:
    """
    Call Paystack GET /transaction/totals for the given period.
    Returns parsed JSON or None on any failure. S14: never raises.
    """
    try:
        with _httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_PAYSTACK_API_BASE}/transaction/totals",
                headers={"Authorization": f"Bearer {secret_key}"},
                params={"from": date_from, "to": date_to},
            )
        if resp.status_code != 200:
            return None
        body = resp.json()
        if not body.get("status"):
            return None
        return body.get("data") or {}
    except Exception:
        return None
 
 
def _call_paystack_transactions(
    secret_key: str,
    date_from: str,
    date_to: str,
    query: str = "",
    per_page: int = 20,
) -> list[dict]:
    """
    Call Paystack GET /transaction for the given period.
    Returns list of transaction dicts. S14: returns [] on any failure.
    """
    try:
        params: dict = {
            "from":     date_from,
            "to":       date_to,
            "perPage":  per_page,
            "page":     1,
            "status":   "success",
        }
        if query:
            params["customer"] = query
        with _httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{_PAYSTACK_API_BASE}/transaction",
                headers={"Authorization": f"Bearer {secret_key}"},
                params=params,
            )
        if resp.status_code != 200:
            return []
        body = resp.json()
        return body.get("data") or []
    except Exception:
        return []

load_dotenv()

logger = logging.getLogger(__name__)


class PaystackProvider(IntegrationProvider):
    """
    Reads payment data from live Paystack API when secret_key is configured,
    falling back to Opsra's subscriptions table populated by the webhook handler.
    """

    name = "paystack"

    def capabilities(self) -> dict:
        return {
            "label": "Subscription Payments & Revenue",
            "emoji": "💰",
            "examples": [
                "What's my subscription revenue this month?",
                "How many payment conversions this week?",
                "Payment summary for last quarter",
                "How much did I receive in payments?",
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
        Returns revenue and payment counts for the given period.
        Tries live Paystack API first (if secret_key in integrations.credentials).
        Falls back to Opsra subscriptions table if no API key is configured.
        S14: returns {'available': False, 'reason': ...} on any failure.
        """
        from_iso = date_from.isoformat()
        to_iso   = date_to.isoformat()
 
        # ── Try live Paystack API ────────────────────────────────────────
        try:
            secret_key = _get_paystack_secret_key(db, org_id)
            if secret_key:
                totals = _call_paystack_totals(secret_key, from_iso, to_iso)
                if totals is not None:
                    # Paystack returns amounts in kobo — convert to naira
                    total_volume = float(totals.get("total_volume") or 0) / 100
                    total_txns   = int(totals.get("total_transactions") or 0)
                    pending      = float(totals.get("pending_transfers") or 0) / 100
                    return {
                        "available":              True,
                        "provider":               self.name,
                        "data_source":            "live_paystack_api",
                        "date_from":              str(date_from),
                        "date_to":                str(date_to),
                        "total_revenue_ngn":      total_volume,
                        "total_transactions":     total_txns,
                        "pending_transfers_ngn":  pending,
                    }
                logger.warning(
                    "PaystackProvider: live API returned None for org=%s, "
                    "falling back to subscriptions table", org_id
                )
        except Exception as exc:
            logger.warning(
                "PaystackProvider: live API attempt failed org=%s: %s", org_id, exc
            )
 
        # ── Fall back to subscriptions table ─────────────────────────────
        try:
            to_iso_dt = to_iso + "T23:59:59"
            result = (
                db.table("subscriptions")
                .select(
                    "id, amount, status, plan_name, "
                    "payment_method, created_at, renewed_at"
                )
                .eq("org_id", org_id)
                .gte("created_at", from_iso)
                .lte("created_at", to_iso_dt)
                .execute()
            )
            rows = result.data or []
 
            total_revenue   = sum(float(r.get("amount") or 0) for r in rows)
            total_count     = len(rows)
            active_count    = sum(1 for r in rows if r.get("status") == "active")
            payment_methods: dict = {}
            for r in rows:
                pm = r.get("payment_method") or "unknown"
                payment_methods[pm] = payment_methods.get(pm, 0) + 1
 
            return {
                "available":            True,
                "provider":             self.name,
                "data_source":          "opsra_subscriptions",
                "date_from":            str(date_from),
                "date_to":              str(date_to),
                "total_revenue_ngn":    total_revenue,
                "total_payments":       total_count,
                "active_subscriptions": active_count,
                "payment_methods":      payment_methods,
            }
        except Exception as exc:
            logger.warning(
                "PaystackProvider.get_summary subscriptions fallback failed "
                "org=%s: %s", org_id, exc
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
        Search transactions. Tries live Paystack API first, falls back to
        subscriptions table. S14: returns [] on any failure.
        """
        # ── Try live Paystack API ────────────────────────────────────────
        try:
            secret_key = _get_paystack_secret_key(db, org_id)
            if secret_key:
                from datetime import date as _date
                # Search last 90 days by default for search queries
                date_to   = _date.today().isoformat()
                date_from = (_date.today().replace(day=1)
                             .replace(month=max(1, _date.today().month - 3))
                             ).isoformat()
                txns = _call_paystack_transactions(
                    secret_key, date_from, date_to, query=query, per_page=limit
                )
                if txns:
                    return [
                        {
                            "reference":   t.get("reference") or "—",
                            "amount_ngn":  float(t.get("amount") or 0) / 100,
                            "status":      t.get("status") or "—",
                            "channel":     t.get("channel") or "—",
                            "created_at":  (t.get("created_at") or "")[:10],
                            "customer":    (t.get("customer") or {}).get("email") or "—",
                        }
                        for t in txns
                    ][:limit]
        except Exception as exc:
            logger.warning(
                "PaystackProvider.search live API failed org=%s: %s", org_id, exc
            )
 
        # ── Fall back to subscriptions table ─────────────────────────────
        try:
            result = (
                db.table("subscriptions")
                .select("id, amount, status, plan_name, payment_method, created_at")
                .eq("org_id", org_id)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            rows        = result.data or []
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
                if not query_lower or (
                    query_lower in (r.get("plan_name") or "").lower()
                    or query_lower in (r.get("status") or "").lower()
                    or query_lower in (r.get("payment_method") or "").lower()
                )
            ]
            return matches[:limit]
        except Exception as exc:
            logger.warning(
                "PaystackProvider.search subscriptions fallback failed "
                "org=%s: %s", org_id, exc
            )
            return []
