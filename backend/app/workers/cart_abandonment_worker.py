"""
app/workers/cart_abandonment_worker.py
COMM-1 — Level 2 Abandoned Cart Recovery Worker.

9E-D gates added:
  D1: is_org_active() — fetch org row per session, skip suspended/read_only.
  D2: is_quiet_hours() — skip send (session left in checkout_sent state,
      will be retried on next 2h run when quiet hours have ended).
  D3: has_exceeded_daily_limit() — skip send if customer daily cap reached.

All other logic unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, field_validator

from app.utils.org_gates import (
    is_org_active,
    is_quiet_hours,
    get_daily_customer_limit,
    has_exceeded_daily_limit,
)

logger = logging.getLogger(__name__)


class AbandonedSessionPayload(BaseModel):
    id:           str
    org_id:       str
    phone_number: str
    checkout_url: str
    customer_id:  str = ""   # used for D3 check

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


def run_cart_abandonment_check() -> dict:
    """
    Main entry point — called by the Celery task and directly for dry-runs.
    Returns: { processed, reminded, abandoned, failed }.
    """
    from app.database import get_supabase
    from app.services.commerce_service import mark_cart_abandoned
    from app.services.whatsapp_service import send_checkout_link

    db  = get_supabase()
    now = datetime.now(timezone.utc)

    remind_cutoff         = (now - timedelta(hours=2)).isoformat()
    abandon_cutoff        = (now - timedelta(hours=24)).isoformat()
    stale_claim_threshold = (now - timedelta(hours=3)).isoformat()

    summary = {"processed": 0, "reminded": 0, "abandoned": 0, "failed": 0}

    # ── Release stale claims ──────────────────────────────────────────────────
    try:
        db.table("commerce_sessions").update(
            {"processing_at": None}
        ).eq("status", "checkout_sent").lt(
            "processing_at", stale_claim_threshold
        ).execute()
    except Exception as exc:
        logger.warning(
            "cart_abandonment_worker: failed to release stale claims: %s", exc
        )

    # ── Atomic claim ──────────────────────────────────────────────────────────
    try:
        claim_result = (
            db.table("commerce_sessions")
            .update({"processing_at": now.isoformat()})
            .eq("status", "checkout_sent")
            .lt("updated_at", remind_cutoff)
            .is_("processing_at", "null")
            .execute()
        )
        sessions = claim_result.data if isinstance(claim_result.data, list) else []
    except Exception as exc:
        logger.warning(
            "cart_abandonment_worker: claim step failed: %s", exc
        )
        return summary

    if not sessions:
        logger.info("cart_abandonment_worker: no sessions to process — exiting.")
        return summary

    logger.info(
        "cart_abandonment_worker: claimed %d session(s) to process.", len(sessions)
    )

    # ── Org row cache — avoid repeated DB lookups for same org ───────────────
    org_cache: dict[str, dict] = {}

    def _get_org(org_id: str) -> dict:
        if org_id not in org_cache:
            try:
                res = (
                    db.table("organisations")
                    .select(
                        "id, subscription_status, quiet_hours_start, "
                        "quiet_hours_end, timezone, daily_customer_message_limit"
                    )
                    .eq("id", org_id)
                    .maybe_single()
                    .execute()
                )
                row = res.data
                if isinstance(row, list):
                    row = row[0] if row else {}
                org_cache[org_id] = row or {}
            except Exception as exc:
                logger.warning(
                    "cart_abandonment_worker: org fetch failed org=%s: %s",
                    org_id, exc,
                )
                org_cache[org_id] = {}
        return org_cache[org_id]

    for raw_session in sessions:
        summary["processed"] += 1
        try:
            session = AbandonedSessionPayload(
                id=raw_session.get("id", ""),
                org_id=raw_session.get("org_id", ""),
                phone_number=raw_session.get("phone_number", ""),
                checkout_url=raw_session.get("checkout_url") or "",
                customer_id=raw_session.get("customer_id") or "",
            )
        except Exception as val_exc:
            logger.warning(
                "cart_abandonment_worker: invalid session %s — skipped: %s",
                raw_session.get("id"), val_exc,
            )
            summary["failed"] += 1
            continue

        org_row = _get_org(session.org_id)

        # ── D1: Subscription gate ─────────────────────────────────────────
        if not is_org_active(org_row):
            logger.info(
                "cart_abandonment_worker: org %s skipped — subscription_status=%s",
                session.org_id, org_row.get("subscription_status"),
            )
            summary["failed"] += 1
            continue

        try:
            updated_at_str = (raw_session.get("updated_at") or "").replace("Z", "+00:00")
            updated_at = datetime.fromisoformat(updated_at_str) if updated_at_str else None
        except Exception:
            updated_at = None

        is_stale = updated_at and updated_at < datetime.fromisoformat(
            abandon_cutoff.replace("Z", "+00:00")
        )

        try:
            if is_stale:
                mark_cart_abandoned(db, session.id)
                summary["abandoned"] += 1
                logger.info(
                    "cart_abandonment_worker: abandoned session %s org=%s",
                    session.id, session.org_id,
                )
            else:
                # ── D2: Quiet hours — skip send (retry on next run) ───────
                if is_quiet_hours(org_row, now):
                    logger.info(
                        "cart_abandonment_worker: session %s skipped — "
                        "quiet hours active for org %s",
                        session.id, session.org_id,
                    )
                    # Release claim so next run re-evaluates when QH ends
                    try:
                        db.table("commerce_sessions").update(
                            {"processing_at": None}
                        ).eq("id", session.id).execute()
                    except Exception:
                        pass
                    summary["failed"] += 1
                    continue

                # ── D3: Daily customer message limit ──────────────────────
                if session.customer_id:
                    daily_limit = get_daily_customer_limit(org_row)
                    if has_exceeded_daily_limit(
                        db, session.org_id, session.customer_id, daily_limit
                    ):
                        logger.info(
                            "cart_abandonment_worker: customer %s skipped — "
                            "daily limit %d reached",
                            session.customer_id, daily_limit,
                        )
                        summary["failed"] += 1
                        continue

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
            logger.warning(
                "cart_abandonment_worker: session %s failed org=%s: %s",
                session.id, session.org_id, exc,
            )
            summary["failed"] += 1

    logger.info("cart_abandonment_worker: complete — %s", summary)
    return summary


try:
    from app.workers.celery_app import celery_app

    @celery_app.task(name="app.workers.cart_abandonment_worker.run_cart_abandonment_check")
    def run_cart_abandonment_check_task() -> dict:
        return run_cart_abandonment_check()

except ImportError:
    pass
