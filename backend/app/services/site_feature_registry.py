"""
app/services/site_feature_registry.py
---------------------------------------
SITE-ADDONS A0-1 - the list of feature keys a site tier or add-on can switch on.

Code owns the KEYS (so a typo in Settings can never invent a feature). Settings owns WHICH tier gets which keys,
the prices, the setup fees and the caps (site_builder_settings.pricing["tiers"] / ["addons"]). The defaults below are
the contents Trust approved on 10 Oct 2026 (Decisions_Summary.md), so the only thing Trust must type into Settings
is the prices.

`built` is False until the phase that implements a feature flips it. A key marked not built can still be listed in a
tier and granted; nothing calls has_feature() for it yet, so it does nothing. It lets the UI show "coming soon".
"""
from __future__ import annotations

TIER_KEYS = ("capture", "convert", "grow")
ADDON_KEYS = ("support_tickets", "renewals_winback", "dashboard_ask_data", "event_funnel", "extra_rep", "extra_wa_number")

# Caps. "monthly" caps are consumed (site_usage_counters); "static" caps are a limit the feature reads (e.g. reps).
CAPS = {
    "ai_messages": "monthly",
    "bulk_recipients": "monthly",
    "reps": "static",
}

# key -> (label, group, cap_key or None, built)
_F = {
    # Capture
    "form_instant_reply": ("Enquiry form with instant reply", "capture", None, True),
    "wa_leads": ("WhatsApp messages saved as leads", "capture", None, False),
    "source_tracking": ("Source tracking (page, product, button)", "capture", None, True),
    "speed_alerts": ("Speed-to-lead alerts", "capture", None, True),
    "wa_menu": ("WhatsApp menu with set answers", "capture", None, False),
    "my_leads_page": ("My leads page", "capture", None, False),
    # Convert
    "ai_assistant": ("AI assistant from the business's own information", "convert", "ai_messages", False),
    "qualification": ("Qualification questions, scoring and hot-lead alerts", "convert", None, False),
    "followups": ("Follow-up and re-contact sequences", "convert", None, False),
    "payment_links": ("Paystack payment links in chat", "convert", None, False),
    "fb_ig_leads": ("Facebook and Instagram lead ads tagged by ad", "convert", None, False),
    "own_wa_number": ("Own WhatsApp number", "convert", None, False),
    "selling_catalog": ("Catalog with recommendations", "convert", None, False),
    "selling_booking": ("Booking with reminders", "convert", None, False),
    # Grow
    "bulk_messaging": ("Bulk customer messaging", "grow", "bulk_recipients", False),
    "welcome_series": ("Welcome series", "grow", None, False),
    "birthday_messages": ("Birthday messages", "grow", None, False),
    "surveys": ("Satisfaction surveys", "grow", None, False),
    "review_reminders": ("Review reminders", "grow", None, False),
    "repeat_reminders": ("Repeat-purchase reminders", "grow", None, False),
    "weekly_report": ("Weekly owner report", "grow", None, False),
    "monday_summary": ("Monday WhatsApp summary", "grow", None, False),
    "multi_rep_inbox": ("Several reps on one shared inbox", "grow", "reps", False),
    "team_tasks": ("Team tasks", "grow", None, False),
    "call_logging": ("Call logging", "grow", None, False),
    # Optional add-ons (each add-on is itself a feature key)
    "support_tickets": ("Support tickets", "addon", None, False),
    "renewals_winback": ("Renewals and win-back", "addon", None, False),
    "dashboard_ask_data": ("Dashboard and ask-your-data", "addon", None, False),
    "event_funnel": ("Paid event or class funnel", "addon", None, False),
    "extra_rep": ("Extra rep", "addon", None, False),
    "extra_wa_number": ("Extra WhatsApp number", "addon", None, False),
}

FEATURES = {k: {"label": v[0], "group": v[1], "cap": v[2], "built": v[3]} for k, v in _F.items()}

_CAPTURE = [k for k, v in FEATURES.items() if v["group"] == "capture"]
_CONVERT = [k for k, v in FEATURES.items() if v["group"] == "convert" and k not in ("selling_catalog", "selling_booking")]
_GROW = [k for k, v in FEATURES.items() if v["group"] == "grow"]

# Approved 10 Oct 2026. Convert gets ONE selling tool (catalog OR booking) chosen per site, so the two keys are a
# pick_one group instead of being in the list; Grow gets both.
DEFAULT_TIER_FEATURES = {
    "capture": list(_CAPTURE),
    "convert": _CAPTURE + _CONVERT,
    "grow": _CAPTURE + _CONVERT + ["selling_catalog", "selling_booking"] + _GROW,
}
DEFAULT_PICK_ONE = {
    "capture": [],
    "convert": [["selling_catalog", "selling_booking"]],
    "grow": [],
}
DEFAULT_LABELS = {"capture": "Capture", "convert": "Convert", "grow": "Grow"}
DEFAULT_ADDON_LABELS = {k: FEATURES[k]["label"] for k in ADDON_KEYS}
# An add-on adds its own key, plus a cap for the ones that raise a limit.
DEFAULT_ADDON_CAPS = {"extra_rep": {"reps": 1}}


def is_feature(key) -> bool:
    return isinstance(key, str) and key in FEATURES


def cap_for_feature(key: str):
    """The cap a feature draws from (ai_messages, bulk_recipients, reps) or None."""
    return (FEATURES.get(key) or {}).get("cap")
