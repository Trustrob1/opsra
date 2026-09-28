"""
app/services/builder_auth_service.py
-------------------------------------
SITE-2B — builder-portal session tokens (spec §10).

Two separate credentials are in play here, and they must not be confused:

  1. The magic link (`site_editor_tokens.token_hash`) — a random, single-use,
     7-day token the builder receives on WhatsApp or via the internal
     "Get edit link" tool. It is hashed with SHA-256 before storage (never
     stored raw), exactly like `site_brief_forms.token_hash` (spec §18).
     Handled in routers/builder_portal.py's /auth/exchange route, which
     exchanges it for #2 below and immediately marks it used (revoked_at).

  2. The builder session JWT — issued by this module once the magic link is
     verified. Signed with a SEPARATE secret from the staff SECRET_KEY
     (BUILDER_JWT_SECRET), `aud="builder"`, 12-hour expiry. Builder sessions
     can only ever be verified by `get_current_builder` in
     routers/builder_portal.py — they are never accepted by
     `get_current_user`/`get_current_org` (different secret, different aud),
     and staff sessions are never accepted here for the same reason.

No refresh tokens in this phase — a session simply expires after 12h and the
builder asks for a new magic link (WhatsApp EDIT, or Trust re-issues one).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_AUDIENCE = "builder"
_SESSION_HOURS = 12


def _secret() -> str:
    # See the BUILDER_JWT_SECRET comment in config.py — this fallback keeps
    # existing deploys working before Trust sets the env var in Render, while
    # still not being literally equal to SECRET_KEY.
    return settings.BUILDER_JWT_SECRET or f"{settings.SECRET_KEY}::builder-portal-fallback"


def issue_builder_session(*, builder_id: str, org_id: str) -> dict:
    """Returns {"access_token": str, "expires_at": iso str}."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_SESSION_HOURS)
    claims = {
        "sub": builder_id,
        "org_id": org_id,
        "aud": _AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, _secret(), algorithm=_ALGORITHM)
    return {"access_token": token, "expires_at": expires_at.isoformat()}


def decode_builder_session(token: str) -> Optional[dict]:
    """Returns {"builder_id": str, "org_id": str} or None if the token is
    invalid, expired, or not a builder-audience token. Never raises —
    callers turn a None into a 401."""
    try:
        claims = jwt.decode(token, _secret(), algorithms=[_ALGORITHM], audience=_AUDIENCE)
    except JWTError as exc:
        logger.info("builder session token rejected: %s", exc)
        return None
    builder_id = claims.get("sub")
    org_id = claims.get("org_id")
    if not builder_id or not org_id:
        return None
    return {"builder_id": builder_id, "org_id": org_id}
