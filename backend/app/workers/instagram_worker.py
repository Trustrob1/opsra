"""
app/workers/instagram_worker.py
UNIFIED-INBOX-1A — Instagram DM inbound processing.

Celery task: process_instagram_webhook(payload)

Triggered by POST /webhooks/instagram on every inbound Meta webhook event.
The route returns 200 immediately and dispatches this task asynchronously —
following the exact 9E-B pattern used by process_inbound_webhook.

Processing per message:
  1. Extract sender instagram_scoped_id, page_id, message text, timestamp, message_id
  2. Look up org by instagram_page_id — dead_letter if not found
  3. D1 gate: is_org_active() — suspended orgs go to dead_letter
  4. Dedup by meta_message_id — skip if already processed (S14 fail-open on DB error)
  5. Look up lead by org_id + instagram_scoped_id
     - Found: use existing lead
     - Not found: auto-create lead via create_lead() with entry_path='instagram_dm'
  6. Insert into whatsapp_messages with channel='instagram'
  7. Update lead last_activity_at
  8. Create notification for assigned rep (or owner/ops_manager if unassigned)
  9. No qualification bot — Instagram leads are considered pre-qualified

S13: payload validated with Pydantic before processing.
S14: per-message failure never stops the loop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel

from app.database import get_supabase
from app.workers.celery_app import celery_app
from app.utils.org_gates import is_org_active

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S13 — Pydantic payload validator
# ---------------------------------------------------------------------------

class InstagramWebhookPayload(BaseModel):
    object: str = ""
    entry: list = []

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.instagram_worker.process_instagram_webhook",
    bind=True,
    max_retries=0,
)
def process_instagram_webhook(self, payload: dict) -> dict:
    """
    Process an inbound Instagram webhook event.

    Expected Meta payload shape:
    {
      "object": "instagram",
      "entry": [
        {
          "id": "<page_id>",
          "messaging": [
            {
              "sender":    {"id": "<instagram_scoped_id>"},
              "recipient": {"id": "<page_id>"},
              "timestamp": 1234567890,
              "message": {
                "mid":  "<message_id>",
                "text": "<message_text>"
              }
            }
          ]
        }
      ]
    }
    """
    summary = {"processed": 0, "skipped": 0, "failed": 0}

    # S13 — validate payload shape before touching anything
    try:
        validated = InstagramWebhookPayload(**payload)
    except Exception as exc:
        logger.warning("process_instagram_webhook: invalid payload shape — %s", exc)
        return {"processed": 0, "skipped": 0, "failed": 1, "reason": "invalid_payload"}

    if validated.object != "instagram":
        logger.info(
            "process_instagram_webhook: object=%s — not instagram, skipping",
            validated.object,
        )
        return summary

    db = get_supabase()

    for entry in (validated.entry or []):
        page_id = entry.get("id", "")

        # Look up org by instagram_page_id
        from app.services.instagram_service import lookup_org_by_instagram_page_id
        org_id = lookup_org_by_instagram_page_id(db, page_id)

        if not org_id:
            logger.info(
                "process_instagram_webhook: no org found for page_id=%s — "
                "writing to dead_letter_webhooks",
                page_id,
            )
            _dead_letter(db, payload, f"no_org_for_page_id:{page_id}")
            summary["skipped"] += 1
            continue

        # D1: subscription gate
        try:
            org_row = (
                db.table("organisations")
                .select("id, subscription_status")
                .eq("id", org_id)
                .maybe_single()
                .execute()
            )
            org_data = org_row.data
            if isinstance(org_data, list):
                org_data = org_data[0] if org_data else None
            org_data = org_data or {}
        except Exception as exc:
            logger.warning(
                "process_instagram_webhook: org fetch failed org=%s: %s", org_id, exc
            )
            summary["failed"] += 1
            continue

        if not is_org_active(org_data):
            logger.info(
                "process_instagram_webhook: org %s skipped — "
                "subscription_status=%s",
                org_id, org_data.get("subscription_status"),
            )
            _dead_letter(db, payload, f"org_suspended:{org_id}")
            summary["skipped"] += 1
            continue

        # Process each messaging event
        for messaging_event in (entry.get("messaging") or []):
            try:
                _process_single_message(db, org_id, messaging_event)
                summary["processed"] += 1
            except Exception as exc:
                # S14: one message failure never stops the loop
                logger.warning(
                    "process_instagram_webhook: message processing failed "
                    "org=%s: %s",
                    org_id, exc,
                )
                summary["failed"] += 1

    logger.info("process_instagram_webhook complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Single message processor
# ---------------------------------------------------------------------------

def _process_single_message(db, org_id: str, messaging_event: dict) -> None:
    """
    Process one Instagram messaging event.
    Raises on unrecoverable errors — caller's S14 handles them.
    """
    sender      = messaging_event.get("sender") or {}
    message     = messaging_event.get("message") or {}
    timestamp   = messaging_event.get("timestamp")

    instagram_scoped_id = sender.get("id", "")
    message_id          = message.get("mid", "")
    text                = message.get("text") or ""

    if not instagram_scoped_id:
        logger.info(
            "_process_single_message: no sender id in event org=%s — skipping",
            org_id,
        )
        return

    # Skip echo events (messages sent by the page itself)
    if messaging_event.get("sender", {}).get("id") == messaging_event.get("recipient", {}).get("id"):
        return

    # Skip delivery/read receipts — only process actual messages
    if not message or (not text and not message.get("attachments")):
        return

    # Dedup by meta_message_id — S14 fail-open on DB error
    if message_id:
        try:
            dedup = (
                db.table("whatsapp_messages")
                .select("id")
                .eq("meta_message_id", message_id)
                .limit(1)
                .execute()
            )
            if dedup.data:
                logger.info(
                    "_process_single_message: duplicate message_id=%s — skipping",
                    message_id,
                )
                return
        except Exception as exc:
            logger.warning(
                "_process_single_message: dedup check failed message_id=%s "
                "— proceeding: %s",
                message_id, exc,
            )

    # Determine message content
    if text:
        content    = text
        msg_type   = "text"
    elif message.get("attachments"):
        # Image/video attachments — log as media, no download in this phase
        content  = "[Instagram media]"
        msg_type = "image"
    else:
        content  = "[Instagram message]"
        msg_type = "text"

    # Convert Unix timestamp to ISO
    if timestamp:
        try:
            created_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
        except Exception:
            created_at = datetime.now(timezone.utc).isoformat()
    else:
        created_at = datetime.now(timezone.utc).isoformat()

    now_ts = datetime.now(timezone.utc).isoformat()
    window_expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    # Look up or create lead
    lead_id, assigned_to = _get_or_create_lead(
        db=db,
        org_id=org_id,
        instagram_scoped_id=instagram_scoped_id,
        first_message=content if msg_type == "text" else None,
        now_ts=now_ts,
    )

    if not lead_id:
        logger.warning(
            "_process_single_message: could not get or create lead for "
            "instagram_scoped_id=%s org=%s — dropping message",
            instagram_scoped_id, org_id,
        )
        return

    # Insert message into whatsapp_messages
    row: dict = {
        "org_id":              org_id,
        "lead_id":             lead_id,
        "channel":             "instagram",
        "direction":           "inbound",
        "message_type":        msg_type,
        "content":             content,
        "status":              "delivered",
        "meta_message_id":     message_id or None,
        "instagram_scoped_id": instagram_scoped_id,
        "window_open":         True,
        "window_expires_at":   window_expires,
        "sent_by":             None,
        "created_at":          created_at,
    }
    db.table("whatsapp_messages").insert(row).execute()

    # Update lead last_activity_at
    try:
        db.table("leads").update(
            {"last_activity_at": now_ts, "updated_at": now_ts}
        ).eq("id", lead_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning(
            "_process_single_message: last_activity_at update failed "
            "lead=%s: %s",
            lead_id, exc,
        )

    # Notify assigned rep (or fallback to owner/ops_manager)
    _notify_rep(
        db=db,
        org_id=org_id,
        lead_id=lead_id,
        assigned_to=assigned_to,
        content=content,
        now_ts=now_ts,
    )


# ---------------------------------------------------------------------------
# Lead lookup / auto-create
# ---------------------------------------------------------------------------

def _get_or_create_lead(
    db,
    org_id: str,
    instagram_scoped_id: str,
    first_message: Optional[str],
    now_ts: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Look up an existing lead by instagram_scoped_id, or auto-create one.
    Returns (lead_id, assigned_to).
    S14: returns (None, None) on unrecoverable failure.
    """
    # Look up existing lead
    try:
        result = (
            db.table("leads")
            .select("id, assigned_to")
            .eq("org_id", org_id)
            .eq("instagram_scoped_id", instagram_scoped_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        rows = result.data if isinstance(result.data, list) else []
        if rows:
            row = rows[0]
            return row["id"], row.get("assigned_to")
    except Exception as exc:
        logger.warning(
            "_get_or_create_lead: lead lookup failed org=%s: %s", org_id, exc
        )

    # Auto-create lead — no phone number available from Instagram DM
    try:
        from app.models.leads import LeadCreate, LeadSource
        from app.services.lead_service import create_lead

        # Use instagram_scoped_id as a provisional identifier in full_name
        # until the lead provides their name via conversation
        payload = LeadCreate(
            full_name=f"Instagram User",
            source=LeadSource.instagram_ad.value,
            problem_stated=first_message[:5000] if first_message else None,
        )
        new_lead = create_lead(
            db=db,
            org_id=org_id,
            user_id=None,           # system-created — Pattern 64
            payload=payload,
            entry_path="instagram_dm",
            utm_source="instagram",
        )
        lead_id = new_lead.get("id")
        assigned_to = new_lead.get("assigned_to")

        if lead_id:
            # Write instagram_scoped_id onto the lead — not in LeadCreate model
            # so we update directly after creation
            db.table("leads").update(
                {"instagram_scoped_id": instagram_scoped_id}
            ).eq("id", lead_id).eq("org_id", org_id).execute()

            # Fetch Instagram username from Graph API — S14: never raises
            try:
                from app.services.instagram_service import _get_org_instagram_credentials
                _, access_token = _get_org_instagram_credentials(db, org_id)
                if access_token:
                    import httpx as _httpx
                    resp = _httpx.get(
                        f"https://graph.facebook.com/v18.0/{instagram_scoped_id}",
                        params={"fields": "name,username", "access_token": access_token},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        ig_data = resp.json()
                        ig_name = ig_data.get("name") or ig_data.get("username") or "Instagram User"
                        ig_username = ig_data.get("username")
                        db.table("leads").update({
                            "full_name": ig_name,
                            "instagram_username": ig_username,
                        }).eq("id", lead_id).eq("org_id", org_id).execute()
            except Exception as exc:
                logger.warning(
                    "_get_or_create_lead: could not fetch Instagram username "
                    "for scoped_id=%s: %s", instagram_scoped_id, exc
                )

        return lead_id, assigned_to

    except Exception as exc:
        logger.warning(
            "_get_or_create_lead: lead creation failed org=%s: %s", org_id, exc
        )
        return None, None


# ---------------------------------------------------------------------------
# Rep notification
# ---------------------------------------------------------------------------

def _notify_rep(
    db,
    org_id: str,
    lead_id: str,
    assigned_to: Optional[str],
    content: str,
    now_ts: str,
) -> None:
    """
    Notify the assigned rep of a new Instagram DM.
    Falls back to all owner/ops_manager users if no rep assigned.
    S14: never raises.
    """
    try:
        notify_user_ids: list[str] = []

        if assigned_to:
            notify_user_ids = [assigned_to]
        else:
            # Fallback: notify all owner + ops_manager
            users_result = (
                db.table("users")
                .select("id, roles(template)")
                .eq("org_id", org_id)
                .eq("is_active", True)
                .execute()
            )
            for u in (users_result.data or []):
                role_template = (u.get("roles") or {}).get("template", "")
                if role_template in ("owner", "ops_manager"):
                    notify_user_ids.append(u["id"])

        for uid in notify_user_ids:
            try:
                db.table("notifications").insert({
                    "org_id":        org_id,
                    "user_id":       uid,
                    "type":          "instagram_dm",
                    "title":         "New Instagram DM",
                    "body":          content[:500] if content else "[Instagram message]",
                    "resource_type": "lead",
                    "resource_id":   lead_id,
                    "is_read":       False,
                    "created_at":    now_ts,
                }).execute()
            except Exception as exc:
                logger.warning(
                    "_notify_rep: notification insert failed user=%s org=%s: %s",
                    uid, org_id, exc,
                )

    except Exception as exc:
        logger.warning("_notify_rep failed org=%s lead=%s: %s", org_id, lead_id, exc)


# ---------------------------------------------------------------------------
# Dead letter helper
# ---------------------------------------------------------------------------

def _dead_letter(db, payload: dict, reason: str) -> None:
    """
    Write an unprocessable Instagram webhook to dead_letter_webhooks.
    S14: never raises.
    """
    try:
        import json
        db.table("dead_letter_webhooks").insert({
            "source":     "instagram",
            "payload":    json.dumps(payload)[:10_000],
            "reason":     reason[:500],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.warning("_dead_letter: failed to write dead letter: %s", exc)
