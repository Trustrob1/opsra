"""
tests/unit/test_store_5.py
--------------------------
STORE-5: share links for the public catalog.
  * tags are cleaned (lowercase, letters digits - _ only, 30 characters)
  * short link, tagged link, ready-made tags
  * owner routes GET /catalog/share and GET /catalog/qr.svg (owner role only, plain 422 when the store has no address)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import catalog_share_service as share
from tests.unit.test_account_plans_1 import BIZ, PLATFORM, FakeDB, _Q


class _MS(_Q):
    def maybe_single(self): return self


class DB(FakeDB):
    def table(self, name): return _MS(self, name)


def _db(slug="royal-rest-mattress"):
    return DB(organisations=[{"id": BIZ, "slug": slug}])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)
    monkeypatch.setenv("FRONTEND_URL", "https://opsra-frontend.onrender.com/")
    monkeypatch.delenv("CATALOG_BASE_URL", raising=False)


@pytest.mark.parametrize("raw,want", [
    ("Instagram", "instagram"), ("  WhatsApp Status!  ", "whatsappstatus"), ("flyer_2026-10", "flyer_2026-10"),
    ("a" * 50, "a" * 30), ("???", ""), (None, ""), ("", ""), ("<script>", "script"),
])
def test_clean_tag(raw, want):
    assert share.clean_tag(raw) == want


def test_share_info_plain():
    i = share.share_info(_db(), BIZ)
    assert i["short_link"] == "https://opsra-frontend.onrender.com/shop/royal-rest-mattress"
    assert i["catalog_link"] == "https://opsra-frontend.onrender.com/catalog/royal-rest-mattress"
    assert i["tag"] is None and i["tagged_link"] == i["short_link"]


def test_share_info_tagged_and_presets():
    i = share.share_info(_db(), BIZ, "Instagram Bio")
    assert i["tag"] == "instagrambio"
    assert i["tagged_link"].endswith("/shop/royal-rest-mattress?src=instagrambio")
    tags = [p["tag"] for p in i["presets"]]
    assert tags == ["instagram", "whatsapp", "facebook", "flyer", "shop"]
    assert all(p["link"].endswith(f"?src={p['tag']}") for p in i["presets"])


def test_catalog_base_url_wins(monkeypatch):
    monkeypatch.setenv("CATALOG_BASE_URL", "https://shop.example.com")
    assert share.share_info(_db(), BIZ)["short_link"] == "https://shop.example.com/shop/royal-rest-mattress"


def test_no_slug_is_a_plain_error():
    with pytest.raises(share.ShareError):
        share.share_info(_db(slug=""), BIZ)


def test_no_base_is_a_plain_error(monkeypatch):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    with patch("app.services.catalog_share_service.base_url", return_value=""):
        with pytest.raises(share.ShareError):
            share.share_info(_db(), BIZ)


def test_qr_is_svg_for_the_link():
    svg = share.qr_svg("https://x.test/shop/a?src=flyer")
    assert svg.startswith(b"<svg") and b"</svg>" in svg


# ---------------------------------------------------------------- routes

@pytest.fixture()
def owner(request):
    from fastapi.testclient import TestClient
    from app.dependencies import get_current_org, get_supabase
    from app.main import app
    role = getattr(request, "param", "owner")
    db = _db()
    app.dependency_overrides[get_current_org] = lambda: {"org_id": BIZ, "roles": {"template": role}}
    app.dependency_overrides[get_supabase] = lambda: db
    with patch("app.services.plan_gate_service.allowed", return_value=True):
        yield TestClient(app), db
    app.dependency_overrides.clear()


def test_route_share(owner):
    c, _ = owner
    r = c.get("/api/v1/catalog/share?src=Flyer")
    assert r.status_code == 200
    j = r.json()
    assert j["tag"] == "flyer" and j["tagged_link"].endswith("/shop/royal-rest-mattress?src=flyer")


def test_route_qr_svg_and_download(owner):
    c, _ = owner
    r = c.get("/api/v1/catalog/qr.svg?src=instagram")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.content.startswith(b"<svg") and "content-disposition" not in r.headers
    d = c.get("/api/v1/catalog/qr.svg?src=instagram&download=true")
    assert 'filename="store-qr-instagram.svg"' in d.headers["content-disposition"]
    assert c.get("/api/v1/catalog/qr.svg").headers["cache-control"] == "no-store"


def test_route_qr_encodes_the_tagged_link(owner):
    c, _ = owner
    with patch("app.services.catalog_share_service.qr_svg", return_value=b"<svg/>") as q:
        c.get("/api/v1/catalog/qr.svg?src=shop")
    assert q.call_args.args[0].endswith("/shop/royal-rest-mattress?src=shop")


@pytest.mark.parametrize("owner", ["sales_agent", "support_agent"], indirect=True)
def test_routes_need_owner_or_ops_manager(owner):
    c, _ = owner
    assert c.get("/api/v1/catalog/share").status_code == 403
    assert c.get("/api/v1/catalog/qr.svg").status_code == 403


def test_route_no_address_is_422(owner):
    c, db = owner
    db.rows("organisations")[0]["slug"] = ""
    r = c.get("/api/v1/catalog/share")
    assert r.status_code == 422 and "not ready" in r.json()["detail"]
