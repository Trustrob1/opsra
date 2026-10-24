"""
app/services/product_mode.py
----------------------------
WA-AUTO-1 - what kind of customer an organisation is (organisations.product_mode).

  'full'           the normal Opsra app (CRM and WhatsApp automation together)
  'wa_automation'  WhatsApp automation only: inbox, bot setup, knowledge, billing. The CRM screens and routes are closed.

  get_mode(db, org_id)       'full' or 'wa_automation'. Kept in memory for 60 seconds. ANY problem answers 'full', so a broken
                             lookup can never lock a business out (S14).
  is_wa_automation(db, org_id)
  set_mode(db, org_id, mode) used by Superadmin; clears the memory so the change shows at once on this server.
  crm_only                   FastAPI dependency added to the CRM routers in main.py. A signed-in WhatsApp-only business gets
                             404 "not found" on them, except the few routes the inbox needs (ALLOWED). Anonymous requests and
                             every other business pass straight through, so the public lead form, which lives inside the
                             leads router, keeps working.

Security note: crm_only reads the user id from the token WITHOUT checking its signature. That is safe because it is only used
to close doors. The route's own login check (get_current_org) still runs and still verifies the token, so a made-up token
can never open anything; at most it earns a 404 on a request that would have been refused anyway.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request

from app.database import get_supabase

logger = logging.getLogger(__name__)

FULL = "full"
WA_AUTOMATION = "wa_automation"
MODES = (FULL, WA_AUTOMATION)

_TTL_SECONDS = 60
_MAX_ENTRIES = 5000
_org_mode: dict = {}     # org_id -> (mode, expires_at)
_user_org: dict = {}     # user_id -> (org_id, expires_at)

# The inbox reads a conversation from the leads and customers routers. These stay open for a WhatsApp-only business.
ALLOWED = (
    ("GET", re.compile(r"^/api/v1/leads/[^/]+/messages/?$")),
    ("PATCH", re.compile(r"^/api/v1/leads/[^/]+/messages/mark-read/?$")),
    ("GET", re.compile(r"^/api/v1/customers/[^/]+/messages/?$")),
)


def _remember(store: dict, key: str, value: Any) -> None:
    if len(store) >= _MAX_ENTRIES:
        store.clear()
    store[key] = (value, time.monotonic() + _TTL_SECONDS)


def invalidate() -> None:
    """Forget everything remembered (after a mode change, and in tests)."""
    _org_mode.clear()
    _user_org.clear()


def get_mode(db: Any, org_id: Optional[str]) -> str:
    if not org_id:
        return FULL
    key = str(org_id)
    hit = _org_mode.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    try:
        rows = (db.table("organisations").select("product_mode").eq("id", key).limit(1).execute().data) or []
        value = rows[0].get("product_mode") if rows else None
        mode = value if value in MODES else FULL
    except Exception as exc:
        logger.warning("product_mode.get_mode failed org=%s - treating as full: %s", key, exc)
        return FULL
    _remember(_org_mode, key, mode)
    return mode


def is_wa_automation(db: Any, org_id: Optional[str]) -> bool:
    return get_mode(db, org_id) == WA_AUTOMATION


def set_mode(db: Any, org_id: str, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("product_mode must be 'full' or 'wa_automation'")
    db.table("organisations").update({"product_mode": mode}).eq("id", org_id).execute()
    invalidate()
    return {"org_id": org_id, "product_mode": mode}


def _token_subject(request: Request) -> Optional[str]:
    """The user id inside a Bearer token, or None. The signature is NOT checked here (see the module note)."""
    parts = (request.headers.get("authorization") or "").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    segments = parts[1].strip().split(".")
    if len(segments) != 3:
        return None
    try:
        payload = segments[1] + "=" * (-len(segments[1]) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload.encode("ascii"))).get("sub")
        return str(sub) if sub else None
    except Exception:
        return None


def _org_for_user(db: Any, user_id: str) -> Optional[str]:
    hit = _user_org.get(user_id)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    org_id = None
    try:
        from app import dependencies as dep
        warm = dep._user_cache.get(user_id)   # filled by get_current_org, so normally no query is needed
        org_id = (warm or {}).get("org_id")
    except Exception:
        org_id = None
    if not org_id:
        try:
            rows = (db.table("users").select("org_id").eq("id", user_id).limit(1).execute().data) or []
            org_id = rows[0].get("org_id") if rows else None
        except Exception as exc:
            logger.warning("product_mode: user lookup failed - letting the request through: %s", exc)
            return None
    if org_id:
        _remember(_user_org, user_id, str(org_id))
    return str(org_id) if org_id else None


async def crm_only(request: Request, db=Depends(get_supabase)) -> None:
    """Close a CRM router to WhatsApp-only businesses. See the module note for why anonymous requests pass."""
    blocked = False
    try:
        sub = _token_subject(request)
        org_id = _org_for_user(db, sub) if sub else None
        if org_id and get_mode(db, org_id) == WA_AUTOMATION:
            method, path = request.method.upper(), request.url.path
            blocked = not any(m == method and rx.match(path) for m, rx in ALLOWED)
    except Exception as exc:
        logger.warning("product_mode.crm_only failed - letting the request through: %s", exc)
        blocked = False
    if blocked:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND",
                                                     "message": "This area is not part of a WhatsApp automation account."})
