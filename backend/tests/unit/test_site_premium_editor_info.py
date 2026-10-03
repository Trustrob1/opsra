"""SITE-PREMIUM P4-1: which content groups a Premium design shows, and the editor info built from it."""
from unittest.mock import MagicMock

from app.services import site_premium_service as svc


def _chain(data):
    result = MagicMock()
    result.data = data
    m = MagicMock()
    for method in ("select", "eq", "limit"):
        getattr(m, method).return_value = m
    m.execute.return_value = result
    return m


def _db(rows):
    db = MagicMock()
    db.table.side_effect = lambda name: _chain(rows)
    return db


MANIFEST = {"version": 1, "slots": [
    {"path": "business.name", "kind": "text"},
    {"path": "hero.headline", "kind": "text"},
    {"path": "hero.image", "kind": "image"},
    {"path": "items", "kind": "repeat"},
    {"path": "name", "kind": "text"},            # relative to an items entry
    {"path": "!about.owner", "kind": "if"},
    {"path": "whatsapp", "kind": "link"},
    {"path": "whatsapp:order", "kind": "link"},
    {"path": "maps", "kind": "link"},
    {"path": "faqs", "kind": "repeat"},
    {"path": "custom.founded", "kind": "text"},
], "custom": ["custom.founded"], "whatsapp_links": 2}


class TestUsedTopLevel:
    def test_collects_groups_from_every_slot_kind(self):
        assert svc.used_top_level(MANIFEST) == ["about", "business", "faqs", "hero", "items", "location"]

    def test_relative_and_custom_paths_add_nothing(self):
        assert svc.used_top_level({"slots": [{"path": "name", "kind": "text"}, {"path": "custom.x", "kind": "text"}]}) == []

    def test_empty_or_missing_manifest(self):
        assert svc.used_top_level(None) == []
        assert svc.used_top_level({}) == []


class TestEditorInfo:
    def test_standard_site_is_none(self):
        assert svc.editor_info(_db([]), "org", {"id": "s", "tier": "standard"}) is None
        assert svc.editor_info(_db([]), "org", {"id": "s"}) is None

    def test_premium_without_current_design_is_none(self):
        assert svc.editor_info(_db([]), "org", {"id": "s", "tier": "premium", "current_design_id": None}) is None

    def test_missing_or_unfinished_design_is_none(self):
        assert svc.editor_info(_db([]), "org", {"id": "s", "tier": "premium", "current_design_id": "d1"}) is None

    def test_premium_returns_version_and_used_groups(self):
        row = {"id": "d1", "version": 7, "slot_manifest": MANIFEST}
        info = svc.editor_info(_db([row]), "org", {"id": "s", "tier": "premium", "current_design_id": "d1"})
        assert info == {"active": True, "design_id": "d1", "version": 7,
                        "used": ["about", "business", "faqs", "hero", "items", "location"]}

    def test_database_error_never_raises(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("boom")
        assert svc.editor_info(db, "org", {"id": "s", "tier": "premium", "current_design_id": "d1"}) is None
