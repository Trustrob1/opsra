"""
app/services/knowledge_service.py
---------------------------------
WA-AUTO-4a - what the bot knows, from uploaded files and typed answers.

  add_file / add_text    cut the text into small chunks ONCE, as a draft the owner can preview
  activate / remove      "Start using this" / discard
  retrieve               the best few chunks for a customer's message, using Postgres full-text search (no AI, no cost)

Cost rule: the AI never reads the whole library. retrieve() returns at most MAX_CHUNKS chunks (about MAX_CHUNK_CHARS each), so
what a reply costs stays flat however much the owner uploads. Nothing here calls an AI model.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

MAX_CHUNKS = 5                  # most chunks ever given to the bot for one message
MAX_CHUNK_CHARS = 1400          # about 230 words
CHUNK_TARGET = 1100             # chunks are filled up to about this size
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_SOURCE_CHARS = 400_000      # about 330 chunks from one file
MAX_ORG_CHUNKS = 5000           # safety cap on a whole library
MAX_TITLE = 120
STALE_MINUTES = 5
PINNED_TITLE = "About our business"   # the wizard's answers; always given to the bot (one chunk), so it knows what the business is
FILE_TYPES = {".pdf", ".docx", ".txt", ".md", ".csv"}

_STOP = frozenset("""a about above after again all also am an and any are as at be because been before being below between both but by
can did do does doing down during each few for from further had has have having he her here hers him his how i if in into is it its just
me more most my no nor not now of off on once only or other our out over own same she should so some such than that the their them then
there these they this those through to too under until up very was we were what when where which while who whom why will with would you your
please pls hi hello hey thanks thank dear good morning afternoon evening sir madam ma""".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _one(res: Any) -> dict:
    data = getattr(res, "data", None)
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


# -- cutting text into chunks ------------------------------------------------------------------------------------------
def clean_text(text: str) -> str:
    text = (text or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long(piece: str) -> list:
    """A paragraph longer than a chunk is cut at sentence ends, then at spaces."""
    if len(piece) <= MAX_CHUNK_CHARS:
        return [piece]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", piece):
        while len(sent) > MAX_CHUNK_CHARS:
            cut = sent.rfind(" ", 0, MAX_CHUNK_CHARS)
            cut = cut if cut > 200 else MAX_CHUNK_CHARS
            if cur:
                out.append(cur); cur = ""
            out.append(sent[:cut].strip()); sent = sent[cut:].strip()
        if cur and len(cur) + 1 + len(sent) > CHUNK_TARGET:
            out.append(cur); cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return [p for p in out if p]


def chunk_text(text: str) -> list:
    """Paragraphs are kept together and packed up to about CHUNK_TARGET characters. Every chunk is at most MAX_CHUNK_CHARS."""
    chunks, cur = [], ""
    for para in [p.strip() for p in clean_text(text).split("\n\n") if p.strip()]:
        for piece in _split_long(para):
            if cur and len(cur) + 2 + len(piece) > CHUNK_TARGET:
                chunks.append(cur); cur = piece
            else:
                cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


# -- reading files -----------------------------------------------------------------------------------------------------
def _ext(name: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return m.group(0).lower() if m else ""


def extract_text(file_name: str, data: bytes) -> str:
    ext = _ext(file_name)
    if ext not in FILE_TYPES:
        _fail(422, "UNSUPPORTED_FILE", "Upload a PDF, Word (.docx), text (.txt, .md) or .csv file.")
    if not data:
        _fail(422, "EMPTY_FILE", "That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        _fail(413, "FILE_TOO_LARGE", "That file is over 10 MB. Split it into smaller files.")
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                _fail(422, "LOCKED_FILE", "That PDF is password protected. Remove the password and try again.")
            if len(reader.pages) > MAX_PDF_PAGES:
                _fail(422, "TOO_MANY_PAGES", f"That PDF has more than {MAX_PDF_PAGES} pages. Split it into smaller files.")
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        if ext == ".docx":
            from docx import Document
            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs]
            for t in doc.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n\n".join(parts)
        return data.decode("utf-8", errors="replace")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("knowledge: could not read %s: %s", file_name, exc)
        _fail(422, "UNREADABLE_FILE", "We could not read that file. Check that it opens normally and try again.")


# -- sources -----------------------------------------------------------------------------------------------------------
def _org_chunk_total(db: Any, org_id: str) -> int:
    rows = db.table("knowledge_sources").select("chunk_count").eq("org_id", org_id).execute().data or []
    return sum(int(r.get("chunk_count") or 0) for r in rows)


def new_source(db: Any, org_id: str, user_id: Optional[str], kind: str, title: str, file_name: Optional[str] = None,
               source_url: Optional[str] = None, status: str = "draft") -> str:
    now = _now()
    row = {"org_id": org_id, "kind": kind, "title": title[:MAX_TITLE], "file_name": (file_name or None), "status": status,
           "chunk_count": 0, "char_count": 0, "created_by": user_id, "created_at": now, "updated_at": now}
    if source_url:
        row["source_url"] = source_url[:500]
    sid = _one(db.table("knowledge_sources").insert(row).execute()).get("id")
    if not sid:
        _fail(500, "SAVE_FAILED", "Could not save that. Please try again.")
    return sid


def fill_source(db: Any, org_id: str, source_id: str, text: str, page_count: int = 0) -> None:
    """Cuts `text` into chunks, saves them and makes the source a draft. Raises HTTPException with a plain message when it cannot."""
    text = clean_text(text)
    if len(text) < 20:
        _fail(422, "NO_TEXT", "We found no readable text. If this is a scanned PDF (a picture of pages), upload a version with real text.")
    if len(text) > MAX_SOURCE_CHARS:
        _fail(422, "TOO_MUCH_TEXT", "That is too much text for one source. Split it into smaller parts.")
    chunks = chunk_text(text)
    if _org_chunk_total(db, org_id) + len(chunks) > MAX_ORG_CHUNKS:
        _fail(409, "LIBRARY_FULL", "Your knowledge library is full. Remove something you no longer need first.")
    try:
        for i in range(0, len(chunks), 200):
            db.table("knowledge_chunks").insert([
                {"org_id": org_id, "source_id": source_id, "position": i + j, "content": c} for j, c in enumerate(chunks[i:i + 200])
            ]).execute()
    except Exception as exc:
        logger.warning("knowledge: chunk save failed org=%s source=%s: %s", org_id, source_id, exc)
        try:
            db.table("knowledge_chunks").delete().eq("source_id", source_id).eq("org_id", org_id).execute()
        except Exception:
            pass
        _fail(500, "SAVE_FAILED", "Could not save that. Please try again.")
    fields = {"status": "draft", "chunk_count": len(chunks), "char_count": len(text), "error": None, "updated_at": _now()}
    if page_count:
        fields["page_count"] = page_count
    db.table("knowledge_sources").update(fields).eq("id", source_id).eq("org_id", org_id).execute()


def mark_failed(db: Any, org_id: str, source_id: str, message: str) -> None:
    try:
        db.table("knowledge_sources").update({"status": "failed", "error": message[:300], "updated_at": _now()}).eq("id", source_id).eq("org_id", org_id).execute()
    except Exception as exc:
        logger.warning("knowledge: could not mark source failed org=%s: %s", org_id, exc)


def _create(db: Any, org_id: str, user_id: Optional[str], kind: str, title: str, file_name: Optional[str], text: str) -> dict:
    text = clean_text(text)
    if len(text) < 20:                      # checked before a row exists, so a refused source leaves nothing behind
        _fail(422, "NO_TEXT", "We found no readable text. If this is a scanned PDF (a picture of pages), upload a version with real text.")
    sid = new_source(db, org_id, user_id, kind, title, file_name)
    try:
        fill_source(db, org_id, sid, text)
    except HTTPException:
        try:
            db.table("knowledge_sources").delete().eq("id", sid).eq("org_id", org_id).execute()
        except Exception:
            pass
        raise
    return preview(db, org_id, sid)


def add_file(db: Any, org_id: str, user_id: Optional[str], file_name: str, data: bytes, title: Optional[str] = None) -> dict:
    text = extract_text(file_name, data)
    name = (title or re.sub(r"\.[A-Za-z0-9]+$", "", file_name or "") or "Uploaded file").strip()
    return _create(db, org_id, user_id, "file", name, file_name, text)


def add_text(db: Any, org_id: str, user_id: Optional[str], title: str, content: str) -> dict:
    title = " ".join((title or "").split())
    if not title:
        _fail(422, "VALIDATION_ERROR", "Give this a short title.")
    return _create(db, org_id, user_id, "text", title, None, content)


def get_source(db: Any, org_id: str, source_id: str) -> dict:
    src = _one(db.table("knowledge_sources").select("*").eq("id", source_id).eq("org_id", org_id).limit(1).execute())
    if not src:
        _fail(404, "NOT_FOUND", "That item was not found.")
    return src


def preview(db: Any, org_id: str, source_id: str) -> dict:
    src = get_source(db, org_id, source_id)
    rows = (db.table("knowledge_chunks").select("position, content").eq("source_id", source_id).eq("org_id", org_id)
            .order("position").limit(3).execute().data) or []
    return {**_public(src), "samples": [r["content"][:400] for r in rows]}


def _public(src: dict) -> dict:
    return {k: src.get(k) for k in ("id", "kind", "title", "file_name", "status", "chunk_count", "char_count", "error", "created_at", "activated_at",
                                     "source_url", "page_count")}


def list_sources(db: Any, org_id: str) -> list:
    rows = db.table("knowledge_sources").select("*").eq("org_id", org_id).order("created_at", desc=True).limit(200).execute().data or []
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)).isoformat()
    for r in rows:      # a website read that never finished (the server restarted, say) is shown as failed, not "reading" forever
        if r.get("status") == "processing" and str(r.get("created_at") or "") < cutoff:
            mark_failed(db, org_id, r["id"], "This took too long and was stopped. Please try again.")
            r["status"], r["error"] = "failed", "This took too long and was stopped. Please try again."
    return [_public(r) for r in rows]


def activate(db: Any, org_id: str, source_id: str) -> dict:
    src = get_source(db, org_id, source_id)
    if src.get("status") in ("failed", "processing"):
        _fail(409, "NOT_READY", "That item is not ready to use." if src.get("status") == "processing" else "That item could not be read, so it cannot be used.")
    now = _now()
    db.table("knowledge_sources").update({"status": "active", "activated_at": now, "updated_at": now}).eq("id", source_id).eq("org_id", org_id).execute()
    return preview(db, org_id, source_id)


def remove(db: Any, org_id: str, source_id: str) -> dict:
    get_source(db, org_id, source_id)
    db.table("knowledge_chunks").delete().eq("source_id", source_id).eq("org_id", org_id).execute()
    db.table("knowledge_sources").delete().eq("id", source_id).eq("org_id", org_id).execute()
    return {"removed": True}


def upsert_text_source(db: Any, org_id: str, user_id: Optional[str], title: str, content: str) -> bool:
    """Replaces the active text source with this title (used for the wizard's 'About our business'). S14: False on any problem."""
    try:
        old = db.table("knowledge_sources").select("id").eq("org_id", org_id).eq("kind", "text").eq("title", title).execute().data or []
        for o in old:
            remove(db, org_id, o["id"])
        created = add_text(db, org_id, user_id, title, content)
        activate(db, org_id, created["id"])
        return True
    except Exception as exc:
        logger.warning("knowledge: could not store '%s' org=%s: %s", title, org_id, exc)
        return False


# -- finding the best chunks -------------------------------------------------------------------------------------------
def query_terms(text: str) -> list:
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(w) < 3 or w in _STOP or w in seen:
            continue
        seen.add(w); out.append(w)
    return out[:12]


def build_query(text: str) -> Optional[str]:
    terms = query_terms(text)
    return " | ".join(f"{t}:*" for t in terms) if terms else None


def has_active(db: Any, org_id: str) -> bool:
    try:
        return bool(db.table("knowledge_sources").select("id").eq("org_id", org_id).eq("status", "active").limit(1).execute().data)
    except Exception:
        return False


def _pinned(db: Any, org_id: str) -> Optional[dict]:
    try:
        src = db.table("knowledge_sources").select("id, title").eq("org_id", org_id).eq("status", "active").eq("title", PINNED_TITLE).limit(1).execute().data or []
        if not src:
            return None
        row = (db.table("knowledge_chunks").select("content").eq("source_id", src[0]["id"]).eq("org_id", org_id).order("position").limit(1).execute().data) or []
        return {"title": src[0]["title"], "content": row[0]["content"][:MAX_CHUNK_CHARS], "chunk": True} if row else None
    except Exception as exc:
        logger.warning("knowledge: pinned lookup failed org=%s: %s", org_id, exc)
        return None


def retrieve(db: Any, org_id: str, text: str, limit: int = MAX_CHUNKS) -> list:
    """At most MAX_CHUNKS chunks as {title, content, chunk: True}: the pinned "About our business" chunk, then the best search
    matches for `text`. S14: whatever was found, never raises."""
    pinned = _pinned(db, org_id)
    room = MAX_CHUNKS - (1 if pinned else 0)
    found: list = []
    q = build_query(text)
    if q:
        try:
            rows = db.rpc("knowledge_search", {"p_org": org_id, "p_query": q, "p_limit": min(max(int(limit), 1), room)}).execute().data or []
            found = [{"title": r.get("title") or "", "content": (r.get("content") or "")[:MAX_CHUNK_CHARS], "chunk": True}
                     for r in rows if not (pinned and r.get("title") == PINNED_TITLE and (r.get("content") or "")[:200] == pinned["content"][:200])]
        except Exception as exc:
            logger.warning("knowledge.retrieve failed org=%s: %s", org_id, exc)
    return ([pinned] if pinned else []) + found[:room]
