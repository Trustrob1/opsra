"""tests/unit/test_site_image_service.py — SITE-1C-3d: uploaded site photos are made web-sized."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import site_image_service as svc


def _img(size=(3000, 2000), mode="RGB", fmt="PNG", colour=None, **save):
    import random
    rnd = random.Random(3)
    im = Image.new(mode, size)
    # noisy content so the file is big like a real photo
    px = im.load()
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 7):
            px[x, y] = colour or ((rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) if mode == "RGB" else (10, 20, 30, 255))
    buf = io.BytesIO()
    im.save(buf, fmt, **save)
    return buf.getvalue()


def _open(b):
    return Image.open(io.BytesIO(b))


class TestOptimise:
    def test_big_photo_png_becomes_a_smaller_capped_jpeg(self):
        raw = _img((3200, 2400))
        out, mime = svc.optimise(raw, "image/png")
        assert mime == "image/jpeg" and out.startswith(b"\xff\xd8\xff")
        assert max(_open(out).size) == 1600 and len(out) < len(raw) / 2

    def test_jpeg_stays_jpeg_and_is_capped(self):
        raw = _img((2400, 1600), fmt="JPEG", quality=98)
        out, mime = svc.optimise(raw, "image/jpeg")
        assert mime == "image/jpeg" and max(_open(out).size) == 1600 and len(out) < len(raw)

    def test_webp_stays_webp(self):
        raw = _img((2400, 1600), fmt="WEBP", quality=98)
        out, mime = svc.optimise(raw, "image/webp")
        assert mime == "image/webp" and out[8:12] == b"WEBP" and max(_open(out).size) == 1600

    def test_png_with_transparency_stays_png(self):
        im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        im.paste((200, 30, 30, 255), (100, 100, 300, 300))
        buf = io.BytesIO(); im.save(buf, "PNG")
        out, mime = svc.optimise(buf.getvalue(), "image/png")
        assert mime == "image/png" and _open(out).mode == "RGBA"

    def test_small_image_is_not_upscaled(self):
        raw = _img((800, 600), fmt="JPEG", quality=90)
        out, mime = svc.optimise(raw, "image/jpeg")
        assert _open(out).size == (800, 600)

    def test_exif_orientation_is_applied_and_metadata_dropped(self):
        im = Image.new("RGB", (600, 300), (10, 120, 200))
        exif = Image.Exif(); exif[0x0112] = 6  # rotate 90 clockwise
        exif[0x010F] = "PhoneMaker"
        buf = io.BytesIO(); im.save(buf, "JPEG", exif=exif)
        out, mime = svc.optimise(buf.getvalue(), "image/jpeg")
        got = _open(out)
        assert got.size == (300, 600)                      # turned upright
        assert not got.getexif()                           # no EXIF (so no GPS) left

    def test_undecodable_bytes_come_back_untouched(self):
        junk = b"\xff\xd8\xff" + b"not really a jpeg" * 20
        assert svc.optimise(junk, "image/jpeg") == (junk, "image/jpeg")

    def test_missing_pillow_falls_back(self, monkeypatch):
        import builtins
        real = builtins.__import__
        def fake(name, *a, **k):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("no pillow")
            return real(name, *a, **k)
        monkeypatch.setattr(builtins, "__import__", fake)
        raw = b"\x89PNG\r\n\x1a\n" + b"x" * 50
        assert svc.optimise(raw, "image/png") == (raw, "image/png")

    def test_huge_pixel_count_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(svc, "MAX_PIXELS", 1000)
        raw = _img((100, 100), fmt="JPEG")
        assert svc.optimise(raw, "image/jpeg") == (raw, "image/jpeg")

    def test_never_returns_a_much_bigger_file(self):
        raw = _img((200, 200), mode="RGB", fmt="JPEG", quality=20)   # already tiny and lossy
        out, mime = svc.optimise(raw, "image/jpeg")
        assert len(out) <= len(raw) * 1.1 + 1

    def test_extension_for(self):
        assert [svc.extension_for(m) for m in ("image/jpeg", "image/png", "image/webp")] == ["jpg", "png", "webp"]
