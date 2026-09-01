"""
app/services/direct_sales_provider_service.py
Direct Sales integration provider — Business Activities' Sales Record.

Reads from Opsra's own `direct_sales` table — no external API calls needed.
Same "no credentials" shape as OpsraOrdersProvider, but a DIFFERENT data
domain: this is transaction-level sales logged/imported by reps through
the Business Activities > Sales Record tab (manual entry, Excel, or
Google Sheets import — Phase 4b/4c), not WhatsApp commerce or leads.

Mutual exclusivity (deliberate, per product decision):
  direct_sales is treated as an alternate "sales channel" to
  shopify / opsra_orders — never both connected for the same org at once.
  Enforced in app/routers/admin.py's connect/disconnect routes via
  app.integrations.registry.find_conflicting_sales_channel(). This
  provider file has no awareness of that rule — it only answers queries
  when the registry has actually made it available.

Data source: direct_sales table
  Columns used: sale_date, region, model, variant, units, amount,
  reconciliation_status ("Reconciled" | "Pending"), rep_name,
  customer_name, phone, channel, notes, source_team, import_source.

Separation of concerns:
  This provider answers questions about: rep-logged/imported sales
  transactions — revenue, units, region performance, model/variant
  mix, reconciliation status.

  It does NOT answer questions about: Shopify storefront orders
  (→ shopify), WhatsApp commerce sessions or lead pipeline (→ opsra_orders),
  subscription/payment revenue (→ paystack).

What the owner can ask:
  get_summary():
    - What's my total sales revenue this month?
    - How many units did we sell this week?
    - What's my average sale value?
    - Which region is performing best?
    - What are my top selling models?
    - How much revenue is still pending reconciliation?

  search():
    - Show me pending reconciliation sales
    - Show me sales in Lagos / Abuja
    - Show me sales for [rep name]
    - Show me Elite Cool sales

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

_SUMMARY_COLUMNS = (
    "sale_date, region, model, variant, units, amount, "
    "reconciliation_status, rep_name"
)


class DirectSalesProvider(IntegrationProvider):
    """
    Reads transaction-level sales data from Opsra's own direct_sales
    table (Business Activities > Sales Record). No external credentials
    needed. Mutually exclusive with shopify/opsra_orders at the
    integrations-table level (enforced in admin.py, not here).
    """

    name = "direct_sales"

    def capabilities(self) -> dict:
        return {
            "label": "Direct Sales (Business Activities)",
            "emoji": "\U0001F4B5",
            "examples": [
                "What's my total sales revenue this month?",
                "How many units did we sell this week?",
                "Which region is performing best?",
                "What are my top selling models?",
                "How much revenue is pending reconciliation?",
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
        Returns revenue, units, region, model, and reconciliation
        breakdowns for the given period — same underlying data as the
        Sales Record dashboard's KPI cards (growth_config.py's
        get_direct_sales_summary), so WhatsApp answers and the dashboard
        never disagree.
        S14: returns {'available': False, 'reason': ...} on any failure.
        """
        try:
            from_iso = date_from.isoformat()
            to_iso   = date_to.isoformat()

            result = (
                db.table("direct_sales")
                .select(_SUMMARY_COLUMNS)
                .eq("org_id", org_id)
                .gte("sale_date", from_iso)
                .lte("sale_date", to_iso)
                .execute()
            )
            rows = result.data or []

            total_transactions = len(rows)
            total_revenue = sum(float(r.get("amount") or 0) for r in rows)
            total_units = sum(int(r.get("units") or 0) for r in rows)
            average_sale_value = (
                round(total_revenue / total_transactions, 2)
                if total_transactions > 0 else 0.0
            )

            # Revenue by region
            revenue_by_region: dict[str, float] = {}
            for r in rows:
                region = r.get("region") or "Unspecified"
                revenue_by_region[region] = (
                    revenue_by_region.get(region, 0.0) + float(r.get("amount") or 0)
                )
            revenue_by_region = {
                k: round(v, 2) for k, v in revenue_by_region.items()
            }

            # Reconciled vs pending (by revenue amount, matching the
            # Sales Record dashboard's "Reconciled vs Pending" card)
            reconciled_amount = sum(
                float(r.get("amount") or 0)
                for r in rows
                if (r.get("reconciliation_status") or "").strip().lower() == "reconciled"
            )
            pending_amount = sum(
                float(r.get("amount") or 0)
                for r in rows
                if (r.get("reconciliation_status") or "").strip().lower() != "reconciled"
            )

            # Top-selling models by units
            units_by_model: dict[str, int] = {}
            for r in rows:
                model = r.get("model")
                if not model:
                    continue
                units_by_model[model] = units_by_model.get(model, 0) + int(r.get("units") or 0)
            top_selling_models = sorted(
                units_by_model.items(), key=lambda kv: kv[1], reverse=True
            )[:5]

            # Best performing region (by revenue)
            best_region = None
            best_region_revenue = 0.0
            for region, revenue in revenue_by_region.items():
                if revenue > best_region_revenue:
                    best_region_revenue = revenue
                    best_region = region

            return {
                "available":               True,
                "provider":                self.name,
                "date_from":               str(date_from),
                "date_to":                 str(date_to),
                "total_revenue_ngn":       round(total_revenue, 2),
                "total_units_sold":        total_units,
                "total_transactions":      total_transactions,
                "average_sale_value_ngn":  average_sale_value,
                "revenue_by_region":       revenue_by_region,
                "best_performing_region":  best_region,
                "reconciled_revenue_ngn":  round(reconciled_amount, 2),
                "pending_revenue_ngn":     round(pending_amount, 2),
                "top_selling_models":      [
                    {"model": m, "units": u} for m, u in top_selling_models
                ],
            }

        except Exception as exc:
            logger.warning(
                "DirectSalesProvider.get_summary failed org=%s: %s", org_id, exc
            )
            return {
                "available": False,
                "reason": "Could not retrieve sales record data right now.",
            }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Flexible search across direct_sales rows — reconciliation status,
        region, model/variant, or rep name.
        S14: returns [] on any failure.
        """
        try:
            query_lower = query.lower()

            q = (
                db.table("direct_sales")
                .select(
                    "id, sale_date, customer_name, region, model, variant, "
                    "units, amount, reconciliation_status, rep_name, channel"
                )
                .eq("org_id", org_id)
                .order("sale_date", desc=True)
                .limit(limit * 3)
            )

            # Reconciliation status filter
            if any(w in query_lower for w in ["pending", "unreconciled", "outstanding"]):
                q = q.ilike("reconciliation_status", "%pending%")
            elif "reconcil" in query_lower:
                q = q.ilike("reconciliation_status", "%reconciled%")

            result = q.execute()
            rows = result.data or []

            # Free-text match on region/model/variant/rep_name — done in
            # Python (Pattern 33 style) since these are short lists per
            # org and a full-text search isn't worth the round trip.
            def _row_matches(row: dict) -> bool:
                haystack = " ".join(
                    str(row.get(f) or "")
                    for f in ("region", "model", "variant", "rep_name")
                ).lower()
                # If the query only carried a reconciliation-status
                # keyword, don't also require a text match.
                remaining_words = [
                    w for w in query_lower.split()
                    if w not in (
                        "pending", "unreconciled", "outstanding",
                        "reconciled", "reconciliation", "show", "me", "sales",
                    )
                ]
                if not remaining_words:
                    return True
                return any(w in haystack for w in remaining_words)

            matched = [r for r in rows if _row_matches(r)][:limit]

            return [
                {
                    "type":         "direct_sale",
                    "customer":     r.get("customer_name") or "—",
                    "region":       r.get("region") or "—",
                    "model":        r.get("model") or "—",
                    "variant":      r.get("variant") or "—",
                    "units":        r.get("units") or 0,
                    "amount_ngn":   float(r.get("amount") or 0),
                    "status":       r.get("reconciliation_status") or "Pending",
                    "rep":          r.get("rep_name") or "—",
                    "channel":      r.get("channel") or "—",
                    "sale_date":    (r.get("sale_date") or "")[:10],
                }
                for r in matched
            ]

        except Exception as exc:
            logger.warning(
                "DirectSalesProvider.search failed org=%s: %s", org_id, exc
            )
            return []
