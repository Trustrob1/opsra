"""
app/services/site_import_service.py
------------------------------------
SITE-IMPORT 1a: staff upload of a finished single-page site (a .zip, or one .html file) made outside Opsra.
Spec: website-business/SITE-IMPORT_Spec.md (sections 3, 4, 6, 17).

What 1a does: reads the upload safely, scans and cleans it, stores the extracted files and the raw upload,
and saves a NEW site_designs row (kind 'import', status 'ready', staged). It does not change the site's tier
or current design, so nothing live changes; IMPORT-1b adds the sandboxed preview, the renderer and the switch.

Rules:
  * Everything is scoped by org_id (S14). Runs in the web service, one request, memory capped (section 3):
    the upload is size-checked first, files are read one at a time with a hard cap, nothing is kept after the call.
  * A failed import saves nothing: files uploaded so far are removed again and no design row is written.
  * Every limit and every refusal has a plain-English message for staff.
"""
from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import posixpath
import secrets
import stat
import zipfile
import zlib
from datetime import datetime, timezone
from typing import Any, Optional

from app.services import site_import_sanitiser as sanitiser
from app.services import site_import_scan as scan

logger = logging.getLogger(__name__)

KEEP_IMPORT_VERSIONS = 10
BUCKET_FILES = "site-import-files"      # public: the extracted files
BUCKET_RAW = "site-imports"             # private: the raw upload

MB = 1024 * 1024
LIMITS = {
    "max_files": 150,
    "max_total_bytes": 60 * MB,           # all files together, uncompressed
    "max_ratio": 100,                     # compression ratio guard
    "max_html_bytes": 1 * MB,
    "max_css_each": 1 * MB,
    "max_css_html_total": 2 * MB,
    "max_js_total": int(1.5 * MB),
    "max_image_each": 5 * MB,
    "max_font_each": 5 * MB,
    "max_json_each": 500 * 1024,
    "max_txt_each": 100 * 1024,
    "max_path_len": 200,
}

_HTML = {".html", ".htm"}
_CSS = {".css"}
_JS = {".js", ".mjs"}
_IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".svg"}
_FONT = {".woff", ".woff2", ".ttf", ".otf"}
_DATA = {".json", ".txt"}
_FORBIDDEN = {".exe", ".dll", ".bat", ".cmd", ".sh", ".php", ".py", ".rb", ".pl", ".jar", ".msi", ".com", ".scr",
              ".vbs", ".ps1", ".apk", ".dmg", ".so", ".asp", ".aspx", ".jsp", ".cgi",
              ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
_JUNK_DIRS = ("__macosx/",)
_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"), ".webp": (b"RIFF",), ".avif": (b"\x00\x00\x00",),
    ".ico": (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00", b"\x89PNG"),
    ".woff": (b"wOFF",), ".woff2": (b"wOF2",), ".ttf": (b"\x00\x01\x00\x00", b"true", b"ttcf"), ".otf": (b"OTTO",),
}


class ImportRejected(Exception):
    """The upload cannot be imported. `errors` are plain sentences for staff; `report` is the analysis, if any."""
    status_code = 422
    code = "VALIDATION_ERROR"

    def __init__(self, errors, report: Optional[dict] = None):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        self.report = report
        super().__init__("Import not accepted: " + "; ".join(self.errors[:5]))


class ImportFailed(Exception):
    """Our side failed (storage, database). Nothing was changed."""
    status_code = 502
    code = "IMPORT_FAILED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _ext(path: str) -> str:
    return posixpath.splitext(path.lower())[1]


def kind_of(path: str) -> str:
    e = _ext(path)
    if e in _HTML:
        return "html"
    if e in _CSS:
        return "css"
    if e in _JS:
        return "js"
    if e in _IMG:
        return "image"
    if e in _FONT:
        return "font"
    if e in _DATA:
        return "data"
    return "other"


# ---------------------------------------------------------------------------
# 1. Reading the upload
# ---------------------------------------------------------------------------

def _clean_name(raw: str) -> Optional[str]:
    """Normalised relative path, or None for entries to skip. Raises ImportRejected for unsafe names."""
    name = raw.replace("\\", "/")
    if name.endswith("/"):
        return None
    if name.startswith("/") or (len(name) > 1 and name[1] == ":") or "\x00" in name:
        raise ImportRejected(f"The zip has an unsafe file name: {raw!r}. Re-zip the site folder and try again.")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ImportRejected(f"The zip has a file path that climbs out of the folder: {raw!r}.")
    norm = "/".join(parts)
    low = norm.lower()
    if any(low.startswith(j) or ("/" + j) in low for j in _JUNK_DIRS) or parts[-1].lower() in _JUNK_NAMES:
        return None
    return norm


def read_upload(data: bytes, filename: str, max_upload_bytes: int, limits: Optional[dict] = None) -> dict:
    """Returns {relative_path: bytes}. Accepts a .zip or a single .html file. Raises ImportRejected."""
    lim = {**LIMITS, **(limits or {})}
    if not data:
        raise ImportRejected("The file is empty.")
    if len(data) > max_upload_bytes:
        raise ImportRejected(f"The upload is {len(data) / MB:.1f} MB. The limit is {max_upload_bytes / MB:.0f} MB.")
    if data[:2] != b"PK":
        if _ext(filename or "") not in _HTML and b"<" not in data[:2000]:
            raise ImportRejected("Upload a .zip of the site folder, or a single .html file.")
        if len(data) > lim["max_html_bytes"]:
            raise ImportRejected(f"The HTML file is {len(data) / MB:.1f} MB. The limit is {lim['max_html_bytes'] / MB:.0f} MB.")
        return {"index.html": data}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportRejected("That file is not a valid zip. Re-zip the site folder and try again.")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > lim["max_files"] * 3:
        raise ImportRejected(f"The zip has {len(infos)} files. The limit is {lim['max_files']}.")

    entries = []
    total_declared = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise ImportRejected("The zip is password protected.")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise ImportRejected(f"The zip contains a link ({info.filename}). Links are not allowed.")
        name = _clean_name(info.filename)
        if name is None:
            continue
        if len(name) > lim["max_path_len"]:
            raise ImportRejected(f"A file path is too long: {name[:60]}...")
        e = _ext(name)
        if e in _FORBIDDEN:
            raise ImportRejected(f"The zip contains a file type that is not allowed ({posixpath.basename(name)}).")
        if info.file_size > lim["max_total_bytes"]:
            raise ImportRejected(f"{name} is too large.")
        if info.file_size > MB and info.compress_size and info.file_size / max(info.compress_size, 1) > lim["max_ratio"]:
            raise ImportRejected(f"{name} compresses suspiciously well (possible zip bomb). Check the file.")
        total_declared += info.file_size
        entries.append((name, info))
    if not entries:
        raise ImportRejected("The zip has no files in it.")
    if len(entries) > lim["max_files"]:
        raise ImportRejected(f"The zip has {len(entries)} files. The limit is {lim['max_files']}.")
    if total_declared > lim["max_total_bytes"]:
        raise ImportRejected(f"The files add up to {total_declared / MB:.0f} MB. The limit is {lim['max_total_bytes'] / MB:.0f} MB.")
    if total_declared / max(len(data), 1) > lim["max_ratio"] and total_declared > 5 * MB:
        raise ImportRejected("The zip compresses suspiciously well (possible zip bomb).")

    # strip one common top-level folder ("my-site/index.html" -> "index.html")
    tops = {n.split("/")[0] for n, _ in entries if "/" in n}
    if all("/" in n for n, _ in entries) and len(tops) == 1:
        strip = next(iter(tops)) + "/"
        entries = [(n[len(strip):], i) for n, i in entries]

    files: dict = {}
    seen_lower: dict = {}
    read_total = 0
    for name, info in entries:
        low = name.lower()
        if low in seen_lower:
            raise ImportRejected(f"Two files have the same name when capitals are ignored: {name} and {seen_lower[low]}.")
        seen_lower[low] = name
        try:
            with zf.open(info) as fh:
                body = fh.read(info.file_size + 1)      # hard cap: never trust the header alone
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OSError):
            raise ImportRejected(f"{name} is damaged inside the zip. Re-zip the site folder and try again.")
        if len(body) > info.file_size:
            raise ImportRejected(f"{name} is larger than the zip says it is.")
        read_total += len(body)
        if read_total > lim["max_total_bytes"]:
            raise ImportRejected("The files are larger than the limit once unzipped.")
        files[name] = body
    return files


# ---------------------------------------------------------------------------
# 2. Analysis (pure: no database, no storage)
# ---------------------------------------------------------------------------

def _decode(path: str, body: bytes, notes: list) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        notes.append({"rule": "not_utf8", "severity": "warning", "file": path, "line": 1, "overridable": False,
                      "message": f"{path} is not UTF-8; it was read as Latin-1. Save it as UTF-8 if letters look wrong.",
                      "snippet": ""})
        return body.decode("latin-1")


def _size_checks(files: dict, lim: dict) -> list:
    errors = []
    css_html_total = js_total = 0
    for path, body in files.items():
        k = kind_of(path)
        n = len(body)
        if k == "html":
            css_html_total += n
            if n > lim["max_html_bytes"]:
                errors.append(f"{path} is {n / MB:.1f} MB. The HTML limit is {lim['max_html_bytes'] / MB:.0f} MB.")
        elif k == "css":
            css_html_total += n
            if n > lim["max_css_each"]:
                errors.append(f"{path} is {n / MB:.1f} MB. The limit for one CSS file is {lim['max_css_each'] / MB:.0f} MB.")
        elif k == "js":
            js_total += n
        elif k == "image" and n > lim["max_image_each"]:
            errors.append(f"{path} is {n / MB:.1f} MB. The image limit is {lim['max_image_each'] / MB:.0f} MB. Compress it and try again.")
        elif k == "font" and n > lim["max_font_each"]:
            errors.append(f"{path} is {n / MB:.1f} MB. The font limit is {lim['max_font_each'] / MB:.0f} MB.")
        elif k == "data":
            cap = lim["max_json_each"] if _ext(path) == ".json" else lim["max_txt_each"]
            if n > cap:
                errors.append(f"{path} is too large ({n // 1024} KB).")
    if css_html_total > lim["max_css_html_total"]:
        errors.append(f"HTML and CSS together are {css_html_total / MB:.1f} MB. The limit is {lim['max_css_html_total'] / MB:.0f} MB.")
    if js_total > lim["max_js_total"]:
        errors.append(f"JavaScript files add up to {js_total / MB:.1f} MB. The limit is {lim['max_js_total'] / MB:.1f} MB.")
    return errors


def _magic_ok(path: str, body: bytes) -> bool:
    sigs = _MAGIC.get(_ext(path))
    if not sigs:
        return True
    if not body.startswith(sigs):
        return False
    if _ext(path) == ".webp":
        return body[8:12] == b"WEBP"
    if _ext(path) == ".avif":
        return body[4:12] in (b"ftypavif", b"ftypavis")
    return True


def _apply_accepted(findings: list, accepted: dict) -> tuple:
    """Downgrade overridable errors that staff accepted for a file. Returns (findings, accepted_log)."""
    log = []
    for f in findings:
        if f["severity"] != "error":
            continue
        rules = accepted.get(f["file"].split(" (")[0], []) or accepted.get(f["file"], [])
        if f["rule"] in rules and f["overridable"]:
            f["severity"] = "warning"
            f["accepted"] = True
            log.append({"file": f["file"], "rule": f["rule"], "line": f["line"]})
    return findings, log


def analyse(files: dict, allowed_hosts, accepted: Optional[dict] = None, limits: Optional[dict] = None) -> dict:
    """Scans and cleans an upload that read_upload() produced. Returns
    {"report": {...}, "html": cleaned_document, "entry": "index.html"}. Never touches the database."""
    lim = {**LIMITS, **(limits or {})}
    hosts = tuple(allowed_hosts) if allowed_hosts else scan.DEFAULT_ALLOWED_HOSTS
    accepted = accepted or {}
    errors: list = []

    # one page only; it must be at the top level
    pages = sorted(p for p in files if kind_of(p) == "html")
    if not pages:
        raise ImportRejected("The upload has no HTML page. Include an index.html at the top level.")
    if len(pages) > 1:
        raise ImportRejected("Only one page is supported for now. Found: " + ", ".join(pages[:6])
                             + ". Keep one index.html and remove the others.")
    entry = pages[0]
    if "/" in entry:
        raise ImportRejected(f"The page must be at the top of the zip (found {entry}). Move it to the top level, keep its folders beside it.")

    errors.extend(_size_checks(files, lim))
    if errors:
        raise ImportRejected(errors)

    findings: list = []
    kept: dict = {}
    skipped: list = []
    for path, body in files.items():
        k = kind_of(path)
        if k == "other":
            skipped.append(path)
            continue
        if not _magic_ok(path, body):
            errors.append(f"{path} is not really a {_ext(path)[1:].upper()} file (its contents do not match).")
            continue
        if path.lower().endswith(".svg"):
            findings.extend(scan.scan_svg(_decode(path, body, findings), path))
        kept[path] = body
    if errors:
        raise ImportRejected(errors)

    notes: list = []
    html_text = _decode(entry, kept[entry], notes)
    findings.extend(notes)
    page = sanitiser.sanitise_page(html_text, kept, hosts, filename=entry)
    findings.extend(page.findings)
    refs = list(page.refs)

    # stylesheets and scripts that are in the upload: scan them all, whether or not the page links them
    css_refs_seen = set()
    for path in [p for p in kept if kind_of(p) == "css"]:
        text = _decode(path, kept[path], findings)
        found, css_refs = scan.scan_css(text, path, hosts)
        findings.extend(found)
        base_dir = posixpath.dirname(path)
        for r in css_refs:
            cls = scan.classify_url(r["url"], hosts)
            entry_ref = {"url": r["url"], "tag": "css", "attr": r["via"], "kind": "style" if r["via"] == "import" else "image",
                         "class": cls, "file": path, "path": None}
            if cls == "local":
                norm = sanitiser.normalise_local(r["url"], base_dir) if not r["url"].startswith("/") else sanitiser.normalise_local(r["url"])
                real = {k.lower(): k for k in kept}.get(norm.lower()) if norm else None
                entry_ref["path"], entry_ref["missing"] = real, real is None
            refs.append(entry_ref)
            css_refs_seen.add(path)
    for path in [p for p in kept if kind_of(p) == "js"]:
        findings.extend(scan.scan_js(_decode(path, kept[path], findings), path, hosts))

    findings, accepted_log = _apply_accepted(findings, accepted)
    errs = [f for f in findings if f["severity"] == "error"]
    warns = [f for f in findings if f["severity"] != "error"]

    # what the page points at
    unknown = [r for r in refs if r["class"] == "external_unknown" and r["kind"] in ("style", "image", "font", "media", "other")]
    allowed_ext = sorted({_host_of(r["url"]) for r in refs if r["class"] == "external_allowed"} - {""})
    missing = sorted({r["url"] for r in refs if r.get("missing")})
    referenced = {r["path"] for r in refs if r.get("path")}
    unreferenced = sorted(p for p in kept if p != entry and p not in referenced
                          and kind_of(p) in ("css", "js", "image", "font"))
    counts = {"files": len(kept), "bytes": sum(len(b) for b in kept.values())}
    for k in ("html", "css", "js", "image", "font", "data"):
        counts[k] = sum(1 for p in kept if kind_of(p) == k)

    report = {
        "ok": not errs, "entry": entry, "counts": counts,
        "errors": errs, "warnings": warns, "accepted": accepted_log,
        "external": {"allowed_hosts_used": allowed_ext, "unknown": unknown[:50]},
        "missing_files": missing[:50], "unreferenced": unreferenced[:100], "skipped": sorted(skipped)[:100],
        "scripts": sorted(set(page.scripts)), "stylesheets": sorted(set(page.stylesheets)),
        "page": {k: v for k, v in page.stats.items()},
    }
    return {"report": report, "html": page.html, "entry": entry, "files": kept}


def _host_of(url: str) -> str:
    try:
        return (scan.urlsplit("https:" + url if url.startswith("//") else url).hostname or "").lower()
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# 3. Saving
# ---------------------------------------------------------------------------

def _content_type(path: str) -> str:
    return {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff": "font/woff",
            ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf", ".svg": "image/svg+xml",
            ".ico": "image/x-icon", ".avif": "image/avif", ".json": "application/json",
            ".txt": "text/plain"}.get(_ext(path)) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def settings_for(settings_row: Optional[dict]) -> dict:
    s = settings_row or {}
    return {"enabled": bool(s.get("site_import_enabled")),
            "allowed_hosts": list(s.get("site_import_allowed_hosts") or scan.DEFAULT_ALLOWED_HOSTS),
            "max_mb": int(s.get("site_import_max_zip_mb") or 25)}


def import_site(db: Any, org_id: str, site: dict, actor: str, data: bytes, filename: str, settings_row: Optional[dict],
                accepted: Optional[dict] = None, dry_run: bool = False) -> dict:
    """Reads, analyses and (unless dry_run) saves an upload as a new, staged 'import' design on the site.
    Raises ImportRejected (nothing saved) or ImportFailed (nothing changed)."""
    cfg = settings_for(settings_row)
    if not cfg["enabled"]:
        raise ImportRejected("Site import is not switched on for this account yet.")
    if site.get("deleted_at") or site.get("status") == "cancelled":
        raise ImportRejected("This site is cancelled or deleted.")

    files = read_upload(data, filename, cfg["max_mb"] * MB)
    result = analyse(files, cfg["allowed_hosts"], accepted)
    report = result["report"]
    if report["errors"]:
        raise ImportRejected([_describe(f) for f in report["errors"]], report)
    if dry_run:
        return {"saved": False, "report": report}

    existing = (db.table("site_designs").select("id, version").eq("site_id", site["id"]).eq("org_id", org_id)
                .execute()).data or []
    version = max((int(r["version"]) for r in existing), default=0) + 1
    token = secrets.token_hex(8)
    prefix = f"{org_id}/{site['id']}/{token}/v{version}"
    raw_ext = ".zip" if data[:2] == b"PK" else ".html"
    source_path = f"{org_id}/{site['id']}/{token}-v{version}{raw_ext}"

    uploaded_files: list = []
    raw_done = False
    manifest = []
    try:
        db.storage.from_(BUCKET_RAW).upload(path=source_path, file=data,
                                            file_options={"content-type": "application/zip" if raw_ext == ".zip" else "text/html",
                                                          "upsert": "false"})
        raw_done = True
        for path, body in sorted(result["files"].items()):
            if path == result["entry"]:
                body_out = result["html"].encode("utf-8")      # the page is stored in the design row, not as a file
                manifest.append({"path": path, "bytes": len(body_out), "sha256": hashlib.sha256(body_out).hexdigest(),
                                 "mime": "text/html", "stored": False})
                continue
            key = f"{prefix}/{path}"
            db.storage.from_(BUCKET_FILES).upload(path=key, file=body,
                                                  file_options={"content-type": _content_type(path), "upsert": "true"})
            uploaded_files.append(key)
            manifest.append({"path": path, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                             "mime": _content_type(path), "stored": True, "storage_path": key})
        row = {
            "org_id": org_id, "site_id": site["id"], "version": version, "kind": "import",
            "parent_id": None,
            "skeleton_html": result["html"], "skeleton_css": "",
            "slot_manifest": {}, "art_direction": {}, "tokens": {},
            "status": "ready", "staged": True, "editable": False,
            "checks": {"import": {"errors": 0, "warnings": len(report["warnings"]),
                                  "scripts": len(report["scripts"]) + report["page"].get("inline_scripts", 0)}},
            "import_meta": {"report": report, "files": manifest, "filename": (filename or "")[:200]},
            "source_path": source_path, "files_prefix": prefix,
            "created_by": actor, "created_at": _now_iso(),
        }
        inserted = _one((db.table("site_designs").insert(row).execute()).data) or {}
        design_id = inserted.get("id")
        if not design_id:
            raise ImportFailed("The design could not be saved. Nothing was changed.")
    except ImportFailed:
        _cleanup(db, uploaded_files, source_path if raw_done else None)
        raise
    except Exception as exc:  # storage or database error: S14, undo what was uploaded
        logger.warning("site_import: save failed site=%s: %s", site.get("id"), exc)
        _cleanup(db, uploaded_files, source_path if raw_done else None)
        raise ImportFailed("The import could not be saved (storage or database problem). Nothing was changed. Try again.")

    _prune(db, org_id, site, keep_id=design_id)
    return {"saved": True, "design_id": design_id, "version": version, "report": report,
            "files": len(manifest), "files_prefix": prefix}


def _describe(f: dict) -> str:
    loc = f"{f['file']}" + (f" line {f['line']}" if f.get("line") else "")
    return f"{loc}: {f['message']}" + (f" ({f['snippet']})" if f.get("snippet") else "")


def _cleanup(db: Any, file_keys: list, raw_key: Optional[str]) -> None:
    try:
        if file_keys:
            db.storage.from_(BUCKET_FILES).remove(file_keys)
        if raw_key:
            db.storage.from_(BUCKET_RAW).remove([raw_key])
    except Exception as exc:  # S14 - housekeeping
        logger.warning("site_import: cleanup failed: %s", exc)


def _prune(db: Any, org_id: str, site: dict, keep_id: str) -> None:
    """Keeps the newest KEEP_IMPORT_VERSIONS import designs (never the current one) and deletes the files of older ones."""
    try:
        rows = (db.table("site_designs").select("id, version, kind, import_meta, source_path")
                .eq("site_id", site["id"]).eq("org_id", org_id).in_("kind", ["import", "import_slot"])
                .execute()).data or []
        rows.sort(key=lambda r: int(r["version"]), reverse=True)
        for old in rows[KEEP_IMPORT_VERSIONS:]:
            if old["id"] in (keep_id, site.get("current_design_id")):
                continue
            keys = [f.get("storage_path") for f in (old.get("import_meta") or {}).get("files", []) if f.get("storage_path")]
            _cleanup(db, keys, old.get("source_path"))
            db.table("site_designs").delete().eq("id", old["id"]).eq("org_id", org_id).execute()
    except Exception as exc:  # S14
        logger.warning("site_import: prune failed site=%s: %s", site.get("id"), exc)


def latest_report(db: Any, org_id: str, site_id: str) -> Optional[dict]:
    row = _one((db.table("site_designs").select("id, version, kind, status, staged, created_at, created_by, import_meta, editable")
                .eq("site_id", site_id).eq("org_id", org_id).in_("kind", ["import", "import_slot"])
                .order("version", desc=True).limit(1).execute()).data)
    if not row:
        return None
    meta = row.get("import_meta") or {}
    return {"design_id": row["id"], "version": row["version"], "kind": row["kind"], "status": row["status"],
            "staged": row["staged"], "editable": row.get("editable", False), "created_at": row["created_at"],
            "created_by": row["created_by"], "report": meta.get("report"), "files": len(meta.get("files", []))}
