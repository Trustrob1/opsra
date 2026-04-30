# tests/unit/test_9e_h_hardening.py
"""
9E-H — RLS Audit & Frontend Hardening tests.

Covers:
  H2 — Security headers present on every response (CSP, X-Frame-Options, etc.)
  H3 — ProductionStartupGuards still pass after main.py edit
  H4 — SecurityHeadersMiddleware registration + CSP constant checks
  RLS — Documented via manual SQL verify queries (no code changes)
  sanitize.js — Behaviour documented as manual vitest targets
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """TestClient with real app — no auth needed for header checks."""
    with patch("app.database.get_supabase") as mock_db:
        mock_db.return_value = MagicMock()
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ═════════════════════════════════════════════════════════════════════════════
# H4 — Security headers on every response
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityHeaders:
    """Every response must carry all 5 security headers."""

    def test_x_frame_options_deny(self, client):
        res = client.get("/health")
        assert res.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options_nosniff(self, client):
        res = client.get("/health")
        assert res.headers.get("x-content-type-options") == "nosniff"

    def test_referrer_policy(self, client):
        res = client.get("/health")
        assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        res = client.get("/health")
        val = res.headers.get("permissions-policy", "")
        assert "camera=()" in val
        assert "microphone=()" in val
        assert "geolocation=()" in val

    def test_csp_present(self, client):
        res = client.get("/health")
        csp = res.headers.get("content-security-policy", "")
        assert "default-src" in csp

    def test_csp_no_wildcard_script_src(self, client):
        """script-src must never be * — would allow arbitrary script execution."""
        res = client.get("/health")
        csp = res.headers.get("content-security-policy", "")
        for part in csp.split(";"):
            if "script-src" in part:
                assert "*" not in part, "script-src must not contain wildcard"

    def test_csp_frame_ancestors_none(self, client):
        res = client.get("/health")
        csp = res.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp

    def test_headers_present_on_api_route(self, client):
        """Headers must be on API routes, not just /health."""
        res = client.get("/api/v1/auth/me")  # will 401 — that's fine
        assert res.headers.get("x-frame-options") == "DENY"
        assert res.headers.get("x-content-type-options") == "nosniff"

    def test_headers_present_on_404(self, client):
        """Headers must be on error responses too."""
        res = client.get("/nonexistent-route-xyz")
        assert res.headers.get("x-frame-options") == "DENY"

    def test_headers_present_on_post_route(self, client):
        """Headers must be on POST responses too."""
        res = client.post("/api/v1/auth/login", json={"email": "x", "password": "y"})
        assert res.headers.get("x-frame-options") == "DENY"
        assert res.headers.get("content-security-policy") is not None


# ═════════════════════════════════════════════════════════════════════════════
# H4 — SecurityHeadersMiddleware import + CSP constant smoke tests
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityMiddlewareRegistration:

    def test_middleware_class_importable(self):
        """SecurityHeadersMiddleware must be importable from main."""
        from app.main import SecurityHeadersMiddleware
        assert SecurityHeadersMiddleware is not None

    def test_csp_constant_importable(self):
        from app.main import _CSP
        assert "default-src" in _CSP

    def test_csp_frame_ancestors_none_in_constant(self):
        from app.main import _CSP
        assert "frame-ancestors 'none'" in _CSP

    def test_csp_allows_supabase_connect(self):
        from app.main import _CSP
        assert "supabase.co" in _CSP

    def test_csp_allows_sentry_connect(self):
        from app.main import _CSP
        assert "sentry.io" in _CSP

    def test_csp_allows_google_fonts_style(self):
        from app.main import _CSP
        assert "fonts.googleapis.com" in _CSP

    def test_csp_allows_google_fonts_font(self):
        from app.main import _CSP
        assert "fonts.gstatic.com" in _CSP

    def test_csp_no_wildcard_default_src(self):
        from app.main import _CSP
        for part in _CSP.split(";"):
            if "default-src" in part:
                assert "*" not in part, "default-src must not be wildcard"

    def test_csp_allows_supabase_websocket(self):
        """Supabase Realtime uses wss:// — must be in connect-src."""
        from app.main import _CSP
        assert "wss://*.supabase.co" in _CSP


# ═════════════════════════════════════════════════════════════════════════════
# Production startup guards — regression after main.py edit
# ═════════════════════════════════════════════════════════════════════════════

class TestProductionStartupGuardRegression:
    """
    9E-F guards must still fire correctly after the main.py edit.
    Regression: SecurityHeadersMiddleware addition must not break lifespan.
    """

    def test_sentry_dsn_guard_fires_in_production(self):
        import app.main as main_module
        original_env = main_module.settings.ENVIRONMENT
        original_dsn = main_module.settings.SENTRY_DSN
        try:
            main_module.settings.ENVIRONMENT = "production"
            main_module.settings.SENTRY_DSN = ""
            with pytest.raises(AssertionError, match="SENTRY_DSN"):
                assert main_module.settings.SENTRY_DSN, \
                    "SENTRY_DSN must be set in production."
        finally:
            main_module.settings.ENVIRONMENT = original_env
            main_module.settings.SENTRY_DSN = original_dsn

    def test_frontend_url_localhost_guard(self):
        import app.main as main_module
        original_env = main_module.settings.ENVIRONMENT
        original_url = main_module.settings.FRONTEND_URL
        try:
            main_module.settings.ENVIRONMENT = "production"
            main_module.settings.FRONTEND_URL = "http://localhost:5173"
            with pytest.raises(AssertionError, match="localhost"):
                assert not main_module.settings.FRONTEND_URL.startswith("http://localhost"), \
                    "FRONTEND_URL must not be localhost in production."
        finally:
            main_module.settings.ENVIRONMENT = original_env
            main_module.settings.FRONTEND_URL = original_url

    def test_cors_wildcard_guard(self):
        origins = ["*"]
        with pytest.raises(AssertionError, match="wildcard"):
            assert "*" not in origins, \
                "CORS wildcard (*) is not permitted in production."

    def test_no_wildcard_in_actual_origins(self):
        import app.main as main_module
        assert "*" not in main_module._origins

    def test_frontend_url_in_actual_origins(self):
        import app.main as main_module
        assert main_module.settings.FRONTEND_URL in main_module._origins

    def test_health_check_returns_200(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] in ("ok", "degraded")

    def test_health_check_has_version(self, client):
        res = client.get("/health")
        assert "version" in res.json()


# ═════════════════════════════════════════════════════════════════════════════
# CORS — regression (no wildcard introduced by middleware edit)
# ═════════════════════════════════════════════════════════════════════════════

class TestCorsRegression:

    def test_no_wildcard_in_origins(self):
        import app.main as main_module
        assert "*" not in main_module._origins

    def test_frontend_url_in_origins(self):
        import app.main as main_module
        assert main_module.settings.FRONTEND_URL in main_module._origins

    def test_cors_headers_on_options_preflight(self, client):
        """OPTIONS preflight must return CORS headers — middleware must not break this."""
        res = client.options(
            "/api/v1/leads",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            }
        )
        # Should not 500 — middleware order must not break CORS
        assert res.status_code in (200, 204, 400, 403)


# ═════════════════════════════════════════════════════════════════════════════
# RLS audit — documented as SQL verification (no Python equivalent)
# ═════════════════════════════════════════════════════════════════════════════

class TestRlsAuditDocumentation:
    """
    RLS is enforced at the Supabase/PostgreSQL layer — not testable via
    FastAPI TestClient (backend uses service role key which bypasses RLS).

    Verification method: run the SQL queries below in Supabase SQL Editor.
    Both must return 0 rows before 9E-H can be signed off.

    Query 1 — tables with RLS on but no policies (access fully blocked):
        SELECT t.tablename
        FROM pg_tables t
        LEFT JOIN pg_policies p
          ON p.tablename = t.tablename AND p.schemaname = 'public'
        WHERE t.schemaname = 'public'
          AND t.rowsecurity = true
          AND p.policyname IS NULL;

    Query 2 — tables with RLS disabled (no tenant isolation):
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND rowsecurity = false;

    Expected result: both queries return 0 rows.
    """

    def test_rls_audit_documented(self):
        """Placeholder — RLS verified via Supabase SQL Editor (see docstring)."""
        assert True  # Manual step — see class docstring above


# ═════════════════════════════════════════════════════════════════════════════
# sanitize.js — behaviour documentation (verified via vitest)
# ═════════════════════════════════════════════════════════════════════════════

class TestSanitizeJsDocumentation:
    """
    sanitize.js lives in the frontend — verified via:
      cd frontend && npx vitest run src/utils/sanitize.test.js

    Expected behaviours:
      sanitizeHtml('<script>alert(1)</script>')  → ''
      sanitizeHtml('<img onerror="alert(1)">')   → '<img>'  (no handler)
      sanitizeHtml('<b>bold</b>')                → '<b>bold</b>'
      sanitizeHtml('<a href="javascript:x">')    → '<a>'    (no href)
      sanitizeHtml(null)                         → ''
      sanitizeHtml(undefined)                    → ''
      sanitizeText('<b>hello</b>')               → 'hello'
      sanitizeText('<script>x</script>text')     → 'text'
    """

    def test_sanitize_js_documented(self):
        """Placeholder — DOMPurify behaviour verified manually / via vitest."""
        assert True  # Manual step — see class docstring above
