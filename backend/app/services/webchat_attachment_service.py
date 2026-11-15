"""
app/services/webchat_attachment_service.py
------------------------------------------
WEBCHAT-ATTACH-1 - a visitor sends a photo, a voice note or a document in the web chat.

Why it is strict: anyone with the chat link can upload, so a file is only accepted when
  * the visitor has already given contact details (the session has a lead),
  * its type is on a short allow-list AND its first bytes really are that type (the browser's word is not trusted),
  * it is within the size limit for its kind,
  * the visitor has not sent too many files recently (route rate limit).
Nothing that can run in a browser (html, svg, scripts, executables, archives) is ever accepted.

Storage: the existing private bucket 'whatsapp-media' (path <org>/webchat/<session>/<uuid>_<name>), and the file becomes a
normal inbound whatsapp_messages row (message_type image | audio | document, media_url, storage_path), so the staff inbox
already shows it, plays it and can download it, exactly like a file received on WhatsApp.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile
from typing import Optional

from app.services import webchat_service as wc

logger = logging.getLogger(__name__)

BUCKET = "whatsapp-media"
SIGNED_SECONDS = 31_536_000          # one year, same as files received on WhatsApp

MB = 1024 * 1024
MAX_BYTES = {"image": 10 * MB, "document": 15 * MB, "audio": 5 * MB}
KINDS = tuple(MAX_BYTES)
MAX_ANY = max(MAX_BYTES.values())

LABEL = {"image": "a photo", "document": "a document", "audio": "a voice note"}
FALLBACK_NAME = {"image": "photo", "document": "document", "audio": "voice-note"}


def _sniff(data: bytes, kind: str, filename: str) -> Optional[tuple[str, str]]:
    """(mime, extension) when the bytes are a genuine file of this kind, else None."""
    head = data[:16]
    low = (filename or "").lower()
    if kind == "image":
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
            return "image/gif", "gif"
        if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", "webp"
        return None
    if kind == "audio":
        if head.startswith(b"\x1a\x45\xdf\xa3"):
            return "audio/webm", "webm"
        if head.startswith(b"OggS"):
            return "audio/ogg", "ogg"
        if data[4:8] == b"ftyp":
            return "audio/mp4", "m4a"
        if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
            return "audio/mpeg", "mp3"
        if head[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "audio/wav", "wav"
        return None
    if kind == "document":
        if head.startswith(b"%PDF-"):
            return "application/pdf", "pdf"
        if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):          # old Word / Excel (OLE)
            if low.endswith(".xls"):
                return "application/vnd.ms-excel", "xls"
            if low.endswith(".doc"):
                return "application/msword", "doc"
            return None
        if head.startswith(b"PK\x03\x04"):                                 # docx / xlsx are zip files
            try:
                names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
            except Exception:
                return None
            if "word/document.xml" in names and low.endswith(".docx"):
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
            if "xl/workbook.xml" in names and low.endswith(".xlsx"):
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
            return None
        if low.endswith(".txt") and b"\x00" not in data[:2048]:
            return "text/plain", "txt"
        return None
    return None


def clean_filename(name: Optional[str], kind: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", str(name or "").replace("\\", "/").split("/")[-1]).strip(" .")
    if not base:
        base = FALLBACK_NAME.get(kind, "file")
    stem = base.rsplit(".", 1)[0][:60] or FALLBACK_NAME.get(kind, "file")
    return f"{stem}.{ext}"


def validate(data: bytes, kind: str, filename: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    """(clean, error). clean = {mime, ext, name}."""
    if kind not in KINDS:
        return None, "That type of file cannot be sent here."
    if not data:
        return None, "That file is empty."
    if len(data) > MAX_BYTES[kind]:
        return None, f"That file is too big. The limit is {MAX_BYTES[kind] // MB} MB."
    hit = _sniff(data, kind, filename or "")
    if not hit:
        what = {"image": "a JPG, PNG, GIF or WebP photo", "audio": "a voice note",
                "document": "a PDF, Word, Excel or text file"}[kind]
        return None, f"We could not read that file. Please send {what}."
    mime, ext = hit
    return {"mime": mime, "ext": ext, "name": clean_filename(filename, kind, ext)}, None


def _signed_url(db, path: str) -> Optional[str]:
    try:
        res = db.storage.from_(BUCKET).create_signed_url(path=path, expires_in=SIGNED_SECONDS)
        if hasattr(res, "data"):
            d = res.data or {}
            return d.get("signedUrl") or d.get("signedURL")
        if isinstance(res, dict):
            return res.get("signedUrl") or res.get("signedURL") or (res.get("data") or {}).get("signedUrl")
    except Exception as exc:
        logger.warning("webchat attachment sign failed path=%s: %s", path, exc)
    return None


def save_attachment(db, session: dict, kind: str, clean: dict, data: bytes) -> dict:
    """Store the file and add it to the chat. Returns the message the page shows. Raises RuntimeError on a storage failure."""
    org_id = session["org_id"]
    path = f"{org_id}/webchat/{session['id']}/{uuid.uuid4()}_{clean['name']}"
    try:
        db.storage.from_(BUCKET).upload(path=path, file=data, file_options={"content-type": clean["mime"]})
    except Exception as exc:
        logger.warning("webchat attachment upload failed org=%s: %s", org_id, exc)
        raise RuntimeError("storage") from exc
    url = _signed_url(db, path)
    if not url:
        raise RuntimeError("sign")
    mid = str(uuid.uuid4())
    now = wc._iso(wc._now())
    text = "Voice note" if kind == "audio" else clean["name"]
    db.table("whatsapp_messages").insert({
        "id": mid, "org_id": org_id, "lead_id": session["lead_id"], "channel": "webchat",
        "webchat_session_id": session["id"], "message_type": kind, "content": text,
        "media_url": url, "storage_path": path, "direction": "inbound", "status": "delivered", "created_at": now,
    }).execute()
    return {"id": mid, "role": "visitor", "text": text, "at": now,
            "attachment": {"kind": kind, "name": text, "size": len(data), "url": url, "mime": clean["mime"]}}


def label(kind: str) -> str:
    return LABEL.get(kind, "a file")
