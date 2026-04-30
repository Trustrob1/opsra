"""
app/workers/webhook_worker.py
------------------------------
9E-D D1 gate added:
  After org lookup, fetch full org row and check subscription_status.
  If org is suspended → write to dead_letter_webhooks and skip processing.
  "active" and "grace" orgs proceed normally.

D2/D3 not applicable — inbound webhook processing, not outbound messaging.

All other logic unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk
from pydantic import BaseModel, field_validator

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.utils.org_gates import is_org_active  # 9E-D D1

logger = logging.getLogger(__name__)


class WebhookPayload(BaseModel):
    object: str
    entry:  list = []

    @field_validator("object")
    @classmethod
    def must_be_whatsapp(cls, v: str) -> str:
        if v != "whatsapp_business_account":
            raise ValueError(f"Unexpected object type: {v}")
        return v


def _write_dead_letter(
    db,
    phone_id:  Optional[str],
    reason:    str,
    payload:   dict,
    org_id:    Optional[str] = None,
) -> None:
    try:
        db.table("dead_letter_webhooks").insert({
            "org_id":      org_id,
            "phone_id":    phone_id,
            "reason":      reason,
            "payload":     payload,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("_write_dead_letter failed reason=%s: %s", reason, exc)


def _fetch_org_row(db, org_id: str) -> Optional[dict]:
    """
    Fetch the full org row needed for D1 gate check.
    Returns None on any error — caller treats as unknown org.
    S14: never raises.
    """
    try:
        result = (
            db.table("organisations")
            .select("id, subscription_status")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        return data or None
    except Exception as exc:
        logger.warning(
            "webhook_worker: _fetch_org_row failed org=%s: %s", org_id, exc
        )
        return None


@celery_app.task(
    name="app.workers.webhook_worker.process_inbound_webhook",
    max_retries=0,
)
def process_inbound_webhook(payload: dict) -> None:
    """
    Process one Meta WhatsApp webhook payload.

    D1 gate: after org lookup, fetch org row and check subscription_status.
    Suspended orgs → dead letter. Active/grace orgs proceed normally.

    S13: validates payload envelope with WebhookPayload before processing.
    S14: any per-entry exception writes to dead_letter_webhooks + Sentry.
    """
    from app.routers.webhooks import (
        _handle_inbound_message,
        _handle_status_update,
        _handle_template_status_update,
        _lookup_org_by_phone_number_id,
    )

    db = get_supabase()

    try:
        validated = WebhookPayload(**payload)
    except Exception as exc:
        logger.warning(
            "process_inbound_webhook: invalid payload envelope — %s", exc
        )
        sentry_sdk.capture_exception(exc)
        return

    for entry in validated.entry:
        for change in (entry.get("changes") or []):
            field = change.get("field")
            value = change.get("value") or {}

            # ── Template approval/rejection events ─────────────────────────
            if field == "message_template_status_update":
                try:
                    _handle_template_status_update(db, value)
                except Exception as exc:
                    logger.warning(
                        "process_inbound_webhook: template status error: %s", exc
                    )
                continue

            if field != "messages":
                continue

            phone_number_id: str = (
                (value.get("metadata") or {}).get("phone_number_id") or ""
            )

            # ── Org lookup ─────────────────────────────────────────────────
            org_id: Optional[str] = None
            try:
                org_id = _lookup_org_by_phone_number_id(db, phone_number_id)
            except Exception as exc:
                logger.warning(
                    "process_inbound_webhook: org lookup error phone_id=%s: %s",
                    phone_number_id, exc,
                )

            if not org_id:
                logger.warning(
                    "process_inbound_webhook: org not found for phone_id=%s "
                    "— dead lettering", phone_number_id,
                )
                _write_dead_letter(db, phone_number_id, "org_not_found", payload)
                sentry_sdk.capture_message(
                    f"Webhook org not found for phone_id={phone_number_id}",
                    level="warning",
                )
                continue

            # ── D1: Subscription gate ──────────────────────────────────────
            # Fetch full org row to check subscription_status.
            # Suspended orgs → dead letter (spec D1).
            # Active/grace orgs proceed normally.
            org_row = _fetch_org_row(db, org_id)
            if org_row and not is_org_active(org_row):
                logger.info(
                    "process_inbound_webhook: org %s is suspended — "
                    "dead lettering webhook for phone_id=%s",
                    org_id, phone_number_id,
                )
                _write_dead_letter(
                    db, phone_number_id, "org_suspended", payload, org_id=org_id
                )
                continue  # S14: don't stop — try remaining changes

            contacts = value.get("contacts") or []
            contact_name: str = (
                (contacts[0].get("profile") or {}).get("name") or ""
                if contacts else ""
            )

            # ── Process inbound messages ───────────────────────────────────
            for message in (value.get("messages") or []):
                msg_id = message.get("id", "")
                try:
                    _handle_inbound_message(
                        db, message, contact_name, phone_number_id
                    )
                except Exception as exc:
                    logger.warning(
                        "process_inbound_webhook: message error msg_id=%s "
                        "org=%s: %s", msg_id, org_id, exc,
                    )
                    _write_dead_letter(
                        db, phone_number_id, "processing_error", payload,
                        org_id=org_id,
                    )
                    sentry_sdk.capture_exception(exc)

            # ── Process delivery/read status updates ───────────────────────
            for status_upd in (value.get("statuses") or []):
                try:
                    _handle_status_update(db, status_upd)
                except Exception as exc:
                    logger.warning(
                        "process_inbound_webhook: status update error "
                        "org=%s: %s", org_id, exc,
                    )
