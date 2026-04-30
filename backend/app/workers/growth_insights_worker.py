"""
app/workers/growth_insights_worker.py
GPM-2 — Growth AI Insights Engine

9E-D gates added:
  D1: is_org_active() — top of per-org loop in both tasks.
  D2: is_quiet_hours() — before _send_whatsapp_text in run_weekly_growth_digest.
  D3: not applicable — sends to staff users, not customers.

All other logic unchanged.
"""

import logging
from datetime import datetime, timezone

from app.database import get_supabase
from app.services.growth_insights_service import (
    build_digest_context,
    check_and_fire_anomalies,
    generate_weekly_digest,
)
from app.workers.celery_app import celery_app
from app.utils.org_gates import is_org_active, is_quiet_hours  # 9E-D

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.growth_insights_worker.run_growth_anomaly_check",
    bind=True,
    max_retries=0,
)
def run_growth_anomaly_check(self):
    """
    Daily — checks every active, live org for growth anomalies.
    D1 gate applied per org.
    """
    db = get_supabase()
    summary = {
        "orgs_checked": 0, "orgs_with_anomalies": 0,
        "alerts_fired": 0, "failed": 0,
    }

    try:
        orgs_resp = (
            db.table("organisations")
            .select("id, subscription_status")
            .eq("is_live", True)
            .execute()
        )
        orgs = orgs_resp.data or []
    except Exception as exc:
        logger.error("run_growth_anomaly_check: failed to fetch orgs: %s", exc)
        return summary

    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            logger.info(
                "growth_insights_worker: org %s skipped — subscription_status=%s",
                org_id, org_row.get("subscription_status"),
            )
            continue

        try:
            teams_resp = (
                db.table("growth_teams")
                .select("id")
                .eq("org_id", org_id)
                .eq("is_active", True)
                .execute()
            )
            if not teams_resp.data:
                continue

            fired = check_and_fire_anomalies(db, org_id)
            summary["orgs_checked"] += 1

            if fired:
                summary["orgs_with_anomalies"] += 1
                summary["alerts_fired"] += len(fired)
                _notify_growth_anomalies(db, org_id, fired)

        except Exception as exc:
            logger.warning("Anomaly check failed for org %s: %s", org_id, exc)
            summary["failed"] += 1

    logger.info("run_growth_anomaly_check complete: %s", summary)
    return summary


def _notify_growth_anomalies(db, org_id: str, anomalies: list[dict]) -> None:
    try:
        users_resp = (
            db.table("users")
            .select("id, roles(template)")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        users = users_resp.data or []
        target_user_ids = [
            u["id"] for u in users
            if (u.get("roles") or {}).get("template") in ("owner", "ops_manager")
        ]

        for anomaly in anomalies:
            for uid in target_user_ids:
                try:
                    db.table("notifications").insert({
                        "org_id":  org_id,
                        "user_id": uid,
                        "type":    "growth_anomaly",
                        "title":   anomaly.get("title", "Growth Alert"),
                        "body":    anomaly.get("detail", ""),
                        "is_read": False,
                    }).execute()
                except Exception as exc:
                    logger.warning(
                        "Notification insert failed for user %s org %s: %s",
                        uid, org_id, exc,
                    )
    except Exception as exc:
        logger.warning(
            "_notify_growth_anomalies failed for org %s: %s", org_id, exc
        )


@celery_app.task(
    name="app.workers.growth_insights_worker.run_weekly_growth_digest",
    bind=True,
    max_retries=0,
)
def run_weekly_growth_digest(self):
    """
    Every Monday morning — sends WhatsApp weekly growth digest.
    D1 gate applied per org. D2 gate applied before each WhatsApp send.
    """
    db  = get_supabase()
    now = datetime.now(timezone.utc)
    summary = {
        "orgs_processed": 0,
        "digests_sent":   0,
        "orgs_skipped":   0,
        "failed":         0,
    }

    try:
        orgs_resp = (
            db.table("organisations")
            .select(
                "id, whatsapp_phone_id, subscription_status, "
                "quiet_hours_start, quiet_hours_end, timezone"
            )
            .eq("is_live", True)
            .execute()
        )
        orgs = orgs_resp.data or []
    except Exception as exc:
        logger.error("run_weekly_growth_digest: failed to fetch orgs: %s", exc)
        return summary

    for org_row in orgs:
        org_id = org_row["id"]

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            logger.info(
                "growth_insights_worker: org %s skipped — subscription_status=%s",
                org_id, org_row.get("subscription_status"),
            )
            summary["orgs_skipped"] += 1
            continue

        try:
            from datetime import timedelta
            today    = datetime.now(timezone.utc).date()
            week_ago = (today - timedelta(days=7)).isoformat()
            leads_resp = (
                db.table("leads")
                .select("id", count="exact")
                .eq("org_id", org_id)
                .gte("created_at", week_ago)
                .is_("deleted_at", None)
                .execute()
            )
            lead_count = leads_resp.count or 0
            if lead_count == 0:
                summary["orgs_skipped"] += 1
                continue

            digest_context = build_digest_context(db, org_id)
            message        = generate_weekly_digest(digest_context)
            if not message:
                summary["orgs_skipped"] += 1
                continue

            users_resp = (
                db.table("users")
                .select("id, whatsapp_number, roles(template)")
                .eq("org_id", org_id)
                .eq("is_active", True)
                .execute()
            )
            users   = users_resp.data or []
            targets = [
                u for u in users
                if (u.get("roles") or {}).get("template") in ("owner", "ops_manager")
                and u.get("whatsapp_number")
            ]

            sent = 0
            for user in targets:
                # ── D2: Quiet hours — skip send (staff digest, retry next week)
                if is_quiet_hours(org_row, now):
                    logger.info(
                        "growth_insights_worker: digest skipped for user %s "
                        "— quiet hours active for org %s",
                        user["id"], org_id,
                    )
                    continue

                try:
                    _send_whatsapp_text(
                        db,
                        org_id=org_id,
                        phone_number_id=org_row.get("whatsapp_phone_id"),
                        to=user["whatsapp_number"],
                        text=message,
                    )
                    sent += 1
                except Exception as exc:
                    logger.warning(
                        "Digest WhatsApp send failed for user %s org %s: %s",
                        user["id"], org_id, exc,
                    )

            try:
                db.table("claude_usage_log").insert({
                    "org_id":             org_id,
                    "user_id":            None,
                    "action_type":        "growth_weekly_digest",
                    "model":              "claude-haiku-4-5-20251001",
                    "input_tokens":       0,
                    "output_tokens":      0,
                    "estimated_cost_usd": 0,
                }).execute()
            except Exception:
                pass

            summary["orgs_processed"] += 1
            summary["digests_sent"]   += sent

        except Exception as exc:
            logger.warning("Weekly digest failed for org %s: %s", org_id, exc)
            summary["failed"] += 1

    logger.info("run_weekly_growth_digest complete: %s", summary)
    return summary


def _send_whatsapp_text(
    db, org_id: str, phone_number_id: str, to: str, text: str
) -> None:
    import os
    import httpx

    token = os.getenv("META_WHATSAPP_TOKEN", "")
    if not phone_number_id or not token:
        logger.warning("WhatsApp config missing for org %s", org_id)
        return

    url     = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to":                to,
        "type":              "text",
        "text":              {"body": text},
    }
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json=payload,
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Meta API {resp.status_code}: {resp.text[:200]}")
