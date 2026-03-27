"""
app/database.py
---------------
Supabase client initialisation for Opsra.

IMPORTANT — lazy initialisation pattern
-----------------------------------------
The Supabase client is NOT created at module import time.
It is created on first use via get_supabase().

Why: creating the client at import time causes test failures because
supabase-py validates the API key format (must be a real JWT) immediately
on construction — before any mock can intercept the call.
Lazy init also means the app can start and respond to /health even if
Supabase credentials are temporarily misconfigured.

Usage in routes (FastAPI dependency injection):
    from app.database import get_supabase

    @router.get("/leads")
    async def list_leads(db = Depends(get_supabase)):
        ...

Usage in service layer (direct call — for Celery workers):
    from app.database import get_supabase
    db = get_supabase()
"""

from __future__ import annotations

import logging
from typing import Optional

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton — None until first request
# ---------------------------------------------------------------------------

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """
    Return the Supabase service-role client, creating it on first call.

    This is used as a FastAPI dependency (Depends(get_supabase)) and can
    also be called directly in Celery workers.

    The client uses the SERVICE KEY — it bypasses RLS and must only ever
    be used server-side. Never expose this client or its key to the frontend.
    """
    global _supabase_client

    if _supabase_client is None:
        logger.debug("Initialising Supabase client (first use)")
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY,
        )

    return _supabase_client


def reset_supabase_client() -> None:
    """
    Force the singleton to be re-created on next call.

    Used in tests to ensure a fresh mock client is injected between test
    cases without stale state from previous runs.
    """
    global _supabase_client
    _supabase_client = None