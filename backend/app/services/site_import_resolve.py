"""
backend/app/services/site_import_resolve.py
SITE-IMPORT 1b - "keep a copy": pictures, stylesheets and fonts that an uploaded page loads from other websites
(not on the allow-list) are downloaded once, checked, stored with the site's own files and the page is pointed at the
copy. After that the page does not depend on those websites, and the published page's security policy does not need
to allow them.

Only files the PAGE points at are resolved (<img>, <link rel=stylesheet>, srcset, inline style url()). A stylesheet
that itself pulls unlisted files, or an unlisted address inside a stylesheet / script, is left as it is and reported.

The download is SSRF-safe: https only, port 443, no credentials in the address, every address of the host must be a
public one (checked for every redirect hop too), size and time capped, content checked against its real bytes.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import socket
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlsplit

from app.services import site_import_scan as scan
from app.services import site_import_service as svc

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 25
MAX_REDIRECTS = 3
TIMEOUT_S = 10.0

_EXT_BY_TYPE = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif",
    "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
    "text/css": ".css", "font/woff": ".woff", "font/woff2": ".woff2", "font/ttf": ".ttf", "font/otf": ".otf",
    "application/font-woff": ".woff", "application/font-woff2": ".woff2",
}
_OK_NESTED = {"data", "external_allowed", "empty", "anchor"}


class FetchError(Exception):
    pass


def _check_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchError("the address could not be found")
    if not infos:
        raise FetchError("the address could not be found")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError("the address points to a private network")


def _check_url(url: str) -> str:
    u = ("https:" + url) if url.startswith("//") else url
    p = urlsplit(u)
    if p.scheme != "https" or not p.hostname:
        raise FetchError("only https addresses can be copied")
    if p.username or p.password:
        raise FetchError("addresses with a login are not copied")
    if p.port not in (None, 443):
        raise FetchError("only the standard https port is allowed")
    _check_host(p.hostname)
    return u


def safe_fetch(url: str, max_bytes: int = MAX_FILE_BYTES) -> tuple:
    """(bytes, content_type) or FetchError. Follows up to MAX_REDIRECTS redirects, re-checking every hop."""
    import httpx
    current = _check_url(url)
    with httpx.Client(follow_redirects=False, timeout=TIMEOUT_S, headers={"User-Agent": "OpsraImport/1.0", "Accept": "*/*"}) as c:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with c.stream("GET", current) as r:
                    if 300 <= r.status_code < 400 and r.headers.get("location"):
                        current = _check_url(urljoin(current, r.headers["location"]))
                        continue
                    if r.status_code != 200:
                        raise FetchError(f"the site answered {r.status_code}")
                    declared = r.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError("the file is too large")
                    chunks, total = [], 0
                    for chunk in r.iter_bytes(65536):
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError("the file is too large")
                        chunks.append(chunk)
                    return b"".join(chunks), (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            except httpx.HTTPError:
                raise FetchError("the download failed")
    raise FetchError("too many redirects")


def _sniff_ext(body: bytes) -> Optional[str]:
    for sig, ext in ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"), (b"wOF2", ".woff2"),
                     (b"wOFF", ".woff"), (b"OTTO", ".otf"), (b"\x00\x01\x00\x00", ".ttf")):
        if body.startswith(sig):
            return ext
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return ".webp"
    return None


def _check_file(url: str, body: bytes, ctype: str, hosts) -> tuple:
    """(extension, body) when the copy is acceptable; FetchError (plain-words reason) when not."""
    ext = _EXT_BY_TYPE.get(ctype) or _sniff_ext(body)
    if not ext:
        raise FetchError(f"it is a type that cannot be hosted ({ctype or 'unknown'})")
    if ext in (".png", ".jpg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf") and not svc._magic_ok("x" + ext, body):
        raise FetchError("its contents do not match what it claims to be")
    if ext == ".svg":
        if [f for f in scan.scan_svg(body.decode("utf-8", "replace"), url) if f["severity"] == "error"]:
            raise FetchError("the picture contains active content")
    if ext == ".css":
        text = body.decode("utf-8", "replace")
        found, refs = scan.scan_css(text, url, hosts)
        if [f for f in found if f["severity"] == "error"]:
            raise FetchError("the stylesheet contains something that is not allowed")
        if any(scan.classify_url(r["url"], hosts) not in _OK_NESTED for r in refs):
            raise FetchError("the stylesheet loads further files from other sites")
    return ext, body


def _replace_url(html: str, url: str, new: str) -> str:
    """Replace `url` only where it is an address: inside quotes, url(...) or a srcset list."""
    variants = {url, url.replace("&", "&amp;")}
    for v in variants:
        rx = re.compile(r"""(?P<pre>["'(=,\s])""" + re.escape(v) + r"""(?P<post>["')\s,])""")
        html = rx.sub(lambda m: m.group("pre") + new + m.group("post"), html)
    return html


def resolve(db: Any, org_id: str, site: dict, design_id: str, allowed_hosts, fetcher: Optional[Callable] = None) -> dict:
    """Copy the unlisted external files the page uses. Returns {resolved: [{url, path}], failed: [{url, reason}], remaining}."""
    fetcher = fetcher or safe_fetch
    row = (db.table("site_designs").select("*").eq("id", design_id).eq("site_id", site["id"]).eq("org_id", org_id)
           .eq("kind", "import").eq("status", "ready").limit(1).execute()).data
    row = row[0] if isinstance(row, list) and row else (row if isinstance(row, dict) else None)
    if not row or not row.get("files_prefix"):
        raise svc.ImportRejected("Imported design not found.")
    meta = row.get("import_meta") or {}
    report = meta.get("report") or {}
    entry = report.get("entry") or "index.html"
    unknown = (report.get("external") or {}).get("unknown") or []
    page_refs = [r for r in unknown if r.get("file") == entry and r.get("tag") != "css"]
    urls = []
    for r in page_refs:
        if r["url"] not in urls:
            urls.append(r["url"])
    skipped = [r for r in unknown if r not in page_refs]
    files = list(meta.get("files") or [])
    prefix = row["files_prefix"]
    html = row["skeleton_html"]
    resolved, failed, uploaded = [], [], []
    for url in urls[:MAX_FILES]:
        try:
            body, ctype = fetcher(url)
            ext, body = _check_file(url, body, ctype, allowed_hosts)
        except FetchError as exc:
            failed.append({"url": url, "reason": str(exc)})
            continue
        digest = hashlib.sha256(body).hexdigest()
        path = f"external/{digest[:16]}{ext}"
        key = f"{prefix}/{path}"
        try:
            if not any(f.get("path") == path for f in files):
                db.storage.from_(svc.BUCKET_FILES).upload(path=key, file=body,
                                                          file_options={"content-type": svc._content_type(path), "upsert": "true"})
                uploaded.append(key)
                files.append({"path": path, "bytes": len(body), "sha256": digest, "mime": svc._content_type(path),
                              "stored": True, "storage_path": key, "source_url": url[:500]})
        except Exception as exc:  # S14
            logger.warning("site_import_resolve: upload failed %s: %s", key, exc)
            failed.append({"url": url, "reason": "it could not be saved"})
            continue
        html = _replace_url(html, url, path)
        resolved.append({"url": url, "path": path})
    for url in urls[MAX_FILES:]:
        failed.append({"url": url, "reason": f"only {MAX_FILES} files are copied at a time; run it again"})

    if resolved:
        done = {r["url"] for r in resolved}
        report = {**report}
        ext_block = dict(report.get("external") or {})
        ext_block["unknown"] = [r for r in unknown if r.get("url") not in done]
        report["external"] = ext_block
        report["resolved"] = (report.get("resolved") or []) + resolved
        try:
            db.table("site_designs").update({"skeleton_html": html, "import_meta": {**meta, "report": report, "files": files}}) \
                .eq("id", row["id"]).eq("org_id", org_id).execute()
        except Exception as exc:  # S14: undo the uploaded copies, change nothing
            logger.warning("site_import_resolve: save failed design=%s: %s", row["id"], exc)
            svc._cleanup(db, uploaded, None)
            raise svc.ImportFailed("The copies could not be saved. Nothing was changed. Try again.")
    return {"resolved": resolved, "failed": failed,
            "remaining": len(unknown) - len(resolved), "not_resolvable": len(skipped)}
