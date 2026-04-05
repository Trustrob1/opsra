"""
app/utils/rate_limiter.py
Redis-backed rate limiting utility — Phase 6A (§11.4 / S15).

Strategy: INCR + EXPIRE pipeline (sliding window approximation).
Fails OPEN if Redis is unavailable — operations continue without rate limiting
rather than blocking all users when Redis is down.

TLS requirement: REDIS_URL must start with rediss:// in production (§2.2).
The Celery app enforces this on startup; the rate limiter reuses the same URL.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lazy Redis singleton ──────────────────────────────────────────────────────

_redis_client = None


def _get_redis():
    """
    Returns a Redis client, or None if:
      - REDIS_URL is not set (local dev without Redis)
      - redis package not importable
      - Connection fails
    In all fallback cases the rate limiter fails open.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None

    try:
        import redis as redis_lib  # noqa: PLC0415 — lazy import

        _redis_client = redis_lib.from_url(url, decode_responses=True)
        # Verify connection on first use
        _redis_client.ping()
        return _redis_client
    except ImportError:
        logger.warning(
            "rate_limiter: redis package not installed — rate limiting disabled. "
            "Install it with: pip install redis"
        )
        return None
    except Exception as exc:
        logger.warning(
            "rate_limiter: Redis connection failed — %s. Failing open.", exc
        )
        return None


# ── Public API ────────────────────────────────────────────────────────────────


def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Check whether the caller is within the rate limit.

    Uses Redis INCR + EXPIRE in a pipeline:
      - Increments a counter for `key`
      - Sets the TTL to `window_seconds` on first call
      - Returns True  if count <= limit  (request allowed)
      - Returns False if count > limit   (request blocked — caller should 429)
      - Returns True  if Redis is unavailable (fail open)

    Args:
        key:            Namespaced key, e.g. "rate:ai:{org_id}:{user_id}"
        limit:          Maximum allowed calls within the window
        window_seconds: Rolling window length in seconds (TTL)
    """
    r = _get_redis()
    if r is None:
        return True  # Fail open — Redis unavailable

    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = pipe.execute()
        count: int = results[0]
        return count <= limit
    except Exception as exc:
        logger.warning("rate_limiter: check failed — %s. Failing open.", exc)
        return True


def reset_rate_limit(key: str) -> None:
    """
    Delete a rate limit key (used in tests and admin tooling).
    Silently no-ops if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as exc:
        logger.warning("rate_limiter: reset failed for key %s — %s", key, exc)