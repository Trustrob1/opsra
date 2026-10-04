"""
tests/integration/test_public_form_access.py
SITE-ACCESS-1 - submitting a brief form creates a site, so it respects the builder's free-site cap.
The answers stay on the form, so a blocked submission loses nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import public_forms as pf
from tests.funnel_fake_db import FakeDB

TOKEN = "tok_access1"


def _db(n_sites, audience="builder", paid_until=None):
    form = {"id": "f1", "org_id": "o1", "builder_id": "b1", "audience": audience, "status": "open", "preset_id": "p1",
            "token_hash": pf.hash_form_token(TOKEN), "expires_at": None, "answers": {"city": "Lagos"}, "submit_count": 0}
    preset = {"id": "p1", "org_id": "o1", "key": "boutique", "name": "B", "sections": ["hero"], "allowed_themes": ["atelier"],
              "default_palettes": ["berry"], "brief_questions": [], "labels": {}}
    builder = {"id": "b1", "org_id": "o1", "full_name": "Chidi", "phone_number": "2348030000001", "status": "active",
               "max_active_sites": None, "access_paid_until": paid_until}
    sites = [{"id": f"s{i}", "org_id": "o1", "builder_id": "b1", "status": "preview_ready", "deleted_at": None} for i in range(n_sites)]
    return FakeDB(site_brief_forms=[form], site_presets=[preset], sites=sites, site_assets=[], site_events=[],
                  site_builders=[builder], site_builder_settings=[{"org_id": "o1", "pricing": {}}], whatsapp_numbers=[])


@pytest.fixture()
def use_db():
    holder = {}

    def _use(*a, **k):
        holder["db"] = _db(*a, **k)
        app.dependency_overrides[get_supabase] = lambda: holder["db"]
        return holder["db"]
    yield _use
    app.dependency_overrides.pop(get_supabase, None)


def _submit():
    with patch("app.services.site_copy_service.call_claude", side_effect=RuntimeError("no ai")):
        return TestClient(app).post(f"/api/v1/forms/{TOKEN}/submit", json={"answers": {}, "client_business_name": "Ada Web"})


def test_submit_works_under_the_cap(use_db):
    db = use_db(2)
    r = _submit()
    assert r.status_code == 200, r.text
    assert len(db.rows("sites")) == 3 and db.rows("site_brief_forms")[0]["status"] == "submitted"


def test_builder_form_is_blocked_at_the_cap_and_keeps_its_answers(use_db):
    db = use_db(3)
    r = _submit()
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "ACCESS_LIMIT" and "subscribe" in d["message"].lower() and "saved" in d["message"].lower()
    assert len(db.rows("sites")) == 3
    form = db.rows("site_brief_forms")[0]
    assert form["status"] == "open" and form["answers"] == {"city": "Lagos"}


def test_client_form_gets_a_neutral_message(use_db):
    use_db(3, audience="client")
    r = _submit()
    assert r.status_code == 403
    msg = r.json()["detail"]["message"]
    assert "subscribe" not in msg.lower() and "person who sent" in msg


def test_subscriber_can_submit_past_the_cap(use_db):
    db = use_db(5, paid_until=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())
    assert _submit().status_code == 200
    assert len(db.rows("sites")) == 6
