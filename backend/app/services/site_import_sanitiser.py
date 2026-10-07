"""
app/services/site_import_sanitiser.py
--------------------------------------
SITE-IMPORT 1a: the import profile for an uploaded page (spec sections 4, 6, 7, 17).

This is NOT the Premium sanitiser and shares none of its allow-lists: Premium strips every script, an import
keeps them (they run on the client's own domain only). Nothing here may call or change site_premium_sanitiser.

What it does, in one pass over the page with the standard-library tokeniser (never regex on markup):
  * removes what can never be hosted safely: <base>, <object>, <embed>, <applet>, frames, <portal>, <meta http-equiv>,
    iframes that are not on the embed allow-list, javascript:/vbscript: addresses, srcdoc, form targets, comments;
  * removes what Opsra writes itself in the live page: <link rel=canonical>, <meta name=robots>;
  * keeps scripts and event handlers, but scans every one (inline scripts, handlers, style blocks, style attributes);
  * lists every file the page points at (refs) and says whether it is in the upload, on the allow-list, or unknown;
  * records findings (errors stop the import, warnings are shown to staff).

The output is the whole cleaned document, with the page's own relative addresses left as written.
Addresses are resolved to stored files at render time (IMPORT-1b), so the same markup works in preview and export.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Iterable, Optional
from urllib.parse import unquote, urlsplit

from app.services import site_import_scan as scan

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
DROP_WITH_CONTENT = frozenset({"object", "embed", "applet", "frame", "frameset", "noembed", "portal", "foreignobject"})
DROP_VOID = frozenset({"base", "param"})
# iframes are kept only for these embeds (spec section 4 / DI-3).
EMBED_HOSTS = ("www.google.com", "maps.google.com", "www.youtube-nocookie.com")
EMBED_PATH_PREFIX = {"www.google.com": "/maps/embed"}

LINK_RELS_KEPT = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "apple-touch-icon-precomposed", "mask-icon",
                  "preload", "prefetch", "preconnect", "dns-prefetch", "modulepreload"}
SCRIPT_TYPES_KEPT = {"", "module", "text/javascript", "application/javascript", "application/x-javascript",
                     "text/ecmascript", "application/ecmascript", "application/ld+json", "importmap"}
INERT_SCRIPT = ("application/ld+json", "importmap")

# attribute -> kind of file it loads
URL_ATTRS = {"src": "src", "href": "href", "poster": "image", "data-src": "image", "data-bg": "image",
             "data-background": "image", "data-poster": "image", "data-lazy-src": "image", "data-original": "image",
             "xlink:href": "href", "action": "action", "formaction": "action", "background": "image", "longdesc": "other"}
SRCSET_ATTRS = {"srcset", "data-srcset", "imagesrcset"}

MAX_DATA_URL = 300_000
_DATA_OK = re.compile(r"^data:(?:image/[a-z0-9.+-]+|font/[a-z0-9.+-]+|application/(?:font-woff2?|x-font-[a-z0-9-]+))[;,]", re.I)
_NOOP_JS_URL = re.compile(r"^javascript:\s*(?:void\s*\(\s*0?\s*\)\s*;?|;?|0;?|false;?|undefined;?)?\s*$", re.I)


@dataclass
class SanitiseResult:
    html: str
    findings: list = field(default_factory=list)
    refs: list = field(default_factory=list)          # [{url, tag, attr, kind, class, path, file}]
    scripts: list = field(default_factory=list)       # local script paths
    stylesheets: list = field(default_factory=list)   # local stylesheet paths
    stats: dict = field(default_factory=dict)


def normalise_local(url: str, base_dir: str = "") -> Optional[str]:
    """'css/app.css?v=3#x' relative to base_dir -> 'css/app.css'; '/img/a.png' -> 'img/a.png'.
    None when it climbs above the site root."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    path = unquote(parts.path)
    if not path:
        return None
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        joined = posixpath.join(base_dir, path) if base_dir else path
    norm = posixpath.normpath(joined)
    if norm.startswith("..") or norm in (".", ""):
        return None
    return norm


def parse_srcset(value: str) -> list:
    out = []
    for item in (value or "").split(","):
        item = item.strip()
        if item:
            out.append(item.split()[0])
    return out


class _Sanitiser(HTMLParser):
    def __init__(self, files: dict, allowed_hosts: Iterable[str], filename: str):
        super().__init__(convert_charrefs=False)
        self.files = {k.lower(): k for k in files}
        self.hosts = tuple(allowed_hosts)
        self.filename = filename
        self.out: list = []
        self.findings: list = []
        self.refs: list = []
        self.scripts: list = []
        self.stylesheets: list = []
        self.skip_tag: Optional[str] = None
        self.skip_depth = 0
        self.script_buf: Optional[list] = None
        self.script_attrs: dict = {}
        self.style_buf: Optional[list] = None
        self.in_svg = 0
        self.stats = {"inline_scripts": 0, "inline_styles": 0, "handlers": 0, "forms": 0, "iframes_removed": 0,
                      "iframes_kept": 0, "removed": [], "has_viewport": False, "has_doctype": False, "noindex_removed": False}

    # -- findings -----------------------------------------------------------
    def _add(self, rule: str, snippet: str = "", message: Optional[str] = None, severity: Optional[str] = None) -> None:
        f = scan.finding(rule, self.filename, self.getpos()[0], snippet, message)
        if severity:
            f["severity"] = severity
        self.findings.append(f)

    def _note(self, severity: str, rule: str, message: str, snippet: str = "") -> None:
        self.findings.append({"rule": rule, "severity": severity, "file": self.filename, "line": self.getpos()[0],
                              "message": message, "snippet": snippet[:160], "overridable": False})

    def _removed(self, what: str) -> None:
        self.stats["removed"].append(what)

    # -- references ---------------------------------------------------------
    def _ref(self, url: str, tag: str, attr: str, kind: str) -> str:
        """Records a reference and returns its class."""
        cls = scan.classify_url(url, self.hosts)
        entry = {"url": url, "tag": tag, "attr": attr, "kind": kind, "class": cls, "file": self.filename, "path": None}
        if cls == "local":
            path = normalise_local(url)
            entry["path"] = self.files.get(path.lower()) if path else None
            entry["missing"] = entry["path"] is None
        self.refs.append(entry)
        return cls

    # -- tokeniser callbacks --------------------------------------------------
    def handle_decl(self, decl):
        if not self.out and decl.lower().startswith("doctype"):
            self.stats["has_doctype"] = True
            self.out.append("<!doctype html>")

    def unknown_decl(self, data):    # <![CDATA[ ... ]]> and IE conditional blocks
        return

    def handle_pi(self, data):       # <?xml ... ?>
        return

    def handle_comment(self, data):
        return

    def handle_entityref(self, name):
        self._text(f"&{name};")

    def handle_charref(self, name):
        self._text(f"&#{name};")

    def handle_data(self, data):
        if self.skip_tag:
            return
        if self.script_buf is not None:
            self.script_buf.append(data)
            return
        if self.style_buf is not None:
            self.style_buf.append(data)
            return
        self.out.append(data)

    def _text(self, s: str) -> None:
        if self.skip_tag or self.script_buf is not None or self.style_buf is not None:
            if self.script_buf is not None:
                self.script_buf.append(s)
            elif self.style_buf is not None:
                self.style_buf.append(s)
            return
        self.out.append(s)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, selfclose=True)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, selfclose=False)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth <= 0:
                    self.skip_tag, self.skip_depth = None, 0
            return
        if tag == "script" and self.script_buf is not None:
            self._finish_script()
            return
        if tag == "style" and self.style_buf is not None:
            self._finish_style()
            return
        if tag == "svg" and self.in_svg:
            self.in_svg -= 1
        if tag in VOID:
            return
        self.out.append(f"</{tag}>")

    def close(self):
        super().close()
        if self.script_buf is not None:
            self._finish_script()
        if self.style_buf is not None:
            self._finish_style()

    # -- element handling -----------------------------------------------------
    def _start(self, tag: str, attrs: list, selfclose: bool) -> None:
        tag = tag.lower()
        if self.skip_tag:
            if tag == self.skip_tag and not selfclose and tag not in VOID:
                self.skip_depth += 1
            return
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        flags = {k.lower() for k, v in attrs if v is None}

        if tag in DROP_VOID:
            self._removed(f"<{tag}>")
            return
        if tag in DROP_WITH_CONTENT:
            self._removed(f"<{tag}>")
            if tag == "foreignobject":
                self._note("warning", "foreignobject_removed", "An SVG foreignObject was removed.")
            if not selfclose and tag not in VOID:
                self.skip_tag, self.skip_depth = tag, 1
            return
        if tag == "meta":
            return self._meta(a, selfclose)
        if tag == "link":
            return self._link(a, selfclose)
        if tag == "script":
            return self._script(a, selfclose)
        if tag == "style":
            self.style_buf = []
            self.style_line = self.getpos()[0]
            self.stats["inline_styles"] += 1
            self.out.append("<style" + self._attrs(tag, a, flags, scan_only={"media", "type", "nonce"}) + ">")
            if selfclose:
                self._finish_style()
            return
        if tag == "iframe":
            return self._iframe(a, selfclose)
        if tag == "svg":
            self.in_svg += 1
        if tag == "form":
            self.stats["forms"] += 1
        if tag in ("input", "button") and a.get("formaction"):
            pass
        attr_s = self._attrs(tag, a, flags)
        if tag in VOID:
            self.out.append(f"<{tag}{attr_s}>")
        elif selfclose:
            self.out.append(f"<{tag}{attr_s}></{tag}>" if not self.in_svg else f"<{tag}{attr_s}/>")
        else:
            self.out.append(f"<{tag}{attr_s}>")

    def _meta(self, a: dict, selfclose: bool) -> None:
        name = a.get("name", "").lower()
        if a.get("http-equiv"):
            self._removed("<meta http-equiv>")
            if a["http-equiv"].lower() == "refresh":
                self._note("warning", "meta_refresh_removed", "A meta refresh (automatic redirect) was removed.", a.get("content", ""))
            return
        if name == "robots":
            self._removed("<meta name=robots>")
            if "noindex" in a.get("content", "").lower():
                self.stats["noindex_removed"] = True
                self._note("warning", "noindex_removed",
                           "The page said noindex. It was removed so the live site can be found by search engines.")
            return
        if name == "viewport":
            self.stats["has_viewport"] = True
        self.out.append("<meta" + self._attrs("meta", a, set()) + ">")

    def _link(self, a: dict, selfclose: bool) -> None:
        rels = set(a.get("rel", "").lower().split())
        href = a.get("href", "")
        if "canonical" in rels:
            self._removed("<link rel=canonical>")
            return
        if not rels & LINK_RELS_KEPT:
            self._removed(f"<link rel={a.get('rel', '')}>")
            return
        kind = "style" if "stylesheet" in rels else ("font" if "preload" in rels and a.get("as") == "font" else "link")
        if href:
            cls = self._ref(href, "link", "href", kind)
            if cls == "js_scheme":
                self._removed("<link javascript:>")
                return
            if cls == "local" and "stylesheet" in rels:
                path = self.refs[-1]["path"]
                if path:
                    self.stylesheets.append(path)
        self.out.append("<link" + self._attrs("link", a, set(), skip_urls={"href"}) + ">")

    def _script(self, a: dict, selfclose: bool) -> None:
        stype = a.get("type", "").lower().split(";")[0].strip()
        if stype not in SCRIPT_TYPES_KEPT and not (stype.startswith("text/") and "javascript" not in stype):
            # unknown script types (text/template, text/x-handlebars...) are inert data; keep without scanning
            pass
        src = a.get("src", "")
        if src:
            cls = self._ref(src, "script", "src", "script")
            if cls == "local":
                path = self.refs[-1]["path"]
                if path:
                    self.scripts.append(path)
            elif cls == "external_unknown":
                self._add("remote_import", src, f"Script loaded from a host that is not on the allow-list: {src}")
            elif cls in ("js_scheme", "data"):
                self._removed("<script src=data/javascript>")
                return
        self.stats["inline_scripts"] += 0 if src else 1
        self.script_buf = []
        self.script_attrs = {"type": stype, "src": src, "n": self.stats["inline_scripts"], "line": self.getpos()[0]}
        self.out.append("<script" + self._attrs("script", a, set(), skip_urls={"src"}) + ">")
        if selfclose:
            self._finish_script()

    def _finish_script(self) -> None:
        body = "".join(self.script_buf or [])
        meta = self.script_attrs
        self.script_buf = None
        if not meta.get("src") and body.strip() and meta.get("type") not in INERT_SCRIPT:
            label = f"{self.filename} (inline script {meta.get('n', 1)})"
            if meta.get("type") == "" or meta.get("type") in SCRIPT_TYPES_KEPT:
                start = meta.get("line", 1)
                for f in scan.scan_js(body, label, self.hosts):
                    f["line"] = start + f["line"] - 1
                    self.findings.append(f)
        # never let the script text close its own tag
        self.out.append(re.sub(r"</(script)", r"<\\/\1", body, flags=re.I))
        self.out.append("</script>")

    def _finish_style(self) -> None:
        body = "".join(self.style_buf or [])
        self.style_buf = None
        label = f"{self.filename} (style block)"
        found, refs = scan.scan_css(body, label, self.hosts)
        for f in found:
            f["line"] = getattr(self, "style_line", 1)
        self.findings.extend(found)
        for r in refs:
            self._css_ref(r["url"], "style", r["via"])
        self.out.append(re.sub(r"</(style)", r"<\\/\1", body, flags=re.I))
        self.out.append("</style>")

    def _css_ref(self, url: str, tag: str, via: str) -> None:
        kind = "style" if via == "import" else "image"
        cls = self._ref(url, tag, via, kind)
        if cls == "local":
            path = self.refs[-1]["path"]
            if path and via == "import":
                self.stylesheets.append(path)

    def _iframe(self, a: dict, selfclose: bool) -> None:
        src = a.get("src", "")
        ok = False
        try:
            u = urlsplit("https:" + src if src.startswith("//") else src)
            host = (u.hostname or "").lower()
            ok = (u.scheme in ("https", "") and host in EMBED_HOSTS
                  and u.path.startswith(EMBED_PATH_PREFIX.get(host, "/")))
        except ValueError:
            ok = False
        if not ok:
            self.stats["iframes_removed"] += 1
            self._removed("<iframe>")
            self._note("warning", "iframe_removed", "An iframe was removed (only Google Maps and YouTube embeds are kept).", src)
            if not selfclose:
                self.skip_tag, self.skip_depth = "iframe", 1
            return
        self.stats["iframes_kept"] += 1
        a = dict(a)
        a.pop("srcdoc", None)
        a.setdefault("referrerpolicy", "no-referrer")
        self._ref(src, "iframe", "src", "frame")
        self.out.append("<iframe" + self._attrs("iframe", a, set(), skip_urls={"src"}) + ">")
        if selfclose:
            self.out.append("</iframe>")

    # -- attributes -----------------------------------------------------------
    def _attrs(self, tag: str, a: dict, flags: set, skip_urls: Iterable[str] = (), scan_only: Iterable[str] = ()) -> str:
        parts = []
        skip = set(skip_urls)
        for name, value in a.items():
            if name == "srcdoc":
                self._removed("srcdoc")
                continue
            if name.startswith("on") and len(name) > 2:
                self.stats["handlers"] += 1
                label = f"{self.filename} ({name} on <{tag}>)"
                self.findings.extend(scan.scan_js(value, label, self.hosts))
                parts.append(f' {name}="{escape(value, quote=True)}"')
                continue
            if name in ("action", "formaction"):
                if value:
                    self._note("warning", "form_action_removed",
                               "A form address was removed: forms cannot post on a hosted page (use a WhatsApp link).", value)
                self._removed(f"{name}")
                continue
            if name == "style" and value:
                found, refs = scan.scan_css("x{" + value + "}", f"{self.filename} (style attribute on <{tag}>)", self.hosts)
                self.findings.extend(found)
                for r in refs:
                    self._css_ref(r["url"], tag, r["via"])
            if name in SRCSET_ATTRS:
                for u in parse_srcset(value):
                    self._ref(u, tag, name, "image")
                parts.append(f' {name}="{escape(value, quote=True)}"')
                continue
            if name in URL_ATTRS and name not in skip:
                cls = scan.classify_url(value, self.hosts)
                if cls == "js_scheme":
                    if tag == "a" and _NOOP_JS_URL.match(re.sub(r"[\x00-\x20]+", " ", value).strip()):
                        parts.append(' href="#"')
                    else:
                        self._removed(f"{name}=javascript:")
                        self._note("warning", "javascript_url_removed",
                                   f"A javascript: address was removed from <{tag}> {name}.", value)
                    continue
                if cls == "data":
                    if name in ("src", "poster", "data-src", "href", "data-bg", "data-background") and tag != "a" \
                            and _DATA_OK.match(value.strip()) and len(value) <= MAX_DATA_URL:
                        parts.append(f' {name}="{escape(value, quote=True)}"')
                    else:
                        self._removed(f"{name}=data:")
                        self._note("warning", "data_url_removed", f"A data: address on <{tag}> {name} was removed.", value[:60])
                    continue
                if name == "xlink:href" or (name == "href" and tag == "use"):
                    if cls in ("external_unknown", "external_allowed"):
                        self._removed("<use external>")
                        self._note("warning", "svg_use_external_removed", "An external SVG <use> reference was removed.", value)
                        continue
                if tag != "a" or name != "href":
                    kind = URL_ATTRS[name]
                    if kind == "src":
                        kind = {"img": "image", "source": "image", "video": "media", "audio": "media", "track": "media",
                                "script": "script", "iframe": "frame", "input": "image"}.get(tag, "other")
                    self._ref(value, tag, name, kind)
                else:
                    self.refs.append({"url": value, "tag": "a", "attr": "href", "kind": "link", "class": cls,
                                      "file": self.filename, "path": None})
                    if cls == "local":
                        path = normalise_local(value)
                        real = self.files.get(path.lower()) if path else None
                        self.refs[-1]["path"] = real
                        if real and real.lower().endswith((".html", ".htm")):
                            self._note("warning", "other_page_link",
                                       "A link points to another page. Only one page is supported, so this link will not work.", value)
                parts.append(f' {name}="{escape(value, quote=True)}"')
                continue
            if name in flags or value == "":
                parts.append(f" {name}" if name in flags else f' {name}=""')
            else:
                parts.append(f' {name}="{escape(value, quote=True)}"')
        for name in sorted(flags - set(a)):
            parts.append(f" {name}")
        return "".join(parts)


def sanitise_page(html: str, files: dict, allowed_hosts: Iterable[str], filename: str = "index.html") -> SanitiseResult:
    """Cleans the entry page. `files` maps relative path -> bytes (or anything) for every file in the upload."""
    p = _Sanitiser(files, allowed_hosts, filename)
    p.feed(html)
    p.close()
    out = "".join(p.out)
    if not p.stats["has_doctype"]:
        out = "<!doctype html>" + out
    p.stats["removed"] = sorted(set(p.stats["removed"]))
    if not p.stats["has_viewport"]:
        p._note("warning", "no_viewport", "The page has no viewport meta tag, so it may look tiny on phones.")
    return SanitiseResult(html=out, findings=p.findings, refs=p.refs, scripts=p.scripts,
                          stylesheets=p.stylesheets, stats=p.stats)
