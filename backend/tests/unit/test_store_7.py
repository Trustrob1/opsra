"""
tests/unit/test_store_7.py
--------------------------
STORE-7: visits per tag. A tagged catalog link that is opened is counted (no cart needed) and Insights shows it by source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import catalog_share_service as share
from app.services import webchat_analytics_service as an
from tests.unit.test_account_plans_1 import BIZ, FakeDB, _Q


class _MS(_Q):
    def maybe_single(self): return self


class DB(FakeDB):
    def table(self, name): return _MS(self, name)


def _db():
    return DB(organisations=[{"id": BIZ, "slug": "royal-rest", "name": "Royal Rest", "webchat_config": {}}], webchat_events=[])


def test_a_tagged_open_is_counted_with_the_clean_tag_and_no_session():
    db = _db()
    assert share.record_visit(db, "royal-rest", "Instagram!") is True
    ev = db.tables["webchat_events"]
    assert len(ev) == 1 and ev[0]["kind"] == "catalog_visit" and ev[0]["source"] == "instagram"
    assert ev[0]["org_id"] == BIZ and ev[0]["session_id"] is None


@pytest.mark.parametrize("src", [None, "", "   ", "!!!"])
def test_untagged_or_unusable_tag_is_not_counted(src):
    db = _db()
    assert share.record_visit(db, "royal-rest", src) is False and db.tables["webchat_events"] == []


def test_unknown_store_is_not_counted_and_never_raises():
    db = _db()
    assert share.record_visit(db, "nope", "ig") is False and db.tables["webchat_events"] == []

    class Boom:
        def table(self, *_): raise RuntimeError("down")
    assert share.record_visit(Boom(), "royal-rest", "ig") is False


def test_a_refused_insert_before_the_migration_does_not_raise():
    db = _db()
    with patch("app.services.webchat_service.log_event", side_effect=RuntimeError("check constraint")):
        assert share.record_visit(db, "royal-rest", "ig") is False


def _ev(kind, src):
    return {"org_id": BIZ, "kind": kind, "source": src, "created_at": datetime.now(timezone.utc).isoformat(), "session_id": None}


def test_insights_counts_catalog_visits_by_source_and_keeps_chat_visits_apart():
    db = DB(organisations=[{"id": BIZ, "name": "S", "webchat_config": {}}],
            webchat_events=[_ev("catalog_visit", "instagram")] * 5 + [_ev("catalog_visit", "flyer")] * 2
            + [_ev("visit", "link")] * 3 + [_ev("started", "link")])
    f = an.analytics(db, BIZ, 30)["funnel"]
    assert f["totals"]["catalog_visit"] == 7 and f["totals"]["visit"] == 3
    by = {s["source"]: s for s in f["sources"]}
    assert by["instagram"]["catalog_visit"] == 5 and by["instagram"]["visit"] == 0
    assert [s["source"] for s in f["sources"]][:2] == ["instagram", "link"]      # most opens first
    assert [s["key"] for s in f["steps"]][:2] == ["visit", "started"]            # the chat funnel is unchanged
    assert next(s for s in f["steps"] if s["key"] == "visit")["count"] == 3


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    db = _db()
    with patch("app.routers.public_catalog.get_supabase", return_value=db):
        yield TestClient(app), db


def test_route_is_public_and_counts(client):
    c, db = client
    r = c.post("/api/v1/public/catalog/royal-rest/visit", json={"src": "facebook"})
    assert r.status_code == 200 and r.json() == {"counted": True}
    assert db.tables["webchat_events"][0]["source"] == "facebook"


def test_route_without_a_tag_or_with_a_bad_body(client):
    c, db = client
    assert c.post("/api/v1/public/catalog/royal-rest/visit", json={}).json() == {"counted": False}
    assert c.post("/api/v1/public/catalog/royal-rest/visit", json={"src": "x" * 61}).status_code == 422
    assert db.tables["webchat_events"] == []
