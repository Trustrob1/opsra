"""
app/main.py
FastAPI application entry point.
Registers all routers — Phase 1 (auth, admin, webhooks) + Phase 2A (leads)
  + Phase 3A (customers, whatsapp) + Phase 4A (tickets)
  + Phase 5A (subscriptions) + Phase 6A (ops intel) + Phase 7A (tasks)
  + M01-10b (assistant / Aria)
  + ORG-ONBOARDING-A (superadmin, onboarding).

9E-A additions:
  - Sentry SDK initialised before app creation (traces_sample_rate=0.2)
  - /health performs real Supabase ping, returns version 49.0
  - SIGTERM graceful shutdown handler via lifespan (10 s drain window)
  - Logging set to INFO at startup; no PII in any log statements
"""
from __future__ import annotations

import logging
import signal
import asyncio
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings

# ---------------------------------------------------------------------------
# Logging — INFO level, no PII.  Configured before anything else so all
# subsequent imports that call getLogger() pick up the right level.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentry — 9E-A Observability.
# SENTRY_DSN = "" is safe (Sentry becomes a no-op in local dev).
# init() must happen before app = FastAPI() so the SDK wraps the ASGI stack.
# ---------------------------------------------------------------------------
sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    environment=settings.ENVIRONMENT,
    traces_sample_rate=0.2,
    # send_default_pii=False is the SDK default — never send PII to Sentry.
)

# ---------------------------------------------------------------------------
# SIGTERM graceful shutdown.
# Uvicorn forwards SIGTERM to the process on Render shutdown.
# We log receipt here; the actual drain window (10 s) is set in the lifespan
# shutdown hook below AND should be configured in Render as graceful timeout.
# ---------------------------------------------------------------------------
def _sigterm_handler(signum, frame) -> None:
    logger.info("SIGTERM received — initiating graceful shutdown")

signal.signal(signal.SIGTERM, _sigterm_handler)


# ---------------------------------------------------------------------------
# Lifespan — startup + shutdown hooks.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Opsra API v49.0 starting up (env=%s)", settings.ENVIRONMENT)

    # F6: Production startup guards — fail fast if critical env vars are missing.
    # These assertions fire before the app accepts any traffic.
    if settings.ENVIRONMENT == "production":
        assert settings.SENTRY_DSN, (
            "SENTRY_DSN must be set in production. "
            "Add it to Render env vars before deploying."
        )
        assert not settings.FRONTEND_URL.startswith("http://localhost"), (
            "FRONTEND_URL must not be localhost in production. "
            "Set it to your deployed frontend URL in Render env vars."
        )
        assert "*" not in _origins, (
            "CORS wildcard (*) is not permitted in production. "
            "Set FRONTEND_URL and ALLOWED_ORIGINS to explicit URLs."
        )

    yield
    # Give in-flight requests up to 10 s to complete before the process exits.
    # Uvicorn's --timeout-graceful-shutdown should also be set to 10 in Render.
    logger.info("Shutdown initiated — draining in-flight requests (10 s window)")
    await asyncio.sleep(10)
    logger.info("Drain complete — shutting down")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Opsra API",
    version="49.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# CORS — Section 11.6: only the deployed frontend URL, never *
_origins = [settings.FRONTEND_URL]
if settings.ALLOWED_ORIGINS:
    for origin in settings.ALLOWED_ORIGINS.split(","):
        origin = origin.strip()
        if origin and origin not in _origins:
            _origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Superadmin-Secret"],
    max_age=600,
)

# ---------------------------------------------------------------------------
# Security headers — 9E-H / H4
# Applied to every response. CSP allows Supabase realtime (wss://), Sentry,
# and Google Fonts used by the frontend. 'unsafe-inline' in style-src is
# required because the React app uses inline style={{ }} props throughout.
# ---------------------------------------------------------------------------
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://*.supabase.co; "
    "connect-src 'self' https://*.supabase.co https://*.sentry.io wss://*.supabase.co; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"]   = _CSP
        response.headers["X-Frame-Options"]            = "DENY"
        response.headers["X-Content-Type-Options"]     = "nosniff"
        response.headers["Referrer-Policy"]            = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]         = "camera=(), microphone=(), geolocation=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import webhooks as webhooks_router
from app.routers import leads as leads_router
from app.routers import customers as customers_router
from app.routers import whatsapp as whatsapp_router
from app.routers import tickets as tickets_router
from app.routers import subscriptions as subscriptions_router
from app.routers import ops as ops_router
from app.routers import tasks as tasks_router
from app.routers import notifications as notifications_router
from app.routers import commissions as commissions_router
from app.routers import assistant as assistant_router
from app.routers import superadmin as superadmin_router
from app.routers import onboarding as onboarding_router
from app.routers import shopify as shopify_router
from app.routers import growth_analytics as growth_analytics_router
from app.routers import growth_config as growth_config_router
from app.routers import growth_insights as growth_insights_router
from app.routers import commerce as commerce_router
from app.routers import superadmin_health as superadmin_health_router
from app.routers.push_notifications import router as push_notifications_router

app.include_router(auth_router.router,          prefix="/api/v1",               tags=["auth"])
app.include_router(admin_router.router,         prefix="/api/v1/admin",         tags=["admin"])
app.include_router(webhooks_router.router,      prefix="/webhooks",             tags=["webhooks"])
app.include_router(leads_router.router,         prefix="/api/v1/leads",         tags=["leads"])
app.include_router(customers_router.router,     prefix="/api/v1/customers",     tags=["customers"])
app.include_router(whatsapp_router.router,      prefix="/api/v1",               tags=["whatsapp"])
app.include_router(tickets_router.router,       prefix="/api/v1",               tags=["tickets"])
app.include_router(subscriptions_router.router, prefix="/api/v1/subscriptions", tags=["subscriptions"])
app.include_router(ops_router.router,           prefix="/api/v1",               tags=["ops"])
app.include_router(tasks_router.router,         prefix="/api/v1",               tags=["tasks"])
app.include_router(notifications_router.router, prefix="/api/v1",               tags=["notifications"])
app.include_router(commissions_router.router,   prefix="/api/v1",               tags=["commissions"])
app.include_router(assistant_router.router,     prefix="/api/v1",               tags=["assistant"])
app.include_router(superadmin_router.router,    prefix="/api/v1",               tags=["superadmin"])
app.include_router(onboarding_router.router,    prefix="/api/v1",               tags=["onboarding"])
app.include_router(shopify_router.router,       prefix="/api/v1/admin",         tags=["shopify"])
app.include_router(growth_analytics_router.router, prefix="/api/v1",           tags=["growth_analytics"])
app.include_router(growth_config_router.router, prefix="/api/v1",              tags=["growth_config"])
app.include_router(growth_insights_router.router,                              tags=["growth_insights"])
app.include_router(commerce_router.router,      prefix="/api/v1/commerce",      tags=["commerce"])
app.include_router(superadmin_health_router.router, prefix="/api/v1",           tags=["superadmin_health"])
app.include_router(push_notifications_router)


# ---------------------------------------------------------------------------
# Health check — 9E-A (replaces stub).
# Performs a real Supabase ping so Render knows the DB is reachable.
# Never raises — degraded state returns 200 with db:"error" so Render
# doesn't trigger a restart loop on transient DB blips.
# ---------------------------------------------------------------------------
from app.database import get_supabase


@app.get("/health", tags=["health"])
async def health_check():
    try:
        db = get_supabase()
        db.table("organisations").select("id").limit(1).execute()
        return {"status": "ok", "db": "ok", "version": "49.0"}
    except Exception as exc:
        logger.warning("Health check DB ping failed: %s", exc)
        return JSONResponse(
            status_code=200,
            content={"status": "degraded", "db": "error", "version": "49.0"},
        )
