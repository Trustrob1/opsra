"""
app/main.py
FastAPI application entry point.
Registers all routers — Phase 1 (auth, admin, webhooks) + Phase 2A (leads).
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
from app.routers import customers as customers_router   # ← ADD
from app.routers import whatsapp as whatsapp_router    # ← ADD


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

app.include_router(                          # ← ADD
    customers_router.router,
    prefix="/api/v1/customers",
    tags=["customers"],
)
app.include_router(                          # ← ADD
    whatsapp_router.router,
    prefix="/api/v1",
    tags=["whatsapp"],
)

# ---------------------------------------------------------------------------
# Health check — Technical Spec Section 5.8
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}