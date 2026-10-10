"""
tests/unit/test_site_partner_service.py
PARTNER-1A — services/site_partner_service.py (create partner, permanent link, status, abuse cap).
Uses the shared in-memory FakeDB (T2: no MagicMock chains).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_partner_service as svc
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-0000000000aa"


def _db(**tables):
    return FakeDB(**tables)


class TestCreatePartner:
    def test_creates_linked_builder_and_partner(self):
        db = _db()
        p = svc.create_partner(db, ORG, "Ada Agent", "0803 123 4567", "ADA@Example.com", "Ada Registrations")
        assert p["partner_code"].startswith("OP") and len(p["partner_code"]) == 7
        assert p["link_url"].endswith("/p/" + p["link_slug"])
        builders = db.rows("site_builders")
        assert len(builders) == 1
        b = builders[0]
        assert b["phone_number"] == "2348031234567"
        assert b["source"] == "manual" and b["account_type"] == "builder" and b["status"] == "active"
        assert b["max_active_sites"] == svc.PARTNER_MAX_ACTIVE_SITES
        assert p["builder_id"] == b["id"]
        assert p["email"] == "ada@example.com"

    def test_links_an_existing_builder(self):
        db = _db(site_builders=[{"id": "b1", "org_id": ORG, "phone_number": "2348031234567", "full_name": "Ada",
                                 "status": "active", "business_name": None}])
        p = svc.create_partner(db, ORG, "Ada Agent", "+2348031234567", None, "Ada Registrations")
        assert p["builder_id"] == "b1"
        assert len(db.rows("site_builders")) == 1
        assert db.rows("site_builders")[0]["max_active_sites"] == svc.PARTNER_MAX_ACTIVE_SITES
        assert db.rows("site_builders")[0]["business_name"] == "Ada Registrations"

    def test_duplicate_partner_rejected(self):
        db = _db()
        svc.create_partner(db, ORG, "Ada Agent", "08031234567")
        with pytest.raises(svc.PartnerError):
            svc.create_partner(db, ORG, "Ada Again", "08031234567")

    def test_bad_inputs_rejected(self):
        with pytest.raises(svc.PartnerError):
            svc.create_partner(_db(), ORG, "A", "08031234567")
        with pytest.raises(svc.PartnerError):
            svc.create_partner(_db(), ORG, "Ada Agent", "abc")

    def test_codes_and_slugs_are_unique_per_partner(self):
        db = _db()
        a = svc.create_partner(db, ORG, "Ada Agent", "08031234567")
        b = svc.create_partner(db, ORG, "Bola Agent", "08031234568")
        assert a["link_slug"] != b["link_slug"] and a["partner_code"] != b["partner_code"]


class TestOpenLink:
    def _setup(self):
        db = _db()
        p = svc.create_partner(db, ORG, "Ada Agent", "08031234567", None, "Ada Registrations")
        return db, p

    def test_ok_mints_fresh_client_form_each_visit(self):
        db, p = self._setup()
        r1 = svc.open_link(db, p["link_slug"])
        r2 = svc.open_link(db, p["link_slug"])
        assert r1["kind"] == "ok" and r2["kind"] == "ok"
        assert r1["url"] != r2["url"] and "/f/" in r1["url"]
        forms = db.rows("site_brief_forms")
        assert len(forms) == 2
        assert all(f["builder_id"] == p["builder_id"] and f["audience"] == "client" and f["status"] == "open" for f in forms)
        assert all(f["client_label"] == svc.PARTNER_FORM_LABEL for f in forms)

    def test_unknown_or_malformed_slug_not_found(self):
        db, _ = self._setup()
        assert svc.open_link(db, "nope-nope")["kind"] == "not_found"
        assert svc.open_link(db, "../etc")["kind"] == "not_found"
        assert svc.open_link(db, "")["kind"] == "not_found"
        assert db.rows("site_brief_forms") == []

    def test_suspended_partner_inactive(self):
        db, p = self._setup()
        svc.set_status(db, ORG, p["id"], "suspended")
        assert svc.open_link(db, p["link_slug"])["kind"] == "inactive"
        assert db.rows("site_brief_forms") == []
        svc.set_status(db, ORG, p["id"], "active")
        assert svc.open_link(db, p["link_slug"])["kind"] == "ok"

    def test_inactive_when_builder_not_active(self):
        db, p = self._setup()
        db.rows("site_builders")[0]["status"] = "suspended"
        assert svc.open_link(db, p["link_slug"])["kind"] == "inactive"

    def test_busy_when_too_many_unsubmitted_forms(self, monkeypatch):
        monkeypatch.setattr(svc, "MAX_UNSUBMITTED_FORMS_PER_DAY", 3)
        db, p = self._setup()
        for _ in range(3):
            assert svc.open_link(db, p["link_slug"])["kind"] == "ok"
        assert svc.open_link(db, p["link_slug"])["kind"] == "ok"      # the 4th still fits (cap counts > limit)
        assert svc.open_link(db, p["link_slug"])["kind"] == "busy"

    def test_old_forms_do_not_count_toward_cap(self, monkeypatch):
        monkeypatch.setattr(svc, "MAX_UNSUBMITTED_FORMS_PER_DAY", 1)
        db, p = self._setup()
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        for i in range(5):
            db.rows("site_brief_forms").append({"id": f"f{i}", "org_id": ORG, "builder_id": p["builder_id"],
                                                 "status": "open", "created_at": old})
        assert svc.open_link(db, p["link_slug"])["kind"] == "ok"


class TestStatus:
    def test_invalid_status_rejected(self):
        with pytest.raises(svc.PartnerError):
            svc.set_status(_db(), ORG, "x", "deleted")

    def test_other_org_cannot_change(self):
        db = _db()
        p = svc.create_partner(db, ORG, "Ada Agent", "08031234567")
        assert svc.set_status(db, "other-org", p["id"], "suspended") is None
        assert db.rows("site_partners")[0]["status"] == "active"

    def test_list_is_org_scoped_and_has_links(self):
        db = _db()
        svc.create_partner(db, ORG, "Ada Agent", "08031234567")
        db.rows("site_partners").append({"id": "x", "org_id": "other", "link_slug": "zzz", "created_at": "2026-01-01"})
        rows = svc.list_partners(db, ORG)
        assert len(rows) == 1 and rows[0]["link_url"].endswith("/p/" + rows[0]["link_slug"])
