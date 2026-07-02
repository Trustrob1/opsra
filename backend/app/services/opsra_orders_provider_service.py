"""
app/services/opsra_orders_provider_service.py
INTEGRATIONS-1 — Opsra-native orders and leads provider.

Reads from Opsra's own database tables — no external API calls needed.
Works for ALL orgs regardless of whether they use Shopify, Paystack, or any
other integration. This is the baseline provider every org gets.

Data sources:
  leads table          — pipeline data, lead counts, conversion rates, sources
  commerce_sessions    — WhatsApp orders placed through the commerce engine
                         (open, checkout_sent, completed, abandoned)

Separation of concerns:
  This provider answers questions about: leads, pipeline, conversions,
  WhatsApp orders, fulfilment status of WhatsApp-originated orders.

  It does NOT answer questions about: payment amounts (→ paystack),
  Shopify storefront orders (→ shopify), subscriptions (→ paystack).

What the owner can ask:
  get_summary():
    - How many leads came in this week/month?
    - Which lead source is performing best?
    - What is my conversion rate?
    - How many WhatsApp orders are pending/completed?
    - What is my pipeline by stage?

  search():
    - Show me unfulfilled orders
    - Show me hot leads
    - Show me new leads from Instagram
    - Show me abandoned carts
    - Show me recent conversions

S14: all methods return error/empty shape on failure, never raise.
Pattern 29: load_dotenv() at module level.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from dotenv import load_dotenv

from app.integrations.base import IntegrationProvider

load_dotenv()

logger = logging.getLogger(__name__)


class OpsraOrdersProvider(IntegrationProvider):
    """
    Reads leads and WhatsApp commerce session data from Opsra's own tables.
    Available to all orgs. No external credentials needed.
    """

    name = "opsra_orders"

    def capabilities(self) -> dict:
        return {
            "label": "Leads, Pipeline & WhatsApp Orders",
            "emoji": "📊",
            "examples": [
                "How many leads came in this week?",
                "What is my conversion rate this month?",
                "Show me unfulfilled WhatsApp orders",
                "Which lead source is converting best?",
                "How many leads are in each stage?",
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
        Returns combined leads pipeline and WhatsApp commerce summary
        for the given period.
        S14: returns {'available': False, 'reason': ...} on any failure.
        """
        try:
            from_iso = date_from.isoformat()
            to_iso   = date_to.isoformat() + "T23:59:59"

            # ── Leads summary ────────────────────────────────────────────────
            leads_result = (
                db.table("leads")
                .select(
                    "id, source, score, stage, created_at, converted_at, "
                    "deleted_at"
                )
                .eq("org_id", org_id)
                .is_("deleted_at", "null")
                .gte("created_at", from_iso)
                .lte("created_at", to_iso)
                .execute()
            )
            leads = leads_result.data or []

            total_leads = len(leads)
            converted   = sum(1 for l in leads if l.get("stage") == "converted")
            conversion_rate = (
                round(converted / total_leads * 100, 1) if total_leads > 0 else 0.0
            )

            # By source
            by_source: dict[str, int] = {}
            for lead in leads:
                src = lead.get("source") or "unknown"
                by_source[src] = by_source.get(src, 0) + 1

            # By stage
            by_stage: dict[str, int] = {}
            for lead in leads:
                stage = lead.get("stage") or "new"
                by_stage[stage] = by_stage.get(stage, 0) + 1

            # By score
            by_score: dict[str, int] = {}
            for lead in leads:
                score = lead.get("score") or "unscored"
                by_score[score] = by_score.get(score, 0) + 1

            # Best converting source
            source_conversion: dict[str, dict] = {}
            for lead in leads:
                src = lead.get("source") or "unknown"
                if src not in source_conversion:
                    source_conversion[src] = {"total": 0, "converted": 0}
                source_conversion[src]["total"] += 1
                if lead.get("stage") == "converted":
                    source_conversion[src]["converted"] += 1

            best_source = None
            best_rate   = 0.0
            for src, counts in source_conversion.items():
                if counts["total"] > 0:
                    rate = counts["converted"] / counts["total"] * 100
                    if rate > best_rate:
                        best_rate   = rate
                        best_source = src

            # ── WhatsApp commerce sessions (only for orgs using commerce mode) ──
            # Skip for consultative/human mode orgs — sessions will be empty
            # and showing zeros adds noise to the owner's report.
            org_mode_result = (
                db.table("organisations")
                .select("whatsapp_sales_mode")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_mode_data = org_mode_result.data
            if isinstance(org_mode_data, list):
                org_mode_data = org_mode_data[0] if org_mode_data else None
            wa_sales_mode = (org_mode_data or {}).get("whatsapp_sales_mode") or "human"
            include_commerce = wa_sales_mode in ("bot", "ai_agent")

            sessions = []
            if include_commerce:
                sessions_result = (
                    db.table("commerce_sessions")
                    .select(
                        "id, status, subtotal, "
                        "created_at, completed_at, abandoned_at, cart"
                    )
                    .eq("org_id", org_id)
                    .gte("created_at", from_iso)
                    .lte("created_at", to_iso)
                    .execute()
                )
                sessions = sessions_result.data or []
            
            total_wa_orders    = len(sessions)
            completed_orders   = sum(
                1 for s in sessions if s.get("status") == "completed"
            )
            open_orders        = sum(
                1 for s in sessions
                if s.get("status") in ("open", "checkout_sent")
            )
            abandoned_sessions = sum(
                1 for s in sessions if s.get("status") == "abandoned"
            )
            wa_revenue         = sum(
                float(s.get("subtotal") or 0)
                for s in sessions
                if s.get("status") == "completed"
            )

            # Only include commerce data in response if org uses commerce mode
            commerce_data = {}
            if include_commerce:
                commerce_data = {
                    "total_wa_sessions":       total_wa_orders,
                    "completed_wa_orders":     completed_orders,
                    "open_wa_orders":          open_orders,
                    "abandoned_wa_sessions":   abandoned_sessions,
                    "wa_commerce_revenue_ngn": round(wa_revenue, 2),
                }

            return {
                "available":                 True,
                "provider":                  self.name,
                "date_from":                 str(date_from),
                "date_to":                   str(date_to),
                # Leads
                "total_leads":               total_leads,
                "converted_leads":           converted,
                "conversion_rate_pct":       conversion_rate,
                "leads_by_source":           by_source,
                "leads_by_stage":            by_stage,
                "leads_by_score":            by_score,
                "best_converting_source":    best_source,
                "best_source_conversion_pct": round(best_rate, 1),
                **commerce_data,
            }

        except Exception as exc:
            logger.warning(
                "OpsraOrdersProvider.get_summary failed org=%s: %s", org_id, exc
            )
            return {
                "available": False,
                "reason": "Could not retrieve pipeline data right now.",
            }

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Flexible search across leads and commerce sessions.
        Detects intent from query keywords and routes to the right table.
        S14: returns [] on any failure.
        """
        try:
            query_lower = query.lower()

            # ── Detect intent ────────────────────────────────────────────────
            is_order_query = any(w in query_lower for w in [
                "order", "commerce", "cart", "checkout", "purchase", "bought",
                "unfulfill", "fulfill", "pending delivery", "not delivered",
                "abandon",
            ])
            is_lead_query = any(w in query_lower for w in [
                "lead", "prospect", "pipeline", "contact", "inquiry",
                "hot", "warm", "cold", "new lead", "converted",
            ])
            # Default to leads if ambiguous
            if not is_order_query and not is_lead_query:
                is_lead_query = True

            results = []

            # ── Commerce session search ───────────────────────────────────────
            if is_order_query:
                # Determine status filter
                status_filter = None
                if any(w in query_lower for w in [
                    "unfulfill", "pending", "open", "not delivered", "outstanding"
                ]):
                    status_filter = ["open", "checkout_sent"]
                elif any(w in query_lower for w in [
                    "completed", "fulfilled", "delivered", "done"
                ]):
                    status_filter = ["completed"]
                elif any(w in query_lower for w in ["abandon", "dropped"]):
                    status_filter = ["abandoned"]

                q = (
                    db.table("commerce_sessions")
                    .select(
                        "id, status, subtotal, "
                        "phone_number, cart, created_at, completed_at, "
                        "checkout_url"
                    )
                    .eq("org_id", org_id)
                    .order("created_at", desc=True)
                    .limit(limit * 2)
                )
                if status_filter:
                    q = q.in_("status", status_filter)

                sess_result = q.execute()
                sessions    = sess_result.data or []

                for s in sessions[:limit]:
                    cart_items = s.get("cart") or []
                    item_names = ", ".join(
                        (item.get("name") or item.get("title") or "—")
                        for item in (cart_items if isinstance(cart_items, list) else [])[:3]
                    ) or "—"
                    results.append({
                        "type":         "whatsapp_order",
                        "status":       s.get("status") or "—",
                        "phone_number": s.get("phone_number") or "—",
                        "total_ngn":    float(s.get("subtotal") or 0),
                        "items":        item_names,
                        "created_at":   (s.get("created_at") or "")[:10],
                        "checkout_url": s.get("checkout_url") or "—",
                    })

            # ── Lead search ───────────────────────────────────────────────────
            if is_lead_query:
                q = (
                    db.table("leads")
                    .select(
                        "id, full_name, phone, whatsapp, source, score, "
                        "stage, business_name, created_at, last_activity_at"
                    )
                    .eq("org_id", org_id)
                    .is_("deleted_at", "null")
                    .order("created_at", desc=True)
                    .limit(limit * 3)
                )

                # Apply score/stage filters from query
                if any(w in query_lower for w in ["hot lead", "hot"]):
                    q = q.eq("score", "hot")
                elif any(w in query_lower for w in ["warm"]):
                    q = q.eq("score", "warm")
                elif any(w in query_lower for w in ["cold"]):
                    q = q.eq("score", "cold")

                if "converted" in query_lower:
                    q = q.eq("stage", "converted")
                elif "new lead" in query_lower or query_lower == "new":
                    q = q.eq("stage", "new")
                elif "contacted" in query_lower:
                    q = q.eq("stage", "contacted")
                elif "lost" in query_lower:
                    q = q.eq("stage", "lost")

                # Source filter
                for src in [
                    "facebook", "instagram", "whatsapp", "landing_page",
                    "referral", "manual"
                ]:
                    if src in query_lower:
                        q = q.ilike("source", f"%{src}%")
                        break

                leads_result = q.execute()
                leads = leads_result.data or []

                for lead in leads[:limit]:
                    results.append({
                        "type":         "lead",
                        "name":         lead.get("full_name") or "—",
                        "phone":        lead.get("whatsapp") or lead.get("phone") or "—",
                        "source":       lead.get("source") or "—",
                        "score":        lead.get("score") or "unscored",
                        "stage":        lead.get("stage") or "new",
                        "business":     lead.get("business_name") or "—",
                        "created_at":   (lead.get("created_at") or "")[:10],
                        "last_active":  (lead.get("last_activity_at") or "")[:10],
                    })

            return results[:limit]

        except Exception as exc:
            logger.warning(
                "OpsraOrdersProvider.search failed org=%s: %s", org_id, exc
            )
            return []
