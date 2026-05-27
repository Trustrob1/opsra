"""
app/workers/report_delivery_worker.py
Scheduled report delivery — RPT-1A.

Beat schedule: every 30 minutes (configured in celery_app.py).

For each active scheduled_report row, determines whether it should fire
in the current window based on frequency, day, hour, and last_sent_at.
Generates the PDF and delivers via email (Resend).

WhatsApp delivery is deferred to RPT-1C — the existing whatsapp_service
document upload flow requires a lead_id/customer_id and is not suitable
for delivery to arbitrary recipient phone numbers. Any scheduled reports
configured for WhatsApp delivery are skipped with a logged warning.

Dependencies:
  resend>=2.0.0  — add to requirements.txt
  weasyprint>=61.0 — add to requirements.txt (PDF generation)

Environment variables required:
  RESEND_API_KEY      — Resend API key for email delivery
  RESEND_FROM_EMAIL   — Sender address (default: reports@opsra.io)

Pattern 48 (Rule 1): get_supabase() used directly — never get_db().
S14: per-report failures never stop the delivery loop.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from app.workers.celery_app import celery_app          # noqa: E402
from app.database import get_supabase                  # noqa: E402
from app.services.report_analytics_service import (    # noqa: E402
    get_full_report,
    generate_report_pdf,
    _resolve_period_preset,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_fire(row: dict, now: datetime) -> bool:
    """
    Determine whether a scheduled_report row should be delivered right now.

    weekly:  day_of_week == today's weekday AND current UTC hour == send_hour
             AND last_sent_at is not today
    monthly: day_of_month == today's day AND current UTC hour == send_hour
             AND last_sent_at does not fall on today's date

    Returns False on any missing/invalid config or if already sent.
    """
    try:
        freq      = row.get("frequency")
        send_hour = int(row.get("send_hour") or 8)
        today     = now.date()

        if now.hour != send_hour:
            return False

        # Guard: already sent today?
        last_sent_raw = row.get("last_sent_at")
        if last_sent_raw:
            try:
                # Slice to "YYYY-MM-DD" and compare as strings — avoids
                # datetime.fromisoformat which breaks when datetime is mocked in tests.
                if str(last_sent_raw)[:10] == today.isoformat():
                    return False
            except Exception:
                pass

        if freq == "weekly":
            dow = row.get("day_of_week")
            if dow is None:
                return False
            return today.weekday() == int(dow)

        if freq == "monthly":
            dom = row.get("day_of_month")
            if dom is None:
                return False
            return today.day == int(dom)

        return False
    except Exception as exc:
        logger.warning("_should_fire: error evaluating row %s: %s", row.get("id"), exc)
        return False


def _send_report_email(
    recipients: list[str],
    subject: str,
    body: str,
    pdf_bytes: bytes,
    filename: str,
) -> None:
    """
    Send the report PDF as an email attachment via Resend.

    Raises RuntimeError if RESEND_API_KEY is not set.
    Raises Exception on any Resend API failure — caller handles S14.
    """
    try:
        import resend as _resend
    except ImportError:
        raise RuntimeError(
            "resend package is not installed. "
            "Run: pip install resend --break-system-packages"
        )

    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY environment variable is not set. "
            "Add it to your Render environment variables."
        )

    _resend.api_key = api_key
    from_email = os.environ.get("RESEND_FROM_EMAIL", "reports@opsra.io")

    # Resend expects attachment content as base64-encoded string
    encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

    for recipient in recipients:
        try:
            _resend.Emails.send({
                "from":    from_email,
                "to":      [recipient],
                "subject": subject,
                "text":    body,
                "attachments": [
                    {
                        "filename": filename,
                        "content":  encoded_pdf,
                    }
                ],
            })
            logger.info(
                "_send_report_email: delivered to %s subject='%s'", recipient, subject
            )
        except Exception as exc:
            logger.warning(
                "_send_report_email: failed for recipient %s: %s", recipient, exc
            )
            raise


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="run_report_delivery")
def run_report_delivery() -> dict:
    """
    Celery beat task — runs every 30 minutes.

    Scans all active scheduled_reports across all orgs, determines which
    should fire in the current window, generates PDFs, and delivers via email.

    Returns:
        {
            "processed": int,  — rows evaluated
            "delivered": int,  — successfully delivered
            "failed":    int,  — delivery or generation errors
            "skipped":   int,  — not due yet or unsupported channel
        }
    """
    summary = {"processed": 0, "delivered": 0, "failed": 0, "skipped": 0}
    now = datetime.now(timezone.utc)

    db = get_supabase()

    # Fetch all active scheduled reports across all orgs
    try:
        result = (
            db.table("scheduled_reports")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]
    except Exception as exc:
        logger.error("run_report_delivery: failed to fetch scheduled_reports: %s", exc)
        return summary

    for row in rows:
        report_id = row.get("id")
        org_id    = row.get("org_id")
        label     = row.get("label") or "Management Report"
        summary["processed"] += 1

        # Check if this report should fire now
        if not _should_fire(row, now):
            summary["skipped"] += 1
            continue

        # WhatsApp delivery is not yet supported — defer to RPT-1C
        channel = row.get("delivery_channel") or "email"
        if channel == "whatsapp":
            logger.warning(
                "run_report_delivery: WhatsApp delivery deferred to RPT-1C — "
                "skipping report_id=%s org=%s", report_id, org_id
            )
            summary["skipped"] += 1
            continue

        try:
            # Resolve date range from period_preset
            preset = row.get("period_preset") or "last_30d"
            try:
                date_from, date_to = _resolve_period_preset(preset)
            except ValueError:
                logger.warning(
                    "run_report_delivery: invalid period_preset '%s' for report_id=%s — using last_30d",
                    preset, report_id,
                )
                date_from, date_to = _resolve_period_preset("last_30d")

            # Build the report
            sections  = row.get("sections") or None     # None → all sections
            team      = row.get("team_filter") or None
            rep_id    = str(row.get("rep_filter")) if row.get("rep_filter") else None

            report_data = get_full_report(
                db=db,
                org_id=org_id,
                date_from=date_from,
                date_to=date_to,
                sections=sections,
                team=team,
                rep_id=rep_id,
                compare="previous_period",
            )

            # Generate PDF
            pdf_bytes = generate_report_pdf(report_data)

            # Build email content
            period_label = (
                report_data.get("report_meta", {}).get("period_label")
                or f"{date_from} – {date_to}"
            )
            subject  = f"[Opsra] {label} — {period_label}"
            body     = f"Please find attached the {label} for {period_label}."
            filename = f"report-{date_from}_{date_to}.pdf"

            recipients = row.get("recipients") or []
            if not recipients:
                logger.warning(
                    "run_report_delivery: no recipients for report_id=%s — skipping",
                    report_id,
                )
                summary["skipped"] += 1
                continue

            # Deliver via email
            _send_report_email(
                recipients=recipients,
                subject=subject,
                body=body,
                pdf_bytes=pdf_bytes,
                filename=filename,
            )

            # Update last_sent_at on success
            try:
                db.table("scheduled_reports").update({
                    "last_sent_at": now.isoformat(),
                    "updated_at":   now.isoformat(),
                }).eq("id", report_id).execute()
            except Exception as upd_exc:
                logger.warning(
                    "run_report_delivery: failed to update last_sent_at for report_id=%s: %s",
                    report_id, upd_exc,
                )

            summary["delivered"] += 1
            logger.info(
                "run_report_delivery: delivered report_id=%s org=%s to %d recipients",
                report_id, org_id, len(recipients),
            )

        except Exception as exc:
            # S14: log and continue — never let one failure block others
            logger.error(
                "run_report_delivery: failed for report_id=%s org=%s: %s",
                report_id, org_id, exc,
            )
            summary["failed"] += 1

    logger.info("run_report_delivery complete: %s", summary)
    return summary
