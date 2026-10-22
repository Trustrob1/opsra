"""
tests/unit/test_store_5b.py
---------------------------
STORE-5b: share one product.
  * link: /shop/{store}/{product}, with ?variant= (a real size of that product) and ?src= (a clean tag)
  * sizes offered: real sizes only (not Shopify's Default Title, not options without an id)
  * warnings: hidden, out of stock, classic look, cart not on
  * routes: GET /catalog/share?item=, GET /catalog/qr.svg?item= (owner role, other business's product is 422)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import catalog_share_service as share
from tests.unit.test_account_plans_1 import BIZ, PLATFORM, FakeDB, _Q

OTHER = "99999999-9999-9999-9999-999999999999"


class _MS(_Q):
    def maybe_single(self): return self


class DB(FakeDB):
    def table(self, name): return _MS(self, name)


def _p(pid="p1", slug="cloud-9-mattress", org=BIZ, **kw):
    row = {"id": pid, "org_id": org, "title": "Cloud 9 Mattress", "slug": slug, "price": 150000, "available": True, "catalog_visible": True,
           "catalog_images": ["https://img/c.jpg"],
           "variants": [{"id": 11, "title": "Single 3/4 ft"}, {"id": "12", "title": "Queen 5/6 ft"}, {"id": 13, "title": "Default Title"},
                        {"title": "No id"}, {"id": 14, "title": "  "}]}
    row.update(kw)
    return row


def _db(products=None, slug="royal-rest-mattress"):
    return DB(organisations=[{"id": BIZ, "slug": slug, "catalog_config": {}}], products=products if products is not None else [_p()])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)
    monkeypatch.setenv("FRONTEND_URL", "https://opsra-frontend.onrender.com")
    monkeypatch.delenv("CATALOG_BASE_URL", raising=False)


@pytest.fixture(autouse=True)
def _storefront_with_cart():
    with patch("app.services.catalog_storefront_service.resolve_template", return_value="storefront"), \
         patch("app.services.catalog_storefront_service.shop_info", return_value={"key": "wc_abcdefgh1"}):
        yield


BASE = "https://opsra-frontend.onrender.com/shop/royal-rest-mattress/cloud-9-mattress"


def test_plain_product_link():
    i = share.product_share_info(_db(), BIZ, "p1")
    assert i["link"] == BASE and i["variant"] is None and i["tag"] is None
    assert i["item"]["title"] == "Cloud 9 Mattress" and i["item"]["image"] == "https://img/c.jpg"
    assert i["short_link"].endswith("/shop/royal-rest-mattress")      # the store fields are still there


def test_tag_and_size_in_the_link_variant_first():
    i = share.product_share_info(_db(), BIZ, "p1", "Instagram", "12")
    assert i["link"] == BASE + "?variant=12&src=instagram"
    assert share.product_share_info(_db(), BIZ, "p1", "flyer")["link"] == BASE + "?src=flyer"
    assert share.product_share_info(_db(), BIZ, "p1", None, "11")["link"] == BASE + "?variant=11"


def test_only_real_sizes_are_offered():
    s = share.product_share_info(_db(), BIZ, "p1")["sizes"]
    assert s == [{"id": "11", "label": "Single 3/4 ft"}, {"id": "12", "label": "Queen 5/6 ft"}]
    assert share.sizes_of({"variants": [{"id": "d", "title": "Default Title"}]}) == []
    assert share.sizes_of({}) == []


@pytest.mark.parametrize("bad", ["13", "999", "12&src=x", "../x", "a b", "x" * 90])
def test_a_size_that_is_not_this_products_is_refused(bad):
    with pytest.raises(share.ShareError, match="not one of this product"):
        share.product_share_info(_db(), BIZ, "p1", None, bad)


def test_another_business_product_is_refused():
    with pytest.raises(share.ShareError, match="not found"):
        share.product_share_info(_db([_p(org=OTHER)]), BIZ, "p1")
    with pytest.raises(share.ShareError, match="not found"):
        share.product_share_info(_db(), BIZ, "nope")


def test_product_without_a_page_address_is_a_plain_error():
    with pytest.raises(share.ShareError, match="no page address"):
        share.product_share_info(_db([_p(slug=None)]), BIZ, "p1")


def test_no_warnings_when_everything_is_fine():
    assert share.product_share_info(_db(), BIZ, "p1")["warnings"] == []


def test_hidden_and_out_of_stock_warnings():
    w = share.product_share_info(_db([_p(catalog_visible=False, available=False)]), BIZ, "p1")["warnings"]
    assert w == ["hidden", "out_of_stock"]
    assert share.product_share_info(_db([_p(available=False)]), BIZ, "p1")["warnings"] == ["out_of_stock"]


def test_classic_look_and_no_cart_warnings():
    with patch("app.services.catalog_storefront_service.resolve_template", return_value="classic"):
        assert share.product_share_info(_db(), BIZ, "p1")["warnings"] == ["classic_look"]
    with patch("app.services.catalog_storefront_service.shop_info", return_value=None):
        assert share.product_share_info(_db(), BIZ, "p1")["warnings"] == ["no_cart"]


def test_a_failing_look_up_does_not_break_the_window():
    with patch("app.services.catalog_storefront_service.resolve_template", side_effect=RuntimeError("boom")):
        i = share.product_share_info(_db(), BIZ, "p1")
    assert i["link"] == BASE and i["warnings"] == []


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


def test_route_share_item(owner):
    c, _ = owner
    r = c.get("/api/v1/catalog/share?item=p1&variant=11&src=Flyer")
    assert r.status_code == 200
    j = r.json()
    assert j["link"] == BASE + "?variant=11&src=flyer" and [s["id"] for s in j["sizes"]] == ["11", "12"] and j["warnings"] == []


def test_route_share_without_item_is_unchanged(owner):
    c, _ = owner
    j = c.get("/api/v1/catalog/share?src=flyer").json()
    assert "link" not in j and j["tagged_link"].endswith("/shop/royal-rest-mattress?src=flyer")


def test_route_bad_size_and_other_product_are_422(owner):
    c, _ = owner
    assert c.get("/api/v1/catalog/share?item=p1&variant=999").status_code == 422
    assert c.get("/api/v1/catalog/share?item=zzz").status_code == 422


def test_route_qr_encodes_the_product_link_and_names_the_download(owner):
    c, _ = owner
    with patch("app.services.catalog_share_service.qr_svg", return_value=b"<svg/>") as q:
        r = c.get("/api/v1/catalog/qr.svg?item=p1&src=shop&download=true")
    assert q.call_args.args[0] == BASE + "?src=shop"
    assert 'filename="product-qr-cloud-9-mattress.svg"' in r.headers["content-disposition"]
    real = c.get("/api/v1/catalog/qr.svg?item=p1")
    assert real.status_code == 200 and real.content.startswith(b"<svg")


@pytest.mark.parametrize("owner", ["sales_agent"], indirect=True)
def test_product_share_needs_owner_or_ops_manager(owner):
    c, _ = owner
    assert c.get("/api/v1/catalog/share?item=p1").status_code == 403
    assert c.get("/api/v1/catalog/qr.svg?item=p1").status_code == 403
