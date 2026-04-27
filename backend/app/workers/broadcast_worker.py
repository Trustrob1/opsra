"""
app/workers/broadcast_worker.py
--------------------------------
Celery task:

  run_broadcast_dispatcher  — Every 5 minutes
    Finds all broadcasts with status='sending' or status='scheduled'
    where scheduled_at <= now().
    For each broadcast:
      1. Verify template is approved.
      2. Resolve recipients from customers table using segment_filter.
      3. Send template message to each recipient via Meta Cloud API.
      4. Log each send to whatsapp_messages.
      5. Update broadcast recipient_count, status='sent', sent_at=now().

Segment filter keys supported (all optional — empty dict = send to all):
  business_type   : str   — exact match on customers.business_type
  churn_risk      : str   — exact match on customers.churn_risk
  plan_tier       : str   — exact match on subscriptions.plan_name (not yet wired)
  onboarding_complete: bool

Pause rules:
  - customers.whatsapp_opt_out_broadcasts = true  → skip (filtered at DB level)
  - customers.whatsapp_opt_in = false             → skip (filtered at DB level)
  - customers.deleted_at IS NOT NULL              → skip (filtered at DB level)
  - No whatsapp number on customer record          → skip
  - Template not approved                          → mark broadcast cancelled, skip all

S14: per-customer failure never stops the broadcast loop.
Pattern 29: load_dotenv() at module level.
Pattern 1:  get_supabase() called inside task body.
Pattern 33: Python-side filtering — no ILIKE.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # Pattern 29

from app.workers.celery_app import celery_app  # noqa: E402
from app.database import get_supabase  # noqa: E402
from app.services.whatsapp_service import (  # noqa: E402
    _get_org_wa_credentials,
    _call_meta_send,
    _build_template_components,
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
    """
    Return True if the customer matches all conditions in segment_filter.
    Empty filter matches all customers.
    Pattern 33 — Python-side filtering only, no DB-level filter expressions.
    """
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
    Sends template messages to matched customers, logs results.
    """
    logger.info("broadcast_worker: run_broadcast_dispatcher starting.")
    db = get_supabase()  # Pattern 1
    now = _now_dt()
    now_iso = now.isoformat()
    total_sent = 0
    total_skipped = 0

    try:
        # ── Fetch all orgs ────────────────────────────────────────────────
        orgs = (
            db.table("organisations")
            .select("id")
            .execute()
            .data or []
        )

        for org_row in orgs:
            org_id: str = org_row["id"]

            try:
                # ── Fetch due broadcasts for this org ─────────────────────
                all_broadcasts = (
                    db.table("broadcasts")
                    .select("*")
                    .eq("org_id", org_id)
                    .in_("status", ["sending", "scheduled"])
                    .execute()
                    .data or []
                )

                # Python-side filter: scheduled_at <= now (Pattern 33)
                due = [
                    b for b in all_broadcasts
                    if b.get("status") == "sending"
                    or (
                        b.get("status") == "scheduled"
                        and (b.get("scheduled_at") or "")[:19] <= now_iso[:19]
                    )
                ]

                for broadcast in due:
                    broadcast_id: str = broadcast["id"]
                    template_id: Optional[str] = broadcast.get("template_id")
                    segment_filter: dict = broadcast.get("segment_filter") or {}

                    try:
                        # ── Mark as sending immediately to prevent double-fire ──
                        db.table("broadcasts").update({
                            "status": "sending",
                        }).eq("id", broadcast_id).eq("org_id", org_id).execute()

                        # ── Verify template is approved ───────────────────
                        if not template_id:
                            logger.warning(
                                "broadcast_worker: broadcast %s has no template_id "
                                "— marking failed", broadcast_id,
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

                        # ── Resolve org credentials ───────────────────────
                        phone_id, access_token, _ = _get_org_wa_credentials(db, org_id)
                        if not phone_id or not access_token:
                            logger.warning(
                                "broadcast_worker: org %s has no WhatsApp credentials "
                                "— skipping broadcast %s", org_id, broadcast_id,
                            )
                            _set_broadcast_status(db, broadcast_id, "scheduled")
                            continue

                        # ── Fetch active opted-in customers ───────────────
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

                        # ── Apply segment filter (Python-side) ────────────
                        recipients = [
                            c for c in customers
                            if _matches_segment_filter(c, segment_filter)
                        ]

                        recipient_count = len(recipients)
                        sent_count = 0
                        window_expires = (
                            _now_dt() + timedelta(hours=24)
                        ).isoformat()

                        for customer in recipients:
                            to_number = customer.get("whatsapp") or customer.get("phone")
                            if not to_number:
                                total_skipped += 1
                                continue

                            # ── Build template payload with name as {{1}} ──
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

                            # ── Send via Meta ──────────────────────────────
                            meta_message_id: Optional[str] = None
                            try:
                                meta_resp = _call_meta_send(
                                    phone_id, meta_payload, token=access_token
                                )
                                msgs = meta_resp.get("messages")
                                if isinstance(msgs, list) and msgs:
                                    meta_message_id = msgs[0].get("id")
                                sent_count += 1
                                total_sent += 1
                            except Exception as send_exc:
                                logger.warning(
                                    "broadcast_worker: Meta send failed for customer "
                                    "%s in broadcast %s: %s",
                                    customer["id"], broadcast_id, send_exc,
                                )
                                total_skipped += 1
                                continue

                            # ── Log to whatsapp_messages ───────────────────
                            try:
                                db.table("whatsapp_messages").insert({
                                    "org_id": org_id,
                                    "customer_id": customer["id"],
                                    "direction": "outbound",
                                    "message_type": "template",
                                    "template_name": template_name,
                                    "status": "sent",
                                    "meta_message_id": meta_message_id,
                                    "window_open": True,
                                    "window_expires_at": window_expires,
                                    "sent_by": None,  # system / automated
                                    "created_at": _now_iso(),
                                }).execute()
                            except Exception as log_exc:
                                logger.warning(
                                    "broadcast_worker: failed to log whatsapp_message "
                                    "for customer %s broadcast %s: %s",
                                    customer["id"], broadcast_id, log_exc,
                                )

                        # ── Mark broadcast as sent ─────────────────────────
                        db.table("broadcasts").update({
                            "status": "sent",
                            "sent_at": _now_iso(),
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

            except Exception as org_exc:
                logger.error(
                    "broadcast_worker: org %s failed — %s", org_id, org_exc
                )

        logger.info(
            "broadcast_worker: done. Sent: %d, Skipped: %d.",
            total_sent, total_skipped,
        )

    except Exception as exc:
        logger.error("broadcast_worker: fatal — %s", exc)
        raise self.retry(exc=exc, countdown=60)


def _set_broadcast_status(db, broadcast_id: str, status: str) -> None:
    """Update broadcasts.status, swallowing any DB error."""
    try:
        db.table("broadcasts").update(
            {"status": status}
        ).eq("id", broadcast_id).execute()
    except Exception as exc:
        logger.warning(
            "broadcast_worker: failed to set status=%s for broadcast %s — %s",
            status, broadcast_id, exc,
        )
