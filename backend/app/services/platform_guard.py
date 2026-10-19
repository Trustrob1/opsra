"""
app/services/platform_guard.py
------------------------------
ACCOUNT-PLANS AP-8 - Opsra's own tools (the Sites engine and Opsra Pricing) belong to ONE organisation: the platform
organisation (env PLATFORM_ORG_ID, Tech with Trust Robert). Nobody else sees them, and a typed URL gets a plain "not found".

  platform_only      FastAPI dependency for every staff-side Sites router (404 for any other organisation)
  is_platform(db, org_id)

If PLATFORM_ORG_ID is not set the code falls back to the oldest site_builder_settings row (as plan pricing already did) and
logs an error once, so a missing setting never locks the owner out. Set PLATFORM_ORG_ID on the Render backend and worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import Depends, HTTPException

from app.database import get_supabase
from app.dependencies import get_current_org
from app.services import account_entitlement_service as acc

logger = logging.getLogger(__name__)
_warned = False


def platform_id(db: Any) -> Optional[str]:
    global _warned
    env = os.getenv("PLATFORM_ORG_ID", "").strip()
    if not env and not _warned:
        _warned = True
        logger.error("PLATFORM_ORG_ID is not set - falling back to the oldest site_builder_settings row. Set it on Render.")
    return acc.platform_org_id(db)


def is_platform(db: Any, org_id: Optional[str]) -> bool:
    pid = platform_id(db)
    return bool(pid and org_id and str(pid) == str(org_id))


async def platform_only(org=Depends(get_current_org), db=Depends(get_supabase)) -> None:
    """Sites routes exist for the platform organisation only. Anyone else gets 'not found', never 'forbidden'."""
    pid = platform_id(db)
    if pid and str(org.get("org_id")) != str(pid):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Site engine is not enabled for this org."})
