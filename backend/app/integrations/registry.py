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


def build_help_message(db: Any, org_id: str, dashboard_url: str) -> str:
    """
    Build the dynamic HELP message based on connected providers for
    this org. Lists only what is actually callable right now.
    S14: returns a minimal fallback message on any failure.
    """
    try:
        connected = get_connected_providers(db, org_id)
        lines = ["*What can I help you with?*\n"]

        if connected:
            lines.append("Here's what I can answer right now:\n")
            for name in connected:
                caps = get_provider_capabilities(name)
                if not caps:
                    continue
                emoji = caps.get("emoji", "📊")
                label = caps.get("label", name.replace("_", " ").title())
                examples = caps.get("examples", [])
                lines.append(f"{emoji} *{label}*")
                for ex in examples[:3]:
                    lines.append(f"- {ex}")
                lines.append("")
        else:
            lines.append(
                "No data sources are connected yet. "
                "Please contact your Opsra administrator."
            )

        lines.append("Reply with your question any time, or send HELP to see this again.")
        if dashboard_url:
            lines.append(f"📈 Full dashboard → {dashboard_url}")

        return "\n".join(lines)
    except Exception as exc:
        logger.warning("registry.build_help_message failed org=%s: %s", org_id, exc)
        return (
            "Send me a question about your business data.\n"
            "Reply HELP any time to see what I can answer."
        )
