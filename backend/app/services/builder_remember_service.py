"""
app/services/builder_remember_service.py
----------------------------------------
HOST-4 - "stay signed in for 30 days" for the builder portal.

The builder JWT still lives only in React state (it is short: 12 hours). What survives a page change is a random value in an
HttpOnly cookie. Only its SHA-256 hash is stored (site_builder_sessions), so a database leak cannot be turned back into a
sign-in. When the portal opens with no sign-in link, it asks POST /auth/session; if the cookie is valid it gets a fresh JWT.
Each use pushes the expiry out 30 days (sliding). Signing out revokes the row and clears the cookie.

Nothing here can block a normal sign-in: every failure returns None / does nothing and the person simply signs in again.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

COOKIE_NAME = "opsra_bsess"
DAYS = 30
_TWO_PART_SUFFIXES = {"com.ng", "org.ng", "net.ng", "gov.ng", "edu.ng", "co.uk", "co.za"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create(db: Any, *, builder_id: str, org_id: str, user_agent: str = "") -> str:
    """Store a new session and return the raw cookie value (shown once, never stored)."""
    raw = secrets.token_urlsafe(32)
    now = _now()
    db.table("site_builder_sessions").insert({
        "id": str(uuid.uuid4()), "org_id": org_id, "builder_id": builder_id, "token_hash": _hash(raw),
        "user_agent": (user_agent or "")[:300], "created_at": now.isoformat(), "last_used_at": now.isoformat(),
        "expires_at": (now + timedelta(days=DAYS)).isoformat(),
    }).execute()
    return raw


def restore(db: Any, raw: Optional[str]) -> Optional[dict]:
    """The active builder row for a valid cookie value, else None. Slides the expiry forward."""
    if not raw or len(raw) > 200:
        return None
    rows = (db.table("site_builder_sessions").select("*").eq("token_hash", _hash(raw)).limit(1).execute()).data or []
    row = rows[0] if rows else None
    if not row or row.get("revoked_at"):
        return None
    try:
        if _now() > datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    brows = (db.table("site_builders").select("*").eq("id", row["builder_id"]).eq("org_id", row["org_id"]).execute()).data or []
    builder = brows[0] if brows else None
    if not builder or builder.get("status") != "active":
        return None
    try:
        now = _now()
        db.table("site_builder_sessions").update({
            "last_used_at": now.isoformat(), "expires_at": (now + timedelta(days=DAYS)).isoformat(),
        }).eq("id", row["id"]).execute()
    except Exception:  # noqa: BLE001 - sliding the expiry is a nicety, never a reason to refuse a valid cookie
        logger.warning("could not extend builder session %s", row.get("id"))
    return builder


def revoke(db: Any, raw: Optional[str]) -> None:
    if not raw:
        return
    try:
        db.table("site_builder_sessions").update({"revoked_at": _now().isoformat()}).eq("token_hash", _hash(raw)).execute()
    except Exception:  # noqa: BLE001
        logger.warning("could not revoke a builder session")


def _site(host: str) -> str:
    labels = [p for p in (host or "").split(":")[0].lower().split(".") if p]
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else ".".join(labels)


def cookie_kwargs(origin: Optional[str], api_host: Optional[str]) -> dict:
    """Cookie attributes. Same-site (site and API share a registrable domain): Lax. Otherwise (for example the API on
    onrender.com) None, which browsers only keep over https, and some (Safari) may still block. Local dev: not Secure."""
    host = (api_host or "").split(":")[0].lower()
    local = host in ("localhost", "127.0.0.1") or host.startswith("127.")
    origin_host = urlparse(origin).hostname if origin else None
    same_site = bool(origin_host) and _site(origin_host) == _site(host)
    samesite = "lax" if (same_site or not origin_host) else "none"
    return {"httponly": True, "secure": not local, "samesite": samesite if not local else "lax",
            "max_age": DAYS * 86400, "path": "/"}
