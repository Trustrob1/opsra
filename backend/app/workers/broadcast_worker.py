"""
app/workers/broadcast_worker.py
--------------------------------
9E-D gates added:
  D1: is_org_active() — fetch org row per broadcast, skip suspended/read_only orgs.
  D2: is_quiet_hours() — hold message (send_after, quiet_hours_held=true).
  D3: has_exceeded_daily_limit() — skip customer if daily cap reached.

All other logic unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.whatsapp_service import (
    _get_org_wa_credentials,
    _call_meta_send,
    _build_template_components,
)
from app.utils.org_gates import (
    is_org_active,
    is_quiet_hours,
    get_quiet_hours_end_utc,
    get_daily_customer_limit,
    has_exceeded_daily_limit,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _normalise(data) -> Optional[dict]:
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _matches_segment_filter(customer: dict, segment_filter: dict) -> bool:
    if not segment_filter:
        return True
    if "business_type" in segment_filter:
        if (customer.get("business_type") or "").lower() != segment_filter["business_type"].lower():
            return False
    if "churn_risk" in segment_filter:
        if (customer.get("churn_risk") or "").lower() != segment_filter["churn_risk"].lower():
            return False
    if "onboarding_complete" in segment_filter:
        if customer.get("onboarding_complete") != segment_filter["onboarding_complete"]:
            return False
    return True


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_broadcast_dispatcher(self):
    """
    Every 5 minutes — dispatch all due broadcasts.
    D1/D2/D3 gates applied per broadcast and per customer.
    """
    logger.info("broadcast_worker: run_broadcast_dispatcher starting.")
    db = get_supabase()
    now     = _now_dt()
    now_iso = now.isoformat()
    total_sent    = 0
    total_skipped = 0

    try:
        # ── C5: Atomic claim ──────────────────────────────────────────────
        claim_result = (
            db.table("broadcasts")
            .update({"processing_at": now_iso})
            .in_("status", ["scheduled", "sending"])
            .lte("scheduled_at", now_iso)
            .is_("processing_at", "null")
            .execute()
        )
        due_broadcasts = claim_result.data or []

        if not due_broadcasts:
            logger.info("broadcast_worker: no broadcasts to process — exiting.")
            return {"sent": 0, "skipped": 0}

        logger.info(
            "broadcast_worker: claimed %d broadcast(s) to process.",
            len(due_broadcasts),
        )

        for broadcast in due_broadcasts:
            broadcast_id:   str           = broadcast["id"]
            org_id:         str           = broadcast["org_id"]
            template_id:    Optional[str] = broadcast.get("template_id")
            segment_filter: dict          = broadcast.get("segment_filter") or {}

            try:
                # ── Fetch org row for gate checks ─────────────────────────
                org_result = (
                    db.table("organisations")
                    .select(
                        "id, subscription_status, quiet_hours_start, "
                        "quiet_hours_end, timezone, daily_customer_message_limit"
                    )
                    .eq("id", org_id)
                    .maybe_single()
                    .execute()
                )
                org_row = org_result.data
                if isinstance(org_row, list):
                    org_row = org_row[0] if org_row else None
                org_row = org_row or {}

                # ── D1: Subscription gate ─────────────────────────────────
                if not is_org_active(org_row):
                    logger.info(
                        "broadcast_worker: org %s skipped — subscription_status=%s",
                        org_id, org_row.get("subscription_status"),
                    )
                    _set_broadcast_status(db, broadcast_id, "scheduled")
                    total_skipped += 1
                    continue

                daily_limit = get_daily_customer_limit(org_row)

                # ── Mark as sending ───────────────────────────────────────
                db.table("broadcasts").update({
                    "status": "sending",
                }).eq("id", broadcast_id).eq("org_id", org_id).execute()

                # ── Verify template is approved ───────────────────────────
                if not template_id:
                    logger.warning(
                        "broadcast_worker: broadcast %s has no template_id "
                        "— marking cancelled", broadcast_id,
                    )
                    _set_broadcast_status(db, broadcast_id, "cancelled")
                    continue

                template = _normalise(
                    db.table("whatsapp_templates")
                    .select("name, meta_status")
                    .eq("id", template_id)
                    .eq("org_id", org_id)
                    .execute()
                    .data
                )
                if not template or template.get("meta_status") != "approved":
                    logger.warning(
                        "broadcast_worker: template %s not approved for "
                        "broadcast %s — marking cancelled",
                        template_id, broadcast_id,
                    )
                    _set_broadcast_status(db, broadcast_id, "cancelled")
                    continue

                template_name: str = template["name"]

                # ── Resolve org credentials ───────────────────────────────
                phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
                if not phone_id or not access_token:
                    logger.warning(
                        "broadcast_worker: org %s has no WhatsApp credentials "
                        "— rescheduling broadcast %s", org_id, broadcast_id,
                    )
                    _set_broadcast_status(db, broadcast_id, "scheduled")
                    continue

                # ── Fetch active opted-in customers ───────────────────────
                customers = (
                    db.table("customers")
                    .select(
                        "id, full_name, whatsapp, phone, business_type, "
                        "churn_risk, onboarding_complete, "
                        "whatsapp_opt_in, whatsapp_opt_out_broadcasts"
                    )
                    .eq("org_id", org_id)
                    .eq("whatsapp_opt_in", True)
                    .eq("whatsapp_opt_out_broadcasts", False)
                    .is_("deleted_at", "null")
                    .execute()
                    .data or []
                )

                recipients = [
                    c for c in customers
                    if _matches_segment_filter(c, segment_filter)
                ]

                recipient_count = len(recipients)
                sent_count      = 0
                window_expires  = (
                    _now_dt() + timedelta(hours=24)
                ).isoformat()

                for customer in recipients:
                    to_number = customer.get("whatsapp") or customer.get("phone")
                    if not to_number:
                        total_skipped += 1
                        continue

                    # ── D3: Daily customer message limit ──────────────────
                    if has_exceeded_daily_limit(
                        db, org_id, customer["id"], daily_limit
                    ):
                        logger.info(
                            "broadcast_worker: customer %s skipped — "
                            "daily limit %d reached",
                            customer["id"], daily_limit,
                        )
                        total_skipped += 1
                        continue

                    # ── D2: Quiet hours — hold message ────────────────────
                    if is_quiet_hours(org_row, now):
                        send_after = get_quiet_hours_end_utc(org_row, now)
                        try:
                            db.table("whatsapp_messages").insert({
                                "org_id":           org_id,
                                "customer_id":      customer["id"],
                                "direction":        "outbound",
                                "message_type":     "template",
                                "template_name":    template_name,
                                "status":           "queued",
                                "send_after":       send_after.isoformat(),
                                "quiet_hours_held": True,
                                "sent_by":          None,
                                "created_at":       _now_iso(),
                            }).execute()
                            sent_count    += 1
                            total_sent    += 1
                        except Exception as hold_exc:
                            logger.warning(
                                "broadcast_worker: failed to hold message for "
                                "customer %s: %s", customer["id"], hold_exc,
                            )
                            total_skipped += 1
                        continue

                    # ── Build template payload ────────────────────────────
                    components = _build_template_components(
                        variables=None,
                        recipient_name=customer.get("full_name"),
                    )
                    template_dict: dict = {
                        "name": template_name,
                        "language": {"code": "en"},
                    }
                    if components:
                        template_dict["components"] = components

                    meta_payload = {
                        "messaging_product": "whatsapp",
                        "to": to_number,
                        "type": "template",
                        "template": template_dict,
                    }

                    # ── Send via Meta ─────────────────────────────────────
                    meta_message_id: Optional[str] = None
                    try:
                        meta_resp = _call_meta_send(
                            phone_id, meta_payload, token=access_token
                        )
                        msgs = meta_resp.get("messages")
                        if isinstance(msgs, list) and msgs:
                            meta_message_id = msgs[0].get("id")
                        sent_count    += 1
                        total_sent    += 1
                    except Exception as send_exc:
                        logger.warning(
                            "broadcast_worker: Meta send failed for customer "
                            "%s in broadcast %s: %s",
                            customer["id"], broadcast_id, send_exc,
                        )
                        total_skipped += 1
                        continue

                    # ── Log to whatsapp_messages ──────────────────────────
                    try:
                        db.table("whatsapp_messages").insert({
                            "org_id":            org_id,
                            "customer_id":       customer["id"],
                            "direction":         "outbound",
                            "message_type":      "template",
                            "template_name":     template_name,
                            "status":            "sent",
                            "meta_message_id":   meta_message_id,
                            "window_open":       True,
                            "window_expires_at": window_expires,
                            "sent_by":           None,
                            "created_at":        _now_iso(),
                        }).execute()
                    except Exception as log_exc:
                        logger.warning(
                            "broadcast_worker: failed to log whatsapp_message "
                            "for customer %s broadcast %s: %s",
                            customer["id"], broadcast_id, log_exc,
                        )

                # ── Mark broadcast as sent ────────────────────────────────
                db.table("broadcasts").update({
                    "status":          "sent",
                    "sent_at":         _now_iso(),
                    "recipient_count": recipient_count,
                    "delivered_count": sent_count,
                }).eq("id", broadcast_id).eq("org_id", org_id).execute()

                logger.info(
                    "broadcast_worker: broadcast %s sent to %d/%d recipients",
                    broadcast_id, sent_count, recipient_count,
                )

            except Exception as exc:
                logger.warning(
                    "broadcast_worker: broadcast %s failed — %s",
                    broadcast_id, exc,
                )
                _set_broadcast_status(db, broadcast_id, "scheduled")

        logger.info(
            "broadcast_worker: done. Sent: %d, Skipped: %d.",
            total_sent, total_skipped,
        )
        return {"sent": total_sent, "skipped": total_skipped}

    except Exception as exc:
        logger.error("broadcast_worker: fatal — %s", exc)
        raise self.retry(exc=exc, countdown=60)


def _set_broadcast_status(db, broadcast_id: str, status: str) -> None:
    try:
        db.table("broadcasts").update(
            {"status": status}
        ).eq("id", broadcast_id).execute()
    except Exception as exc:
        logger.warning(
            "broadcast_worker: failed to set status=%s for broadcast %s — %s",
            status, broadcast_id, exc,
        )
