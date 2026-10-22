"""
tests/unit/test_store_1.py
--------------------------
STORE-1: the "Storefront" catalog look, backend only.
  * plan feature key catalog_storefront (account scope, in no default tier)
  * resolve_template: Classic by default, Storefront only when chosen AND the plan includes it
  * shop_info: the cart is offered only when web chat + shop + plan + Paystack + a chat key all exist; never writes
  * discount_percent / public_style helpers
  * web chat cart refuses out-of-stock items and options (add + checkout re-check)
  * public catalog routes return template / shop / style / compare_at_price / discount_percent
  * owner PATCH /catalog/config: Storefront settings validated, plan decides who may switch it on
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import catalog_storefront_service as sf
from app.services import site_feature_registry as reg
from app.services import webchat_shop_service as shop
from tests.unit.test_account_plans_1 import BIZ, PLATFORM, FakeDB, _plan

KEY = "catalog_storefront"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def _plan_db(enforced=False, plans=None, tier_features=None, **extra):
    settings = {"org_id": PLATFORM, "pricing": {"tiers": {
        "capture": {"monthly_ngn": 15000, "features": ["webchat_basic"], "caps": {}},
        "convert": {"monthly_ngn": 30000, "features": tier_features if tier_features is not None else ["webchat_basic", "payment_links", KEY], "caps": {}},
        "grow": {"monthly_ngn": 0},
    }}}
    return FakeDB(
        site_builder_settings=[settings],
        organisations=[{"id": BIZ, "name": "Glow", "slug": "glow", "subscription_status": "active", "plans_enforced": enforced,
                        "webchat_config": extra.pop("webchat_config", {})}],
        org_plans=plans or [], org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[],
        webchat_keys=extra.pop("webchat_keys", []), **extra)


# ---------------------------------------------------------------- registry

def test_feature_key_is_registered_account_scope_and_built():
    f = reg.FEATURES[KEY]
    assert f["scope"] == "account" and f["built"] and f["group"] == "convert" and f["cap"] is None


def test_feature_key_is_in_no_default_tier():
    for tier, feats in reg.DEFAULT_TIER_FEATURES.items():
        assert KEY not in feats, tier
    assert all(KEY not in pair for pairs in reg.DEFAULT_PICK_ONE.values() for pair in pairs)


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("price,compare,expected", [
    (59.99, 89.99, 33), (50, 100, 50), (100, 100, None), (100, 80, None), (0, 100, None),
    (100, None, None), ("x", 100, None), (None, None, None), (99.9, 100, None),
])
def test_discount_percent_only_when_really_higher(price, compare, expected):
    assert sf.discount_percent(price, compare) == expected


def test_public_style_cleans_everything():
    out = sf.public_style({"announcement": "  Free   delivery in Lagos  " + "x" * 200, "trust_points": ["a", " b  c ", "", "d", "e"],
                           "accent": "#0B6E74", "logo_url": "https://cdn.example.com/l.png"})
    assert len(out["announcement"]) == sf.ANNOUNCEMENT_MAX and out["announcement"].startswith("Free delivery in Lagos")
    assert out["trust_points"] == ["a", "b c"]          # first 3 taken, blanks dropped
    assert out["accent"] == "#0B6E74" and out["logo_url"] == "https://cdn.example.com/l.png"


@pytest.mark.parametrize("bad", ["red", "#12345", "#GGGGGG", "javascript:alert(1)", None, 5])
def test_public_style_rejects_bad_accent(bad):
    assert sf.public_style({"accent": bad})["accent"] is None


@pytest.mark.parametrize("bad", ["http://x.com/a.png", "javascript:alert(1)", "data:image/png;base64,AAA", "https://a b.com/x", "", None])
def test_public_style_rejects_bad_logo(bad):
    assert sf.public_style({"logo_url": bad})["logo_url"] is None


def test_public_style_handles_junk_config():
    assert sf.public_style(None) == {"announcement": None, "trust_points": [], "accent": None, "logo_url": None}
    assert sf.public_style({"trust_points": "nope"})["trust_points"] == []


# ---------------------------------------------------------------- resolve_template

def test_default_is_classic():
    db = _plan_db()
    assert sf.resolve_template(db, BIZ, {}) == "classic"
    assert sf.resolve_template(db, BIZ, None) == "classic"
    assert sf.resolve_template(db, BIZ, {"template": "classic"}) == "classic"
    assert sf.resolve_template(db, BIZ, {"template": "weird"}) == "classic"


def test_storefront_when_not_switched_onto_plans():
    assert sf.resolve_template(_plan_db(enforced=False), BIZ, {"template": "storefront"}) == "storefront"


def test_storefront_when_plan_includes_it():
    db = _plan_db(enforced=True, plans=[_plan(key="convert")])
    assert sf.resolve_template(db, BIZ, {"template": "storefront"}) == "storefront"


def test_classic_when_plan_lacks_it_and_choice_is_kept():
    db = _plan_db(enforced=True, plans=[_plan(key="convert")], tier_features=["webchat_basic"])
    cfg = {"template": "storefront"}
    assert sf.resolve_template(db, BIZ, cfg) == "classic"
    assert cfg == {"template": "storefront"}


def test_classic_when_enforced_and_no_plan():
    assert sf.resolve_template(_plan_db(enforced=True), BIZ, {"template": "storefront"}) == "classic"


def test_classic_when_the_check_blows_up():
    with patch.object(sf, "storefront_allowed", side_effect=RuntimeError("down")):
        assert sf.resolve_template(_plan_db(), BIZ, {"template": "storefront"}) == "classic"


# ---------------------------------------------------------------- shop_info

CHAT_ON = {"enabled": True, "shop_enabled": True}


def _shop_db(**kw):
    kw.setdefault("webchat_config", CHAT_ON)
    kw.setdefault("webchat_keys", [{"key": "wc_abcdefghijkl", "org_id": BIZ, "active": True}])
    return _plan_db(**kw)


def _creds(secret="sk_test_x"):
    return patch("app.services.paystack_storefront_service._get_storefront_credentials", return_value={"secret_key": secret} if secret else {})


def test_shop_info_when_everything_is_ready():
    db = _shop_db()
    with _creds():
        assert sf.shop_info(db, BIZ) == {"key": "wc_abcdefghijkl"}
    assert not [c for c in db.calls if c[1] != "select"]           # reading never writes


def test_shop_info_needs_shop_switch():
    with _creds():
        assert sf.shop_info(_shop_db(webchat_config={"enabled": True, "shop_enabled": False}), BIZ) is None


def test_shop_info_needs_web_chat_on():
    with _creds():
        assert sf.shop_info(_shop_db(webchat_config={"enabled": False, "shop_enabled": True}), BIZ) is None


def test_shop_info_needs_paystack():
    for secret in (None, "", "   "):
        with _creds(secret):
            assert sf.shop_info(_shop_db(), BIZ) is None


def test_shop_info_needs_an_existing_key_and_never_creates_one():
    db = _shop_db(webchat_keys=[])
    with _creds():
        assert sf.shop_info(db, BIZ) is None
    assert db.rows("webchat_keys") == []


def test_shop_info_ignores_inactive_key():
    db = _shop_db(webchat_keys=[{"key": "wc_abcdefghijkl", "org_id": BIZ, "active": False}])
    with _creds():
        assert sf.shop_info(db, BIZ) is None


def test_shop_info_needs_plan_payment_links():
    db = _shop_db(enforced=True, plans=[_plan(key="convert")], tier_features=["webchat_basic", KEY])      # no payment_links
    with _creds():
        assert sf.shop_info(db, BIZ) is None


def test_shop_info_fails_safe():
    with patch("app.services.webchat_service.get_config", side_effect=RuntimeError("down")):
        assert sf.shop_info(_shop_db(), BIZ) is None


def test_public_extras_classic_exposes_nothing_extra():
    db = _shop_db()
    with _creds():
        out = sf.public_extras(db, BIZ, {"announcement": "hi"})
    assert out == {"template": "classic", "shop": None, "style": None}


def test_public_extras_storefront():
    db = _shop_db()
    with _creds():
        out = sf.public_extras(db, BIZ, {"template": "storefront", "announcement": "Hello", "accent": "#112233"})
    assert out["template"] == "storefront" and out["shop"] == {"key": "wc_abcdefghijkl"}
    assert out["style"]["announcement"] == "Hello" and out["style"]["accent"] == "#112233"
    assert set(out["shop"]) == {"key"}                                  # nothing else about the shop leaks


# ---------------------------------------------------------------- cart stock checks

ORG = "00000000-0000-0000-0000-0000000000e1"


class _FakeShopDB:
    def __init__(self, products):
        self.products = products
        self.saved = None

    def table(self, name):
        assert name == "products"
        outer = self

        class Q:
            def __init__(self): self.pid = None
            def select(self, *_a, **_k): return self
            def eq(self, c, v):
                if c == "id": self.pid = v
                return self
            def limit(self, _n): return self
            def execute(self):
                rows = [p for p in outer.products if self.pid is None or p["id"] == self.pid]
                return MagicMock(data=rows)
        return Q()


def _session(cart=None):
    return {"org_id": ORG, "id": "S1", "state": {"cart": cart or []}, "lead_id": "L1"}


def _patch_save():
    return patch.object(shop, "_save", side_effect=lambda db, s, cart: {"items": cart, "total": 0, "count": len(cart)})


MATTRESS = {"id": "p1", "title": "Cloud 9", "price": 150000, "available": True, "variants": [
    {"id": "v-in", "title": "Queen", "price": 150000, "available": True},
    {"id": "v-out", "title": "King", "price": 190000, "available": False},
    {"id": "sh-in", "title": "Double", "price": 120000, "inventory_management": "shopify", "inventory_quantity": 3},
    {"id": "sh-out", "title": "Single", "price": 90000, "inventory_management": "shopify", "inventory_quantity": 0, "inventory_policy": "deny"},
    {"id": "sh-cont", "title": "Twin", "price": 95000, "inventory_management": "shopify", "inventory_quantity": 0, "inventory_policy": "continue"},
]}


def test_add_in_stock_option_works():
    db = _FakeShopDB([MATTRESS])
    for vid in ("v-in", "sh-in", "sh-cont"):
        with _patch_save():
            assert "error" not in shop.add(db, _session(), "p1", vid, 1), vid


@pytest.mark.parametrize("vid", ["v-out", "sh-out"])
def test_add_out_of_stock_option_is_refused(vid):
    with _patch_save():
        res = shop.add(_FakeShopDB([MATTRESS]), _session(), "p1", vid, 1)
    assert res == {"error": "That option is out of stock."}


def test_add_unavailable_product_is_refused():
    p = {"id": "p2", "title": "Pillow", "price": 5000, "available": False, "variants": []}
    with _patch_save():
        assert shop.add(_FakeShopDB([p]), _session(), "p2", None, 1) == {"error": "That item is out of stock."}


def test_available_unset_is_still_sellable():
    p = {"id": "p3", "title": "Sheet", "price": 5000, "variants": []}                 # older rows: no available flag
    with _patch_save():
        assert "error" not in shop.add(_FakeShopDB([p]), _session(), "p3", None, 1)


def test_checkout_reprice_drops_lines_that_sold_out_since():
    cart = [{"pid": "p1", "vid": "v-in", "name": "Cloud 9 - Queen", "price": 1, "qty": 1},
            {"pid": "p1", "vid": "v-out", "name": "Cloud 9 - King", "price": 1, "qty": 1}]
    kept, dropped = shop._reprice(_FakeShopDB([MATTRESS]), _session(cart))
    assert [k["vid"] for k in kept] == ["v-in"] and kept[0]["price"] == 150000
    assert dropped == ["Cloud 9 - King"]


def test_checkout_reprice_drops_product_marked_unavailable():
    p = {"id": "p2", "title": "Pillow", "price": 5000, "available": False, "variants": []}
    kept, dropped = shop._reprice(_FakeShopDB([p]), _session([{"pid": "p2", "vid": None, "name": "Pillow", "price": 5000, "qty": 1}]))
    assert kept == [] and dropped == ["Pillow"]


# ---------------------------------------------------------------- public catalog routes

SLUG = "royal-rest"
ORG_ROW = {"id": "org-1", "name": "Royal Rest", "slug": SLUG, "org_whatsapp_number": "2348012345678", "qualification_flow": None,
           "catalog_config": {"template": "storefront", "announcement": "Delivery in Lagos", "accent": "#0B6E74"}}
ITEM = {"id": "i1", "title": "Cloud 9", "slug": "cloud-9", "description": "d", "price": 60, "compare_at_price": 90, "catalog_images": [],
        "tags": {}, "custom_fields": {}, "available": True, "catalog_views": 0, "variants": []}


def _route_db(org=ORG_ROW, items=None):
    db = MagicMock()

    def chain(rows):
        q = MagicMock()
        q.select.return_value = q
        q.eq.return_value = q
        q.is_.return_value = q
        q.execute.return_value = MagicMock(data=rows)
        return q
    orgs, prods = chain([org]), chain(items if items is not None else [ITEM])
    db.table.side_effect = lambda n: orgs if n == "organisations" else prods if n == "products" else MagicMock()
    return db


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import public_catalog
    public_catalog._list_cache.clear()
    public_catalog._item_cache.clear()
    public_catalog._rate_store.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _extras(template="storefront", shop_=None, style=None):
    return patch("app.routers.public_catalog.storefront.public_extras", return_value={"template": template, "shop": shop_, "style": style})


def test_list_route_returns_extras_and_discount(client):
    with patch("app.routers.public_catalog.get_supabase", return_value=_route_db()), \
            _extras("storefront", {"key": "wc_abcdefghijkl"}, {"announcement": "Delivery in Lagos"}):
        body = client.get(f"/api/v1/public/catalog/{SLUG}").json()
    assert body["template"] == "storefront" and body["shop"] == {"key": "wc_abcdefghijkl"}
    assert body["style"]["announcement"] == "Delivery in Lagos"
    it = body["items"][0]
    assert it["compare_at_price"] == 90 and it["discount_percent"] == 33


def test_item_route_returns_extras(client):
    with patch("app.routers.public_catalog.get_supabase", return_value=_route_db()), _extras("classic"):
        body = client.get(f"/api/v1/public/catalog/{SLUG}/cloud-9").json()
    assert body["template"] == "classic" and body["shop"] is None
    assert body["item"]["compare_at_price"] == 90


def test_no_discount_when_compare_at_not_higher(client):
    item = {**ITEM, "compare_at_price": 50}
    with patch("app.routers.public_catalog.get_supabase", return_value=_route_db(items=[item])), _extras("classic"):
        it = client.get(f"/api/v1/public/catalog/{SLUG}").json()["items"][0]
    assert it["discount_percent"] is None


def test_price_on_request_hides_the_was_price(client):
    org = {**ORG_ROW, "catalog_config": {**ORG_ROW["catalog_config"], "price_on_request": True}}
    with patch("app.routers.public_catalog.get_supabase", return_value=_route_db(org=org)), _extras("classic"):
        it = client.get(f"/api/v1/public/catalog/{SLUG}").json()["items"][0]
    assert it["compare_at_price"] is None and it["discount_percent"] is None


def test_existing_item_fields_unchanged(client):
    with patch("app.routers.public_catalog.get_supabase", return_value=_route_db()), _extras("classic"):
        it = client.get(f"/api/v1/public/catalog/{SLUG}").json()["items"][0]
    for k in ("id", "title", "slug", "description", "catalog_description", "price", "price_label", "catalog_images", "tags",
              "custom_fields", "available", "catalog_views", "variants"):
        assert k in it
    assert "org_id" not in it


def test_public_response_never_leaks_internals(client):
    db = _route_db()
    with patch("app.routers.public_catalog.get_supabase", return_value=db), _shop_ready():
        raw = client.get(f"/api/v1/public/catalog/{SLUG}").text
    for secret in ("sk_test_x", "secret_key", "org-1", "token", "webchat_config"):
        assert secret not in raw


def _shop_ready():
    class _Ctx:
        def __enter__(self):
            self.ps = [patch("app.services.catalog_storefront_service.storefront_allowed", return_value=True),
                       patch("app.services.catalog_storefront_service.shop_info", return_value={"key": "wc_abcdefghijkl"})]
            for p in self.ps: p.start()
        def __exit__(self, *a):
            for p in self.ps: p.stop()
    return _Ctx()


# ---------------------------------------------------------------- owner settings

def _owner_client(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_current_org, get_supabase
    app.dependency_overrides[get_current_org] = lambda: {"org_id": BIZ, "roles": {"template": "owner"}}
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


@pytest.fixture()
def owner_cleanup():
    yield
    from app.main import app
    app.dependency_overrides.clear()


def _owner_db(allowed=True, config=None):
    return MagicMock(), allowed, config or {"catalog_item_label": "Product"}


def test_owner_can_save_storefront_settings_when_plan_allows(owner_cleanup):
    db = MagicMock()
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=True), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config", side_effect=lambda d, o, u: {"catalog_item_label": "P", **u}) as upd:
        c = _owner_client(db)
        r = c.patch("/api/v1/catalog/config", json={"template": "storefront", "announcement": "Hi", "trust_points": [" Pay  safely ", "x"],
                                                   "accent": "#0B6E74", "logo_url": "https://cdn.example.com/a.png"})
    assert r.status_code == 200, r.text
    saved = upd.call_args[0][2]
    assert saved["template"] == "storefront" and saved["trust_points"] == ["Pay safely", "x"]
    assert r.json()["storefront_allowed"] is True


def test_owner_blocked_from_storefront_when_plan_lacks_it(owner_cleanup):
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=False), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config") as upd:
        r = _owner_client(MagicMock()).patch("/api/v1/catalog/config", json={"template": "storefront"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "PLAN_REQUIRED"
    upd.assert_not_called()


def test_owner_can_always_go_back_to_classic(owner_cleanup):
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=False), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config", side_effect=lambda d, o, u: u):
        r = _owner_client(MagicMock()).patch("/api/v1/catalog/config", json={"template": "classic"})
    assert r.status_code == 200


@pytest.mark.parametrize("body", [
    {"template": "fancy"}, {"accent": "red"}, {"accent": "#12345"}, {"logo_url": "http://x.com/a.png"}, {"logo_url": "javascript:alert(1)"},
    {"trust_points": ["a", "b", "c", "d"]}, {"trust_points": ["x" * 41]}, {"announcement": "x" * 121},
])
def test_owner_bad_storefront_values_are_422(owner_cleanup, body):
    with patch("app.services.plan_gate_service.allowed", return_value=True), patch("app.routers.catalog.update_catalog_config") as upd:
        r = _owner_client(MagicMock()).patch("/api/v1/catalog/config", json=body)
    assert r.status_code == 422
    upd.assert_not_called()


def test_owner_can_clear_text_settings(owner_cleanup):
    with patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.update_catalog_config", side_effect=lambda d, o, u: u) as upd:
        r = _owner_client(MagicMock()).patch("/api/v1/catalog/config", json={"announcement": "", "accent": "", "logo_url": "", "trust_points": []})
    assert r.status_code == 200
    assert upd.call_args[0][2] == {"announcement": "", "accent": "", "logo_url": "", "trust_points": []}


def test_owner_config_get_reports_whether_storefront_is_allowed(owner_cleanup):
    with patch("app.routers.catalog.storefront.storefront_allowed", return_value=False), \
            patch("app.services.plan_gate_service.allowed", return_value=True), \
            patch("app.routers.catalog.get_catalog_config", return_value={"template": "storefront"}):
        r = _owner_client(MagicMock()).get("/api/v1/catalog/config")
    assert r.status_code == 200 and r.json()["storefront_allowed"] is False
