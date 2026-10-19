"""ACCOUNT-PLANS AP-8: Sites and Opsra Pricing belong to the platform organisation only."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.routers import account_plan as ap
from app.routers import superadmin_pricing as sp
from app.services import platform_guard as pg
from tests.unit.test_account_plans_1 import BIZ, OTHER, PLATFORM, FakeDB, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self


def _db():
    return FakeDB(site_builder_settings=[{"org_id": PLATFORM, "enabled": True, "pricing": {"tiers": {"capture": {"monthly_ngn": 1000}}}}],
                  organisations=[{"id": PLATFORM, "name": "Tech with Trust Robert"}, {"id": BIZ, "name": "Glow"}],
                  site_discount_codes=[])


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def test_platform_org_passes_and_everyone_else_gets_not_found():
    db = _db()
    assert asyncio.run(pg.platform_only({"org_id": PLATFORM}, db)) is None
    for other in (BIZ, OTHER):
        with pytest.raises(HTTPException) as e:
            asyncio.run(pg.platform_only({"org_id": other}, db))
        assert e.value.status_code == 404


def test_without_the_env_it_falls_back_to_the_oldest_settings_row(monkeypatch):
    monkeypatch.delenv("PLATFORM_ORG_ID")
    db = _db()
    assert pg.is_platform(db, PLATFORM) and not pg.is_platform(db, BIZ)


def test_status_endpoint_tells_the_app_which_org_is_platform():
    db = _db()
    assert ap.platform_status(db, {"org_id": PLATFORM}).data["is_platform"] is True
    assert ap.platform_status(db, {"org_id": BIZ}).data["is_platform"] is False


def test_every_staff_sites_router_is_guarded():
    import app.main as m
    guarded = {r.path for r in m.app.routes if getattr(r, "dependant", None)
               and any(d.call is pg.platform_only for d in r.dependant.dependencies)}
    for path in ("/api/v1/sites/settings", "/api/v1/site-addons/catalog", "/api/v1/sites/discount-codes"):
        assert path in guarded or any(g.endswith(path) for g in guarded), path
    unguarded = [r.path for r in m.app.routes if getattr(r, "path", "") in ("/api/v1/billing/plan", "/api/v1/builder/me")
                 and any(d.call is pg.platform_only for d in r.dependant.dependencies)]
    assert unguarded == []


def test_pricing_settings_are_saved_to_the_platform_row_and_checked():
    db = _db()
    assert sp.context(None, db).data["org_name"] == "Tech with Trust Robert"
    new = {"tiers": {"capture": {"monthly_ngn": 15000, "features": [], "caps": {}}}, "addons": {"extra_rep": {"monthly_ngn": 5000}}}
    out = sp.patch_settings({"pricing": new}, None, db).data
    assert out["pricing"]["addons"]["extra_rep"]["monthly_ngn"] == 5000 and out["org_id"] == PLATFORM
    assert sp.get_settings(None, db).data["pricing"]["tiers"]["capture"]["monthly_ngn"] == 15000
    with pytest.raises(HTTPException) as e:
        sp.patch_settings({"pricing": {"tiers": {"capture": {"monthly_ngn": -5}}}}, None, db)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        sp.patch_settings({"nothing": 1}, None, db)


def test_catalog_lists_plans_addons_and_features():
    cat = sp.catalog(None, _db()).data
    assert {t["key"] for t in cat["tiers"]} >= {"capture", "convert", "grow"}
    assert any(a["key"] == "extra_rep" for a in cat["addons"]) and any(f["key"] == "wa_leads" for f in cat["features"])


def test_pricing_without_a_platform_org_is_refused(monkeypatch):
    monkeypatch.delenv("PLATFORM_ORG_ID")
    with pytest.raises(HTTPException) as e:
        sp.get_settings(None, FakeDB(site_builder_settings=[]))
    assert e.value.status_code == 422
