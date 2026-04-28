"""
app/main.py
FastAPI application entry point.
Registers all routers — Phase 1 (auth, admin, webhooks) + Phase 2A (leads)
  + Phase 3A (customers, whatsapp) + Phase 4A (tickets)
  + Phase 5A (subscriptions) + Phase 6A (ops intel) + Phase 7A (tasks)
  + M01-10b (assistant / Aria)
  + ORG-ONBOARDING-A (superadmin, onboarding).
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
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Superadmin-Secret"],
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
from app.routers import assistant as assistant_router          # ← M01-10b
from app.routers import superadmin as superadmin_router        # ← ORG-ONBOARDING-A
from app.routers import onboarding as onboarding_router        # ← ORG-ONBOARDING-A
from app.routers import shopify as shopify_router
from app.routers import growth_analytics as growth_analytics_router   # ← GPM-1A
from app.routers import growth_config as growth_config_router         # ← GPM-1A
from app.routers import growth_insights as growth_insights_router
from app.routers import commerce as commerce_router              # ← COMM-1

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

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
# M01-10b — Aria AI Assistant
app.include_router(
    assistant_router.router,
    prefix="/api/v1",
    tags=["assistant"],
)
# ORG-ONBOARDING-A — Super-Admin provisioning
app.include_router(
    superadmin_router.router,
    prefix="/api/v1",
    tags=["superadmin"],
)
# ORG-ONBOARDING-A — Onboarding checklist + go-live
app.include_router(
    onboarding_router.router,
    prefix="/api/v1",
    tags=["onboarding"],
)

# SHOP-1A — Shopify Integration
app.include_router(
    shopify_router.router,
    prefix="/api/v1/admin",
    tags=["shopify"],
)
 
# GPM-1A — Growth Analytics
app.include_router(
    growth_analytics_router.router,
    prefix="/api/v1",
    tags=["growth_analytics"],
)
 
# GPM-1A — Growth Config (teams, spend, direct sales)
app.include_router(
    growth_config_router.router,
    prefix="/api/v1",
    tags=["growth_config"],
)

# GPM-2 — Growth AI Insights
app.include_router(
    growth_insights_router.router,
    tags=["growth_insights"],
)

# COMM-1 — Commerce session routes
app.include_router(
    commerce_router.router,
    prefix="/api/v1/commerce",
    tags=["commerce"],
)

# ---------------------------------------------------------------------------
# Health check — Technical Spec Section 5.8
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}