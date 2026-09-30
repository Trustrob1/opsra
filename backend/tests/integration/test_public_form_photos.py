"""
tests/integration/test_public_form_photos.py
Brief-form photos must survive autosave and submit. The upload route stores full photo records in
answers._photos; the page only holds picture URLs and used to send them back, which overwrote the
records and made the submit-time copy fail (TypeError) — the site was created with no photos.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import public_forms as pf
from tests.funnel_fake_db import FakeDB

TOKEN = "tok_abc123"
URL = "https://x.supabase.co/storage/v1/object/public/site-assets/forms/aaaa/photos-1234.png"
RECORD = {"storage_path": "forms/aaaa/photos-1234.png", "public_url": URL, "mime_type": "image/png", "bytes": 999}


@contextmanager
def _c():
    yield TestClient(app)


def _db(photos):
    form = {"id": "f1", "org_id": "o1", "builder_id": "b1", "audience": "builder", "status": "open", "preset_id": "p1",
            "token_hash": pf.hash_form_token(TOKEN), "expires_at": None, "answers": {"_photos": photos, "city": "Lagos"}, "submit_count": 0}
    preset = {"id": "p1", "org_id": "o1", "key": "boutique", "name": "B", "sections": ["hero"], "allowed_themes": ["atelier"],
              "default_palettes": ["berry"], "brief_questions": [], "labels": {}}
    return FakeDB(site_brief_forms=[form], site_presets=[preset], sites=[], site_assets=[], site_events=[], site_builders=[], whatsapp_numbers=[])


@pytest.fixture()
def use_db():
    holder = {}

    def _use(photos):
        holder["db"] = _db(photos)
        app.dependency_overrides[get_supabase] = lambda: holder["db"]
        return holder["db"]
    yield _use
    app.dependency_overrides.pop(get_supabase, None)


def test_autosave_never_lets_the_client_overwrite_photo_records(use_db):
    db = use_db({"photos": [RECORD]})
    with _c() as c:
        r = c.patch(f"/api/v1/forms/{TOKEN}", json={"answers": {"city": "Abuja", "_photos": {"photos": [URL]}}})
    assert r.status_code == 200, r.text
    ans = db.rows("site_brief_forms")[0]["answers"]
    assert ans["city"] == "Abuja" and ans["_photos"] == {"photos": [RECORD]}


def test_submit_copies_photos_even_when_the_client_sends_urls(use_db):
    db = use_db({"photos": [RECORD]})
    with _c() as c, patch("app.services.site_copy_service.call_claude", side_effect=RuntimeError("no ai")):
        r = c.post(f"/api/v1/forms/{TOKEN}/submit", json={"answers": {"_photos": {"photos": [URL]}}, "client_business_name": "Ada Web"})
    assert r.status_code == 200, r.text
    assets = db.rows("site_assets")
    assert len(assets) == 1 and assets[0]["storage_path"] == RECORD["storage_path"] and assets[0]["slot"] == "photos"


def test_submit_recovers_a_form_already_damaged_by_the_old_bug(use_db):
    db = use_db({"photos": [URL]})            # the stored value is a bare URL, as older forms have
    with _c() as c, patch("app.services.site_copy_service.call_claude", side_effect=RuntimeError("no ai")):
        r = c.post(f"/api/v1/forms/{TOKEN}/submit", json={"answers": {}, "client_business_name": "Ada Web"})
    assert r.status_code == 200, r.text
    assets = db.rows("site_assets")
    assert len(assets) == 1 and assets[0]["storage_path"] == "forms/aaaa/photos-1234.png" and assets[0]["mime_type"] == "image/png"


@pytest.mark.parametrize("entry,ok", [(RECORD, True), (URL, True), ("not a url", False), (123, False), ({"storage_path": "x"}, False)])
def test_photo_record(entry, ok):
    assert bool(pf._photo_record(entry)) is ok
