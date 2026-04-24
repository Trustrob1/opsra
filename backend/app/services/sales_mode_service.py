"""
app/services/sales_mode_service.py
------------------------------------
SM-1: Sales Mode Engine

Provides:
  get_entry_experience(org, contact_type) -> str
    Returns the correct entry path label for a given org + contact_type.
    contact_type: "new" | "returning_lead" | "returning_commerce" | "known_customer"

  get_sales_path(org, entry_point, user_action) -> str
    Returns "transactional" | "consultative" based on sales_mode + user_action.

  build_hybrid_entry_message(phone_number) -> dict
    Returns a WhatsApp interactive buttons payload for the hybrid gate.
    Buttons: "🛒 Buy Now" (id: buy_now) | "💬 Speak to Sales" (id: talk_sales)

  build_returning_contact_menu(org, phone_number) -> dict | None
    Returns a WhatsApp interactive list payload from the org's
    whatsapp_triage_config.returning_contact_menu config, or None if not configured.

  build_known_customer_menu(org, phone_number) -> dict | None
    Returns a WhatsApp interactive list payload from the org's
    whatsapp_triage_config.known_customer_menu config, or None if not configured.

All public functions: S14 — no function may raise. Each is wrapped in try/except.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entry experience resolver
# ---------------------------------------------------------------------------

def get_entry_experience(org: dict, contact_type: str) -> str:
    """
    Return the entry experience label for this org + contact_type combination.

    contact_type values:
      "new"                — never contacted before
      "returning_lead"     — already in the leads pipeline
      "returning_commerce" — had a commerce_session but never spoke to sales
      "known_customer"     — has a completed purchase / customer record

    Return values:
      "qualification"          — fire existing _action_qualify() path
      "commerce"               — create commerce_session (SHOP-1 stub)
      "hybrid_gate"            — send Buy Now / Speak to Sales buttons
      "returning_contact_menu" — send returning_contact_menu list
      "known_customer_menu"    — send known_customer_menu list

    S14: returns "qualification" as safe fallback on any failure.
    """
    try:
        sales_mode = (org.get("sales_mode") or "consultative").lower()

        if sales_mode == "consultative":
            # All contact types: existing qualification path
            return "qualification"

        if sales_mode == "transactional":
            if contact_type == "known_customer":
                return "known_customer_menu"
            # new + returning_commerce + returning_lead → commerce
            return "commerce"

        if sales_mode == "hybrid":
            if contact_type == "known_customer":
                return "known_customer_menu"
            if contact_type == "returning_lead":
                return "returning_contact_menu"
            # new + returning_commerce → hybrid gate
            return "hybrid_gate"

        # Unknown mode — safe fallback
        logger.warning(
            "get_entry_experience: unrecognised sales_mode '%s' for org %s — "
            "defaulting to qualification",
            sales_mode, org.get("id"),
        )
        return "qualification"

    except Exception as exc:
        logger.warning("get_entry_experience failed: %s", exc)
        return "qualification"


# ---------------------------------------------------------------------------
# Sales path resolver (post-hybrid-gate user action)
# ---------------------------------------------------------------------------

def get_sales_path(org: dict, entry_point: str, user_action: str) -> str:
    """
    Resolve the downstream sales path after a user has acted.

    entry_point: "hybrid_gate" | "returning_contact_menu" | etc.
    user_action: "buy_now" | "talk_sales" | any returning_contact_menu action

    Returns:
      "transactional" — proceed to commerce_session
      "consultative"  — proceed to qualification flow

    S14: returns "consultative" as safe fallback on any failure.
    """
    try:
        if user_action == "buy_now":
            return "transactional"
        if user_action == "talk_sales":
            return "consultative"
        # Any other action — safe fallback
        return "consultative"
    except Exception as exc:
        logger.warning("get_sales_path failed: %s", exc)
        return "consultative"


# ---------------------------------------------------------------------------
# WhatsApp message payload builders
# ---------------------------------------------------------------------------

def build_hybrid_entry_message(phone_number: str) -> dict:
    """
    Build the WhatsApp interactive buttons payload for the hybrid gate.
    Two buttons: Buy Now (buy_now) and Speak to Sales (talk_sales).
    S14: returns empty dict on failure.
    """
    try:
        return {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "Hi! How can we help you today?",
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "buy_now",
                                "title": "🛒 Buy Now",
                            },
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "talk_sales",
                                "title": "💬 Speak to Sales",
                            },
                        },
                    ]
                },
            },
        }
    except Exception as exc:
        logger.warning("build_hybrid_entry_message failed phone=%s: %s", phone_number, exc)
        return {}


def build_returning_contact_menu(org: dict, phone_number: str) -> Optional[dict]:
    """
    Build the WhatsApp interactive list payload for the returning_contact_menu.
    Returns None if the menu is not configured (no items).
    S14: returns None on any failure.
    """
    try:
        triage_config = (org.get("whatsapp_triage_config") or {})
        menu_config = triage_config.get("returning_contact_menu") or {}
        items = menu_config.get("items") or []
        if not items:
            return None

        rows = [
            {
                "id": item.get("id", f"rc_{i}"),
                "title": (item.get("label") or "")[:24],
                "description": (item.get("description") or "")[:72],
            }
            for i, item in enumerate(items)
        ]

        return {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": menu_config.get("greeting") or "How can we help you today?",
                },
                "action": {
                    "button": "See options",
                    "sections": [
                        {
                            "title": menu_config.get("section_title") or "Choose an option",
                            "rows": rows,
                        }
                    ],
                },
            },
        }
    except Exception as exc:
        logger.warning(
            "build_returning_contact_menu failed org=%s phone=%s: %s",
            org.get("id"), phone_number, exc,
        )
        return None


def build_known_customer_menu(org: dict, phone_number: str) -> Optional[dict]:
    """
    Build the WhatsApp interactive list payload for the known_customer_menu.
    Returns None if the menu is not configured (no items).
    S14: returns None on any failure.
    """
    try:
        triage_config = (org.get("whatsapp_triage_config") or {})
        menu_config = triage_config.get("known_customer_menu") or {}
        items = menu_config.get("items") or []
        if not items:
            return None

        rows = [
            {
                "id": item.get("id", f"kc_{i}"),
                "title": (item.get("label") or "")[:24],
                "description": (item.get("description") or "")[:72],
            }
            for i, item in enumerate(items)
        ]

        return {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": menu_config.get("greeting") or "Hi! How can we help you today?",
                },
                "action": {
                    "button": "See options",
                    "sections": [
                        {
                            "title": menu_config.get("section_title") or "Choose an option",
                            "rows": rows,
                        }
                    ],
                },
            },
        }
    except Exception as exc:
        logger.warning(
            "build_known_customer_menu failed org=%s phone=%s: %s",
            org.get("id"), phone_number, exc,
        )
        return None
