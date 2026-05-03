"""
Opsra Load Test — test_data.py
Seed credentials and payload factories for locustfile.py.

All credentials must exist in the staging Supabase before running.
Run the seed SQL in README.md to create them.
"""

import random
import string
import uuid
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Backend credentials — override via environment variables or edit here
# ---------------------------------------------------------------------------
# One account per role that exists in the org.
# Set OPSRA_BACKEND_URL in CMD before running:
#   set OPSRA_BACKEND_URL=https://opsra.onrender.com
STAFF_ACCOUNTS = [
    {"email": "load_owner@opsra.dev",        "password": "LoadTest#2026!", "label": "owner"},
    {"email": "load_opsmanager@opsra.dev",   "password": "LoadTest#2026!", "label": "ops_manager"},
    {"email": "load_salesrep1@opsra.dev",    "password": "LoadTest#2026!", "label": "sales_rep"},
    {"email": "load_salesrep2@opsra.dev",    "password": "LoadTest#2026!", "label": "sales_rep"},
    {"email": "load_salesrep3@opsra.dev",    "password": "LoadTest#2026!", "label": "sales_rep"},
    {"email": "load_support1@opsra.dev",     "password": "LoadTest#2026!", "label": "support_agent"},
    {"email": "load_support2@opsra.dev",     "password": "LoadTest#2026!", "label": "support_agent"},
    {"email": "load_support3@opsra.dev",     "password": "LoadTest#2026!", "label": "support_agent"},
    {"email": "load_renewalmgr@opsra.dev",   "password": "LoadTest#2026!", "label": "renewal_manager"},
    {"email": "load_readonly@opsra.dev",     "password": "LoadTest#2026!", "label": "viewer"},
]

# Accounts with owner/ops_manager role only — used by DashboardUser
# so growth analytics routes (restricted to these roles) don't 403
MANAGER_ACCOUNTS = [
    {"email": "load_owner@opsra.dev",      "password": "LoadTest#2026!", "label": "owner"},
    {"email": "load_opsmanager@opsra.dev", "password": "LoadTest#2026!", "label": "ops_manager"},
]

# Org slug — used by the public lead-form endpoint
# Replace with your actual org slug from the organisations table
STAGING_ORG_SLUG = "ovaloop"

# ---------------------------------------------------------------------------
# Performance thresholds (DRD §13.1)
# ---------------------------------------------------------------------------
THRESHOLD_STANDARD_MS  = 2_000   # all standard API responses
THRESHOLD_AI_MS        = 5_000   # Claude-powered generation endpoints
THRESHOLD_SEARCH_MS    = 1_000   # global search
THRESHOLD_DASHBOARD_MS = 2_000   # executive dashboard (same as standard)

# ---------------------------------------------------------------------------
# Payload factories
# ---------------------------------------------------------------------------

def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))

def _rand_phone() -> str:
    return f"+234{random.randint(700_000_0000, 819_999_9999)}"

def _rand_future(days_min: int = 1, days_max: int = 14) -> str:
    delta = timedelta(days=random.randint(days_min, days_max))
    return (datetime.utcnow() + delta).isoformat() + "Z"


def lead_create_payload() -> dict:
    """Valid payload for POST /api/v1/leads"""
    business_types = ["supermarket", "pharmacy", "fashion", "electronics", "restaurant"]
    return {
        "full_name":      f"Load {_rand_str()} Test",
        "whatsapp":       _rand_phone(),
        "email":          f"lead_{_rand_str()}@example.com",
        "business_name":  f"{_rand_str().title()} Stores",
        "business_type":  random.choice(business_types),
        "location":       random.choice(["Lagos", "Abuja", "Kano", "Port Harcourt"]),
        "problem_stated": f"We need better inventory tracking — load test lead {_rand_str()}",
        "source":         random.choice(["facebook_ad", "instagram_ad", "landing_page"]),
    }


def ticket_create_payload() -> dict:
    """Valid payload for POST /api/v1/tickets"""
    categories = ["technical_bug", "billing", "feature_question", "onboarding_help"]
    urgencies  = ["low", "medium", "high", "critical"]
    return {
        "title":    f"Load test issue {_rand_str()}",
        "content":  f"Synthetic ticket from load test suite. Ref: {uuid.uuid4()}",
        "category": random.choice(categories),
        "urgency":  random.choice(urgencies),
    }


def task_create_payload() -> dict:
    """Valid payload for POST /api/v1/tasks"""
    return {
        "title":      f"Load test task {_rand_str()}",
        "task_type":  "manual",
        "due_at":     _rand_future(),
        "priority":   random.choice(["low", "medium", "high"]),
    }


def ask_payload() -> dict:
    """Valid payload for POST /api/v1/ask"""
    questions = [
        "How many hot leads do we have this week?",
        "What is our current ticket resolution rate?",
        "Which customers are at highest churn risk?",
        "How many leads converted last month?",
        "What is the average response time for support tickets?",
    ]
    return {"question": random.choice(questions)}


def lead_form_public_payload() -> dict:
    """Valid payload for the public lead capture form endpoint"""
    return {
        "full_name":      f"FormTest {_rand_str()}",
        "whatsapp":       _rand_phone(),
        "email":          f"form_{_rand_str()}@example.com",
        "business_name":  f"{_rand_str().title()} Ltd",
        "business_type":  "pharmacy",
        "problem_stated": f"Public form load test {_rand_str()}",
        "source":         "landing_page",
    }


# ---------------------------------------------------------------------------
# Endpoint catalogue — used in README and as single source of truth
# ---------------------------------------------------------------------------
STANDARD_GET_ENDPOINTS = [
    # Auth
    "/api/v1/auth/me",
    # Module 01 — Leads
    "/api/v1/leads",
    "/api/v1/leads?stage=new",
    "/api/v1/leads?stage=contacted",
    # Module 02 — WhatsApp / Customers
    "/api/v1/customers",
    "/api/v1/broadcasts",
    "/api/v1/templates",
    # Module 03 — Support
    "/api/v1/tickets",
    "/api/v1/tickets?status=open",
    "/api/v1/tickets?sla_breached=true",
    # Module 04 — Renewal
    "/api/v1/subscriptions",
    "/api/v1/renewals",
    "/api/v1/churn-scores",
    # Module 05 — Ops
    "/api/v1/dashboard/metrics",
    "/api/v1/dashboard/health",
    "/api/v1/anomalies",
    # Tasks
    "/api/v1/tasks",
    "/api/v1/tasks?status=pending",
    # Reports
    "/api/v1/reports/sales",
    "/api/v1/reports/support",
]

AI_ENDPOINTS = [
    # These call Claude — measured against THRESHOLD_AI_MS
    "/api/v1/ask",          # POST only — payload in ask_payload()
    # Score + pre-call brief are triggered from a lead id resolved at runtime
]

SEARCH_ENDPOINTS = [
    # Measured against THRESHOLD_SEARCH_MS
    "/api/v1/leads?search=test",
    "/api/v1/tickets?search=load",
    "/api/v1/customers?search=store",
]
