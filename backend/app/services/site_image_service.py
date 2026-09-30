"""
backend/app/services/site_image_service.py
SITE-1C-3d — makes uploaded site photos web-sized before they are stored.

Phone photos and PNG exports are often 3-8 MB, which is slow on mobile data and makes a site feel
cheap. Every site photo upload path (staff editor, builder portal, client brief form, WhatsApp) passes
its bytes through optimise() first:

  * the longest side is capped at MAX_SIDE (1600px) — plenty for a full-width hero on a phone;
  * EXIF is applied (so phone photos stay upright) and then dropped, which also removes GPS location;
  * photographs are stored as JPEG (or WebP if they came in as WebP); a PNG is kept as PNG only when it
    really has transparency (a logo), otherwise it becomes a JPEG, which is several times smaller.

Best effort (S14): if Pillow is missing or the file cannot be decoded, the ORIGINAL bytes and mime type
are returned untouched, so an upload never fails because of optimisation. Input has already passed
the router's magic-byte check and the 8 MB cap.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MAX_SIDE = 1600
JPEG_QUALITY = 82
WEBP_QUALITY = 82
MAX_PIXELS = 64_000_000          # refuse to decode anything bigger (decompression bombs) — keep original
_KEEP_IF_NOT_LARGER = 1.10       # use the optimised file unless it is >10% bigger than the original


def _has_alpha(img) -> bool:
    if img.mode in ("RGBA", "LA"):
        lo, hi = img.getchannel("A").getextrema()
        return lo < 255
    return img.mode == "P" and "transparency" in img.info


def optimise(file_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Returns (bytes, mime). Never raises."""
    try:
        from PIL import Image, ImageOps  # lazy: the app still runs if Pillow is not installed

        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(file_bytes)) as src:
            if src.width * src.height > MAX_PIXELS:
                return file_bytes, mime
            src.load()
            img = ImageOps.exif_transpose(src)
            if max(img.size) > MAX_SIDE:
                img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

            out_mime = mime
            if mime == "image/png" and not _has_alpha(img):
                out_mime = "image/jpeg"

            buf = io.BytesIO()
            if out_mime == "image/jpeg":
                img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
            elif out_mime == "image/webp":
                img.save(buf, "WEBP", quality=WEBP_QUALITY, method=4)
            else:  # PNG with real transparency
                img.save(buf, "PNG", optimize=True)
        out = buf.getvalue()
        if not out or len(out) > len(file_bytes) * _KEEP_IF_NOT_LARGER:
            return file_bytes, mime
        return out, out_mime
    except Exception as exc:
        logger.warning("[SITE-1C-3d] image optimisation skipped: %s", exc)
        return file_bytes, mime


def extension_for(mime: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
