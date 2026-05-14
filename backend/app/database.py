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
    Return a fresh Supabase service-role client for this request.

    A new client is created on every call. This is intentional.

    supabase-py's sync Client is NOT safe for concurrent use. It uses a
    mutable PostgREST query builder — chained calls (.table().select().eq())
    mutate internal state on the builder object. Sharing one instance across
    concurrent coroutines causes builder state corruption: concurrent requests
    overwrite each other's query parameters mid-chain, resulting in Supabase
    returning HTTP 200 with 0 rows (valid response to a malformed query).
    This manifested as the persistent sign-out loop: 0 rows → 401 → clearAuth().

    Client construction is cheap — no connection is opened until .execute().
    Each request gets isolated state. Celery workers (single-threaded per task)
    are unaffected.

    The module-level singleton (_supabase_client) and reset_supabase_client()
    are retained for test compatibility only.
    """
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY,
    )


def reset_supabase_client() -> None:
    """
    Force the singleton to be re-created on next call.

    Used in tests to ensure a fresh mock client is injected between test
    cases without stale state from previous runs.
    """
    global _supabase_client
    _supabase_client = None