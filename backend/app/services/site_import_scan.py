"""
app/services/site_import_scan.py
---------------------------------
SITE-IMPORT 1a: static scans for the files of an imported site (spec sections 4, 6, 17).

Pure functions, no database, no network. Three scanners:
  * scan_js(text, filename, allowed_hosts)   - JavaScript (a file or an inline script / event handler)
  * scan_css(text, filename, allowed_hosts)  - CSS (tokenised with tinycss2; returns every url() / @import it finds)
  * scan_svg(text, filename)                 - SVG files

Why this exists: scripts are allowed on the CLIENT'S OWN DOMAIN only (decision 7 Oct 2026), so a script that
reads cookies or storage, runs text as code, loads more code, or sends data to an unlisted host must be found
at import. A static scan is a first filter, not the security boundary: the real boundary is the sandboxed
preview and the page's Content-Security-Policy (spec section 5).

A finding is a dict: {rule, severity, file, line, message, snippet, overridable}.
severity "error" stops the import. An "overridable" error can be downgraded to a warning by staff for a
named file (a vendored library, say); a non-overridable one can only be fixed by changing the file or, for
hosts, the allow-list in Settings.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlsplit

import tinycss2

DEFAULT_ALLOWED_HOSTS = (
    "fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com",
)

# rule id -> (severity, overridable, message)
RULES: dict = {
    "eval":                  ("error", True,  "eval() runs text as code"),
    "new_function":          ("error", True,  "new Function() / Function() builds code from text"),
    "string_timer":          ("warning", True, "setTimeout/setInterval with a string runs text as code"),
    "document_write_script": ("error", False, "document.write() that writes a script tag"),
    "document_write":        ("warning", True, "document.write() is slow and can break the page"),
    "document_cookie":       ("error", False, "reads or writes cookies (not allowed on hosted sites)"),
    "web_storage":           ("error", True,  "uses localStorage, sessionStorage or IndexedDB"),
    "network_blocked":       ("error", False, "calls a host that is not on the allow-list (add it in Settings, or remove the call)"),
    "network_dynamic":       ("warning", True, "network call whose address is built at run time (the page's CSP limits where it can go)"),
    "dynamic_script_element": ("error", True, "creates a script element at run time"),
    "dynamic_iframe_element": ("error", True, "creates an iframe element at run time"),
    "remote_import":         ("error", False, "imports code from a host that is not on the allow-list"),
    "worker":                ("error", True,  "starts a Web Worker or calls importScripts()"),
    "crypto_miner":          ("error", False, "looks like a crypto-miner"),
    "obfuscated_payload":    ("error", False, "decodes a large hidden payload (looks obfuscated)"),
    "window_open":           ("warning", True, "opens a new window"),
    "inner_html":            ("warning", True, "assigns innerHTML / outerHTML"),
    "post_message":          ("warning", True, "uses postMessage"),
    "top_location":          ("warning", True, "changes the top window's location"),
    "char_code_heavy":       ("warning", True, "builds text from many character codes (may be obfuscated)"),
    "css_expression":        ("error", False, "CSS expression() / behavior / -moz-binding"),
    "css_js_url":            ("error", False, "CSS url() that runs script"),
    "svg_unsafe":            ("error", False, "SVG contains script, foreignObject, event handlers or external references"),
}


def finding(rule: str, file: str, line: int, snippet: str = "", message: Optional[str] = None) -> dict:
    severity, overridable, default_msg = RULES[rule]
    return {"rule": rule, "severity": severity, "file": file, "line": int(line),
            "message": message or default_msg, "snippet": (snippet or "").strip()[:160],
            "overridable": bool(overridable)}


# ---------------------------------------------------------------------------
# URL classification (shared with the HTML sanitiser)
# ---------------------------------------------------------------------------

def host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    for a in allowed_hosts:
        a = str(a).lower().strip().rstrip(".")
        if a and (host == a or host.endswith("." + a)):
            return True
    return False


def classify_url(url: str, allowed_hosts: Iterable[str]) -> str:
    """One of: empty, anchor, local, external_allowed, external_unknown, js_scheme, data, other_scheme."""
    u = (url or "").strip()
    # Browsers ignore tabs / newlines inside a scheme ("java\tscript:"), so remove them before judging.
    compact = re.sub(r"[\x00-\x20]+", "", u).lower()
    if not compact:
        return "empty"
    if compact.startswith(("javascript:", "vbscript:")):
        return "js_scheme"
    if compact.startswith("data:"):
        return "data"
    if compact.startswith("#"):
        return "anchor"
    if compact.startswith("//") or re.match(r"^[a-z][a-z0-9+.\-]*:", compact):
        try:
            parts = urlsplit("https:" + u if compact.startswith("//") else u)
        except ValueError:
            return "external_unknown"
        if parts.scheme not in ("http", "https", "ws", "wss"):
            return "other_scheme"        # mailto:, tel:, sms:, whatsapp: ...
        return "external_allowed" if host_allowed(parts.hostname or "", allowed_hosts) else "external_unknown"
    return "local"


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?m)^[ \t]*//.*$")      # only whole-line comments: "//" inside strings (URLs) stays safe


def _blank_comments(text: str) -> str:
    """Replace comments by spaces of the same length, newlines kept, so line numbers stay right."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _line_text(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start: end if end != -1 else len(text)]


_STR = r"""(?:'([^'\\\n]*)'|"([^"\\\n]*)"|`([^`\\]*)`)"""
_SIMPLE = [
    ("eval", re.compile(r"(?<![\w$.])eval\s*\(")),
    ("new_function", re.compile(r"\bnew\s+Function\s*\(|(?<![\w$.])Function\s*\(\s*['\"`]")),
    ("string_timer", re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*['\"`]")),
    ("document_write_script", re.compile(r"document\s*\.\s*write(?:ln)?\s*\([^)]*<\s*script", re.I | re.S)),
    ("document_write", re.compile(r"document\s*\.\s*write(?:ln)?\s*\(")),
    ("document_cookie", re.compile(r"\bdocument\s*\.\s*cookie\b|\bdocument\s*\[\s*['\"]cookie['\"]\s*\]")),
    ("web_storage", re.compile(r"\b(?:local|session)Storage\b|\bindexedDB\b|\bopenDatabase\s*\(")),
    ("dynamic_script_element", re.compile(r"createElement(?:NS)?\s*\([^)]*['\"]script['\"]", re.I)),
    ("dynamic_iframe_element", re.compile(r"createElement\s*\(\s*['\"]iframe['\"]", re.I)),
    ("worker", re.compile(r"\bnew\s+(?:Shared)?Worker\s*\(|\bimportScripts\s*\(")),
    ("crypto_miner", re.compile(r"coinhive|coin-hive|cryptonight|cryptoloot|webminer|minero\.cc|jsecoin|authedmine", re.I)),
    ("window_open", re.compile(r"\bwindow\s*\.\s*open\s*\(")),
    ("inner_html", re.compile(r"\.(?:inner|outer)HTML\s*(?:\+)?=(?!=)")),
    ("post_message", re.compile(r"\.postMessage\s*\(")),
    ("top_location", re.compile(r"\b(?:top|parent)\s*\.\s*location\b")),
]
# Network entry points whose first argument we can judge when it is a literal.
_NET_CALLS = re.compile(
    r"(?<![\w$])(fetch|sendBeacon|EventSource|WebSocket)\s*\(\s*(?:" + _STR + r")?")
_IMPORT_CALL = re.compile(r"(?<![\w$.])import\s*\(\s*(?:" + _STR + r")?")
_XHR_OPEN = re.compile(r"\.open\s*\(\s*['\"](?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)['\"]\s*,\s*(?:" + _STR + r")?", re.I)
_ATOB_LONG = re.compile(r"\b(?:atob|unescape|decodeURIComponent)\s*\(\s*['\"`][A-Za-z0-9+/=%\\]{400,}['\"`]")
_FROM_CHAR = re.compile(r"String\s*\.\s*fromCharCode")


def _literal(m: "re.Match", first_group: int) -> Optional[str]:
    for g in (first_group, first_group + 1, first_group + 2):
        v = m.group(g)
        if v is not None:
            return v
    return None


def _check_url_literal(url: str, allowed_hosts) -> str:
    kind = classify_url(url, allowed_hosts)
    if kind in ("local", "anchor", "empty", "external_allowed", "other_scheme", "data"):
        return "ok"
    if kind == "js_scheme":
        return "blocked"
    return "blocked"       # external_unknown


def scan_js(text: str, filename: str, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS) -> list:
    """Findings for one piece of JavaScript. `filename` is only used to label the findings
    ("js/app.js", "index.html (inline script 2)", "index.html (onclick)")."""
    if not text or not text.strip():
        return []
    hosts = tuple(allowed_hosts)
    src = _blank_comments(text)
    out: list = []

    for rule, rx in _SIMPLE:
        for m in rx.finditer(src):
            out.append(finding(rule, filename, _line_of(src, m.start()), _line_text(src, m.start())))
    # document.write of a script is also a document.write; keep only the more serious finding per line.
    scripty_lines = {f["line"] for f in out if f["rule"] == "document_write_script"}
    out = [f for f in out if not (f["rule"] == "document_write" and f["line"] in scripty_lines)]

    for m in _NET_CALLS.finditer(src):
        url = _literal(m, 2)
        line = _line_of(src, m.start())
        if url is None:
            out.append(finding("network_dynamic", filename, line, _line_text(src, m.start())))
        elif _check_url_literal(url, hosts) == "blocked":
            out.append(finding("network_blocked", filename, line, url))
    if "XMLHttpRequest" in src:
        for m in _XHR_OPEN.finditer(src):
            url = _literal(m, 1)
            line = _line_of(src, m.start())
            if url is None:
                out.append(finding("network_dynamic", filename, line, _line_text(src, m.start())))
            elif _check_url_literal(url, hosts) == "blocked":
                out.append(finding("network_blocked", filename, line, url))
    for m in _IMPORT_CALL.finditer(src):
        url = _literal(m, 1)
        if url is not None and _check_url_literal(url, hosts) == "blocked":
            out.append(finding("remote_import", filename, _line_of(src, m.start()), url))
    for m in _ATOB_LONG.finditer(src):
        out.append(finding("obfuscated_payload", filename, _line_of(src, m.start()), m.group(0)[:60] + "..."))
    if len(_FROM_CHAR.findall(src)) > 20:
        out.append(finding("char_code_heavy", filename, 1))

    # ES module imports with a literal remote address: import x from "https://..."; import "https://..."
    for m in re.finditer(r"""(?m)^\s*(?:import|export)\s[^'"\n]*?from\s*['"]([^'"]+)['"]|^\s*import\s*['"]([^'"]+)['"]""", src):
        url = m.group(1) or m.group(2)
        if url and _check_url_literal(url, hosts) == "blocked":
            out.append(finding("remote_import", filename, _line_of(src, m.start()), url))

    # one entry per (rule, line)
    seen, unique = set(), []
    for f in out:
        key = (f["rule"], f["line"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_MAX_CSS_DEPTH = 40


def _css_tokens(tokens, state: dict, depth: int = 0) -> None:
    if depth > _MAX_CSS_DEPTH:
        return
    for tok in tokens or []:
        t = getattr(tok, "type", "")
        if t == "url":
            state["refs"].append({"url": tok.value, "via": "url"})
        elif t == "function":
            name = tok.lower_name
            if name == "expression":
                state["flags"].append("css_expression")
            if name == "url":
                for a in tok.arguments:
                    if getattr(a, "type", "") == "string":
                        state["refs"].append({"url": a.value, "via": "url"})
                        break
            elif name in ("image-set", "-webkit-image-set", "src", "image"):
                for a in tok.arguments:
                    if getattr(a, "type", "") == "string":
                        state["refs"].append({"url": a.value, "via": "url"})
            _css_tokens(tok.arguments, state, depth + 1)
        elif t in ("[] block", "() block", "{} block"):
            _css_tokens(tok.content, state, depth + 1)


def _css_declarations(decls, state: dict, depth: int = 0) -> None:
    if depth > _MAX_CSS_DEPTH:
        return
    for d in decls:
        t = getattr(d, "type", "")
        if t == "declaration":
            if d.lower_name in ("behavior", "-moz-binding"):
                state["flags"].append("css_expression")
            _css_tokens(d.value, state)
        elif t == "at-rule":
            _css_rule(d, state, depth + 1)
        elif t == "qualified-rule":
            _css_rule(d, state, depth + 1)
        elif t == "error":
            state["parse_errors"] += 1


_RULE_CONTAINERS = {"media", "supports", "layer", "container", "document", "-moz-document", "scope", "starting-style"}


def _css_rule(r, state: dict, depth: int = 0) -> None:
    if depth > _MAX_CSS_DEPTH:
        return
    t = getattr(r, "type", "")
    if t == "error":
        state["parse_errors"] += 1
        return
    if t == "at-rule":
        kw = r.lower_at_keyword
        if kw == "import":
            toks = r.prelude or []
            first = next((x for x in toks if getattr(x, "type", "") in ("string", "url", "function")), None)
            if first is not None:
                if first.type == "string":
                    state["refs"].append({"url": first.value, "via": "import"})
                elif first.type == "url":
                    state["refs"].append({"url": first.value, "via": "import"})
                elif first.type == "function" and first.lower_name == "url":
                    for a in first.arguments:
                        if getattr(a, "type", "") == "string":
                            state["refs"].append({"url": a.value, "via": "import"})
                            break
            return
        _css_tokens(r.prelude, state)
        if r.content is not None:
            if kw in _RULE_CONTAINERS:
                for sub in tinycss2.parse_rule_list(r.content, skip_comments=True, skip_whitespace=True):
                    _css_rule(sub, state, depth + 1)
            else:
                _css_declarations(tinycss2.parse_declaration_list(r.content, skip_comments=True, skip_whitespace=True),
                                  state, depth + 1)
    elif t == "qualified-rule":
        _css_declarations(tinycss2.parse_declaration_list(r.content, skip_comments=True, skip_whitespace=True),
                          state, depth + 1)


def scan_css(text: str, filename: str, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS) -> tuple:
    """Returns (findings, refs). refs = [{"url", "via": "url"|"import"}] in document order.
    Never raises: a stylesheet tinycss2 cannot read at all is reported as one warning-free empty result
    (the browser will ignore what it cannot read too)."""
    state = {"refs": [], "flags": [], "parse_errors": 0}
    try:
        rules = tinycss2.parse_stylesheet(text or "", skip_comments=True, skip_whitespace=True)
        for r in rules:
            _css_rule(r, state)
    except Exception:  # defensive: a tokeniser bug must not take the import down
        state["flags"].append("css_expression") if re.search(r"expression\s*\(|behavior\s*:|-moz-binding", text or "", re.I) else None
    out: list = []
    flagged_expr = "css_expression" in state["flags"] or bool(re.search(r"expression\s*\(|-moz-binding|behavior\s*:\s*url", text or "", re.I))
    if flagged_expr:
        out.append(finding("css_expression", filename, 1))
    for ref in state["refs"]:
        if classify_url(ref["url"], allowed_hosts) == "js_scheme":
            out.append(finding("css_js_url", filename, 1, ref["url"]))
    # Safety net for forms the tokeniser reports as bad-url (a javascript: address with brackets in it).
    if not any(f["rule"] == "css_js_url" for f in out) and re.search(
            r"url\(\s*['\"]?[\s\x00-\x20]*(?:java[\s\x00-\x20]*script|vbscript)[\s\x00-\x20]*:", text or "", re.I):
        out.append(finding("css_js_url", filename, 1))
    return out, state["refs"]


# ---------------------------------------------------------------------------
# SVG files
# ---------------------------------------------------------------------------

_SVG_BAD = [
    (re.compile(r"<\s*script", re.I), "a script element"),
    (re.compile(r"<\s*foreignobject", re.I), "a foreignObject element"),
    (re.compile(r"<\s*(?:iframe|embed|object)\b", re.I), "an embedded frame or object"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "an event handler attribute"),
    (re.compile(r"javascript\s*:", re.I), "a javascript: address"),
    (re.compile(r"<!\s*(?:entity|doctype[^>]*\[)", re.I), "an XML entity declaration"),
    (re.compile(r"<\?xml-stylesheet", re.I), "an external stylesheet instruction"),
    (re.compile(r"<\s*use\b[^>]*(?:xlink:)?href\s*=\s*['\"]\s*(?:https?:)?//", re.I), "an external <use> reference"),
    (re.compile(r"<\s*(?:image|feimage)\b[^>]*href\s*=\s*['\"]\s*(?:https?:)?//", re.I), "an external image reference"),
]


def scan_svg(text: str, filename: str) -> list:
    out = []
    for rx, label in _SVG_BAD:
        m = rx.search(text or "")
        if m:
            out.append(finding("svg_unsafe", filename, _line_of(text, m.start()), m.group(0),
                               message=f"SVG contains {label}"))
    return out
