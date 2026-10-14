"""
tests/integration/test_site_option_forms.py
SITE-OPTIONS OPT-1 - a brief form made for an option set builds a design OPTION: it is not blocked by the builder's
free-sites limit, the new site joins the set and does not use a free slot. A full or foreign set gives no exemption.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import public_forms as pf
from app.services import site_access_service as access
from tests.funnel_fake_db import FakeDB

TOKEN = "tok_options1"


def _db(n_sites=3, set_builder="b1", set_status="open", n_items=0):
    form = {"id": "f1", "org_id": "o1", "builder_id": "b1", "audience": "builder", "status": "open", "preset_id": "p1",
            "token_hash": pf.hash_form_token(TOKEN), "expires_at": None, "answers": {}, "submit_count": 0,
            "option_set_id": "set1"}
    preset = {"id": "p1", "org_id": "o1", "key": "boutique", "name": "B", "sections": ["hero"], "allowed_themes": ["atelier"],
              "default_palettes": ["berry"], "brief_questions": [], "labels": {}}
    builder = {"id": "b1", "org_id": "o1", "full_name": "Chidi", "phone_number": "2348030000001", "status": "active",
               "max_active_sites": None, "access_paid_until": None}
    sites = [{"id": f"s{i}", "org_id": "o1", "builder_id": "b1", "status": "preview_ready", "deleted_at": None,
              "option_offered": False} for i in range(n_sites)]
    oset = {"id": "set1", "org_id": "o1", "builder_id": set_builder, "status": set_status, "token": "t" * 30,
            "chosen_site_id": None, "expires_at": "2099-01-01T00:00:00+00:00", "client_name": "Mrs Obi"}
    items = []
    for i in range(n_items):
        sites.append({"id": f"o{i}", "org_id": "o1", "builder_id": "b1", "status": "preview_ready", "deleted_at": None,
                      "option_offered": True, "option_set_id": "set1"})
        items.append({"id": f"i{i}", "org_id": "o1", "set_id": "set1", "site_id": f"o{i}", "label": f"Design {i}",
                      "sort_order": i, "status": "offered"})
    return FakeDB(site_brief_forms=[form], site_presets=[preset], sites=sites, site_assets=[], site_events=[],
                  site_builders=[builder], site_builder_settings=[{"org_id": "o1", "pricing": {}}], whatsapp_numbers=[],
                  site_option_sets=[oset], site_option_items=items, site_orders=[])


@pytest.fixture()
def use_db():
    holder = {}

    def _use(**k):
        holder["db"] = _db(**k)
        app.dependency_overrides[get_supabase] = lambda: holder["db"]
        return holder["db"]
    yield _use
    app.dependency_overrides.pop(get_supabase, None)


def _submit():
    with patch("app.services.site_copy_service.call_claude", side_effect=RuntimeError("no ai")):
        return TestClient(app).post(f"/api/v1/forms/{TOKEN}/submit", json={"answers": {}, "client_business_name": "Ada Web"})


def test_an_option_form_works_at_the_free_limit_and_joins_the_set(use_db):
    db = use_db(n_sites=3)
    r = _submit()
    assert r.status_code == 200, r.text
    new = [s for s in db.rows("sites") if s.get("client_business_name") == "Ada Web"][0]
    assert new["option_set_id"] == "set1" and new["option_offered"] is True
    assert [i["site_id"] for i in db.rows("site_option_items")] == [new["id"]]
    assert db.rows("site_option_items")[0]["label"] == "Design A"
    assert access.count_sites(db, "o1", "b1") == 3                  # the new design did not use a free slot


def test_the_limit_applies_again_once_the_set_is_full(use_db):
    db = use_db(n_sites=3, n_items=5)
    r = _submit()
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACCESS_LIMIT"
    assert len(db.rows("sites")) == 8 and db.rows("site_brief_forms")[0]["status"] == "open"


def test_someone_elses_set_gives_no_exemption(use_db):
    use_db(n_sites=3, set_builder="b2")
    assert _submit().status_code == 403


def test_a_closed_set_gives_no_exemption(use_db):
    use_db(n_sites=3, set_status="closed")
    assert _submit().status_code == 403


def test_a_form_without_a_set_behaves_as_before(use_db):
    db = use_db(n_sites=3)
    db.rows("site_brief_forms")[0].pop("option_set_id")
    assert _submit().status_code == 403
