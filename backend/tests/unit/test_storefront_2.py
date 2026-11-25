"""
tests/unit/test_storefront_2.py
-------------------------------
STOREFRONT-2: logo + banner photo uploads, banner words, and the logo in the public catalog payload.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from app.services import catalog_storefront_service as sf
from tests.unit.test_account_plans_1 import BIZ


def _png(w=900, h=400, mode="RGBA"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _storage_db(url="https://abc.supabase.co/storage/v1/object/public/catalog/x/logo.png?"):
    db = MagicMock()
    bucket = db.storage.from_.return_value
    bucket.get_public_url.return_value = url
    return db, bucket


# ---------------------------------------------------------------- public style

def test_public_style_has_banner_fields_cleaned():
    out = sf.public_style({"hero_title": "  Sleep   well " + "x" * 100, "hero_text": " Made  in Lagos ",
                           "hero_image_url": "https://cdn.example.com/h.jpg"})
    assert out["hero_title"] == ("Sleep well " + "x" * 100)[:sf.HERO_TITLE_MAX]
    assert out["hero_text"] == "Made in Lagos"
    assert out["hero_image_url"] == "https://cdn.example.com/h.jpg"


@pytest.mark.parametrize("bad", ["http://x/h.jpg", "javascript:alert(1)", "https://x/a b.jpg", 5])
def test_public_style_drops_unsafe_banner_photo(bad):
    assert sf.public_style({"hero_image_url": bad})["hero_image_url"] is None


def test_public_style_banner_fields_empty_by_default():
    out = sf.public_style(None)
    assert out["hero_title"] is None and out["hero_text"] is None and out["hero_image_url"] is None


# ---------------------------------------------------------------- clean_image

def test_clean_image_redraws_logo_as_small_png():
    out = sf.clean_image(_png(1200, 800), 600, "PNG")
    from PIL import Image
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and max(img.size) == 600


def test_clean_image_makes_banner_a_jpeg():
    out = sf.clean_image(_png(2400, 1200), 1800, "JPEG")
    from PIL import Image
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.size == (1800, 900)


@pytest.mark.parametrize("data,msg", [
    (b"", "5 MB"),
    (b"GIF89a" + b"0" * 50, "PNG, JPG or WebP"),
    (b"<svg onload=alert(1)>", "PNG, JPG or WebP"),
    (b"\x89PNG\r\n\x1a\n" + b"broken", "could not be read"),
])
def test_clean_image_refuses_bad_files(data, msg):
    with pytest.raises(sf.LookImageError) as e:
        sf.clean_image(data, 600, "PNG")
    assert msg in e.value.message and e.value.status == 422


def test_clean_image_refuses_huge_files():
    with pytest.raises(sf.LookImageError):
        sf.clean_image(b"\x89PNG\r\n\x1a\n" + b"0" * (sf.IMAGE_MAX_BYTES + 1), 600, "PNG")


# ---------------------------------------------------------------- save / remove

def test_save_logo_stores_png_and_saves_link():
    db, bucket = _storage_db()
    with patch("app.services.catalog_service.update_catalog_config", side_effect=lambda d, o, u: {"x": 1, **u}) as upd:
        out = sf.save_look_image(db, BIZ, _png(), "logo")
    path = bucket.upload.call_args.kwargs["path"]
    assert path.startswith(f"{BIZ}/catalog-look/logo-") and path.endswith(".png")
    assert bucket.upload.call_args.kwargs["file_options"]["content-type"] == "image/png"
    assert upd.call_args[0][2] == {"logo_url": "https://abc.supabase.co/storage/v1/object/public/catalog/x/logo.png"}
    assert out["logo_url"].startswith("https://")


def test_save_banner_stores_jpeg_under_hero_field():
    db, bucket = _storage_db("https://abc.supabase.co/storage/v1/object/public/catalog/x/hero.jpg")
    with patch("app.services.catalog_service.update_catalog_config", side_effect=lambda d, o, u: u) as upd:
        sf.save_look_image(db, BIZ, _png(), "hero")
    assert bucket.upload.call_args.kwargs["path"].endswith(".jpg")
    assert list(upd.call_args[0][2]) == ["hero_image_url"]


def test_save_fails_safely_when_storage_is_down():
    db, bucket = _storage_db()
    bucket.upload.side_effect = RuntimeError("down")
    with patch("app.services.catalog_service.update_catalog_config") as upd:
        with pytest.raises(sf.LookImageError) as e:
            sf.save_look_image(db, BIZ, _png(), "logo")
    assert e.value.status == 503 and not upd.called


def test_unknown_kind_is_refused():
    with pytest.raises(sf.LookImageError) as e:
        sf.save_look_image(MagicMock(), BIZ, _png(), "favicon")
    assert e.value.status == 404


def test_remove_clears_only_that_picture():
    with patch("app.services.catalog_service.update_catalog_config", side_effect=lambda d, o, u: u) as upd:
        sf.remove_look_image(MagicMock(), BIZ, "hero")
    assert upd.call_args[0][2] == {"hero_image_url": ""}


# ---------------------------------------------------------------- owner routes

def _owner_client(db, roles=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_current_org, get_supabase
    app.dependency_overrides[get_current_org] = lambda: {"org_id": BIZ, "roles": roles or {"template": "owner"}}
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


@pytest.fixture()
def owner_cleanup():
    yield
    from app.main import app
    app.dependency_overrides.clear()


def test_upload_route_saves_logo(owner_cleanup):
    db, _ = _storage_db()
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=True), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.services.catalog_service.update_catalog_config", side_effect=lambda d, o, u: u):
        r = _owner_client(db).post("/api/v1/catalog/look/logo", files={"file": ("l.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["catalog_config"]["logo_url"].startswith("https://")


def test_upload_route_refuses_bad_file_with_owner_message(owner_cleanup):
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        r = _owner_client(MagicMock()).post("/api/v1/catalog/look/hero", files={"file": ("x.gif", b"GIF89a....", "image/gif")})
    assert r.status_code == 422
    assert "PNG, JPG or WebP" in r.text


def test_upload_route_unknown_kind_404s(owner_cleanup):
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        r = _owner_client(MagicMock()).post("/api/v1/catalog/look/favicon", files={"file": ("l.png", _png(), "image/png")})
    assert r.status_code == 422      # FastAPI rejects a kind that is not logo/hero


def test_delete_route_clears_banner(owner_cleanup):
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=True), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.services.catalog_service.update_catalog_config", side_effect=lambda d, o, u: u) as upd:
        r = _owner_client(MagicMock()).delete("/api/v1/catalog/look/hero")
    assert r.status_code == 200, r.text
    assert upd.call_args[0][2] == {"hero_image_url": ""}


def test_patch_config_accepts_banner_words(owner_cleanup):
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=True), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config", side_effect=lambda d, o, u: u) as upd:
        r = _owner_client(MagicMock()).patch("/api/v1/catalog/config", json={"hero_title": "  Sleep   well ", "hero_text": "Made in Lagos"})
    assert r.status_code == 200, r.text
    assert upd.call_args[0][2] == {"hero_title": "Sleep well", "hero_text": "Made in Lagos"}


def test_patch_config_rejects_long_or_unsafe_banner(owner_cleanup):
    with patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config") as upd:
        c = _owner_client(MagicMock())
        assert c.patch("/api/v1/catalog/config", json={"hero_title": "x" * (sf.HERO_TITLE_MAX + 1)}).status_code == 422
        assert c.patch("/api/v1/catalog/config", json={"hero_image_url": "http://x/h.jpg"}).status_code == 422
    assert not upd.called


# ---------------------------------------------------------------- public payload

def test_public_config_carries_cleaned_logo_for_classic():
    from app.routers.public_catalog import _public_config_fields
    assert _public_config_fields({"logo_url": "https://cdn.example.com/l.png"})["logo_url"] == "https://cdn.example.com/l.png"
    assert _public_config_fields({"logo_url": "javascript:x"})["logo_url"] is None
    assert _public_config_fields({})["logo_url"] is None
