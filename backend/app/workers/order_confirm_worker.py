"""
app/workers/order_confirm_worker.py
-----------------------------------
ORDER-GATE-1 - 10 minutes after a customer asks to order, if no person has replied, tell the owner / ops managers.
"""
from __future__ import annotations

import logging

from app.workers.celery_app import celery_app
from app.database import get_supabase

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.order_confirm_worker.check_order_confirmed")
def check_order_confirmed(org_id: str, lead_id: str, requested_at: str, product: str = "") -> dict:
    try:
        from app.services import order_request_service as ors
        db = get_supabase()
        if ors.team_replied_since(db, lead_id, requested_at):
            return {"late": False}
        try:
            from app.services.lead_service import write_timeline_event
            write_timeline_event(db, org_id, lead_id, event_type="order_request_late", actor_id=None,
                                 description="No reply to the order request after 10 minutes", metadata={})
        except Exception:
            pass
        return {"late": True, "notified": ors.notify_managers(db, org_id, lead_id, product or "a product")}
    except Exception as exc:
        logger.warning("check_order_confirmed failed lead=%s: %s", lead_id, exc)
        return {"error": str(exc)}
