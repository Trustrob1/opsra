"""tests/unit/test_site_upload_optimises.py — SITE-1C-3d: the upload routes store the web-sized file."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.routers import builder_portal, sites


def _big_png():
    import random
    rnd = random.Random(1)
    im = Image.new("RGB", (3000, 2000))
    px = im.load()
    for x in range(0, 3000, 6):
        for y in range(0, 2000, 6):
            px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    b = io.BytesIO(); im.save(b, "PNG")
    return b.getvalue()


class _File:
    def __init__(self, data, content_type):
        self.content_type, self._d = content_type, data
    async def read(self):
        return self._d


def _db():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "asset1"}])
    db.storage.from_.return_value.get_public_url.return_value = "https://x.supabase.co/p"
    return db


def _uploaded(db):
    kw = db.storage.from_.return_value.upload.call_args.kwargs
    return kw["path"], kw["file"], kw["file_options"]["content-type"]


@pytest.mark.asyncio
async def test_staff_upload_stores_a_capped_jpeg(monkeypatch):
    monkeypatch.setattr(sites, "_get_site", lambda *a, **k: {"id": "s1"})
    monkeypatch.setattr(sites, "_require", lambda *a, **k: None)
    monkeypatch.setattr(sites, "_log_event", lambda *a, **k: None)
    db, raw = _db(), _big_png()
    await sites.upload_asset("s1", slot="hero", file=_File(raw, "image/png"), org={"org_id": "o", "id": "u"}, db=db)
    path, data, ctype = _uploaded(db)
    assert path.endswith(".jpg") and ctype == "image/jpeg" and data.startswith(b"\xff\xd8\xff")
    assert max(Image.open(io.BytesIO(data)).size) == 1600 and len(data) < len(raw)
    row = db.table.return_value.insert.call_args.args[0]
    assert row["mime_type"] == "image/jpeg" and row["bytes"] == len(data)


@pytest.mark.asyncio
async def test_builder_upload_stores_a_capped_jpeg(monkeypatch):
    monkeypatch.setattr(builder_portal, "_get_site", lambda *a, **k: {"id": "s1"})
    monkeypatch.setattr(builder_portal, "_log_event", lambda *a, **k: None)
    db, raw = _db(), _big_png()
    await builder_portal.upload_my_asset("s1", slot="hero", file=_File(raw, "image/png"), builder={"org_id": "o", "id": "b"}, db=db)
    path, data, ctype = _uploaded(db)
    assert path.endswith(".jpg") and ctype == "image/jpeg" and max(Image.open(io.BytesIO(data)).size) == 1600


@pytest.mark.asyncio
async def test_a_tiny_fake_image_still_uploads_untouched(monkeypatch):
    monkeypatch.setattr(sites, "_get_site", lambda *a, **k: {"id": "s1"})
    monkeypatch.setattr(sites, "_require", lambda *a, **k: None)
    monkeypatch.setattr(sites, "_log_event", lambda *a, **k: None)
    db = _db()
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * 40          # passes the magic-byte check but is not decodable
    await sites.upload_asset("s1", slot="hero", file=_File(raw, "image/png"), org={"org_id": "o", "id": "u"}, db=db)
    path, data, ctype = _uploaded(db)
    assert data == raw and ctype == "image/png" and path.endswith(".png")
