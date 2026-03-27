"""
tests/conftest.py
------------------
Shared pytest fixtures and environment bootstrapping for the entire Opsra
test suite.

Sets minimal required environment variables so app/config.py can be imported
without a real Supabase / Redis / Anthropic connection.

Test database: separate Supabase project (SUPABASE_TEST_URL +
SUPABASE_TEST_SERVICE_KEY) — see Build Status env var table.
"""

import os
import types
import sys
import pytest


# ---------------------------------------------------------------------------
# Environment variable defaults — allow tests to run without a real .env
# ---------------------------------------------------------------------------

_TEST_ENV_DEFAULTS = {
    "SUPABASE_URL":          "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY":  "test-service-key",
    "SUPABASE_ANON_KEY":     "test-anon-key",
    "ANTHROPIC_API_KEY":     "test-anthropic-key",
    "META_WHATSAPP_TOKEN":   "test-whatsapp-token",
    "META_WHATSAPP_PHONE_ID":"test-phone-id",
    "META_VERIFY_TOKEN":     "test-verify-token",
    "META_APP_SECRET":       "test-app-secret",
    "REDIS_URL":             "rediss://fake:fake@localhost:6379",
    "RESEND_API_KEY":        "test-resend-key",
    "SECRET_KEY":            "a" * 64,
    "ENVIRONMENT":           "development",
    "FRONTEND_URL":          "http://localhost:5173",
    "ALLOWED_ORIGINS":       "http://localhost:5173",
}

# Set only if not already present (allows real .env.test to override)
for key, value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# Stub redbeat so tests don't require the package
# ---------------------------------------------------------------------------

if "redbeat" not in sys.modules:
    redbeat_stub = types.ModuleType("redbeat")
    redbeat_stub.RedBeatScheduler = object
    sys.modules["redbeat"] = redbeat_stub


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def org_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def user_id() -> str:
    return "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def mock_supabase():
    """
    Basic Supabase mock suitable for unit tests.
    Override specific methods in individual test fixtures as needed.
    """
    from unittest.mock import MagicMock

    client = MagicMock()
    # Default: audit_logs insert succeeds silently
    client.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return client