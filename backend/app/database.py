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

import contextvars
import logging
from typing import List, Optional

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton — None until first request
# ---------------------------------------------------------------------------

_supabase_client: Optional[Client] = None

# ---------------------------------------------------------------------------
# OOM FIX (2026-07): connection tracking for cleanup.
#
# get_supabase() intentionally creates a brand-new Client on every call (see
# docstring below) to avoid query-builder state corruption under concurrency.
# The problem: each Client opens its own underlying HTTP connection(s) to
# Supabase, and nothing ever closed them — they were left for the garbage
# collector, which does not promptly close sockets. Over hours, this piled
# up hundreds of stale ESTABLISHED connections per worker process and slowly
# exhausted memory until Render's OOM killer restarted the instance.
#
# Fix: every client created gets appended to this contextvar-scoped list (if
# a context is active). A FastAPI middleware (app/main.py) and Celery signal
# handlers (app/workers/celery_app.py) open a fresh list at the start of each
# request/task and close every registered client's sessions at the end.
# This requires ZERO changes to any of the 50+ existing get_supabase() call
# sites across routers and workers.
# ---------------------------------------------------------------------------

_active_clients: contextvars.ContextVar[Optional[List[Client]]] = contextvars.ContextVar(
    "_active_clients", default=None
)


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

    OOM fix: if called within a tracked context (see _active_clients above),
    registers this client so its sessions get closed once the request/task
    ends. If called outside any tracked context (e.g. a script, a test), this
    is a silent no-op — behaviour is identical to before.
    """
    client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY,
    )
    clients = _active_clients.get()
    if clients is not None:
        clients.append(client)
    return client


def close_client_sessions(client: Client) -> None:
    """
    Closes the underlying HTTP session(s) held by a Supabase client.
    Called by the request/task-scoped cleanup hooks — never raises.
    """
    try:
        client.postgrest.session.close()
    except Exception:
        logger.debug("Failed closing postgrest session", exc_info=True)
    try:
        auth_http = getattr(client.auth, "_http_client", None)
        if auth_http is not None:
            auth_http.close()
    except Exception:
        logger.debug("Failed closing auth session", exc_info=True)


def reset_supabase_client() -> None:
    """
    Force the singleton to be re-created on next call.

    Used in tests to ensure a fresh mock client is injected between test
    cases without stale state from previous runs.
    """
    global _supabase_client
    _supabase_client = None