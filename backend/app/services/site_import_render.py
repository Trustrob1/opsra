"""
backend/app/services/site_import_render.py
SITE-IMPORT 1b - turns a saved 'import' design into a page.

  render_imported_page()   the cleaned page with a Content-Security-Policy meta tag added.
                           export=True  : addresses are left exactly as the site's author wrote them (the file tree is
                                          published beside index.html at the same paths).
                           export=False : preview. Every address that points at a stored file is rewritten to the
                                          public storage address, so the page shows in the dashboard / on /s/{slug}.
  render_if_imported()     what the four render call sites reach (through site_premium_service.render_if_premium).
                           Never raises: a problem is logged and None is returned (the caller renders Standard).
  export_bundle()          the files to publish / zip for an imported site. RAISES ImportRenderError rather than
                           falling back to Standard, so a broken import is never published as a different site.
  activate() / designs()   make an import design the site's page / list the import designs of a site.

Scripts are kept (scanned in 1a). They only ever run on the client's own domain: the published page carries a CSP
that allows scripts from the page itself and the allow-listed hosts, and the preview is sandboxed (opaque origin).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from app.services import site_import_scan as scan
from app.services import site_import_sanitiser as sanitiser

logger = logging.getLogger(__name__)

BUCKET_FILES = "site-import-files"
EMBED_FRAMES = ("https://www.google.com", "https://maps.google.com", "https://www.youtube-nocookie.com")
FORM_TARGETS = ("https://wa.me", "https://api.whatsapp.com")
_EVAL_RULES = {"eval", "new_function", "string_timer"}


class ImportRenderError(Exception):
    """The import design cannot be turned into a page (missing, unfinished, files gone)."""


def _one(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Content-Security-Policy
# ---------------------------------------------------------------------------

def _hosts(allowed_hosts) -> list:
    out = []
    for h in allowed_hosts or scan.DEFAULT_ALLOWED_HOSTS:
        h = str(h).strip().lower().rstrip(".")
        if h and re.fullmatch(r"[a-z0-9.-]+", h):
            out.append("https://" + h)
            out.append("https://*." + h)
    return out


def build_csp(allowed_hosts, accepted_rules=(), preview_origin: Optional[str] = None) -> str:
    """The policy for a page. Published page: its own files ('self') plus the allow-list. Preview: the files come from the
    storage origin and the page itself has an opaque origin, so that origin is named instead of 'self'."""
    own = [preview_origin] if preview_origin else ["'self'"]
    hosts = _hosts(allowed_hosts)
    script = ["'unsafe-inline'"] + (["'unsafe-eval'"] if set(accepted_rules or ()) & _EVAL_RULES else [])
    parts = [
        "default-src 'none'",
        "script-src " + " ".join(own + script + hosts),
        "style-src " + " ".join(own + ["'unsafe-inline'"] + hosts),
        "img-src " + " ".join(own + ["data:", "blob:"] + hosts),
        "font-src " + " ".join(own + ["data:"] + hosts),
        "media-src " + " ".join(own + ["data:"]),
        "connect-src " + " ".join(own),
        "frame-src " + " ".join(EMBED_FRAMES),
        "form-action " + " ".join(FORM_TARGETS),
        "base-uri 'none'",
        "object-src 'none'",
    ]
    return "; ".join(parts)


def preview_headers(allowed_hosts, preview_origin: Optional[str]) -> dict:
    """Response headers for /s/{slug} when the site is an imported one (scripts run, but in a sandbox)."""
    csp = build_csp(allowed_hosts, preview_origin=preview_origin) + "; sandbox allow-scripts allow-popups; frame-ancestors 'none'"
    return {"Content-Security-Policy": csp, "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


_HEAD_RX = re.compile(r"<head\b[^>]*>", re.I)


def _with_meta(html: str, csp: str, extra_head: str = "") -> str:
    tag = f'<meta http-equiv="Content-Security-Policy" content="{csp.replace(chr(34), "&quot;")}">' + extra_head
    m = _HEAD_RX.search(html)
    if m:
        return html[:m.end()] + tag + html[m.end():]
    m2 = re.search(r"<html\b[^>]*>", html, re.I)
    if m2:
        return html[:m2.end()] + "<head>" + tag + "</head>" + html[m2.end():]
    return "<!doctype html><html><head>" + tag + "</head><body>" + html + "</body></html>"


# ---------------------------------------------------------------------------
# Preview: point stored-file addresses at the public storage address
# ---------------------------------------------------------------------------

_ATTR_RX = re.compile(r"""(\s(?:src|href|poster|srcset|data-src|data-srcset|data-poster|data-bg|xlink:href)\s*=\s*)(["'])(.*?)\2""",
                      re.I | re.S)
_URL_RX = re.compile(r"""url\(\s*(["']?)(.*?)\1\s*\)""", re.I | re.S)
_SCHEME_RX = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def _map_one(url: str, lookup: dict, base: str) -> str:
    u = url.strip()
    if not u or u[0] in "#?" or u.startswith("//") or _SCHEME_RX.match(u):
        return url
    parts = urlsplit(u)
    norm = sanitiser.normalise_local(parts.path if parts.path.startswith("/") else parts.path)
    real = lookup.get((norm or "").lower())
    if not real:
        return url
    out = base.rstrip("/") + "/" + quote(real, safe="/")
    if parts.query:
        out += "?" + parts.query
    if parts.fragment:
        out += "#" + parts.fragment
    return out


def rewrite_for_preview(html: str, stored_paths, base: str) -> str:
    lookup = {p.lower(): p for p in stored_paths}
    if not lookup:
        return html

    def attr(m):
        name, q, val = m.group(1), m.group(2), m.group(3)
        if "srcset" in name.lower():
            items = []
            for item in val.split(","):
                bits = item.strip().split(None, 1)
                if bits:
                    bits[0] = _map_one(bits[0], lookup, base)
                    items.append(" ".join(bits))
            val = ", ".join(items)
        else:
            val = _map_one(val, lookup, base)
        return f"{name}{q}{val}{q}"

    def css(m):
        return f"url({m.group(1)}{_map_one(m.group(2), lookup, base)}{m.group(1)})"

    return _URL_RX.sub(css, _ATTR_RX.sub(attr, html))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _stored_paths(design: dict) -> list:
    return [f["path"] for f in ((design.get("import_meta") or {}).get("files") or []) if f.get("stored")]


def _accepted_rules(design: dict) -> list:
    return [a.get("rule") for a in (((design.get("import_meta") or {}).get("report") or {}).get("accepted") or [])]


def _allowed_hosts(db: Any, org_id: str) -> list:
    try:
        row = _one((db.table("site_builder_settings").select("site_import_allowed_hosts").eq("org_id", org_id)
                    .limit(1).execute()).data)
        hosts = (row or {}).get("site_import_allowed_hosts")
        if hosts:
            return list(hosts)
    except Exception as exc:  # S14: fall back to the default list
        logger.warning("site_import_render: settings read failed org=%s: %s", org_id, exc)
    return list(scan.DEFAULT_ALLOWED_HOSTS)


def public_base(db: Any, design: dict) -> Optional[str]:
    """The public storage address of this design's file folder, no trailing slash."""
    prefix = design.get("files_prefix")
    if not prefix:
        return None
    try:
        url = db.storage.from_(BUCKET_FILES).get_public_url(prefix + "/x")
        url = url if isinstance(url, str) else (url or {}).get("publicUrl") or (url or {}).get("publicURL")
        url = (url or "").split("?")[0]
        return url[:-2] if url.endswith("/x") else None
    except Exception as exc:  # S14
        logger.warning("site_import_render: public url failed design=%s: %s", design.get("id"), exc)
        return None


def render_imported_page(db: Any, design: dict, allowed_hosts, export: bool = False) -> str:
    html = design.get("skeleton_html") or ""
    if not html.strip():
        raise ImportRenderError("The imported design has no page.")
    accepted = _accepted_rules(design)
    if export:
        return _with_meta(html, build_csp(allowed_hosts, accepted))
    base = public_base(db, design)
    if not base:
        raise ImportRenderError("The imported files could not be located.")
    origin = "{u.scheme}://{u.netloc}".format(u=urlsplit(base))
    return _with_meta(rewrite_for_preview(html, _stored_paths(design), base), build_csp(allowed_hosts, accepted, origin))


def _current_design(db: Any, site: dict, design_id: Optional[str] = None) -> Optional[dict]:
    did = design_id or site.get("current_design_id")
    if not did:
        return None
    return _one((db.table("site_designs").select("*").eq("id", did).eq("site_id", site["id"])
                 .eq("org_id", site["org_id"]).eq("kind", "import").eq("status", "ready").limit(1).execute()).data)


def render_if_imported(db: Any, site: dict, assets_by_id: dict, export: bool = False,
                       canonical_domain: Optional[str] = None) -> Optional[str]:
    """None when the site is not an imported one or its design cannot be used (the caller renders Standard)."""
    if (site.get("tier") or "standard") != "imported":
        return None
    try:
        design = _current_design(db, site)
        if not design:
            logger.warning("site_import_render: design missing for site %s - rendering Standard", site.get("id"))
            return None
        return render_imported_page(db, design, _allowed_hosts(db, site["org_id"]), export=export)
    except Exception as exc:  # S14
        logger.warning("site_import_render: render failed site=%s: %s", site.get("id"), exc)
        return None


def preview_design(db: Any, org_id: str, site: dict, design_id: str) -> str:
    design = _current_design(db, {"id": site["id"], "org_id": org_id}, design_id)
    if not design:
        raise ImportRenderError("Imported design not found.")
    return render_imported_page(db, design, _allowed_hosts(db, org_id), export=False)


# ---------------------------------------------------------------------------
# Export / publish
# ---------------------------------------------------------------------------

def export_bundle(db: Any, site: dict) -> list:
    """[(path, bytes_or_str)] for an imported site: the page as index.html and every stored file at its own path.
    Raises ImportRenderError when anything is missing."""
    design = _current_design(db, site)
    if not design:
        raise ImportRenderError("This site's imported design is missing. Open the Import panel and choose a design.")
    files = [("index.html", render_imported_page(db, design, _allowed_hosts(db, site["org_id"]), export=True))]
    for f in ((design.get("import_meta") or {}).get("files") or []):
        if not f.get("stored"):
            continue
        try:
            body = db.storage.from_(BUCKET_FILES).download(f["storage_path"])
        except Exception as exc:
            logger.warning("site_import_render: export download failed %s: %s", f.get("storage_path"), exc)
            raise ImportRenderError(f"A file of the imported site could not be read ({f.get('path')}). Nothing was published.")
        if f["path"].lower() == "index.html":
            continue
        files.append((f["path"], body))
    return files


# ---------------------------------------------------------------------------
# Activation / listing
# ---------------------------------------------------------------------------

def designs(db: Any, org_id: str, site: dict) -> list:
    rows = (db.table("site_designs").select("id, version, kind, status, staged, created_by, created_at, checks, import_meta")
            .eq("site_id", site["id"]).eq("org_id", org_id).eq("kind", "import").order("version", desc=True)
            .execute()).data or []
    out = []
    for r in rows:
        meta = r.get("import_meta") or {}
        rep = meta.get("report") or {}
        out.append({"id": r["id"], "version": r.get("version"), "status": r.get("status"), "staged": bool(r.get("staged")),
                    "created_at": r.get("created_at"), "created_by": r.get("created_by"), "filename": meta.get("filename"),
                    "active": r["id"] == site.get("current_design_id") and site.get("tier") == "imported",
                    "counts": rep.get("counts"), "warnings": len(rep.get("warnings") or []),
                    "scripts": len(rep.get("scripts") or []) + (rep.get("page") or {}).get("inline_scripts", 0),
                    "external_unknown": len((rep.get("external") or {}).get("unknown") or []),
                    "missing_files": len(rep.get("missing_files") or [])})
    return out


def activate(db: Any, org_id: str, site: dict, design_id: str) -> dict:
    row = _current_design(db, {"id": site["id"], "org_id": org_id}, design_id)
    if not row:
        raise ImportRenderError("Imported design not found.")
    db.table("sites").update({"tier": "imported", "current_design_id": row["id"], "updated_at": _now_iso()}) \
        .eq("id", site["id"]).eq("org_id", org_id).execute()
    db.table("site_designs").update({"staged": False}).eq("id", row["id"]).eq("org_id", org_id).execute()
    return row
