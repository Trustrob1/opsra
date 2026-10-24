"""
app/services/knowledge_gap_service.py
-------------------------------------
WA-AUTO-4c - the "Not answered" list: questions the bot could not answer from what it knows (the agent hands those to a
person). The owner can answer one (it becomes a typed source the bot uses from then on) or dismiss it.
Phone numbers and emails inside a question are hidden before it is saved. S14: recording never raises.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from app.services import knowledge_service as ks

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 300
MIN_QUESTION_CHARS = 6
MAX_OPEN = 200
MAX_ANSWER_CHARS = 2000
_DIGITS = re.compile(r"\+?\d[\d\s\-()]{5,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def clean_question(text: str) -> str:
    t = _EMAIL.sub("[email]", str(text or ""))
    t = _DIGITS.sub("[number]", t)
    return " ".join(t.split())[:MAX_QUESTION_CHARS]


def question_key(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())[:200]


def record(db: Any, org_id: str, question: str, lead_id: Optional[str] = None) -> bool:
    """Notes one unanswered question (counts repeats). Returns True when something was saved. Never raises."""
    try:
        q = clean_question(question)
        if len(q) < MIN_QUESTION_CHARS:
            return False
        key = question_key(q)
        if not key:
            return False
        rows = db.table("knowledge_gaps").select("*").eq("org_id", org_id).eq("question_key", key).limit(1).execute().data or []
        now = _now()
        if rows:
            row = rows[0]
            if row.get("status") == "dismissed":
                return False
            fields = {"times_asked": int(row.get("times_asked") or 1) + 1, "last_asked_at": now, "last_lead_id": lead_id}
            if row.get("status") == "answered":     # asked again after it was answered: the answer did not work, so it comes back
                fields.update({"status": "open", "resolved_at": None})
            db.table("knowledge_gaps").update(fields).eq("id", row["id"]).eq("org_id", org_id).execute()
            return True
        open_now = db.table("knowledge_gaps").select("id").eq("org_id", org_id).eq("status", "open").limit(MAX_OPEN + 1).execute().data or []
        if len(open_now) >= MAX_OPEN:
            return False
        db.table("knowledge_gaps").insert({"org_id": org_id, "question": q, "question_key": key, "times_asked": 1, "status": "open",
                                           "last_lead_id": lead_id, "first_asked_at": now, "last_asked_at": now}).execute()
        return True
    except Exception as exc:
        logger.warning("knowledge_gap: could not record org=%s: %s", org_id, exc)
        return False


def list_open(db: Any, org_id: str) -> list:
    rows = db.table("knowledge_gaps").select("*").eq("org_id", org_id).eq("status", "open").limit(MAX_OPEN).execute().data or []
    rows.sort(key=lambda r: str(r.get("last_asked_at") or ""), reverse=True)      # newest first ...
    rows.sort(key=lambda r: -(r.get("times_asked") or 1))                         # ... then the most asked on top
    return [{k: r.get(k) for k in ("id", "question", "times_asked", "first_asked_at", "last_asked_at")} for r in rows]


def _get_open(db: Any, org_id: str, gap_id: str) -> dict:
    rows = db.table("knowledge_gaps").select("*").eq("id", gap_id).eq("org_id", org_id).limit(1).execute().data or []
    if not rows:
        _fail(404, "NOT_FOUND", "That question was not found.")
    return rows[0]


def answer(db: Any, org_id: str, user_id: Optional[str], gap_id: str, text: str) -> dict:
    """Saves the owner's answer as a typed source the bot uses straight away, and closes the question."""
    gap = _get_open(db, org_id, gap_id)
    text = str(text or "").strip()
    if len(text) < 2:
        _fail(422, "VALIDATION_ERROR", "Type the answer first.")
    if len(text) > MAX_ANSWER_CHARS:
        _fail(422, "VALIDATION_ERROR", f"Keep the answer under {MAX_ANSWER_CHARS} characters.")
    title = ("Answer: " + gap["question"])[:120]
    body = f"Question: {gap['question']}\nAnswer: {text}"
    if len(body) < 20:
        body = body + " " * (20 - len(body)) + "."
    created = ks.add_text(db, org_id, user_id, title, body)
    ks.activate(db, org_id, created["id"])
    db.table("knowledge_gaps").update({"status": "answered", "resolved_at": _now()}).eq("id", gap_id).eq("org_id", org_id).execute()
    return {"answered": True, "source_id": created["id"]}


def dismiss(db: Any, org_id: str, gap_id: str) -> dict:
    _get_open(db, org_id, gap_id)
    db.table("knowledge_gaps").update({"status": "dismissed", "resolved_at": _now()}).eq("id", gap_id).eq("org_id", org_id).execute()
    return {"dismissed": True}
