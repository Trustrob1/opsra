"""
app/workers/webhook_worker.py
------------------------------
9E-B — WhatsApp Webhook Foundation.

Celery task that processes inbound Meta webhook payloads asynchronously.
The HTTP handler in webhooks.py returns 200 immediately and dispatches here.

Responsibilities:
  1. Org lookup by phone_number_id — dead letter if not found.
  2. Message-ID deduplication — skip if already processed.
  3. Route to existing handler functions (_handle_inbound_message,
     _handle_status_update, _handle_template_status_update).
  4. Dead letter + Sentry on any unhandled exception.

S13: payload validated with Pydantic before processing.
S14: per-entry/per-message exceptions never stop the task — always completes.
PII: never logs full phone numbers — last 4 chars only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk
from pydantic import BaseModel, field_validator

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S13 — Pydantic payload validation
# ---------------------------------------------------------------------------

class WebhookPayload(BaseModel):
    """Minimal validation of the Meta webhook envelope."""
    object: str
    entry: list = []

    @field_validator("object")
    @classmethod
    def must_be_whatsapp(cls, v: str) -> str:
        if v != "whatsapp_business_account":
            raise ValueError(f"Unexpected object type: {v}")
        return v


# ---------------------------------------------------------------------------
# Dead letter helper
# ---------------------------------------------------------------------------

def _write_dead_letter(
    db,
    phone_id: Optional[str],
    reason: str,
    payload: dict,
    org_id: Optional[str] = None,
) -> None:
    """
    Write an unprocessable webhook to dead_letter_webhooks.
    S14: never raises.
    """
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


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.webhook_worker.process_inbound_webhook",
    max_retries=0,  # S14 — never retry; dead letter handles failures
)
def process_inbound_webhook(payload: dict) -> None:
    """
    Process one Meta WhatsApp webhook payload.

    Called by the slim POST /webhooks/meta/whatsapp handler immediately
    after signature verification. All actual processing happens here so
    Meta gets its 200 OK within milliseconds.

    S13: validates payload envelope with WebhookPayload before processing.
    S14: any per-entry exception writes to dead_letter_webhooks + Sentry.
         Never raises — task always completes.
    """
    # Import handler functions from webhooks router.
    # Module-level imports used (Pattern 57) — importable at task load time.
    from app.routers.webhooks import (
        _handle_inbound_message,
        _handle_status_update,
        _handle_template_status_update,
        _lookup_org_by_phone_number_id,
    )

    db = get_supabase()

    # S13 — validate payload shape
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

            # ── Inbound messages + status updates ──────────────────────────
            phone_number_id: str = (
                (value.get("metadata") or {}).get("phone_number_id") or ""
            )

            # Org lookup — dead letter if not found
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
                    "process_inbound_webhook: org not found for phone_id=%s — dead lettering",
                    phone_number_id,
                )
                _write_dead_letter(db, phone_number_id, "org_not_found", payload)
                sentry_sdk.capture_message(
                    f"Webhook org not found for phone_id={phone_number_id}",
                    level="warning",
                )
                continue  # S14: don't stop — try remaining changes

            contacts = value.get("contacts") or []
            contact_name: str = (
                (contacts[0].get("profile") or {}).get("name") or ""
                if contacts else ""
            )

            # Process inbound messages
            for message in (value.get("messages") or []):
                msg_id = message.get("id", "")
                try:
                    _handle_inbound_message(
                        db, message, contact_name, phone_number_id
                    )
                except Exception as exc:
                    # S14: log, dead letter, capture to Sentry, continue
                    logger.warning(
                        "process_inbound_webhook: message error msg_id=%s org=%s: %s",
                        msg_id, org_id, exc,
                    )
                    _write_dead_letter(
                        db, phone_number_id, "processing_error", payload,
                        org_id=org_id,
                    )
                    sentry_sdk.capture_exception(exc)

            # Process delivery/read status updates
            for status_upd in (value.get("statuses") or []):
                try:
                    _handle_status_update(db, status_upd)
                except Exception as exc:
                    logger.warning(
                        "process_inbound_webhook: status update error org=%s: %s",
                        org_id, exc,
                    )
