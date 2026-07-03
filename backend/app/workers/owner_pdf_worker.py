"""
app/workers/owner_pdf_worker.py
OWNER-PDF-1 — Owner-facing WhatsApp PDF report generation.

Celery task: generate_owner_pdf_report
Triggered ON-DEMAND ONLY, dispatched via .delay() from
owner_query_service._execute_query's pdf_report action handler. There is
deliberately NO beat schedule entry for this task — it never runs on a timer.

Flow:
  1. Receive org_id, sender_number, provider_names, report_type, date_from, date_to.
  2. Call the matching formatter in owner_pdf_service.py.
  3. Formatter returns (pdf_bytes, meta) — never raises (S14).
  4. Upload PDF to the private Supabase Storage 'owner-reports' bucket
     (see migration_owner_pdf_reports_storage.sql).
  5. Create a short-link row in owner_pdf_report_links (see
     migration_owner_pdf_report_links.sql) — 24h expiry.
  6. Send the SHORT link to the owner via WhatsApp — never the raw Supabase
     signed URL (that's a 350+ char JWT-bearing string). The link resolves
     through GET /api/v1/r/report/{short_code} in public_performance.py,
     which generates a fresh signed URL server-side at click time and
     302-redirects. This mirrors the existing RPT-DAILY short-link pattern
     (GET /r/{token}/{date}) in the same file, using RENDER_EXTERNAL_URL
     for the absolute domain — same env var owner_report_worker.py uses.
  7. Any failure sends a plain-language fallback WhatsApp message. The task
     itself never raises back to Celery — it always returns a summary dict.

Note on Storage path / upsert: a prior session (whatsapp-media upload,
CATALOG image mirroring era) hit a supabase-py UnboundLocalError caused by
passing "upsert": "false" (string) in file_options — see Build Status bug
log ("Media upload 503 with 'cannot access local variable response'").
This worker avoids the whole failure class by never setting "upsert" and
instead making every report path collision-free (date + report_type + a
short time suffix), so two reports of the same type on the same day never
collide.

Pattern 48 (Rule 1): get_supabase() used directly — never get_db().
Pattern 29: load_dotenv() at module level.
Pattern 63: lazy imports for cross-module worker/service calls.
S13: report_type validated against a known set before any processing.
S14: never raises — failure sends the owner a plain-language fallback message,
     task always returns a summary dict.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from app.workers.celery_app import celery_app   # noqa: E402
from app.database import get_supabase            # noqa: E402

logger = logging.getLogger(__name__)

_STORAGE_BUCKET = "owner-reports"
_SHORT_LINK_EXPIRY_HOURS = 24  # the "link expires in 24 hours" promise made to the owner

# Same env var owner_report_worker.py uses to build its absolute /r/{token}/{date}
# short link — mirrored here rather than reintroducing FRONTEND_URL, since this
# link points at a backend redirect route, not the frontend SPA.
_API_BASE_URL = os.getenv("API_BASE_URL", "")

_VALID_REPORT_TYPES = frozenset({
    "period_summary", "lead_pipeline", "orders_fulfilment", "comparison",
})


def _storage_path(org_id: str, report_type: str) -> str:
    """
    owner-reports/{org_id}/{date}-{report_type}-{HHMMSS}.pdf

    Extends the OWNER-PDF-1 spec's documented path pattern
    (owner-reports/{org_id}/{date}-{report_type}.pdf) with a time suffix so
    a second report of the same type requested later the same day never
    collides with the first — deliberately avoiding any reliance on
    Storage upsert (see module docstring).
    """
    today = datetime.now(timezone.utc)
    return f"{org_id}/{today.strftime('%Y-%m-%d')}-{report_type}-{today.strftime('%H%M%S')}.pdf"


def _upload_pdf(db: Any, org_id: str, report_type: str, pdf_bytes: bytes) -> Optional[str]:
    """
    Upload PDF bytes to the private owner-reports bucket. Returns the
    storage path on success, None on any failure. S14: never raises.

    Deliberately does NOT sign a URL here — signing now happens at click
    time in the /r/report/{short_code} redirect route, so this function's
    only job is getting the bytes into Storage.
    """
    try:
        path = _storage_path(org_id, report_type)
        db.storage.from_(_STORAGE_BUCKET).upload(
            path,
            pdf_bytes,
            {"content-type": "application/pdf"},
        )
        return path
    except Exception as exc:
        logger.error(
            "owner_pdf_worker._upload_pdf failed org=%s report_type=%s: %s",
            org_id, report_type, exc,
        )
        return None


def _create_short_link(db: Any, org_id: str, storage_path: str) -> Optional[str]:
    """
    Insert a short_code -> storage_path row with a 24h expiry and return
    the short_code. Retries a few times on the (astronomically unlikely)
    event of a short_code collision. S14: returns None on any failure.
    """
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=_SHORT_LINK_EXPIRY_HOURS)).isoformat()

    for attempt in range(3):
        short_code = secrets.token_urlsafe(6)  # 8 URL-safe chars
        try:
            db.table("owner_pdf_report_links").insert({
                "short_code":   short_code,
                "org_id":       org_id,
                "storage_path": storage_path,
                "created_at":   now.isoformat(),
                "expires_at":   expires_at,
            }).execute()
            return short_code
        except Exception as exc:
            logger.warning(
                "owner_pdf_worker._create_short_link attempt=%d collision/failure org=%s: %s",
                attempt, org_id, exc,
            )
    logger.error(
        "owner_pdf_worker._create_short_link: exhausted retries org=%s path=%s",
        org_id, storage_path,
    )
    return None


@celery_app.task(name="generate_owner_pdf_report", bind=True, max_retries=0)
def generate_owner_pdf_report(
    self,
    org_id: str,
    sender_number: str,
    provider_names: list[str],
    report_type: str,
    date_from: Optional[str],
    date_to: Optional[str],
) -> dict:
    """
    Generate an owner-facing PDF report and deliver a short link via WhatsApp.

    S13: report_type validated before any processing — falls back to
    period_summary rather than failing outright, matching the same default
    behaviour already established in owner_query_service._validate_routing_response.
    S14: never raises — sends a fallback WhatsApp message on any failure and
    always returns a summary dict (never None), consistent with every other
    worker in this codebase (run_report_delivery, run_broadcast_dispatcher, etc.).
    """
    summary = {
        "org_id": org_id,
        "report_type": report_type,
        "delivered": False,
        "failed": False,
    }

    db = None
    try:
        if report_type not in _VALID_REPORT_TYPES:
            logger.warning(
                "generate_owner_pdf_report: invalid report_type=%r org=%s — defaulting to period_summary",
                report_type, org_id,
            )
            report_type = "period_summary"
            summary["report_type"] = report_type

        db = get_supabase()

        from app.workers.owner_report_worker import _send_owner_whatsapp
        from app.services.owner_pdf_service import (
            build_period_summary_pdf,
            build_lead_pipeline_pdf,
            build_orders_fulfilment_pdf,
            build_comparison_pdf,
        )

        parsed_date_from = date.fromisoformat(date_from) if date_from else None
        parsed_date_to = date.fromisoformat(date_to) if date_to else None

        builders = {
            "period_summary":    build_period_summary_pdf,
            "lead_pipeline":     build_lead_pipeline_pdf,
            "orders_fulfilment": build_orders_fulfilment_pdf,
            "comparison":        build_comparison_pdf,
        }
        builder = builders[report_type]

        pdf_bytes, meta = builder(
            db=db,
            org_id=org_id,
            provider_names=provider_names or [],
            date_from=parsed_date_from,
            date_to=parsed_date_to,
        )

        if not pdf_bytes:
            reason = (meta or {}).get("reason") or "no data was available for that period."
            logger.warning(
                "generate_owner_pdf_report: builder returned no PDF org=%s report_type=%s reason=%s",
                org_id, report_type, reason,
            )
            _send_owner_whatsapp(
                db, org_id, sender_number,
                f"I couldn't generate that report \u2014 {reason}",
            )
            summary["failed"] = True
            return summary

        storage_path = _upload_pdf(db, org_id, report_type, pdf_bytes)
        if not storage_path:
            _send_owner_whatsapp(
                db, org_id, sender_number,
                "Your report was generated but I couldn't upload it right now. Please try again shortly.",
            )
            summary["failed"] = True
            return summary

        short_code = _create_short_link(db, org_id, storage_path)
        if not short_code:
            _send_owner_whatsapp(
                db, org_id, sender_number,
                "Your report was generated but I couldn't create a link for it right now. Please try again shortly.",
            )
            summary["failed"] = True
            return summary

        if not _API_BASE_URL:
            # RENDER_EXTERNAL_URL missing is a config error, not a per-request
            # failure — owner_report_worker.py relies on the same env var and
            # would already be broken if this were unset in production.
            logger.error(
                "generate_owner_pdf_report: RENDER_EXTERNAL_URL not set — cannot build report link org=%s",
                org_id,
            )
            _send_owner_whatsapp(
                db, org_id, sender_number,
                "Your report was generated but I couldn't create a link for it right now. Please try again shortly.",
            )
            summary["failed"] = True
            return summary

        report_url = f"{_API_BASE_URL}/api/v1/r/report/{short_code}"

        label = (meta or {}).get("label") or report_type.replace("_", " ").title()
        _send_owner_whatsapp(
            db, org_id, sender_number,
            f"\U0001F4C4 Your *{label}* is ready:\n{report_url}\n\n(Link expires in 24 hours.)",
        )
        summary["delivered"] = True
        return summary

    except Exception as exc:
        logger.error(
            "generate_owner_pdf_report failed org=%s report_type=%s: %s",
            org_id, report_type, exc,
        )
        try:
            if db is None:
                db = get_supabase()
            from app.workers.owner_report_worker import _send_owner_whatsapp
            _send_owner_whatsapp(
                db, org_id, sender_number,
                "Something went wrong generating your report. Please try again in a moment.",
            )
        except Exception:
            pass  # S14 — even the fallback message must never raise
        summary["failed"] = True
        return summary
