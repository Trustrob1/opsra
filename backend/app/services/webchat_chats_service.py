"""
app/services/webchat_chats_service.py
-------------------------------------
WEBCHAT-CHATS-1 — the Chats tab on the Web chat page: every web chat in the period, including visitors who never left a contact.

Read-only. Everything is filtered by org_id. No new tables:
  list  <- webchat_sessions (+ webchat_events for orders and payments)
  one   <- the session's history while there is no lead, or whatsapp_messages (webchat_session_id) once there is one.
A visitor with no contact is shown as "Visitor 4F2A": the first four characters of the chat id, so the same chat always has the same code
and nobody is named or contacted from here. Phone numbers and emails are never returned in the list.
S14: a failed query returns an empty list rather than breaking the screen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CAP_ROWS = 2000          # most chats looked at in one request (newest first)
PAGE_MAX = 100
FILTERS = ("all", "asked", "no_contact", "gap", "ordered", "human")
MSG_CAP = 300


def _since(days: int, counting_from: Optional[str]) -> str:
    days = max(1, min(int(days or 30), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return counting_from if counting_from and counting_from > since else since


def _rows(build) -> list:
    try:
        return build().execute().data or []
    except Exception as exc:
        logger.warning("webchat chats query failed: %s", exc)
        return []


def visitor_code(session_id: str) -> str:
    return "Visitor " + (str(session_id).replace("-", "")[:4] or "0000").upper()


def _cart_count(state: dict) -> int:
    c = state.get("cart")
    return sum(int(i.get("qty") or 0) for i in c if isinstance(i, dict)) if isinstance(c, list) else 0


def _row(r: dict, ordered: set, paid: set) -> dict:
    st = r.get("state") or {}
    has = bool(r.get("lead_id"))
    sid = r["id"]
    return {
        "id": sid, "code": visitor_code(sid), "has_contact": has, "lead_id": r.get("lead_id"),
        "name": (r.get("contact_name") or "").strip() or None if has else None,
        "source": r.get("source") or "link",
        "started_at": r.get("created_at"), "last_at": r.get("last_activity_at"),
        "messages": int(r.get("turn_count") or 0),
        "viewing": st.get("viewing_title") or None,
        "cart_items": _cart_count(st),
        "ordered": sid in ordered or bool(st.get("last_checkout")),
        "paid": sid in paid,
        "handed": bool(st.get("human_at") or st.get("human")),
        "gap": bool(st.get("gap_at")),
    }


def _matches(row: dict, flt: str) -> bool:
    if flt == "asked":
        return row["messages"] > 0
    if flt == "no_contact":
        return not row["has_contact"]
    if flt == "gap":
        return row["gap"]
    if flt == "ordered":
        return row["ordered"] or row["paid"]
    if flt == "human":
        return row["handed"]
    return True


def list_chats(db, org_id: str, days: int = 30, flt: str = "all", source: Optional[str] = None,
               limit: int = 50, offset: int = 0) -> dict:
    flt = flt if flt in FILTERS else "all"
    limit = max(1, min(int(limit or 50), PAGE_MAX))
    offset = max(0, int(offset or 0))
    counting_from = None
    try:
        from app.services import webchat_service as wc
        counting_from = (wc.get_config(db, org_id) or {}).get("stats_from")
    except Exception:
        pass
    since = _since(days, counting_from)
    sessions = _rows(lambda: db.table("webchat_sessions")
                     .select("id, lead_id, contact_name, source, state, turn_count, created_at, last_activity_at")
                     .eq("org_id", org_id).gte("last_activity_at", since).order("last_activity_at", desc=True).limit(CAP_ROWS))
    events = _rows(lambda: db.table("webchat_events").select("session_id, kind").eq("org_id", org_id)
                   .in_("kind", ["order", "paid"]).gte("created_at", since).limit(CAP_ROWS * 2))
    ordered = {e["session_id"] for e in events if e.get("kind") == "order" and e.get("session_id")}
    paid = {e["session_id"] for e in events if e.get("kind") == "paid" and e.get("session_id")}
    rows = [_row(r, ordered, paid) for r in sessions]
    sources = sorted({r["source"] for r in rows})
    if source:
        rows = [r for r in rows if r["source"] == source]
    counts = {f: sum(1 for r in rows if _matches(r, f)) for f in FILTERS}
    shown = [r for r in rows if _matches(r, flt)]
    return {"chats": shown[offset:offset + limit], "total": len(shown), "counts": counts, "sources": sources,
            "capped": len(sessions) >= CAP_ROWS, "since": since}


def get_chat(db, org_id: str, session_id: str) -> Optional[dict]:
    got = _rows(lambda: db.table("webchat_sessions").select("*").eq("org_id", org_id).eq("id", session_id).limit(1))
    if not got:
        return None
    s = got[0]
    events = _rows(lambda: db.table("webchat_events").select("kind").eq("org_id", org_id).eq("session_id", session_id)
                   .in_("kind", ["order", "paid"]).limit(20))
    kinds = {e.get("kind") for e in events}
    row = _row(s, {session_id} if "order" in kinds else set(), {session_id} if "paid" in kinds else set())
    if s.get("lead_id"):
        msgs = _rows(lambda: db.table("whatsapp_messages").select("id, content, direction, sent_by, created_at")
                     .eq("org_id", org_id).eq("webchat_session_id", session_id).order("created_at").limit(MSG_CAP))
        messages = [{"id": m["id"], "role": "visitor" if m.get("direction") == "inbound" else ("rep" if m.get("sent_by") else "bot"),
                     "text": m.get("content") or "", "at": m.get("created_at")} for m in msgs]
    else:
        messages = [{"id": m.get("id"), "role": m.get("role") or "bot", "text": str(m.get("text") or ""), "at": m.get("at")}
                    for m in (s.get("history") or []) if isinstance(m, dict)][-MSG_CAP:]
    cart = [{"title": str(i.get("title") or "")[:120], "qty": int(i.get("qty") or 0), "price": i.get("price")}
            for i in ((s.get("state") or {}).get("cart") or []) if isinstance(i, dict)]
    return {"chat": row, "messages": messages, "cart": cart}
