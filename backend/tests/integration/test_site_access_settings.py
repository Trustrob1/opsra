"""
tests/integration/test_site_access_settings.py
SITE-WEB-2 - PATCH /sites/settings checks the pricing.builder_access numbers, and the saved numbers drive
site_access_service (free sites, price, days) and the sign-up daily cap.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import builder_signup_service as su, site_access_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
URL = "/api/v1/sites/settings"


def _org(template="owner"):
    return {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG, "roles": {"template": template}}


@pytest.fixture
def api():
    db = FakeDB(site_builder_settings=[{"org_id": ORG, "enabled": True, "pricing": {"vat_pct": 7.5}}])
    holder = {"db": db, "role": "owner"}
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: _org(holder["role"])
    yield holder, TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_supabase, None)
    app.dependency_overrides.pop(get_current_org, None)


def _patch(c, ba, **extra):
    return c.patch(URL, json={"pricing": {"vat_pct": 7.5, "builder_access": ba, **extra}})


def test_good_numbers_are_saved_and_whole(api):
    h, c = api
    r = _patch(c, {"free_sites": 5, "price_ngn": 7500.0, "days": 30, "signup_daily_cap": 80})
    assert r.status_code == 200, r.text
    saved = h["db"].rows("site_builder_settings")[0]["pricing"]
    assert saved["builder_access"] == {"free_sites": 5, "price_ngn": 7500, "days": 30, "signup_daily_cap": 80}
    assert saved["vat_pct"] == 7.5                                       # the rest of pricing is untouched
    cfg = site_access_service.get_config(h["db"].rows("site_builder_settings")[0])
    assert cfg == {"free_sites": 5, "price_ngn": 7500, "days": 30}
    assert su._daily_cap(h["db"].rows("site_builder_settings")[0]) == 80


@pytest.mark.parametrize("bad", [
    {"free_sites": -1}, {"free_sites": 1001}, {"free_sites": 2.5}, {"free_sites": "3"}, {"free_sites": True},
    {"price_ngn": -5}, {"price_ngn": 10_000_001}, {"days": 0}, {"days": 367}, {"signup_daily_cap": -1},
    {"signup_daily_cap": None},
])
def test_bad_numbers_are_a_422_and_nothing_is_saved(api, bad):
    h, c = api
    r = _patch(c, bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "builder_access" not in h["db"].rows("site_builder_settings")[0]["pricing"]


def test_zero_free_sites_and_zero_cap_are_allowed(api):
    h, c = api
    assert _patch(c, {"free_sites": 0, "signup_daily_cap": 0}).status_code == 200
    assert su._daily_cap(h["db"].rows("site_builder_settings")[0]) == 0


def test_builder_access_must_be_an_object(api):
    h, c = api
    assert _patch(c, "lots").status_code == 422


def test_pricing_without_builder_access_still_saves(api):
    h, c = api
    r = c.patch(URL, json={"pricing": {"vat_pct": 5}})
    assert r.status_code == 200 and h["db"].rows("site_builder_settings")[0]["pricing"]["vat_pct"] == 5


def test_only_owner_or_ops_manager_can_change_it(api):
    h, c = api
    h["role"] = "sales_agent"
    assert _patch(c, {"free_sites": 9}).status_code == 403


# ── SITE-TOOLS: design tool switches ─────────────────────────────────────

_FLAGS = ("premium_enabled", "site_import_enabled", "site_library_enabled")


def test_owner_can_switch_each_design_tool_on_and_off(api):
    h, c = api
    for f in _FLAGS:
        assert c.patch(URL, json={f: True}).status_code == 200
        assert h["db"].rows("site_builder_settings")[0][f] is True
        assert c.patch(URL, json={f: False}).json()["data"][f] is False


def test_ops_manager_cannot_switch_design_tools(api):
    h, c = api
    h["role"] = "ops_manager"
    for f in _FLAGS:
        r = c.patch(URL, json={f: True})
        assert r.status_code == 403
        assert f not in h["db"].rows("site_builder_settings")[0]
    assert c.patch(URL, json={"enabled": True}).status_code == 200      # other settings still allowed


@pytest.mark.parametrize("bad", ["true", 1, 0, None, "yes", []])
def test_design_tool_must_be_true_or_false(api, bad):
    h, c = api
    r = c.patch(URL, json={"site_library_enabled": bad})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "site_library_enabled" not in h["db"].rows("site_builder_settings")[0]


def test_switching_one_tool_leaves_the_others_alone(api):
    h, c = api
    c.patch(URL, json={"premium_enabled": True})
    c.patch(URL, json={"site_library_enabled": True})
    row = h["db"].rows("site_builder_settings")[0]
    assert row["premium_enabled"] is True and row["site_library_enabled"] is True
    assert "site_import_enabled" not in row
