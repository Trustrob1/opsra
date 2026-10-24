"""
app/services/knowledge_refresh_service.py
-----------------------------------------
WA-AUTO-4c - keeps website and Google Doc sources fresh. An ACTIVE source is read again about once a week; the bot keeps
using the old text until the new text is saved (no gap), and a read that fails or looks wrong never replaces good text.
S14: one source's failure never stops the others.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.services import knowledge_service as ks
from app.services import knowledge_web_service as web
from app.services.site_import_resolve import FetchError, safe_fetch

logger = logging.getLogger(__name__)

REFRESH_AFTER_DAYS = 6          # the daily sweep picks a source up once its last check is this old
MAX_PER_RUN = 40                # a run takes at most 40 sources (each website read is capped at about 45 seconds)
MANUAL_COOLDOWN_MIN = 10
SHRINK_GUARD = 0.3              # a new text under 30% of a big old one is treated as a failed read (site down, blocked page)
SHRINK_MIN_OLD_CHARS = 2000
REFRESHABLE = ("url", "gdoc")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(src: dict, fetch: Callable) -> tuple:
    """Returns (text, page_count) for a website or Google Doc source. Raises FetchError or ValueError with a plain message."""
    if src.get("kind") == "url":
        pages = web.crawl(web.clean_start_url(src.get("source_url") or ""), fetch)
        return web.assemble(pages), len(pages)
    export = web.gdoc_export_url(src.get("source_url") or "")
    body, ctype = fetch(export, 5 * 1024 * 1024)
    if ctype and not ctype.startswith("text/plain"):
        raise FetchError("the document is no longer shared with everyone who has the link")
    return body.decode("utf-8", errors="replace"), 1


def _stamp(db: Any, org_id: str, source_id: str, fields: dict) -> None:
    try:
        db.table("knowledge_sources").update(fields).eq("id", source_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("knowledge_refresh: could not save result org=%s source=%s: %s", org_id, source_id, exc)


def refresh_source(db: Any, src: dict, fetch: Callable = safe_fetch) -> str:
    """Reads one source again. Returns 'unchanged', 'updated' or 'failed'. Never raises."""
    org_id, sid = src["org_id"], src["id"]
    now = _now().isoformat()
    try:
        text, pages = _read(src, fetch)
        text = ks.clean_text(text)
        if len(text) < 20:
            raise FetchError("no readable text was found")
        if (src.get("char_count") or 0) >= SHRINK_MIN_OLD_CHARS and len(text) < (src.get("char_count") or 0) * SHRINK_GUARD:
            raise FetchError("it now looks much smaller than before, so we kept the old copy")
        digest = ks.text_hash(text)
        if digest == src.get("content_hash"):
            _stamp(db, org_id, sid, {"last_refreshed_at": now, "refresh_error": None})
            return "unchanged"
        count = ks.replace_chunks(db, org_id, sid, text)
        _stamp(db, org_id, sid, {"chunk_count": count, "char_count": len(text), "page_count": pages, "content_hash": digest,
                                 "last_refreshed_at": now, "refresh_error": None, "updated_at": now})
        return "updated"
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        msg = (detail.get("message") if isinstance(detail, dict) else None) or str(exc) or "unknown problem"
        if not isinstance(exc, (FetchError, ValueError)) and not isinstance(detail, dict):
            logger.warning("knowledge_refresh: unexpected failure org=%s source=%s: %s", org_id, sid, exc)
            msg = "something went wrong"
        _stamp(db, org_id, sid, {"last_refreshed_at": now, "refresh_error": f"The last update failed ({msg[:200]}). The bot is still using the previous copy."})
        return "failed"


def is_due(src: dict, now: Optional[datetime] = None) -> bool:
    now = now or _now()
    last = src.get("last_refreshed_at") or src.get("activated_at") or src.get("created_at")
    if not last:
        return True
    return str(last) < (now - timedelta(days=REFRESH_AFTER_DAYS)).isoformat()


def run_due(db: Any, now: Optional[datetime] = None, fetch: Callable = safe_fetch, limit: int = MAX_PER_RUN) -> dict:
    """The daily sweep: every active website or Google Doc source whose last check is over six days old."""
    from app.services import plan_gate_service
    now = now or _now()
    total = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0, "skipped": 0}
    try:
        rows = (db.table("knowledge_sources").select("*").eq("status", "active").in_("kind", list(REFRESHABLE)).execute().data) or []
    except Exception as exc:
        logger.warning("knowledge_refresh: could not list sources: %s", exc)
        total["failed"] += 1
        return total
    due = sorted([r for r in rows if r.get("auto_refresh") is not False and r.get("source_url") and is_due(r, now)],
                 key=lambda r: str(r.get("last_refreshed_at") or ""))
    allowed_cache: dict = {}
    for src in due:
        if total["checked"] >= limit:
            break
        org_id = src["org_id"]
        if org_id not in allowed_cache:
            try:
                allowed_cache[org_id] = bool(plan_gate_service.allowed(db, org_id, "knowledge_base"))
            except Exception:
                allowed_cache[org_id] = False
        if not allowed_cache[org_id]:
            total["skipped"] += 1
            continue
        total["checked"] += 1
        total[refresh_source(db, src, fetch)] += 1
    return total
