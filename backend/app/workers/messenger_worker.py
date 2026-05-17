"""
app/workers/messenger_worker.py
---------------------------------
UNIFIED-INBOX-1B — Facebook Messenger inbound webhook processor.

Celery task: process_messenger_webhook
  - Dispatched by POST /webhooks/messenger immediately after signature verify
  - Processes messaging events from Meta's Messenger webhook payload
  - Auto-creates leads for new senders (messenger_psid stored on leads table)
  - Saves inbound message to whatsapp_messages (channel='messenger')
  - Notifies the assigned rep (owner fallback)
  - Dead-letter handler: unprocessable payloads written to dead_letter_webhooks

Pattern 48: uses get_supabase() directly, not get_db()
Pattern 57: all imports at MODULE LEVEL so patch() works in tests
S13: Celery payload validated with Pydantic
S14: per-message failure never stops the loop; top-level except catches all

Instagram worker (instagram_worker.py) is the reference implementation
for this file's structure.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel, ValidationError

from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.services.messenger_service import get_org_by_messenger_page_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S13 — Pydantic payload validator
# ---------------------------------------------------------------------------

class MessengerWebhookPayload(BaseModel):
    object: str
    entry: list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_messenger_profile(psid: str, access_token: str) -> dict:
    """
    Fetch the user's first/last name from the Graph API.
    Returns {"first_name": ..., "last_name": ...} or {} on failure.
    S14: never raises.
    """
    try:
        import httpx
        url = f"https://graph.facebook.com/v18.0/{psid}"
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                url,
                params={
                    "fields": "first_name,last_name",
                    "access_token": access_token,
                },
            )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:
        logger.warning(
            "_fetch_messenger_profile failed psid=%s: %s", psid, exc
        )
    return {}


def _write_dead_letter(db, payload: dict, reason: str) -> None:
    """Write an unprocessable payload to dead_letter_webhooks. S14."""
    try:
        import json
        db.table("dead_letter_webhooks").insert({
            "source":     "messenger",
            "payload":    json.dumps(payload)[:10000],
            "reason":     reason[:500],
            "created_at": _now_iso(),
        }).execute()
    except Exception as exc:
        logger.warning("_write_dead_letter failed: %s", exc)


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_messaging_event(db, org_id: str, messaging: dict) -> None:
    """
    Process a single messaging event from the Messenger webhook.

    Handles:
      - text messages
      - attachments (image, video, audio, file) — stored as [(media)]
      - read / echo / delivery receipts — silently skipped

    S14: entire function wrapped at the task level.
    """
    sender  = messaging.get("sender") or {}
    psid    = sender.get("id", "")

    # Skip echo (messages we sent) and non-message events
    if messaging.get("read") or messaging.get("delivery"):
        return
    if not messaging.get("message"):
        return
    message_obj = messaging["message"]
    if message_obj.get("is_echo"):
        return

    msg_id = message_obj.get("mid", "")

    # ── Deduplication ─────────────────────────────────────────────────────
    if msg_id:
        try:
            dedup = (
                db.table("whatsapp_messages")
                .select("id")
                .eq("meta_message_id", msg_id)
                .limit(1)
                .execute()
            )
            if dedup.data:
                logger.info(
                    "messenger_worker: duplicate mid=%s — skipping", msg_id
                )
                return
        except Exception as exc:
            logger.warning(
                "messenger_worker: dedup check failed mid=%s — proceeding: %s",
                msg_id, exc,
            )

    # ── Parse message content ──────────────────────────────────────────────
    content: Optional[str] = None
    msg_type = "text"

    text_obj = message_obj.get("text")
    if text_obj:
        content = text_obj
    elif message_obj.get("attachments"):
        attachment = message_obj["attachments"][0]
        att_type = attachment.get("type", "file")
        type_map = {
            "image":    "[Image]",
            "video":    "[Video]",
            "audio":    "[Voice note]",
            "file":     "[Document]",
            "location": "[Location]",
        }
        content = type_map.get(att_type, f"[{att_type}]")
        msg_type = att_type if att_type in ("image", "video", "audio") else "document"
    else:
        content = "[Unsupported message type]"

    logger.info(
        "messenger_worker: org=%s psid=%s msg_type=%s content=%r",
        org_id, psid, msg_type, content,
    )

    now_ts = _now_iso()
    window_expires = (
        datetime.now(timezone.utc) + timedelta(hours=24)
    ).isoformat()

    # ── Find or create lead by messenger_psid ─────────────────────────────
    lead_id: Optional[str] = None
    assigned_to: Optional[str] = None
    lead_name: Optional[str] = None

    try:
        lead_result = (
            db.table("leads")
            .select("id, full_name, assigned_to")
            .eq("org_id", org_id)
            .eq("messenger_psid", psid)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        rows = lead_result.data if isinstance(lead_result.data, list) else []
        if rows:
            lead_id     = rows[0]["id"]
            assigned_to = rows[0].get("assigned_to")
            lead_name   = rows[0].get("full_name")
    except Exception as exc:
        logger.warning(
            "messenger_worker: lead lookup failed org=%s psid=%s: %s",
            org_id, psid, exc,
        )

    if not lead_id:
        # New contact — fetch profile from Graph API then create a lead
        from app.services.messenger_service import _get_org_messenger_credentials
        from app.models.leads import LeadCreate, LeadSource
        from app.services import lead_service

        _, access_token = _get_org_messenger_credentials(db, org_id)
        profile = _fetch_messenger_profile(psid, access_token or "")
        first = (profile.get("first_name") or "").strip()
        last  = (profile.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip() or "Messenger User"
        lead_name = full_name

        try:
            new_lead = lead_service.create_lead(
                db=db,
                org_id=org_id,
                user_id=None,   # system-triggered (Pattern 64)
                payload=LeadCreate(
                    full_name=full_name,
                    source=LeadSource.facebook_dm.value,
                ),
                entry_path="messenger",
            )
            lead_id     = new_lead["id"]
            assigned_to = new_lead.get("assigned_to")

            # Store PSID on lead so future messages match
            db.table("leads").update(
                {"messenger_psid": psid}
            ).eq("id", lead_id).execute()

            logger.info(
                "messenger_worker: created lead %s for psid=%s org=%s",
                lead_id, psid, org_id,
            )
        except Exception as exc:
            logger.error(
                "messenger_worker: lead creation failed org=%s psid=%s: %s",
                org_id, psid, exc,
            )
            return

    # ── Save inbound message to whatsapp_messages ──────────────────────────
    row: dict = {
        "org_id":            org_id,
        "lead_id":           lead_id,
        "direction":         "inbound",
        "message_type":      msg_type,
        "channel":           "messenger",
        "content":           content,
        "status":            "delivered",
        "meta_message_id":   msg_id or None,
        "window_open":       True,
        "window_expires_at": window_expires,
        "sent_by":           None,
        "created_at":        now_ts,
    }

    try:
        db.table("whatsapp_messages").insert(row).execute()
    except Exception as exc:
        logger.error(
            "messenger_worker: failed to save message org=%s lead=%s: %s",
            org_id, lead_id, exc,
        )
        return

    # ── Notify assigned rep (owner fallback) ──────────────────────────────
    notify_user_id = assigned_to
    if not notify_user_id:
        try:
            users_r = (
                db.table("users")
                .select("id, roles(template)")
                .eq("org_id", org_id)
                .execute()
            )
            for u in (users_r.data or []):
                if (u.get("roles") or {}).get("template", "").lower() == "owner":
                    notify_user_id = u["id"]
                    break
        except Exception as exc:
            logger.warning(
                "messenger_worker: owner lookup failed org=%s: %s", org_id, exc
            )

    if notify_user_id:
        try:
            display_name = lead_name or f"Messenger:{psid[:8]}"
            is_new = assigned_to is None  # if no assigned_to, lead was just created
            db.table("notifications").insert({
                "org_id":        org_id,
                "user_id":       notify_user_id,
                "type":          "whatsapp_new_lead" if is_new else "whatsapp_reply",
                "title":         (
                    f"New lead via Messenger: {display_name}"
                    if is_new else
                    f"New Messenger reply from {display_name}"
                ),
                "body":          content or f"[{msg_type}]",
                "resource_type": "lead",
                "resource_id":   lead_id,
                "is_read":       False,
                "created_at":    now_ts,
            }).execute()
        except Exception as exc:
            logger.warning(
                "messenger_worker: notification failed lead=%s: %s",
                lead_id, exc,
            )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.messenger_worker.process_messenger_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_messenger_webhook(self, payload: dict) -> dict:
    """
    Process a Facebook Messenger webhook payload dispatched by the webhook route.

    Iterates over all entries and messaging events.
    S14: per-org and per-message failures are isolated — one failure never
         stops processing of other events in the same payload.

    Returns a summary dict { processed: int, skipped: int, failed: int }.
    """
    db = get_supabase()
    processed = 0
    skipped   = 0
    failed    = 0

    try:
        # S13: validate payload structure
        try:
            validated = MessengerWebhookPayload(**payload)
        except ValidationError as exc:
            logger.warning(
                "process_messenger_webhook: invalid payload — %s", exc
            )
            _write_dead_letter(db, payload, f"ValidationError: {exc}")
            return {"processed": 0, "skipped": 0, "failed": 1}

        if validated.object != "page":
            logger.info(
                "process_messenger_webhook: object=%s — skipping (not a page event)",
                validated.object,
            )
            return {"processed": 0, "skipped": 1, "failed": 0}

        for entry in validated.entry:
            page_id = str(entry.get("id", ""))

            # Resolve org from Facebook Page ID
            org_id = get_org_by_messenger_page_id(db, page_id)
            if not org_id:
                logger.info(
                    "process_messenger_webhook: no org for page_id=%s — skipping",
                    page_id,
                )
                skipped += 1
                continue

            for messaging in (entry.get("messaging") or []):
                try:
                    _process_messaging_event(db, org_id, messaging)
                    processed += 1
                except Exception as exc:
                    logger.error(
                        "process_messenger_webhook: event failed org=%s: %s",
                        org_id, exc,
                    )
                    failed += 1

    except Exception as exc:
        logger.error(
            "process_messenger_webhook: top-level error — %s", exc
        )
        failed += 1

    logger.info(
        "process_messenger_webhook: done processed=%d skipped=%d failed=%d",
        processed, skipped, failed,
    )
    return {"processed": processed, "skipped": skipped, "failed": failed}
