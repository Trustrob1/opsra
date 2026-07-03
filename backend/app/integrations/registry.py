"""
app/integrations/registry.py
INTEGRATIONS-1 — Provider registry.

Maps provider name strings to their IntegrationProvider instances.
Reads the integrations table to discover which providers are
connected for a given org.

Adding a new provider:
  1. Create app/services/<provider>_service.py implementing IntegrationProvider.
  2. Import it here and add to PROVIDERS.
  3. No other file needs to change.

S14: all functions in this module never raise.
Pattern 29: load_dotenv() called at module level.
"""
from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv

from app.integrations.base import IntegrationProvider

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry — import and register providers here
# ---------------------------------------------------------------------------

def _load_providers() -> dict[str, IntegrationProvider]:
    providers: dict[str, IntegrationProvider] = {}
    try:
        from app.services.payment_service import PaystackProvider
        providers["paystack"] = PaystackProvider()
    except Exception as exc:
        logger.warning("registry: failed to load paystack provider — %s", exc)
    # TESTING ONLY — remove before go-live with real data
    try:
        from app.services.mock_provider_service import (
            MockRevenueProvider, MockLeadsProvider
        )
        providers["mock_revenue"] = MockRevenueProvider()
        providers["mock_leads"]   = MockLeadsProvider()
    except Exception as exc:
        logger.warning("registry: failed to load mock providers — %s", exc)
    try:
        from app.services.shopify_provider_service import ShopifyProvider
        providers["shopify"] = ShopifyProvider()
    except Exception as exc:
        logger.warning("registry: failed to load shopify provider — %s", exc)
    try:
        from app.services.opsra_orders_provider_service import OpsraOrdersProvider
        providers["opsra_orders"] = OpsraOrdersProvider()
    except Exception as exc:
        logger.warning("registry: failed to load opsra_orders provider — %s", exc)
    # Future providers added here:
    # from app.services.zoho_service import ZohoBooksProvider
    # providers["zoho_books"] = ZohoBooksProvider()
    return providers


# Module-level cache — populated on first access
_PROVIDERS: dict[str, IntegrationProvider] | None = None


def _get_providers() -> dict[str, IntegrationProvider]:
    global _PROVIDERS
    if _PROVIDERS is None:
        _PROVIDERS = _load_providers()
    return _PROVIDERS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_provider(name: str) -> IntegrationProvider | None:
    """
    Return the provider instance for the given name, or None if not
    registered. S14: never raises.
    """
    try:
        return _get_providers().get(name)
    except Exception as exc:
        logger.warning("registry.get_provider failed for '%s': %s", name, exc)
        return None


def get_connected_providers(db: Any, org_id: str) -> list[str]:
    """
    Return list of provider name strings that are status='connected'
    in the integrations table for this org, and also registered
    in PROVIDERS (i.e. actually callable).

    S14: returns [] on any DB failure.
    """
    try:
        result = (
            db.table("integrations")
            .select("provider")
            .eq("org_id", org_id)
            .eq("status", "connected")
            .execute()
        )
        rows = result.data or []
        registered = _get_providers()
        return [
            row["provider"]
            for row in rows
            if row.get("provider") in registered
        ]
    except Exception as exc:
        logger.warning(
            "registry.get_connected_providers failed org=%s: %s", org_id, exc
        )
        return []


def get_provider_capabilities(provider_name: str) -> dict:
    """
    Return the capabilities dict for the named provider.
    Used to build the dynamic HELP message.
    S14: returns {} on any failure.
    """
    try:
        provider = get_provider(provider_name)
        if provider is None:
            return {}
        return provider.capabilities()
    except Exception as exc:
        logger.warning(
            "registry.get_provider_capabilities failed for '%s': %s",
            provider_name, exc,
        )
        return {}


def build_help_message(
    db: Any, org_id: str, dashboard_url: str, ask_guide_url: str = ""
) -> str:
    """
    Build the dynamic HELP message based on connected providers for
    this org.

    Kept deliberately short — the full example list moved to a linked
    web page (see public_performance.py's get_ask_guide /
    _render_ask_guide_html) because a WhatsApp message can never fit
    the genuinely unbounded space of things the owner can ask (routing
    is natural-language via Sonnet, not a fixed command list — no
    example list in chat text will ever be complete).

    S14: returns a minimal fallback message on any failure.
    """
    try:
        connected = get_connected_providers(db, org_id)
        lines = ["*What can I help you with?*\n"]

        if connected:
            lines.append(
                "Ask me anything about your leads, pipeline, payments, or "
                "orders — in plain English. I can also generate PDF reports."
            )
        else:
            lines.append(
                "No data sources are connected yet. "
                "Please contact your Opsra administrator."
            )

        if connected and ask_guide_url:
            lines.append(f"\n📘 See everything you can ask → {ask_guide_url}")

        lines.append("\nReply with your question any time, or send HELP to see this again.")
        if dashboard_url:
            lines.append(f"📈 Full dashboard → {dashboard_url}")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("registry.build_help_message failed org=%s: %s", org_id, exc)
        return (
            "Send me a question about your business data.\n"
            "Reply HELP any time to see what I can answer."
        )
