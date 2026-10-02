"""
app/services/site_premium_slots.py
-----------------------------------
SITE-PREMIUM P1 - checks the slot markers in a sanitised skeleton against the content vocabulary
(models.sites.SiteContentV1) and builds the slot manifest stored in site_designs.slot_manifest
(spec section 6). Pure functions, no I/O.

What it rejects (each a plain-English reason, fed back to the model on its one retry):
  * a slot path that is not in SiteContentV1 (or a "custom.<name>" field),
  * data-repeat on something that is not a list, data-slot-img not on <img>, data-slot-href not on <a>,
  * unknown link kinds or formats,
  * the required slots missing: business name, hero headline, a WhatsApp link on at least 2 calls to
    action, and an items repeat when the site has items.
"""
from __future__ import annotations

import re
import types
import typing
from typing import Any, Optional

from pydantic import BaseModel

from app.models.sites import SiteContentV1
from app.services.site_premium_renderer import Node, VOID_TAGS, parse_fragment

LINK_KINDS = {"whatsapp", "phone", "instagram", "maps"}
FORMATS = {"naira", "price"}
MAX_REPEAT_DEPTH = 3
_CUSTOM_RE = re.compile(r"^custom\.[a-z][a-z0-9_]{0,40}$")

Desc = Optional[tuple]


def _describe(ann: Any) -> Desc:
    origin = typing.get_origin(ann)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        return _describe(args[0]) if len(args) == 1 else ("scalar", None)
    if origin is typing.Literal:
        return ("scalar", None)
    if origin in (list, typing.List):
        args = typing.get_args(ann)
        return ("list", _describe(args[0]) if args else ("scalar", None))
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ("model", ann)
    return ("scalar", ann)


ROOT: Desc = ("model", SiteContentV1)


def _resolve(desc: Desc, segs: list[str]) -> Desc:
    cur = desc
    for seg in segs:
        if cur is None:
            return None
        kind = cur[0]
        if kind == "model":
            field = cur[1].model_fields.get(seg)
            if field is None:
                return None
            cur = _describe(field.annotation)
        elif kind == "list" and seg.isdigit():
            cur = cur[1]
        else:
            return None
    return cur


def _lookup(path: str, scopes: list) -> Desc:
    if path == ".":
        return scopes[-1] if scopes else None
    if _CUSTOM_RE.match(path):
        return ("scalar", None)
    segs = path.split(".")
    for scope in reversed(scopes):
        r = _resolve(scope, segs)
        if r is not None:
            return r
    return None


class _Walk:
    def __init__(self):
        self.errors: list[str] = []
        self.slots: list[dict] = []
        self.custom: set[str] = set()
        self.wa_links = 0
        self.repeats: set[str] = set()
        self.has: set[str] = set()

    def err(self, msg: str) -> None:
        if msg not in self.errors and len(self.errors) < 25:
            self.errors.append(msg)

    def visit(self, nodes: list, scopes: list, depth: int) -> None:
        for n in nodes:
            if not isinstance(n, Node):
                continue
            a = n.attrs
            inner = scopes
            if "data-if" in a:
                path = a["data-if"].lstrip("!")
                if _lookup(path, scopes) is None:
                    self.err(f"data-if path '{path}' is not in the content")
                else:
                    self.slots.append({"path": path, "kind": "if"})
            if "data-repeat" in a:
                path = a["data-repeat"]
                d = _lookup(path, scopes)
                if d is None:
                    self.err(f"data-repeat path '{path}' is not in the content")
                elif d[0] != "list":
                    self.err(f"data-repeat='{path}' is not a list")
                elif depth >= MAX_REPEAT_DEPTH:
                    self.err("data-repeat is nested too deeply")
                else:
                    inner = scopes + [d[1]]
                    self.repeats.add(path)
                    self.slots.append({"path": path, "kind": "repeat"})
                    depth += 1
            if "data-slot" in a:
                path = a["data-slot"]
                d = _lookup(path, inner)
                if n.tag in VOID_TAGS:
                    self.err(f"data-slot cannot be used on <{n.tag}>")
                elif d is None:
                    self.err(f"data-slot path '{path}' is not in the content")
                elif d[0] in ("list", "model"):
                    self.err(f"data-slot='{path}' is a group, not a single value (use data-repeat)")
                else:
                    fmt = a.get("data-format", "")
                    if fmt and fmt not in FORMATS:
                        self.err(f"data-format '{fmt}' is not one of: naira, price")
                    self.slots.append({"path": path, "kind": "text", **({"format": fmt} if fmt else {})})
                    self.has.add(path)
                    if _CUSTOM_RE.match(path):
                        self.custom.add(path)
            if "data-slot-img" in a:
                path = a["data-slot-img"]
                if n.tag != "img":
                    self.err("data-slot-img must be on an <img>")
                elif _lookup(path, inner) is None and _lookup(path + "_asset_id", inner) is None:
                    self.err(f"data-slot-img path '{path}' is not in the content")
                else:
                    self.slots.append({"path": path, "kind": "image"})
            if "data-slot-href" in a:
                kind = a["data-slot-href"]
                base, _, key = kind.partition(":")
                if n.tag != "a":
                    self.err("data-slot-href must be on an <a>")
                elif base not in LINK_KINDS:
                    self.err(f"data-slot-href '{kind}' is not one of: whatsapp, phone, instagram, maps")
                elif key and base != "whatsapp":
                    self.err(f"data-slot-href '{kind}' does not take a message key")
                else:
                    if base == "whatsapp":
                        from app.services.site_renderer import DEFAULT_WA_MESSAGES
                        if key and key not in DEFAULT_WA_MESSAGES:
                            self.err(f"WhatsApp message key '{key}' is unknown")
                        else:
                            self.wa_links += 1
                    self.slots.append({"path": kind, "kind": "link"})
            self.visit(n.children, inner, depth)


def analyse(skeleton_html: str, content: Optional[dict] = None) -> tuple[dict, list[str]]:
    """Returns (manifest, errors). `content` (the site's content JSON) decides whether an items repeat is required."""
    w = _Walk()
    w.visit(parse_fragment(skeleton_html), [ROOT], 0)
    if "business.name" not in w.has:
        w.err("Required slot missing: business.name (the business name must come from a slot)")
    if "hero.headline" not in w.has:
        w.err("Required slot missing: hero.headline")
    if w.wa_links < 2:
        w.err("Required: a WhatsApp link (data-slot-href='whatsapp') on at least 2 calls to action")
    if (content or {}).get("items") and "items" not in w.repeats:
        w.err("Required: this site has items, so the skeleton needs a data-repeat='items' block")
    seen: set = set()
    slots = []
    for s in w.slots:
        key = (s["path"], s["kind"])
        if key not in seen:
            seen.add(key)
            slots.append(s)
    manifest = {"version": 1, "slots": slots, "custom": sorted(w.custom), "whatsapp_links": w.wa_links}
    return manifest, w.errors
