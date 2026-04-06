"""
app/main.py
FastAPI application entry point.
Registers all routers — Phase 1 (auth, admin, webhooks) + Phase 2A (leads)
  + Phase 3A (customers, whatsapp) + Phase 4A (tickets)
  + Phase 5A (subscriptions) + Phase 6A (ops intel) + Phase 7A (tasks).
"""
from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
app = FastAPI(
    title="Opsra API",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
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
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    max_age=600,
)
# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import webhooks as webhooks_router
from app.routers import leads as leads_router
from app.routers import customers as customers_router
from app.routers import whatsapp as whatsapp_router
from app.routers import tickets as tickets_router       # ← Phase 4A
from app.routers import subscriptions as subscriptions_router  # ← Phase 5A
from app.routers import ops as ops_router                      # ← Phase 6A
from app.routers import tasks as tasks_router                  # ← Phase 7A
from app.routers import notifications as notifications_router
from app.routers import commissions as commissions_router

app.include_router(
    auth_router.router,
    prefix="/api/v1",
    tags=["auth"],
)
app.include_router(
    admin_router.router,
    prefix="/api/v1/admin",
    tags=["admin"],
)
# Webhooks — no /api/v1 prefix, no auth
app.include_router(
    webhooks_router.router,
    prefix="/webhooks",
    tags=["webhooks"],
)
# Phase 2A — Leads
app.include_router(
    leads_router.router,
    prefix="/api/v1/leads",
    tags=["leads"],
)
app.include_router(
    customers_router.router,
    prefix="/api/v1/customers",
    tags=["customers"],
)
app.include_router(
    whatsapp_router.router,
    prefix="/api/v1",
    tags=["whatsapp"],
)
# Phase 4A — Support (tickets, knowledge-base, interaction-logs)
app.include_router(
    tickets_router.router,
    prefix="/api/v1",
    tags=["tickets"],
)
# Phase 5A — Renewal & Upsell Engine (subscriptions)
app.include_router(
    subscriptions_router.router,
    prefix="/api/v1/subscriptions",
    tags=["subscriptions"],
)
# Phase 6A — Operations Intelligence
app.include_router(
    ops_router.router,
    prefix="/api/v1",
    tags=["ops"],
)
# Phase 7A — Task Management
app.include_router(
    tasks_router.router,
    prefix="/api/v1",
    tags=["tasks"],
)
# Phase 9 — Notifications
app.include_router(
    notifications_router.router,
    prefix="/api/v1",
    tags=["notifications"],
)
# Phase 9C — Commissions
app.include_router(
    commissions_router.router,
    prefix="/api/v1",
    tags=["commissions"],
)
# ---------------------------------------------------------------------------
# Health check — Technical Spec Section 5.8
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}