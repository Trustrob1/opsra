"""
app/services/webchat_msg_service.py
-----------------------------------
WEBCHAT-MSG-1 - a visitor edits or deletes one of THEIR OWN messages in the web chat (WhatsApp style).

  * only the visitor's own messages; never the bot's or the team's
  * edit: text messages only, within 15 minutes of sending, not after a delete
  * delete: any of their own messages (text, photo, voice note, document), any time; removed for everyone, the team sees
    "This message was deleted"
The words before an edit, and before a delete, are kept in original_content for the team's record (never sent to the visitor).
A reply needs no function here: append_message(reply_to=...) stores it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

EDIT_WINDOW_MIN = 15
DELETED_TEXT = "This message was deleted"


def _parse(v) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _mine(found: Optional[tuple]) -> tuple[Optional[tuple], Optional[str]]:
    if not found:
        return None, "We could not find that message."
    if found[2] != "visitor":
        return None, "You can only change your own messages."
    if found[1].get("deleted_at"):
        return None, "That message was already deleted."
    return found, None


def _save(db, session: dict, found: tuple, changes_db: dict, changes_hist: dict) -> dict:
    where, row, role = found
    if where == "db":
        db.table("whatsapp_messages").update(changes_db).eq("id", row["id"]).eq("org_id", session["org_id"]).execute()
        row = {**row, **changes_db}
    else:
        hist = [({**m, **changes_hist} if m.get("id") == row["id"] else m) for m in (session.get("history") or [])]
        wc.update_session(db, session, {"history": hist})
        row = {**row, **changes_hist}
    out = wc._out(role, row)
    if row.get("reply_to_id") or row.get("reply_to"):
        wc._attach_quotes(db, session, [out], [row])
    return out


def edit(db, session: dict, mid: str, text: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    found, err = _mine(wc.find_message(db, session, mid))
    if err:
        return None, err
    row = found[1]
    if row.get("message_type") not in (None, "text"):
        return None, "Only written messages can be edited."
    new = wc._clean_text(text, wc.MAX_TEXT)
    if not new:
        return None, "A message cannot be empty."
    sent = _parse(row.get("created_at") or row.get("at"))
    if sent and wc._now() - sent > timedelta(minutes=EDIT_WINDOW_MIN):
        return None, f"Messages can only be edited for {EDIT_WINDOW_MIN} minutes after sending."
    cur = row.get("content") if found[0] == "db" else row.get("text")
    if new == (cur or ""):
        return wc._out(found[2], row), None
    now = wc._iso(wc._now())
    original = row.get("original_content") if found[0] == "db" else row.get("original")
    keep = original or cur
    return _save(db, session, found,
                 {"content": new, "edited_at": now, "original_content": keep},
                 {"text": new, "edited_at": now, "original": keep}), None


def delete(db, session: dict, mid: str) -> tuple[Optional[dict], Optional[str]]:
    found, err = _mine(wc.find_message(db, session, mid))
    if err:
        return None, err
    row = found[1]
    cur = row.get("content") if found[0] == "db" else row.get("text")
    now = wc._iso(wc._now())
    original = (row.get("original_content") if found[0] == "db" else row.get("original")) or cur
    # the file (if any) stays in storage for the team's record; the message no longer points at it
    return _save(db, session, found,
                 {"content": DELETED_TEXT, "message_type": "text", "media_url": None, "deleted_at": now, "original_content": original},
                 {"text": DELETED_TEXT, "deleted_at": now, "original": original}), None
