"""
tests/unit/test_store_5c.py
---------------------------
STORE-5c: the link preview for one product.
  * share_link  {api}/og/shop/{store}/{product}[?variant=..&src=..] is what the owner copies and sends
  * preview_for: photo, name and price of a visible product; the store's own preview for anything else; never raises
  * preview_html: escaped, https images only, redirects people to the direct link
  * route GET /og/shop/{store}/{product}: public, always 200 HTML
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


def _p(**kw):
    row = {"id": "p1", "org_id": BIZ, "title": "Cloud 9 Mattress", "slug": "cloud-9", "price": 150000, "available": True,
           "catalog_visible": True, "catalog_images": ["https://img/c.jpg"], "catalog_description": "Soft  and\nsupportive.",
           "variants": [{"id": 12, "title": "Queen"}]}
    row.update(kw)
    return row


def _db(products=None, cfg=None, name="Royal Rest"):
    return DB(organisations=[{"id": BIZ, "slug": "royal-rest", "name": name, "catalog_config": cfg or {}}],
              products=products if products is not None else [_p()])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)
    monkeypatch.setenv("FRONTEND_URL", "https://front.test")
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.test/")
    monkeypatch.delenv("CATALOG_BASE_URL", raising=False)


def test_share_link_points_at_the_preview_page_and_keeps_size_and_tag():
    with patch("app.services.catalog_storefront_service.resolve_template", return_value="storefront"), \
         patch("app.services.catalog_storefront_service.shop_info", return_value={"key": "k"}):
        i = share.product_share_info(_db(), BIZ, "p1")
        assert i["share_link"] == "https://api.test/og/shop/royal-rest/cloud-9"
        assert i["link"] == "https://front.test/shop/royal-rest/cloud-9"            # the direct link is unchanged
        j = share.product_share_info(_db(), BIZ, "p1", "Instagram", "12")
        assert j["share_link"] == "https://api.test/og/shop/royal-rest/cloud-9?variant=12&src=instagram"


def test_api_base_defaults_and_trims(monkeypatch):
    assert share.api_base() == "https://api.test"
    monkeypatch.delenv("PUBLIC_API_URL")
    assert share.api_base() == "https://opsra.onrender.com"


def test_preview_has_photo_name_price_and_direct_link():
    p = share.preview_for(_db(), "royal-rest", "cloud-9", "12", "Instagram")
    assert p["title"] == "Cloud 9 Mattress - Royal Rest"
    assert p["image"] == "https://img/c.jpg"
    assert p["description"] == "₦150,000 | Soft and supportive."
    assert p["url"] == "https://front.test/shop/royal-rest/cloud-9?variant=12&src=instagram"


def test_price_on_request_hides_the_price_and_template_is_used():
    p = share.preview_for(_db(cfg={"price_on_request": True}), "royal-rest", "cloud-9")
    assert "150" not in p["description"]
    p = share.preview_for(_db(cfg={"price_label_template": "NGN {price}"}), "royal-rest", "cloud-9")
    assert p["description"].startswith("NGN 150,000")


def test_out_of_stock_is_said():
    p = share.preview_for(_db([_p(available=False)]), "royal-rest", "cloud-9")
    assert "Out of stock" in p["description"]


def test_bad_variant_and_tag_are_dropped_from_the_link():
    p = share.preview_for(_db(), "royal-rest", "cloud-9", "a b<script>", "!!")
    assert p["url"] == "https://front.test/shop/royal-rest/cloud-9"


def test_hidden_or_unknown_product_gives_the_stores_own_preview():
    for products in ([_p(catalog_visible=False)], [], [_p(slug="other")]):
        p = share.preview_for(_db(products), "royal-rest", "cloud-9", "12", "ig")
        assert p["title"] == "Royal Rest" and p["image"] == "" and p["url"] == "https://front.test/shop/royal-rest"


def test_unknown_store_and_failures_never_raise():
    p = share.preview_for(_db(), "nope", "cloud-9")
    assert p["url"] == "https://front.test"
    with patch.object(share, "base_url", return_value="https://front.test"):
        class Boom:
            def table(self, *_): raise RuntimeError("down")
        assert share.preview_for(Boom(), "royal-rest", "x")["url"] == "https://front.test/shop/royal-rest"


def test_images_must_be_https():
    p = share.preview_for(_db([_p(catalog_images=["http://img/c.jpg"])]), "royal-rest", "cloud-9")
    assert p["image"] == ""
    p = share.preview_for(_db([_p(catalog_images=[{"url": "https://img/d.jpg?"}])]), "royal-rest", "cloud-9")
    assert p["image"] == "https://img/d.jpg"


def test_html_is_escaped_and_redirects():
    h = share.preview_html({"title": 'A "bad" <b>name</b>', "description": "x & y", "image": "https://i/x.jpg?a=1&b=2",
                            "url": "https://front.test/shop/a/b?variant=1&src=ig"})
    assert "<b>" not in h and "&quot;bad&quot;" in h and "x &amp; y" in h
    assert 'property="og:image" content="https://i/x.jpg?a=1&amp;b=2"' in h
    assert 'twitter:card" content="summary_large_image"' in h
    assert 'http-equiv="refresh" content="0;url=https://front.test/shop/a/b?variant=1&amp;src=ig"' in h
    assert 'window.location.replace("https://front.test/shop/a/b?variant=1&src=ig")' in h


def test_html_without_image_has_no_image_tag_and_script_cannot_break_out():
    h = share.preview_html({"title": "t", "description": "", "image": "", "url": 'https://x/"</script><script>alert(1)'})
    assert "og:image" not in h and 'summary"' in h
    assert "</script><script>" not in h


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_supabase
    db = _db()
    app.dependency_overrides[get_supabase] = lambda: db
    with patch("app.routers.public_catalog.get_supabase", return_value=db):
        yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_is_public_and_returns_the_tags(client):
    r = client.get("/og/shop/royal-rest/cloud-9?variant=12&src=instagram")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "https://img/c.jpg" in r.text and "Cloud 9 Mattress - Royal Rest" in r.text
    assert "https://front.test/shop/royal-rest/cloud-9?variant=12&amp;src=instagram" in r.text


def test_route_for_an_unknown_product_is_still_200(client):
    r = client.get("/og/shop/royal-rest/nothing")
    assert r.status_code == 200 and "https://front.test/shop/royal-rest" in r.text
