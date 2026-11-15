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
import os
import threading
from typing import List, Optional

import httpx
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


# ---------------------------------------------------------------------------
# DB-POOL-1 (Nov 2026): reuse open connections to Supabase.
#
# Every get_supabase() call builds a NEW Client (see above), and the cleanup
# hooks close its session at the end of the request. Result: every database
# call opened a brand-new TLS connection (TCP + TLS handshake = several
# round trips) before it could send a query. With the backend far from the
# database that cost more than the query itself.
#
# Fix: clients are still created fresh (so query-builder state is never
# shared - the sign-out-loop bug), but each client's HTTP session is given a
# SHARED, bounded connection pool, so connections stay open between calls.
#  - one pool per OS process (a forked Celery child builds its own: sockets
#    must never be shared across a fork)
#  - bounded (max 40 open, 20 kept idle, idle ones dropped after 20 s), so
#    the old "hundreds of stale connections" memory problem cannot return
#  - the shared transport ignores close(), so the per-request cleanup that
#    closes each client does not close the pool
#  - switch off without a deploy: set env SUPABASE_POOL=0
# ---------------------------------------------------------------------------


class _SharedTransport(httpx.HTTPTransport):
    """HTTP transport that stays open when a client that uses it is closed."""

    def close(self) -> None:  # the pool belongs to the process, not to one client
        return None


_pool_lock = threading.Lock()
_pool_pid: Optional[int] = None
_pool_transport: Optional[_SharedTransport] = None


def _pool_enabled() -> bool:
    return os.environ.get("SUPABASE_POOL", "1").strip().lower() not in ("0", "false", "off", "no")


def _shared_transport() -> _SharedTransport:
    """The connection pool for THIS process (created on first use, again after a fork)."""
    global _pool_pid, _pool_transport
    pid = os.getpid()
    if _pool_transport is None or _pool_pid != pid:
        with _pool_lock:
            if _pool_transport is None or _pool_pid != pid:
                _pool_transport = _SharedTransport(
                    limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=20.0),
                )
                _pool_pid = pid
    return _pool_transport


def _use_shared_pool(client: Client) -> None:
    """Point the client's PostgREST session at the shared pool. Never raises: on any problem the
    client simply keeps its own session (the old behaviour)."""
    try:
        old = client.postgrest.session
        client.postgrest.session = type(old)(
            base_url=old.base_url,
            headers=old.headers,
            timeout=old.timeout,
            follow_redirects=True,
            transport=_shared_transport(),
        )
        old.close()
    except Exception:
        logger.warning("DB-POOL-1: could not attach the shared pool; using a private connection", exc_info=True)


# ---------------------------------------------------------------------------
# DB-POOL-1 part 2: build the TLS certificate setup once per process.
# Every Supabase Client creates several httpx clients (auth, REST, storage, functions) and each one used to
# reload the whole CA certificate bundle (about 40 ms of CPU each, so ~160 ms per get_supabase() call, on every
# request). The result is a plain SSLContext that is safe to share, so build it once and hand it out again.
# Only the ordinary case is cached (verify=True, no client certificate); anything else is built as before.
# Off switch without a deploy: env SUPABASE_SSL_CACHE=0.
# ---------------------------------------------------------------------------

_ssl_cache: dict = {}


def _install_ssl_cache() -> None:
    try:
        import httpx._transports.default as _hd

        original = _hd.create_ssl_context
        if getattr(original, "_opsra_cached", False):
            return

        def cached_create_ssl_context(*args, **kwargs):
            if (os.environ.get("SUPABASE_SSL_CACHE", "1").strip().lower() in ("0", "false", "off", "no")
                    or args or kwargs.get("cert") is not None or kwargs.get("verify", True) is not True):
                return original(*args, **kwargs)
            key = (bool(kwargs.get("trust_env", True)), bool(kwargs.get("http2", False)))
            ctx = _ssl_cache.get(key)
            if ctx is None:
                ctx = original(*args, **kwargs)
                _ssl_cache[key] = ctx
            return ctx

        cached_create_ssl_context._opsra_cached = True
        cached_create_ssl_context._original = original
        _hd.create_ssl_context = cached_create_ssl_context
    except Exception:
        logger.warning("DB-POOL-1: could not install the TLS setup cache", exc_info=True)


_install_ssl_cache()


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
    if _pool_enabled():
        _use_shared_pool(client)                       # DB-POOL-1: keep connections open between calls
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