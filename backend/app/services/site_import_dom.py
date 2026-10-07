"""
backend/app/services/site_import_dom.py
SITE-IMPORT 2 - a small HTML tree that keeps the page's own text byte for byte.

The Premium renderer parses a fragment into a tree and writes it back escaped, which would damage an uploaded page
(script text escaped, comments and the doctype dropped, <input>/<source> swallowing what follows). Level 2 needs the opposite:
everything the engine does not deliberately change must come out exactly as it went in. So every node keeps its raw source:

  Text  - raw text (entities kept as written)        Raw  - a comment, doctype, processing instruction, stray end tag
  Elem  - raw start tag, children, raw end tag (None when the page left it implied)

serialise(parse(html)) == html for well-formed pages (the tests prove it on the fixtures); for sloppy ones the output renders the
same. Changing an element only ever INSERTS or REMOVES whole attributes in its raw start tag (set_attrs / strip_attrs).
"""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Iterator, Optional

VOID = frozenset("area base basefont bgsound br col command embed frame hr img input keygen link meta param source track wbr".split())
RAW_TEXT = frozenset({"script", "style"})
_BLOCK = frozenset("address article aside blockquote details div dl fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr "
                   "main menu nav ol p pre section table ul".split())
_CLOSES_LI = frozenset({"ul", "ol", "menu"})


class Text:
    __slots__ = ("raw",)

    def __init__(self, raw: str):
        self.raw = raw


class Raw:
    __slots__ = ("raw",)

    def __init__(self, raw: str):
        self.raw = raw


class Elem:
    __slots__ = ("tag", "attrs", "raw_start", "children", "raw_end", "void", "id", "parent")

    def __init__(self, tag: str, attrs: Optional[dict] = None, raw_start: str = "", void: bool = False):
        self.tag = tag
        self.attrs = attrs or {}
        self.raw_start = raw_start
        self.children: list = []
        self.raw_end: Optional[str] = None
        self.void = void
        self.id: Optional[str] = None
        self.parent: Optional["Elem"] = None

    def add(self, node) -> None:
        if isinstance(node, Elem):
            node.parent = self
        self.children.append(node)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = Elem("#root")
        self.stack = [self.root]

    # -- text
    def _text(self, raw: str) -> None:
        top = self.stack[-1]
        if top.children and isinstance(top.children[-1], Text):
            top.children[-1].raw += raw
        else:
            top.add(Text(raw))

    def handle_data(self, data):
        self._text(data)

    def handle_entityref(self, name):
        self._text(f"&{name};")

    def handle_charref(self, name):
        self._text(f"&#{name};")

    def handle_comment(self, data):
        self.stack[-1].add(Raw(f"<!--{data}-->"))

    def handle_decl(self, decl):
        self.stack[-1].add(Raw(f"<!{decl}>"))

    def handle_pi(self, data):
        self.stack[-1].add(Raw(f"<?{data}>"))

    def unknown_decl(self, data):
        self.stack[-1].add(Raw(f"<![{data}]>"))

    # -- tags
    def _implied_close(self, tag: str) -> None:
        """The few end tags HTML lets a page leave out, so siblings (list items, paragraphs, cells) are siblings in the tree."""
        def pop_to(names, stop=frozenset()):
            for i in range(len(self.stack) - 1, 0, -1):
                t = self.stack[i].tag
                if t in stop:
                    return
                if t in names:
                    del self.stack[i:]
                    return
        if tag == "li":
            pop_to({"li"}, _CLOSES_LI)
        elif tag in ("dt", "dd"):
            pop_to({"dt", "dd"}, {"dl"})
        elif tag in ("td", "th"):
            pop_to({"td", "th"}, {"tr", "table"})
        elif tag == "tr":
            pop_to({"tr"}, {"table", "tbody", "thead", "tfoot"})
        elif tag == "option":
            pop_to({"option"}, {"select", "datalist"})
        if tag in _BLOCK and self.stack[-1].tag == "p":
            self.stack.pop()

    def handle_starttag(self, tag, attrs):
        self._implied_close(tag)
        el = Elem(tag, {k: (v if v is not None else "") for k, v in attrs}, self.get_starttag_text() or "", tag in VOID)
        self.stack[-1].add(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self._implied_close(tag)
        el = Elem(tag, {k: (v if v is not None else "") for k, v in attrs}, self.get_starttag_text() or "", True)
        self.stack[-1].add(el)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack[i].raw_end = f"</{tag}>"
                del self.stack[i:]
                return
        self.stack[-1].add(Raw(f"</{tag}>"))


def parse(html: str) -> Elem:
    b = _Builder()
    b.feed(html or "")
    b.close()
    return b.root


def _ser(nodes: list, out: list) -> None:
    for n in nodes:
        if isinstance(n, Elem):
            out.append(n.raw_start)
            _ser(n.children, out)
            if n.raw_end:
                out.append(n.raw_end)
        else:
            out.append(n.raw)


def serialise(root_or_nodes) -> str:
    out: list = []
    _ser(root_or_nodes.children if isinstance(root_or_nodes, Elem) else root_or_nodes, out)
    return "".join(out)


def iter_elems(node: Elem) -> Iterator[Elem]:
    for c in node.children:
        if isinstance(c, Elem):
            yield c
            yield from iter_elems(c)


def assign_ids(root: Elem) -> dict:
    """e1, e2 ... in document order. Returns {id: Elem}."""
    index = {}
    for n, el in enumerate(iter_elems(root), 1):
        el.id = f"e{n}"
        index[el.id] = el
    return index


def find(root: Elem, tag: str) -> Optional[Elem]:
    return next((e for e in iter_elems(root) if e.tag == tag), None)


def is_inside(el: Elem, tags: frozenset) -> bool:
    p = el.parent
    while p is not None:
        if p.tag in tags:
            return True
        p = p.parent
    return False


def ancestors(el: Elem) -> Iterator[Elem]:
    p = el.parent
    while p is not None and p.tag != "#root":
        yield p
        p = p.parent


def text_of(el: Elem) -> str:
    """Visible text of an element, entities decoded, whitespace collapsed. Script and style content is not text."""
    parts: list = []

    def walk(e: Elem):
        for c in e.children:
            if isinstance(c, Text):
                parts.append(unescape(c.raw))
            elif isinstance(c, Elem) and c.tag not in RAW_TEXT:
                if c.tag == "br":
                    parts.append(" ")
                walk(c)
    walk(el)
    return " ".join("".join(parts).split())


def is_leaf_text(el: Elem) -> bool:
    """Only text (and comments) inside: the one kind of element a text slot may replace without losing markup."""
    return not el.void and el.tag not in RAW_TEXT and all(isinstance(c, (Text, Raw)) for c in el.children)


# ---------------------------------------------------------------- editing a raw start tag

def _attr_rx(name: str) -> "re.Pattern":
    return re.compile(r"""\s+""" + re.escape(name) + r"""(?=[\s=/>])(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?""", re.I)


def strip_attrs(raw: str, names) -> str:
    for n in names:
        raw = _attr_rx(n).sub("", raw)
    return raw


def set_attrs(raw: str, updates: dict) -> str:
    """Adds or replaces whole attributes in a raw start tag; nothing else in it changes. A value of None removes the attribute."""
    raw = strip_attrs(raw, list(updates))
    add = "".join(f' {k}="{_esc(str(v))}"' for k, v in updates.items() if v is not None)
    if not add:
        return raw
    m = re.search(r"\s*/?>$", raw)
    if not m:
        return raw + add
    tail = raw[m.start():]
    head = raw[:m.start()]
    return head + add + (" /" if tail.strip().startswith("/") else "") + ">"


def _esc(v: str) -> str:
    return v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
