"""
app/workers/owner_report_worker.py
------------------------------------
RPT-DAILY: Daily owner WhatsApp morning brief.

Runs every morning 07:30 WAT (06:30 UTC).

On Mondays, the weekly growth section from growth_insights_service is
appended to the message, absorbing the now-retired weekly_growth_digest
beat entry (growth_insights_worker.run_weekly_growth_digest).

9E-D gates:
  D1: is_org_active() — top of per-org loop.
  D2: is_quiet_hours() — before each WhatsApp send. Skip rather than
      retry — the brief is time-sensitive and stale by the next day.
  D3: not applicable — sends to staff users (owner), not customers.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from app.database import get_supabase
from app.services.performance_service import get_daily_brief
from app.services.whatsapp_service import _get_org_wa_credentials
from app.utils.org_gates import is_org_active, is_quiet_hours
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_FRONTEND_URL = os.getenv("FRONTEND_URL", "https://opsra-frontend.onrender.com")
_API_BASE_URL  = os.getenv("RENDER_EXTERNAL_URL", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ngn(value) -> str:
    """Format a number as a compact Naira string."""
    try:
        v = float(value or 0)
        if v >= 1_000_000:
            return f"\u20a6{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"\u20a6{v / 1_000:.0f}K"
        return f"\u20a6{v:,.0f}"
    except (TypeError, ValueError):
        return "\u20a6\u2014"


def _build_message(
    brief: dict,
    brief_date: date,
    dashboard_url: str,
    weekly_section: str | None = None,
    pdf_url: str | None = None,
) -> str:
    """
    Format the WhatsApp message body from the daily brief dict.
    Uses WhatsApp bold (*text*) for headers — no markdown beyond that.
    """
    rev    = brief.get("revenue") or {}
    pipe   = brief.get("pipeline") or {}
    issues = brief.get("attention_issues") or []

    mtd        = rev.get("revenue_mtd") or 0
    target_pct = rev.get("target_pct")
    convs      = rev.get("total_conversions") or 0
    cr         = rev.get("conversion_rate") or 0
    leads      = (
        pipe.get("this_week")
        or pipe.get("leads_this_week")
        or pipe.get("total_leads")
        or 0
    )
    n_issues = len(issues)

    target_str = f" ({target_pct:.0f}% of target)" if target_pct is not None else ""

    lines = [
        f"*Daily Brief \u2014 {brief_date.strftime('%d %b %Y')}*\n",
        f"Revenue MTD: {_fmt_ngn(mtd)}{target_str}",
        f"New leads (week): {leads}",
        f"Conversions: {convs} ({cr:.1f}% CR)",
    ]

    if n_issues:
        lines.append(
            f"\u26a0 {n_issues} item{'s' if n_issues != 1 else ''} "
            f"need{'s' if n_issues == 1 else ''} your attention"
        )

    if weekly_section:
        lines.append(f"\n*Weekly Growth Summary*\n{weekly_section}")

    if pdf_url:
        lines.append(f"\n\U0001f4c4 Activity log \u2192 {pdf_url}")
    lines.append(f"\U0001f4ca Full brief \u2192 {dashboard_url}")

    return "\n".join(lines)


def _send_owner_whatsapp(db, org_id: str, to: str, text: str) -> None:
    """
    Send a plain-text WhatsApp message directly to a staff user (owner).

    Uses _get_org_wa_credentials for the per-org token (multi-org safe,
    no META_WHATSAPP_TOKEN env-var fallback per I0 in whatsapp_service.py).
    Makes the HTTP call directly with httpx rather than _call_meta_send,
    to avoid HTTPException propagating into the Celery worker context.
    """
    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
    if not phone_id or not access_token:
        logger.warning(
            "owner_report_worker: no WA credentials for org %s — skipping send",
            org_id,
        )
        return

    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type":  "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to":   to,
                "type": "text",
                "text": {"body": text},
            },
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Meta API {resp.status_code}: {resp.text[:200]}"
        )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.owner_report_worker.run_owner_daily_report",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def run_owner_daily_report(self):
    """
    Every morning 07:30 WAT (06:30 UTC) — sends each org's owner a
    WhatsApp message with a brief summary of yesterday's activity and
    a link to the full Owner Dashboard.

    On Mondays: the weekly growth section is appended, absorbing the
    retired weekly_growth_digest beat entry.

    Per-org failures are isolated and logged; they do not abort the loop.
    """
    logger.info("owner_report_worker: run_owner_daily_report starting.")
    db        = get_supabase()
    now       = datetime.now(timezone.utc)
    yesterday = now.date() - timedelta(days=1)
    is_monday = now.weekday() == 0  # UTC Monday — close enough for WAT offset
    sent      = 0

    try:
        orgs = (
            db.table("organisations")
            .select(
                "id, subscription_status, owner_dashboard_token, "
                "whatsapp_phone_id, quiet_hours_start, quiet_hours_end, timezone"
            )
            .eq("is_live", True)
            .execute()
            .data or []
        )
    except Exception as exc:
        logger.error("owner_report_worker: failed to fetch orgs — %s", exc)
        raise self.retry(exc=exc, countdown=120)

    for org_row in orgs:
        org_id: str = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            logger.info(
                "owner_report_worker: org %s skipped — subscription_status=%s",
                org_id, org_row.get("subscription_status"),
            )
            continue

        try:
            # Find active owners with a WhatsApp number on record
            users = (
                db.table("users")
                .select("id, whatsapp_number, roles(template)")
                .eq("org_id", org_id)
                .eq("is_active", True)
                .execute()
                .data or []
            )
            targets = [
                u for u in users
                if (u.get("roles") or {}).get("template") == "owner"
                and u.get("whatsapp_number")
            ]
            if not targets:
                continue

            # Build yesterday's brief (async → sync bridge)
            try:
                brief = asyncio.run(
                    get_daily_brief(db, org_id, brief_date=yesterday)
                )
            except Exception as exc:
                logger.warning(
                    "owner_report_worker: get_daily_brief failed for org %s — %s",
                    org_id, exc,
                )
                continue

            # Build the Owner Dashboard deep-link — skip org if dashboard
            # hasn't been set up yet (no token means no useful link to send)
            dash_token = org_row.get("owner_dashboard_token") or ""
            if not dash_token:
                logger.info(
                    "owner_report_worker: org %s skipped — no owner_dashboard_token",
                    org_id,
                )
                continue
            dashboard_url = f"{_FRONTEND_URL}/owner-dashboard/{dash_token}"

            # On Mondays: fetch weekly growth section to append
            weekly_section: str | None = None
            if is_monday:
                try:
                    from app.services.growth_insights_service import (
                        build_digest_context,
                        generate_weekly_digest,
                    )
                    ctx = build_digest_context(db, org_id)
                    weekly_section = generate_weekly_digest(ctx) or None
                except Exception as exc:
                    # Non-fatal — send the daily message without the weekly section
                    logger.warning(
                        "owner_report_worker: weekly section failed for org %s — %s. "
                        "Sending daily brief without it.",
                        org_id, exc,
                    )

            pdf_url = (
                f"{_API_BASE_URL}/api/v1/r/{dash_token}/{yesterday.isoformat()}"
            ) if _API_BASE_URL else None

            message = _build_message(brief, yesterday, dashboard_url, weekly_section, pdf_url)

            for user in targets:
                # ── D2: Quiet hours — skip (brief is time-sensitive) ──────
                if is_quiet_hours(org_row, now):
                    logger.info(
                        "owner_report_worker: skipped for user %s — "
                        "quiet hours active for org %s",
                        user["id"], org_id,
                    )
                    continue

                try:
                    _send_owner_whatsapp(
                        db, org_id, user["whatsapp_number"], message
                    )
                    sent += 1
                    logger.info(
                        "owner_report_worker: sent daily report to user %s (org %s)",
                        user["id"], org_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "owner_report_worker: WA send failed for user %s org %s — %s",
                        user["id"], org_id, exc,
                    )

            # Audit log — no LLM cost for this task (no Haiku call)
            try:
                db.table("claude_usage_log").insert({
                    "org_id":             org_id,
                    "user_id":            None,
                    "action_type":        "owner_daily_report",
                    "model":              "none",
                    "input_tokens":       0,
                    "output_tokens":      0,
                    "estimated_cost_usd": 0,
                }).execute()
            except Exception:
                pass  # Non-fatal — don't abort the loop for a log failure

        except Exception as exc:
            logger.error(
                "owner_report_worker: failed for org %s — %s", org_id, exc
            )

    logger.info(
        "owner_report_worker: run_owner_daily_report done. Sent %d reports.", sent
    )
    return {"sent": sent}