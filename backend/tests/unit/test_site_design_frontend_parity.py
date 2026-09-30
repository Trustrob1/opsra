"""
tests/unit/test_site_design_frontend_parity.py
SITE-1C-1 — the frontend picker lists (sitesKit.js) must match the backend registry, or the
Templates drawer offers a choice the server rejects (or hides one it would accept).
Skipped when the frontend folder is not part of the checkout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import site_design_registry as reg

KIT = Path(__file__).resolve().parents[3] / "frontend" / "src" / "modules" / "sites" / "sitesKit.js"
pytestmark = pytest.mark.skipif(not KIT.exists(), reason="frontend not in this checkout")


def _block(name: str) -> str:
    src = KIT.read_text(encoding="utf-8")
    m = re.search(r"export const " + name + r"\b.*?=\s*\[(.*?)\n\]", src, re.S)
    assert m, name
    return m.group(1)


def test_palettes_match():
    body = _block("PALETTES")
    assert re.findall(r"value: '([a-z_]+)'", body) == list(reg.PALETTES.keys())


def test_palette_accents_and_grounds_match():
    body = _block("PALETTES")
    for m in re.finditer(r"value: '([a-z_]+)'.*?accent: '(#[0-9A-Fa-f]{6})', ground: '(#[0-9A-Fa-f]{6})'", body):
        key, accent, ground = m.groups()
        assert reg.PALETTES[key]["accent"].lower() == accent.lower(), key
        assert reg.PALETTES[key]["ground"].lower() == ground.lower(), key


def test_font_pairings_match():
    body = _block("FONT_PAIRINGS")
    found = re.findall(r"value: '([a-z_]+)'.*?group: '([a-z]+)'", body)
    assert [k for k, _ in found] == list(reg.FONT_PAIRINGS.keys())
    for key, group in found:
        assert reg.FONT_PAIRINGS[key]["group"] == group


def test_tokens_match():
    body = _block("TOKENS")
    for m in re.finditer(r"key: '([a-z_]+)'.*?options: \[(.*?)\] \}", body):
        key, opts = m.groups()
        assert re.findall(r"value: '([a-z_]+)'", opts) == list(reg.TOKENS[key]), key
    assert set(re.findall(r"key: '([a-z_]+)'", body)) == set(reg.TOKENS)
