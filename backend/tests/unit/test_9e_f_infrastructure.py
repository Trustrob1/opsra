"""
tests/unit/test_9e_f_infrastructure.py
---------------------------------------
Unit tests for Phase 9E-F — Infrastructure Hardening.

Coverage:
  1. Production startup guard — SENTRY_DSN missing → AssertionError
  2. Production startup guard — FRONTEND_URL is localhost → AssertionError
  3. Production startup guard — CORS wildcard present → AssertionError
  4. Production startup guard — all valid → no error
  5. Non-production environment — guards not enforced (dev mode passes)
  6. CORS origins — no wildcard in built origins list
  7. _add_ssl_cert_reqs — appends ssl_cert_reqs to rediss:// URL
  8. _add_ssl_cert_reqs — leaves non-rediss:// URL unchanged
  9. _add_ssl_cert_reqs — does not double-append if already present
 10. Redis TLS guard — production + redis:// raises RuntimeError
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_lifespan_startup(env_overrides: dict):
    """
    Run only the startup portion of the lifespan context manager.
    Patches settings values and _origins so the guard sees the right values.
    Returns without error if the guard passes, raises AssertionError if it fails.
    """
    import asyncio
    from app.main import lifespan, app

    async def _run():
        async with lifespan(app):
            pass  # yield point reached — startup complete

    with patch("app.main.settings") as mock_settings, \
         patch("app.main._origins", env_overrides.get("_origins", ["https://app.opsra.io"])):

        mock_settings.ENVIRONMENT    = env_overrides.get("ENVIRONMENT", "production")
        mock_settings.SENTRY_DSN     = env_overrides.get("SENTRY_DSN", "https://abc@sentry.io/1")
        mock_settings.FRONTEND_URL   = env_overrides.get("FRONTEND_URL", "https://app.opsra.io")

        # asyncio.sleep in shutdown hook — patch it to avoid 10s wait in tests
        with patch("app.main.asyncio.sleep", return_value=None):
            asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 1–5: Production startup guard
# ---------------------------------------------------------------------------

class TestProductionStartupGuard:

    def test_missing_sentry_dsn_raises(self):
        """F6: SENTRY_DSN empty in production → AssertionError at startup."""
        with pytest.raises(AssertionError, match="SENTRY_DSN"):
            _run_lifespan_startup({
                "ENVIRONMENT":  "production",
                "SENTRY_DSN":   "",
                "FRONTEND_URL": "https://app.opsra.io",
                "_origins":     ["https://app.opsra.io"],
            })

    def test_localhost_frontend_url_raises(self):
        """F6: FRONTEND_URL = localhost in production → AssertionError at startup."""
        with pytest.raises(AssertionError, match="localhost"):
            _run_lifespan_startup({
                "ENVIRONMENT":  "production",
                "SENTRY_DSN":   "https://abc@sentry.io/1",
                "FRONTEND_URL": "http://localhost:5173",
                "_origins":     ["http://localhost:5173"],
            })

    def test_cors_wildcard_raises(self):
        """F6: wildcard in _origins in production → AssertionError at startup."""
        with pytest.raises(AssertionError, match="wildcard"):
            _run_lifespan_startup({
                "ENVIRONMENT":  "production",
                "SENTRY_DSN":   "https://abc@sentry.io/1",
                "FRONTEND_URL": "https://app.opsra.io",
                "_origins":     ["*"],
            })

    def test_valid_production_config_passes(self):
        """F6: all guards satisfied → startup completes without error."""
        _run_lifespan_startup({
            "ENVIRONMENT":  "production",
            "SENTRY_DSN":   "https://abc@sentry.io/1",
            "FRONTEND_URL": "https://app.opsra.io",
            "_origins":     ["https://app.opsra.io"],
        })

    def test_development_environment_skips_guards(self):
        """Guards only fire in production — development mode must always pass."""
        _run_lifespan_startup({
            "ENVIRONMENT":  "development",
            "SENTRY_DSN":   "",                     # would fail in production
            "FRONTEND_URL": "http://localhost:5173", # would fail in production
            "_origins":     ["http://localhost:5173"],
        })


# ---------------------------------------------------------------------------
# 6: CORS origins — no wildcard
# ---------------------------------------------------------------------------

class TestCorsOrigins:

    def test_origins_list_contains_no_wildcard(self):
        """
        The _origins list built in main.py must never contain '*'.
        Confirmed by importing and inspecting the live value.
        """
        from app.main import _origins
        assert "*" not in _origins, (
            "CORS wildcard found in _origins — this is a security violation"
        )

    def test_origins_list_is_not_empty(self):
        """_origins must contain at least the FRONTEND_URL."""
        from app.main import _origins
        assert len(_origins) >= 1


# ---------------------------------------------------------------------------
# 7–9: _add_ssl_cert_reqs
# ---------------------------------------------------------------------------

class TestAddSslCertReqs:

    def test_appends_to_rediss_url_without_query(self):
        """rediss:// URL with no query string → appends ?ssl_cert_reqs=CERT_NONE."""
        from app.workers.celery_app import _add_ssl_cert_reqs
        url = "rediss://user:pass@host:6380"
        result = _add_ssl_cert_reqs(url)
        assert "ssl_cert_reqs=CERT_NONE" in result
        assert result.startswith("rediss://")

    def test_appends_to_rediss_url_with_existing_query(self):
        """rediss:// URL with existing query → appends &ssl_cert_reqs=CERT_NONE."""
        from app.workers.celery_app import _add_ssl_cert_reqs
        url = "rediss://user:pass@host:6380?db=0"
        result = _add_ssl_cert_reqs(url)
        assert "ssl_cert_reqs=CERT_NONE" in result
        assert "&ssl_cert_reqs" in result

    def test_does_not_modify_non_rediss_url(self):
        """Plain redis:// URL → returned unchanged."""
        from app.workers.celery_app import _add_ssl_cert_reqs
        url = "redis://localhost:6379"
        result = _add_ssl_cert_reqs(url)
        assert result == url

    def test_does_not_double_append(self):
        """If ssl_cert_reqs already in URL → not added again."""
        from app.workers.celery_app import _add_ssl_cert_reqs
        url = "rediss://user:pass@host:6380?ssl_cert_reqs=CERT_NONE"
        result = _add_ssl_cert_reqs(url)
        assert result.count("ssl_cert_reqs") == 1


# ---------------------------------------------------------------------------
# 10: Redis TLS production guard
# ---------------------------------------------------------------------------

class TestRedisTlsGuard:

    def test_plaintext_redis_in_production_raises(self):
        """
        celery_app raises RuntimeError if ENVIRONMENT=production
        and REDIS_URL uses plain redis:// (not rediss://).
        """
        import sys
        import types

        # Stub redbeat so the import doesn't fail if package is absent
        redbeat_stub = types.ModuleType("redbeat")
        redbeat_stub.RedBeatScheduler = object

        # Remove cached celery_app module so reimport triggers the guard
        for key in list(sys.modules.keys()):
            if "celery_app" in key:
                del sys.modules[key]

        with patch.dict(os.environ, {
            "REDIS_URL":   "redis://localhost:6379",
            "ENVIRONMENT": "production",
        }), patch.dict(sys.modules, {"redbeat": redbeat_stub}):
            with pytest.raises(RuntimeError, match="rediss://"):
                import app.workers.celery_app  # noqa: F401

    def test_rediss_url_in_production_does_not_raise(self):
        """
        celery_app must not raise when ENVIRONMENT=production
        and REDIS_URL correctly uses rediss://.
        """
        import sys
        import types

        redbeat_stub = types.ModuleType("redbeat")
        redbeat_stub.RedBeatScheduler = object

        for key in list(sys.modules.keys()):
            if "celery_app" in key:
                del sys.modules[key]

        with patch.dict(os.environ, {
            "REDIS_URL":   "rediss://user:pass@host:6380",
            "ENVIRONMENT": "production",
        }), patch.dict(sys.modules, {"redbeat": redbeat_stub}):
            try:
                import app.workers.celery_app  # noqa: F401
            except RuntimeError as exc:
                pytest.fail(f"Unexpected RuntimeError with valid rediss:// URL: {exc}")
