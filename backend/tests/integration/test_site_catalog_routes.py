"""
tests/integration/test_site_catalog_routes.py
GIVEAWAY-2 - the builder portal: a save that adds items past the template's limit is refused with a pack offer (402),
the site detail carries the limit, and the pack checkout route works.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-0000000000aa"
BUILDER = {"id": "b1", "org_id": ORG, "phone_number": "+2348000000001", "full_name": "Ada", "status": "active", "lead_id": "lead-1"}


def _content(n):
    return {"business": {"name": "Zed Shop", "whatsapp_e164": "+2348000000002"},
            "hero": {"headline": "Hi", "subhead": "", "image_asset_id": None},
            "items": [{"name": f"Item {i}", "desc": "", "price_ngn": 100, "price_style": "exact", "tag": None, "image_asset_id": None} for i in range(n)]}


@pytest.fixture
def ctx():
    db = FakeDB(
        sites=[{"id": "s1", "org_id": ORG, "builder_id": "b1", "preset_id": "pr1", "status": "preview_ready", "slug": "zed",
                "client_business_name": "Zed Shop", "content": _content(30), "recipe": {}, "revision_count": 0, "extra_items": 0}],
        site_presets=[{"id": "pr1", "org_id": ORG, "max_items": 30, "sections": [], "allowed_themes": []}],
        site_builder_settings=[], site_care_plans=[], site_revisions=[], site_events=[], site_assets=[], site_orders=[],
        payment_links=[], site_premium_designs=[], site_import_pages=[])
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[builder_portal.get_current_builder] = lambda: BUILDER
    yield TestClient(app, raise_server_exceptions=False), db
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def test_adding_past_the_limit_is_refused_with_the_pack_offer(ctx):
    client, db = ctx
    r = client.patch("/api/v1/builder/sites/s1/content", json={"content": _content(31)})
    assert r.status_code == 402
    d = r.json()["detail"]
    assert d["code"] == "CATALOG_LIMIT" and d["offer"]["pack_items"] == 30 and d["offer"]["pack_price"] == 5000
    assert len(db.rows("sites")[0]["content"]["items"]) == 30            # nothing saved
    assert db.rows("site_care_plans") == []                              # and no edit was used up


def test_same_size_or_smaller_saves_still_work(ctx):
    client, db = ctx
    assert client.patch("/api/v1/builder/sites/s1/content", json={"content": _content(30)}).status_code == 200
    assert client.patch("/api/v1/builder/sites/s1/content", json={"content": _content(20)}).status_code == 200


def test_a_bought_pack_allows_growth(ctx):
    client, db = ctx
    db.tables["sites"][0]["extra_items"] = 30
    assert client.patch("/api/v1/builder/sites/s1/content", json={"content": _content(45)}).status_code == 200


def test_site_detail_carries_the_limit(ctx):
    client, db = ctx
    r = client.get("/api/v1/builder/sites/s1")
    assert r.status_code == 200
    lim = r.json()["data"]["item_limit"]
    assert lim["limit"] == 30 and lim["can_buy"] is True and lim["pack_price"] == 5000


def test_pack_checkout_route(ctx, monkeypatch):
    client, db = ctx
    from app.services import paystack_storefront_service as pay
    monkeypatch.setattr(pay, "generate_payment_link", lambda **k: {"checkout_url": "https://pay.test/p", "reference": "r1", "payment_link_id": "pl1"})
    r = client.post("/api/v1/builder/sites/s1/catalog/checkout")
    assert r.status_code == 200 and r.json()["data"]["amount"] == 5000 and r.json()["data"]["items"] == 30
    assert db.rows("site_orders")[0]["kind"] == "catalog_pack"
    assert client.post("/api/v1/builder/sites/nope/catalog/checkout").status_code == 404
