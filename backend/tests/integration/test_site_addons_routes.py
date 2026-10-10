"""
tests/integration/test_site_addons_routes.py
SITE-ADDONS A0-1 - the staff routes for a site's tier and add-ons, and PATCH /sites/settings checking the
pricing.tiers / addons / tier_billing numbers.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
SITE = "site-1"


def _org(template="owner", org_id=ORG):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": org_id, "roles": {"template": template}}


@pytest.fixture
def api():
    db = FakeDB(
        site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {"vat_pct": 7.5}}],
        sites=[{"id": SITE, "org_id": ORG, "deleted_at": None}, {"id": "site-x", "org_id": "org-2", "deleted_at": None}],
        site_addons=[], site_usage_counters=[], site_events=[])
    holder = {"db": db, "role": "owner"}
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    yield holder, TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


# -- settings validation ------------------------------------------------------------

def test_good_tier_settings_are_saved_whole_and_the_rest_of_pricing_is_kept(api):
    h, c = api
    r = c.patch("/api/v1/sites/settings", json={"pricing": {"vat_pct": 7.5, "tiers": {
        "capture": {"monthly_ngn": 15000.0, "setup_fee_ngn": 0}, "convert": {"monthly_ngn": 40000, "caps": {"ai_messages": 300}}},
        "tier_billing": {"grace_days": 7}}})
    assert r.status_code == 200, r.text
    saved = h["db"].rows("site_builder_settings")[0]["pricing"]
    assert saved["tiers"]["capture"]["monthly_ngn"] == 15000 and saved["vat_pct"] == 7.5


@pytest.mark.parametrize("pricing", [
    {"tiers": {"capture": {"monthly_ngn": -5}}}, {"tiers": {"capture": {"features": ["made_up"]}}},
    {"tiers": {"platinum": {}}}, {"addons": {"flying_car": {}}}, {"tier_billing": {"grace_days": 99}},
])
def test_bad_tier_settings_are_a_422_and_nothing_is_saved(api, pricing):
    h, c = api
    r = c.patch("/api/v1/sites/settings", json={"pricing": {"vat_pct": 7.5, **pricing}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR"
    saved = h["db"].rows("site_builder_settings")[0]["pricing"]
    assert "tiers" not in saved and "addons" not in saved and "tier_billing" not in saved


# -- routes -------------------------------------------------------------------------

def test_catalog_lists_tiers_addons_and_features_with_prices_at_zero(api):
    _, c = api
    r = c.get("/api/v1/site-addons/catalog")
    assert r.status_code == 200
    d = r.json()["data"]
    assert [t["key"] for t in d["tiers"]] == ["capture", "convert", "grow"]
    assert all(not t["sellable"] for t in d["tiers"])
    assert any(f["key"] == "form_instant_reply" and f["group"] == "capture" for f in d["features"])
    assert d["billing"]["grace_days"] == 7


def test_grant_then_read_then_pause_through_the_routes(api):
    h, c = api
    r = c.put(f"/api/v1/sites/{SITE}/addons", json={"kind": "tier", "key": "convert", "picks": ["selling_booking"]})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["tier"]["key"] == "convert" and "selling_booking" in d["features"] and "ai_assistant" in d["features"]
    got = c.get(f"/api/v1/sites/{SITE}/addons").json()["data"]
    assert got["features"] == d["features"]
    rid = got["tier"]["id"]
    p = c.post(f"/api/v1/sites/{SITE}/addons/{rid}/pause")
    assert p.status_code == 200 and p.json()["data"]["features"] == []
    again = c.post(f"/api/v1/sites/{SITE}/addons/{rid}/pause")
    assert again.status_code == 422
    res = c.post(f"/api/v1/sites/{SITE}/addons/{rid}/resume", json={"until": "2099-01-01T00:00:00Z"})
    assert res.status_code == 200 and res.json()["data"]["tier"]["status"] == "active"


def test_bad_grants_are_plain_errors(api):
    _, c = api
    assert c.put(f"/api/v1/sites/{SITE}/addons", json={"kind": "tier", "key": "platinum"}).status_code == 422
    assert c.put(f"/api/v1/sites/{SITE}/addons", json={"kind": "bogus", "key": "capture"}).status_code == 422
    assert c.put("/api/v1/sites/nope/addons", json={"kind": "tier", "key": "capture"}).status_code == 404
    assert c.put("/api/v1/sites/site-x/addons", json={"kind": "tier", "key": "capture"}).status_code == 404   # another org's site


def test_roles_and_feature_switch(api):
    h, c = api
    h["role"] = "admin"                                                    # read yes, write no
    assert c.get(f"/api/v1/sites/{SITE}/addons").status_code == 200
    assert c.put(f"/api/v1/sites/{SITE}/addons", json={"kind": "tier", "key": "capture"}).status_code == 403
    h["role"] = "sales_agent"
    assert c.get(f"/api/v1/sites/{SITE}/addons").status_code == 403
    assert c.get("/api/v1/site-addons/catalog").status_code == 403
    h["role"] = "owner"
    h["db"].rows("site_builder_settings")[0]["enabled"] = False
    assert c.get(f"/api/v1/sites/{SITE}/addons").status_code == 404        # the site engine is off for this org
