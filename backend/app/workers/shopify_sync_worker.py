"""
app/workers/shopify_sync_worker.py
------------------------------------
SHOP-1A: Nightly product re-sync for all Shopify-connected orgs.
Runs as a Celery periodic task (or standalone dry-run).

Dry-run command:
  python -c "
from dotenv import load_dotenv; load_dotenv()
from app.workers.shopify_sync_worker import sync_all_orgs
print(sync_all_orgs())
"
Expected: {'orgs_processed': N, 'total_synced': N, 'total_failed': 0}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def sync_all_orgs() -> dict:
    """
    Fetch all Shopify-connected orgs and re-sync their product catalogues.
    S14: per-org failure never stops the loop.
    Returns { orgs_processed, total_synced, total_failed }.
    """
    from app.database import get_supabase
    from app.services.shopify_service import bulk_sync_products

    db = get_supabase()
    orgs_processed = 0
    total_synced = 0
    total_failed = 0

    try:
        result = (
            db.table("organisations")
            .select("id, shopify_shop_domain, shopify_client_id, shopify_client_secret")
            .eq("shopify_connected", True)
            .execute()
        )
        orgs = result.data or []
        if isinstance(orgs, dict):
            orgs = [orgs]

        for org in orgs:
            org_id        = org.get("id")
            shop_domain   = (org.get("shopify_shop_domain") or "").strip()
            client_id     = (org.get("shopify_client_id") or "").strip()
            client_secret = (org.get("shopify_client_secret") or "").strip()

            if not org_id or not shop_domain or not client_id or not client_secret:
                logger.warning(
                    "shopify_sync_worker: skipping org %s — incomplete credentials", org_id
                )
                continue

            try:
                counts = bulk_sync_products(
                    db=db,
                    org_id=org_id,
                    shop_domain=shop_domain,
                    client_id=client_id,
                    client_secret=client_secret,
                )
                total_synced += counts.get("synced", 0)
                total_failed += counts.get("failed", 0)
                orgs_processed += 1
                logger.info(
                    "shopify_sync_worker: org=%s synced=%d failed=%d",
                    org_id, counts.get("synced", 0), counts.get("failed", 0),
                )
            except Exception as exc:
                logger.warning(
                    "shopify_sync_worker: org=%s failed: %s", org_id, exc
                )
                total_failed += 1

    except Exception as exc:
        logger.error("shopify_sync_worker: fatal error: %s", exc)

    summary = {
        "orgs_processed": orgs_processed,
        "total_synced":   total_synced,
        "total_failed":   total_failed,
    }
    logger.info("shopify_sync_worker complete: %s", summary)
    return summary


# Celery task registration (used in production)
try:
    from app.celery_app import celery_app

    @celery_app.task(name="shopify_sync_worker.sync_all_orgs")
    def sync_all_orgs_task():
        return sync_all_orgs()

except ImportError:
    pass  # Celery not configured — worker runs standalone via dry-run command
