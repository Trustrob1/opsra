"""
app/services/monitoring_service.py
SA-2A — Centralised error logging for the Superadmin Health Dashboard.

Exports:
  log_system_error(db, ...) — writes to system_error_log + Sentry. S14.
  write_worker_log(db, ...) — writes to worker_run_log. S14.

All functions are S14 — they NEVER raise. A monitoring failure must not
break the caller or change its response code.

generate_fix_hint() lives in ai_service.py (SA-2A spec §Modified: ai_service.py).
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_system_error(
    db,
    *,
    error_type: str,
    error_message: str,
    org_id: Optional[str] = None,
    org_slug: Optional[str] = None,
    http_status: Optional[int] = None,
    file_path: Optional[str] = None,
    function_name: Optional[str] = None,
    line_number: Optional[int] = None,
    route: Optional[str] = None,
    exc: Optional[BaseException] = None,
    generate_hint: bool = True,
) -> None:
    """
    Write one row to system_error_log and forward to Sentry.

    Args:
        db              — Supabase client
        error_type      — short category string e.g. "webhook_error", "worker_failure"
        error_message   — full error message (truncated to 2000 chars)
        org_id          — UUID of affected org (NULL = platform-level error)
        org_slug        — org slug for display (NULL = unknown)
        http_status     — HTTP status code if this is an API error
        file_path       — source file where the error occurred
        function_name   — function where the error occurred
        line_number     — line number
        route           — API route or worker name
        exc             — original exception (used for Sentry + stack trace context)
        generate_hint   — if True, calls generate_fix_hint() for a plain-English hint.
                          Set False for high-frequency errors to avoid Haiku cost.

    S14: never raises. Any failure is logged at WARNING level only.
    """
    try:
        # Auto-extract file/function/line from exception traceback if not provided
        _file = file_path
        _fn = function_name
        _line = line_number
        _plain = None

        if exc is not None and (_file is None or _fn is None or _line is None):
            try:
                tb = traceback.extract_tb(exc.__traceback__)
                if tb:
                    frame = tb[-1]
                    _file = _file or frame.filename
                    _fn = _fn or frame.name
                    _line = _line or frame.lineno
            except Exception:
                pass

        # Generate plain-English fix hint via Haiku (async-safe: runs sync)
        fix_hint = None
        if generate_hint:
            try:
                from app.services.ai_service import generate_fix_hint
                fix_hint = generate_fix_hint(
                    error_type=error_type,
                    error_message=error_message[:500],
                    file_path=_file,
                    function_name=_fn,
                )
            except Exception as hint_exc:
                logger.warning("log_system_error: generate_fix_hint failed — %s", hint_exc)

        # Write to DB
        db.table("system_error_log").insert({
            "org_id": org_id or None,
            "error_type": error_type[:100],
            "http_status": http_status,
            "file_path": (_file or "")[:500],
            "function_name": (_fn or "")[:200],
            "line_number": _line,
            "error_message": (error_message or "")[:2000],
            "plain_english": None,  # reserved for future auto-translation
            "fix_hint": fix_hint,
            "route": (route or "")[:500],
            "org_slug": (org_slug or "")[:100],
            "occurred_at": _now_iso(),
        }).execute()

        # Forward to Sentry
        if exc is not None:
            with sentry_sdk.push_scope() as scope:
                if org_id:
                    scope.set_tag("org_id", org_id)
                if route:
                    scope.set_tag("route", route)
                scope.set_tag("error_type", error_type)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_message(
                f"{error_type}: {error_message[:200]}",
                level="error",
                scope=sentry_sdk.Scope.get_isolation_scope(),
            )

    except Exception as monitor_exc:
        # S14: monitoring must never raise
        logger.warning(
            "log_system_error: failed to write monitoring row — %s", monitor_exc
        )


def write_worker_log(
    db,
    *,
    worker_name: str,
    status: str,
    items_processed: int = 0,
    items_failed: int = 0,
    items_skipped: int = 0,
    error_message: Optional[str] = None,
    run_duration_ms: Optional[int] = None,
    started_at: Optional[datetime] = None,
    org_id: Optional[str] = None,
) -> None:
    """
    Write one row to worker_run_log after a worker completes.

    Args:
        db              — Supabase client
        worker_name     — e.g. "broadcast_worker", "renewal_worker"
        status          — "passed" | "failed" | "skipped" | "partial"
        items_processed — total items touched
        items_failed    — items that errored (S14 per-item failures)
        items_skipped   — items skipped by gate checks
        error_message   — top-level error if status=failed
        run_duration_ms — wall-clock duration of the run
        started_at      — when the run started (defaults to now if omitted)
        org_id          — set if this run is org-scoped; NULL for platform-level workers

    S14: never raises.
    """
    try:
        now = datetime.now(timezone.utc)
        started = started_at or now

        # Derive status from counts if not explicitly failed
        effective_status = status
        if status == "passed" and items_failed > 0:
            effective_status = "partial"

        db.table("worker_run_log").insert({
            "worker_name": worker_name[:100],
            "org_id": org_id or None,
            "status": effective_status,
            "items_processed": items_processed,
            "items_failed": items_failed,
            "items_skipped": items_skipped,
            "error_message": (error_message or "")[:2000] or None,
            "run_duration_ms": run_duration_ms,
            "started_at": started.isoformat(),
            "completed_at": now.isoformat(),
        }).execute()

    except Exception as monitor_exc:
        # S14: never raises
        logger.warning(
            "write_worker_log: failed to write worker_run_log row — %s", monitor_exc
        )
