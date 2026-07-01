"""
app/integrations/base.py
INTEGRATIONS-1 — Generic provider interface.

Every integration provider must expose get_summary() and search().
Write actions are structurally prohibited in v1 — the base class
intentionally provides no write/mutating method. This is enforced
by design, not just by prompting.

All methods must be S14-safe: return empty/error dict on failure,
never raise.
"""
from __future__ import annotations

from datetime import date
from typing import Any


class IntegrationProvider:
    """
    Base contract for all Opsra integration providers.

    Subclasses must implement get_summary() and search().
    name must be set to a unique lowercase string matching the
    provider column value in the integrations table.

    Write actions are deliberately absent from this interface.
    No provider in v1 may implement any mutating call.
    """

    name: str = ""

    def get_summary(
        self,
        db: Any,
        org_id: str,
        date_from: date,
        date_to: date,
    ) -> dict:
        """
        Return high-level numbers for the given period.

        Must return {'available': False, 'reason': '<msg>'} on any
        failure — never raises.

        Expected successful shape (provider-specific values):
        {
            'available': True,
            'provider': self.name,
            'date_from': str(date_from),
            'date_to': str(date_to),
            ...provider-specific numeric fields...
        }
        """
        raise NotImplementedError(
            f"Provider '{self.name}' must implement get_summary()"
        )

    def search(
        self,
        db: Any,
        org_id: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Return a list of matching records for the given query string.

        Provider interprets the query in whatever way is most useful
        for its data domain.

        Must return [] on any failure — never raises.
        """
        raise NotImplementedError(
            f"Provider '{self.name}' must implement search()"
        )

    def capabilities(self) -> dict:
        """
        Return a human-readable description of what this provider
        can answer. Used to build the dynamic HELP message.

        Shape: {
            'label': str,          # e.g. "Revenue & Payments"
            'emoji': str,          # e.g. "💰"
            'examples': list[str]  # 2-3 example questions
        }
        """
        raise NotImplementedError(
            f"Provider '{self.name}' must implement capabilities()"
        )
