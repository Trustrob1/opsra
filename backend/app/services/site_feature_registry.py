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

TIER_KEYS = ("capture", "convert", "grow", "scale", "automate")
# PLANS-1 (Nov 2026): the account plans are Chat Basic = automate, Growth = convert, Essential = grow, Scale = scale.
# Capture stays the website entry plan. Labels for convert/grow are renamed in Settings > Pricing at go-live.
# WA-AUTO-1b: "automate" is the WhatsApp-automation-only plan. Only businesses whose product_mode is wa_automation can buy it, and
# they can buy nothing else. Websites never offer it. Its price is set in Superadmin pricing settings (not for sale until then).
WA_ONLY_TIERS = ("automate",)
ADDON_KEYS = ("support_tickets", "renewals_winback", "dashboard_ask_data", "event_funnel", "extra_rep", "extra_wa_number", "booking")

# Caps. "monthly" caps are consumed (site_usage_counters); "static" caps are a limit the feature reads (e.g. reps).
CAPS = {
    "ai_messages": "monthly",
    "bulk_recipients": "monthly",
    "reps": "static",
    "bookings": "monthly",         # BOOKING-ALLOWANCE-1: counted per booking, over-allowance bookings cost credit (never blocked)
    "users_included": "static",   # users a plan includes (default 2; PLANS-1: 2 Chat Basic, 3 Growth, 5 Essential, 10 Scale)
}

# key -> (label, group, cap_key or None, built)
_F = {
    # Capture
    "form_instant_reply": ("Enquiry form with instant reply", "capture", None, True),
    "wa_leads": ("WhatsApp messages saved as leads", "capture", None, True),
    "source_tracking": ("Source tracking (page, product, button)", "capture", None, True),
    "speed_alerts": ("Speed-to-lead alerts", "capture", None, True),
    "wa_menu": ("WhatsApp menu with set answers", "capture", None, True),
    "my_leads_page": ("My leads page", "capture", None, True),
    "leads_download": ("View and download leads", "capture", None, True),
    # Web chat (ACCOUNT-PLANS: an account feature, no site needed)
    "webchat_basic": ("Web chat page, menu answers and booking", "capture", None, True),
    "webchat_insights": ("Web chat insights, tagged links and QR codes", "capture", None, True),
    # Convert
    "ai_assistant": ("AI assistant from the business's own information", "convert", "ai_messages", True),
    "qualification": ("Qualification questions, scoring and hot-lead alerts", "convert", None, True),
    "followups": ("Follow-up and re-contact sequences", "convert", None, True),
    "payment_links": ("Paystack payment links in chat", "convert", None, True),
    "fb_ig_leads": ("Facebook and Instagram lead ads tagged by ad", "convert", None, True),
    "own_wa_number": ("Own WhatsApp number", "convert", None, True),
    # PLANS-1: plan-page features. built=False until the phase that gates them flips it (listing a key does nothing yet).
    "crm": ("CRM for every lead and customer", "convert", None, False),   # no route is gated by it yet (CRM routers use product_mode)
    "performance_hub": ("Performance Hub", "convert", None, True),
    "reports": ("Reports", "convert", None, True),
    "knowledge_base": ("Bot knowledge: uploaded files and typed answers", "convert", None, True),   # WA-AUTO-4a
    "webchat_followups": ("Web chat email and WhatsApp follow-ups", "convert", None, True),
    "selling_catalog": ("Catalog with recommendations", "convert", None, True),
    "selling_booking": ("Booking with reminders", "convert", None, True),
    "catalog_storefront": ("Storefront catalog template", "convert", None, True),   # STORE-1: not in any default tier; ticked in Billing
    # Grow
    "bulk_messaging": ("Bulk customer messaging", "grow", "bulk_recipients", True),
    "welcome_series": ("Welcome series", "grow", None, True),
    "birthday_messages": ("Birthday messages", "grow", None, False),
    "surveys": ("Satisfaction surveys", "grow", None, True),
    "review_reminders": ("Review reminders", "grow", None, False),
    "repeat_reminders": ("Repeat-purchase reminders", "grow", None, False),
    "weekly_report": ("Weekly owner report", "grow", None, True),
    "monday_summary": ("Monday WhatsApp summary", "grow", None, True),
    "multi_rep_inbox": ("Several reps on one shared inbox", "grow", "reps", True),
    "team_tasks": ("Team tasks", "grow", None, True),
    "call_logging": ("Call logging", "grow", None, False),
    "ai_lead_management": ("AI lead management", "grow", None, False),
    "business_activities": ("Business Activities", "grow", None, True),
    # Optional add-ons (each add-on is itself a feature key)
    "support_tickets": ("Support tickets", "addon", None, True),
    "renewals_winback": ("Renewals and win-back", "addon", None, True),
    "dashboard_ask_data": ("Dashboard and ask-your-data", "addon", None, False),
    "event_funnel": ("Paid event or class funnel", "addon", None, True),
    "extra_rep": ("Extra rep", "addon", None, True),
    "extra_wa_number": ("Extra WhatsApp number", "addon", None, True),
    "booking": ("Booking with reminders", "addon", None, True),   # BOOKING-ADDON-1: switches on selling_booking
}

# ACCOUNT-PLANS: where a feature is checked. "site" needs a website (form, tracked links, per-site leads page);
# "account" belongs to the organisation as a whole (web chat); "both" works for either (the default).
_SITE_ONLY = ("form_instant_reply", "source_tracking", "my_leads_page")
_ACCOUNT_ONLY = ("webchat_basic", "webchat_insights", "webchat_followups", "catalog_storefront")


def _scope(key: str) -> str:
    return "site" if key in _SITE_ONLY else "account" if key in _ACCOUNT_ONLY else "both"


FEATURES = {k: {"label": v[0], "group": v[1], "cap": v[2], "built": v[3], "scope": _scope(k)} for k, v in _F.items()}

_CAPTURE = [k for k, v in FEATURES.items() if v["group"] == "capture"]
_CONVERT = [k for k, v in FEATURES.items() if v["group"] == "convert" and k not in ("selling_catalog", "selling_booking", "catalog_storefront")]
_GROW = [k for k, v in FEATURES.items() if v["group"] == "grow"]

# Approved 10 Oct 2026. Convert gets ONE selling tool (catalog OR booking) chosen per site, so the two keys are a
# pick_one group instead of being in the list; Grow gets both.
DEFAULT_TIER_FEATURES = {
    "capture": list(_CAPTURE),
    "convert": _CAPTURE + _CONVERT,
    "grow": _CAPTURE + _CONVERT + ["selling_catalog", "selling_booking"] + _GROW,
    # Scale = everything in Grow plus support tickets and extra WhatsApp numbers (included instead of the add-ons).
    "scale": _CAPTURE + _CONVERT + ["selling_catalog", "selling_booking"] + _GROW + ["support_tickets", "extra_wa_number"],
    "automate": ["wa_leads", "wa_menu", "speed_alerts", "ai_assistant", "own_wa_number", "webchat_basic", "knowledge_base",
                 "leads_download", "multi_rep_inbox"],
}
DEFAULT_PICK_ONE = {
    "capture": [],
    "convert": [["selling_catalog", "selling_booking"]],
    "grow": [],
    "scale": [],
    "automate": [],
}
DEFAULT_LABELS = {"capture": "Capture", "convert": "Convert", "grow": "Grow", "scale": "Scale", "automate": "Chat Basic"}
# Starting allowances, used until Superadmin saves its own. Prices are never defaulted.
DEFAULT_TIER_CAPS = {
    "automate": {"ai_messages": 100, "users_included": 2, "reps": 2},
    "convert": {"ai_messages": 1000, "users_included": 3},
    "grow": {"ai_messages": 3000, "bulk_recipients": 500, "bookings": 500, "users_included": 5, "reps": 5},
    "scale": {"ai_messages": 8000, "bulk_recipients": 2000, "bookings": 2000, "users_included": 10, "reps": 10},
}
# Shown in Superadmin pricing settings as a hint only (Trust, 24 Oct 2026: recommended start, price is fixed by Trust).
# PLANS-3: naira of credit a plan includes every month (expires at month end, no rollover). Settings can override per tier
# with included_credit_ngn. Chat Basic and Capture include none.
DEFAULT_INCLUDED_CREDIT_NGN = {"convert": 2000, "grow": 7500, "scale": 15000}
RECOMMENDED_START = {
    "automate": {"monthly_ngn": 40000, "ai_messages": 100, "users_included": 2},
    "scale": {"monthly_ngn": 300000, "ai_messages": 8000, "users_included": 10},
}
DEFAULT_ADDON_LABELS = {k: FEATURES[k]["label"] for k in ADDON_KEYS}
# An add-on adds its own key, plus a cap for the ones that raise a limit.
DEFAULT_ADDON_CAPS = {"extra_rep": {"reps": 1}}
# What an add-on switches on when Settings has not saved its own list (default is the add-on key itself).
DEFAULT_ADDON_FEATURES = {"booking": ["selling_booking"]}


def is_feature(key) -> bool:
    return isinstance(key, str) and key in FEATURES


def scope_of(key: str) -> str:
    """'site', 'account' or 'both' (unknown keys are 'both' but is_feature() is False for them)."""
    return (FEATURES.get(key) or {}).get("scope", "both")


def cap_for_feature(key: str):
    """The cap a feature draws from (ai_messages, bulk_recipients, reps) or None."""
    return (FEATURES.get(key) or {}).get("cap")
