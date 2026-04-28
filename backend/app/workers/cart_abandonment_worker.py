"""
app/workers/cart_abandonment_worker.py
COMM-1 — Level 2 Abandoned Cart Recovery Worker.

Runs every 2 hours via Celery beat.

Level 1 (Shopify-initiated):
  Handled by handle_abandoned_cart() in shopify_service.py —
  fires when Shopify's checkouts/update webhook fires.
  Contact opened the link on Shopify but didn't pay.

Level 2 (this worker):
  Contact received the WhatsApp checkout link but never clicked it —
  so Shopify never sees the abandonment.
  Finds commerce_sessions where status = 'checkout_sent'
  AND updated_at < now - 2h.
  Sends a WhatsApp reminder. Abandons sessions older than 24h.

Pattern 48: get_supabase (not get_db).
S13: Pydantic payload validation.
S14: per-session failure never stops the loop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S13 — Pydantic session payload validation
# ---------------------------------------------------------------------------

class AbandonedSessionPayload(BaseModel):
    id:           str
    org_id:       str
    phone_number: str
    checkout_url: str

    @field_validator("phone_number")
    @classmethod
    def phone_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("phone_number is required")
        return v

    @field_validator("checkout_url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("checkout_url is required")
        return v


# ---------------------------------------------------------------------------
# Core logic — importable for dry-run
# ---------------------------------------------------------------------------

def run_cart_abandonment_check() -> dict:
    """
    Main entry point — called by the Celery task and directly for dry-runs.
    Returns a summary dict: { processed, reminded, abandoned, failed }.
    """
    from app.database import get_supabase
    from app.services.commerce_service import mark_cart_abandoned
    from app.services.whatsapp_service import send_checkout_link

    db = get_supabase()
    now = datetime.now(timezone.utc)

    remind_cutoff  = (now - timedelta(hours=2)).isoformat()   # sent > 2h ago → reminder
    abandon_cutoff = (now - timedelta(hours=24)).isoformat()  # sent > 24h ago → abandon

    summary = {"processed": 0, "reminded": 0, "abandoned": 0, "failed": 0}

    try:
        result = (
            db.table("commerce_sessions")
            .select("id, org_id, phone_number, checkout_url, updated_at")
            .eq("status", "checkout_sent")
            .lt("updated_at", remind_cutoff)
            .execute()
        )
        sessions = result.data if isinstance(result.data, list) else []
    except Exception as exc:
        logger.warning("cart_abandonment_worker: session fetch failed: %s", exc)
        return summary

    for raw_session in sessions:
        summary["processed"] += 1
        try:
            # S13 — validate before processing
            session = AbandonedSessionPayload(
                id=raw_session.get("id", ""),
                org_id=raw_session.get("org_id", ""),
                phone_number=raw_session.get("phone_number", ""),
                checkout_url=raw_session.get("checkout_url") or "",
            )
        except Exception as val_exc:
            logger.warning(
                "cart_abandonment_worker: invalid session %s — skipped: %s",
                raw_session.get("id"), val_exc,
            )
            summary["failed"] += 1
            continue

        try:
            updated_at_str = (raw_session.get("updated_at") or "").replace("Z", "+00:00")
            updated_at = datetime.fromisoformat(updated_at_str)
        except Exception:
            updated_at = None

        is_stale = updated_at and updated_at < datetime.fromisoformat(
            abandon_cutoff.replace("Z", "+00:00")
        )

        try:
            if is_stale:
                # > 24h — cart is dead, mark abandoned
                mark_cart_abandoned(db, session.id)
                summary["abandoned"] += 1
                logger.info(
                    "cart_abandonment_worker: abandoned session %s org=%s phone=%s",
                    session.id, session.org_id, session.phone_number,
                )
            else:
                # 2–24h — send reminder
                send_checkout_link(
                    db=db,
                    org_id=session.org_id,
                    phone_number=session.phone_number,
                    checkout_url=session.checkout_url,
                    commerce_config={
                        "checkout_message":
                            "You have items waiting in your cart — "
                            "your checkout link:"
                    },
                )
                summary["reminded"] += 1
                logger.info(
                    "cart_abandonment_worker: reminder sent session=%s org=%s",
                    session.id, session.org_id,
                )

        except Exception as exc:
            # S14 — one session failure never stops the loop
            logger.warning(
                "cart_abandonment_worker: session %s failed org=%s: %s",
                session.id, session.org_id, exc,
            )
            summary["failed"] += 1

    logger.info("cart_abandonment_worker: complete — %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Celery task registration (optional import — runs standalone too)
# ---------------------------------------------------------------------------

try:
    from app.workers.celery_app import celery_app

    @celery_app.task(name="app.workers.cart_abandonment_worker.run_cart_abandonment_check")
    def run_cart_abandonment_check_task() -> dict:
        return run_cart_abandonment_check()

except ImportError:
    pass
