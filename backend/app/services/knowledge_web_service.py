"""
app/services/knowledge_web_service.py
-------------------------------------
WA-AUTO-4b - knowledge from a website address or a public Google Doc.

Reading is polite and bounded: https only, public addresses only (the same SSRF-safe download SITE-IMPORT uses), the same website
only, robots.txt respected, at most MAX_PAGES pages, a time budget, and a size limit on every download. The pages are turned into
plain text (no scripts, styles or repeated menus) and cut into chunks like any other source; the owner then previews it and presses
"Start using this". Nothing here calls an AI model.
"""
from __future__ import annotations

import logging
import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from app.services import knowledge_service as ks
from app.services.site_import_resolve import FetchError, safe_fetch

logger = logging.getLogger(__name__)

MAX_PAGES = 20
MAX_PAGE_BYTES = 1_500_000
TIME_BUDGET_S = 45.0
_SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".mp4", ".mp3", ".css", ".js", ".xml", ".json",
             ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".woff", ".woff2")
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "main", "header", "footer", "nav", "aside",
               "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "form", "address", "dt", "dd"}
_HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.links, self._parts, self._skip, self._in_title = "", [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS and tag != "head":
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt and not self._skip:
                self._parts.append(f" {alt} ")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and tag != "head" and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.split("\n")]
        return "\n".join(ln for ln in lines if ln)


def parse_html(body: bytes) -> tuple:
    """(title, text, links) from a page. Never raises."""
    try:
        html = body.decode("utf-8", errors="replace")
        p = _Page()
        p.feed(html)
        return " ".join(p.title.split())[:200], p.text(), p.links
    except Exception as exc:
        logger.warning("knowledge_web: could not parse a page: %s", exc)
        return "", "", []


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def normalise(url: str) -> str:
    u, _ = urldefrag(url.strip())
    p = urlsplit(u)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query and len(p.query) < 40 else "")


def clean_start_url(raw: str) -> str:
    """The address the owner typed, as an https address. Raises ValueError with a plain message."""
    u = (raw or "").strip()
    if not u or len(u) > 500 or any(ch.isspace() for ch in u):
        raise ValueError("Enter your website address, for example https://www.yourshop.com")
    if "://" not in u:
        u = "https://" + u
    p = urlsplit(u)
    if p.scheme != "https":
        raise ValueError("The address must start with https://")
    if not p.hostname or "." not in p.hostname or p.username or p.password:
        raise ValueError("Enter your website address, for example https://www.yourshop.com")
    return normalise(u)


def gdoc_export_url(raw: str) -> str:
    """The plain-text download address of a Google Doc link. Raises ValueError with a plain message."""
    m = re.match(r"^https://docs\.google\.com/document/d/([A-Za-z0-9_-]{20,})", (raw or "").strip())
    if not m:
        raise ValueError("Paste the link of a Google Doc (it starts with https://docs.google.com/document/d/).")
    return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"


def _link_ok(url: str, start_host: str) -> bool:
    p = urlsplit(url)
    return (p.scheme == "https" and _host(url) == start_host and not p.path.lower().endswith(_SKIP_EXT)
            and not (p.username or p.password))


def _sitemap_urls(fetch: Callable, base: str, start_host: str, deadline: float) -> list:
    found: list = []
    try:
        body, _ = fetch(urljoin(base, "/sitemap.xml"), 1_000_000)
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body.decode("utf-8", errors="replace"))
        nested = [u for u in locs if u.lower().endswith(".xml")][:2]
        found = [u for u in locs if not u.lower().endswith(".xml")]
        for n in nested:
            if time.monotonic() > deadline:
                break
            try:
                b2, _ = fetch(n, 1_000_000)
                found += [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", b2.decode("utf-8", errors="replace")) if not u.lower().endswith(".xml")]
            except FetchError:
                continue
    except FetchError:
        pass
    return [unescape(u) for u in found if _link_ok(unescape(u), start_host)]


def _robots(fetch: Callable, base: str) -> Optional[RobotFileParser]:
    try:
        body, _ = fetch(urljoin(base, "/robots.txt"), 200_000)
        rp = RobotFileParser()
        rp.parse(body.decode("utf-8", errors="replace").splitlines())
        return rp
    except FetchError:
        return None


def crawl(start_url: str, fetch: Callable = safe_fetch, max_pages: int = MAX_PAGES, budget_s: float = TIME_BUDGET_S) -> list:
    """Reads the start page, then pages from the sitemap and the start page's links, on the same website only.
    Returns [{url, title, text}]. Raises FetchError only when the start page itself cannot be read."""
    deadline = time.monotonic() + budget_s
    start_host = _host(start_url)
    robots = _robots(fetch, start_url)
    allowed = lambda u: robots is None or robots.can_fetch("*", u)      # noqa: E731
    queue, seen, pages = [start_url], {start_url}, []

    def add(urls):
        for u in urls:
            n = normalise(urljoin(start_url, u))
            if n not in seen and _link_ok(n, start_host):
                seen.add(n); queue.append(n)

    first = True
    while queue and len(pages) < max_pages and time.monotonic() < deadline:
        url = queue.pop(0)
        if not allowed(url):
            if first:
                raise FetchError("this website asks not to be read by automatic tools")
            continue
        try:
            body, ctype = fetch(url, MAX_PAGE_BYTES)
        except FetchError:
            if first:
                raise
            continue
        if ctype and ctype not in _HTML_TYPES:
            if first:
                raise FetchError("that address is not a web page")
            continue
        title, text, links = parse_html(body)
        if text:
            pages.append({"url": url, "title": title, "text": text})
        if first:
            add(_sitemap_urls(fetch, start_url, start_host, deadline))
            first = False
        add(links)
    return pages


def assemble(pages: list) -> str:
    """One text for the whole website: a heading per page, and any line already seen on an earlier page (menus, footers) is dropped."""
    seen, out = set(), []
    for pg in pages:
        lines = []
        for ln in pg["text"].split("\n"):
            key = ln.lower()
            if len(ln) < 60 and key in seen:
                continue
            seen.add(key)
            lines.append(ln)
        if lines:
            out.append(f"{pg['title'] or pg['url']} ({pg['url']})\n" + "\n".join(lines))
    return "\n\n".join(out)


# -- jobs run after the request has returned ---------------------------------------------------------------------------
def run_website(db: Any, org_id: str, source_id: str, start_url: str, fetch: Callable = safe_fetch) -> None:
    try:
        pages = crawl(start_url, fetch)
        text = assemble(pages)
        if len(text) < 20:
            raise FetchError("no readable text was found on that website")
        ks.fill_source(db, org_id, source_id, text, page_count=len(pages))
    except FetchError as exc:
        ks.mark_failed(db, org_id, source_id, f"We could not read that website: {exc}. Check the address and try again.")
    except Exception as exc:     # includes HTTPException from fill_source
        detail = getattr(exc, "detail", None)
        msg = detail.get("message") if isinstance(detail, dict) else None
        if not msg:
            logger.warning("knowledge_web: website read failed org=%s: %s", org_id, exc)
        ks.mark_failed(db, org_id, source_id, msg or "Something went wrong while reading that website. Please try again.")


def run_gdoc(db: Any, org_id: str, source_id: str, export_url: str, fetch: Callable = safe_fetch) -> None:
    try:
        body, ctype = fetch(export_url, 5 * 1024 * 1024)
        if ctype and not ctype.startswith("text/plain"):
            raise FetchError("the document is not shared with everyone who has the link")
        ks.fill_source(db, org_id, source_id, body.decode("utf-8", errors="replace"), page_count=1)
    except FetchError as exc:
        ks.mark_failed(db, org_id, source_id,
                       f"We could not read that Google Doc: {exc}. In Google Docs choose Share, then set General access to Anyone with the link (Viewer).")
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        msg = detail.get("message") if isinstance(detail, dict) else None
        if not msg:
            logger.warning("knowledge_web: gdoc read failed org=%s: %s", org_id, exc)
        ks.mark_failed(db, org_id, source_id, msg or "Something went wrong while reading that document. Please try again.")
