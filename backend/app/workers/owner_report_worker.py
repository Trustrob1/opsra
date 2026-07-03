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
  D2: deliberately NOT applied. Quiet hours exist to stop customer-facing
      messages at antisocial hours; this is the owner's own operational
      brief, scheduled at 07:30 WAT — which falls inside the typical
      20:00-08:00 customer quiet-hours window. Applying D2 here would
      silently skip the send every single morning.
  D3: not applicable — sends to staff users (owner), not customers.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.database import get_supabase
from app.services.performance_service import get_daily_brief
from app.services.whatsapp_service import _get_org_wa_credentials
from app.utils.org_gates import is_org_active
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_FRONTEND_URL = os.getenv("FRONTEND_URL", "https://opsra-frontend.onrender.com")
_API_BASE_URL  = os.getenv("API_BASE_URL", "")

# Nigeria has no DST — fixed UTC+1 year-round. Used for "yesterday" / "is
# Monday" so the report reflects the owner's local calendar day regardless
# of which exact UTC moment the beat schedule fires at.
_LAGOS_TZ = ZoneInfo("Africa/Lagos")

# Must match the approved template name exactly as shown in WhatsApp Manager.
_TEMPLATE_NAME = os.getenv("OWNER_DAILY_BRIEF_TEMPLATE_NAME", "owner_daily_brief_notification")
_META_REENGAGEMENT_ERROR_CODE = 131047


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
    rev    = brief.get("revenue_snapshot") or {}
    issues = brief.get("attention_issues") or []

    mtd        = rev.get("revenue_mtd") or 0
    target_pct = rev.get("revenue_pct")
    convs      = rev.get("total_converted") or 0
    cr         = rev.get("conversion_rate") or 0
    leads      = rev.get("total_leads") or 0
    n_issues   = len(issues)

    target_str = f" ({target_pct:.0f}% of target)" if target_pct is not None else ""

    lines = [
        f"*Daily Brief \u2014 {brief_date.strftime('%d %b %Y')}*\n",
        f"Revenue MTD: {_fmt_ngn(mtd)}{target_str}",
        f"Total leads (MTD): {leads}",
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


def _send_owner_whatsapp(
    db, org_id: str, to: str, text: str, template_params: list[str] | None = None
) -> str:
    """
    Sends the owner's daily report, preferring free text and falling back
    to the approved template only when Meta rejects the free text because
    the 24h customer service window is closed (error 131047).

    Free text first: if the owner messaged the business number within the
    last 24h, the full dynamic message — live numbers and, on Mondays,
    the weekly growth section — goes through as-is.

    Template fallback: fixed, minimal notification (date + both links) —
    Meta won't approve a template carrying the full dynamic body, so the
    owner taps through to the dashboard for the actual numbers.

    Returns "text" or "template" depending on which path succeeded.
    Raises RuntimeError if both attempts fail.
    """
    phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
    if not phone_id or not access_token:
        raise RuntimeError(f"No WA credentials for org {org_id}")

    url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"

    # ── 1. Try free text first ──────────────────────────────────────────
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
    if resp.status_code in (200, 201):
        return "text"

    # Only fall back to the template for the specific 24h-window error —
    # any other failure (bad number, auth issue) should surface as a real
    # error rather than being masked by a template send attempt.
    is_reengagement_error = False
    try:
        is_reengagement_error = (
            resp.json().get("error", {}).get("code") == _META_REENGAGEMENT_ERROR_CODE
        )
    except Exception:
        pass

    if not is_reengagement_error:
        raise RuntimeError(f"Meta API {resp.status_code}: {resp.text[:200]}")

    if not template_params:
        raise RuntimeError(
            "Free text failed (24h window closed) and no template_params provided"
        )

    # ── 2. Fall back to the approved template ───────────────────────────
    with httpx.Client(timeout=15) as client:
        resp2 = client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type":  "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to":   to,
                "type": "template",
                "template": {
                    "name": _TEMPLATE_NAME,
                    "language": {"code": "en"},
                    "components": [{
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": p} for p in template_params
                        ],
                    }],
                },
            },
        )
    if resp2.status_code not in (200, 201):
        raise RuntimeError(f"Meta API (template) {resp2.status_code}: {resp2.text[:200]}")
    return "template"


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
    now_lagos = datetime.now(_LAGOS_TZ)     # used for all date/weekday decisions
    yesterday = now_lagos.date() - timedelta(days=1)
    is_monday = now_lagos.weekday() == 0
    sent      = 0

    try:
        orgs = (
            db.table("organisations")
            .select(
                "id, subscription_status, owner_dashboard_token, "
                "org_business_contact_number, whatsapp_phone_id, "
                "quiet_hours_start, quiet_hours_end, timezone"
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
            # Owner's personal contact number lives on the org row itself,
            # not on a user record. org_whatsapp_number is a different
            # field (the Business API number used for customer-facing
            # chat) — must not be confused with this one.
            owner_number = org_row.get("org_business_contact_number") or ""
            if not owner_number:
                logger.info(
                    "owner_report_worker: org %s skipped — no org_business_contact_number",
                    org_id,
                )
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

            # Fixed, minimal content for the template fallback — date plus
            # both links, in the same order as the approved template body.
            template_params = [
                yesterday.strftime("%d %b %Y"),
                pdf_url or dashboard_url,
                dashboard_url,
            ]

            # D2 (quiet hours) intentionally not applied — see module
            # docstring. This is the owner's own brief, not a customer
            # message, and is deliberately timed for early morning.
            try:
                send_method = _send_owner_whatsapp(
                    db, org_id, owner_number, message,
                    template_params=template_params,
                )
                sent += 1
                logger.info(
                    "owner_report_worker: sent daily report for org %s via %s",
                    org_id, send_method,
                )
            except Exception as exc:
                logger.warning(
                    "owner_report_worker: WA send failed for org %s — %s",
                    org_id, exc,
                )

            # Audit log — no LLM cost for this task (no Haiku call)
            try:
                db.table("claude_usage_log").insert({
                    "org_id":             org_id,
                    "user_id":            None,
                    "action_type":        "owner_daily_report",
                    "function_name":      "run_owner_daily_report",
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