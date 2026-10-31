"""
backend/app/workers/booking_payment_worker.py
BOOKING-3A - every 2 minutes: confirm Paystack deposits that were paid, release holds whose time ran out.
S14: never raises into Celery.
"""
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.booking_payment_worker.run_booking_payment_sweep")
def run_booking_payment_sweep():
    try:
        from app.database import get_supabase
        from app.services import booking_deposit_service
        db = get_supabase()
        out = booking_deposit_service.sweep(db)
        logger.info("booking_payment_sweep: %s", out)
        return out
    except Exception as exc:
        logger.error("booking_payment_sweep failed: %s", exc)
        return {"error": str(exc)[:200]}
