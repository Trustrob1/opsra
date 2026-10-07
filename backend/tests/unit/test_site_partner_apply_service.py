"""
tests/unit/test_site_partner_apply_service.py
PARTNER-1B — apply (emailed code), staff approve/decline, partner sign-in lookup, referrals.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_partner_apply_service as svc
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
GOOD = {"full_name": "Ada Obi", "email": "Ada@Example.com", "phone": "0803 000 0001", "agency_name": "Ada Regs",
        "accept_terms": True}


def _db(**extra):
    return FakeDB(
        whatsapp_numbers=[{"id": "n1", "org_id": ORG, "wa_sales_mode": "site_builder"}],
        site_builders=[], site_partners=[], site_partner_applications=[], sites=[], site_editor_tokens=[], **extra)


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "_send_email", lambda to, subj, text: sent.append((to, subj, text)) or True)
    return sent


def _code(mail):
    return mail[-1][1].rsplit(": ", 1)[1]


def _apply(db, mail, payload=None, ip="1.1.1.1"):
    r = svc.start(db, {**GOOD, **(payload or {})}, ip, now=NOW)
    svc.verify(db, r["request_id"], _code(mail), now=NOW)
    return r["request_id"]


class TestApply:
    def test_start_emails_a_code_and_stores_only_a_hash(self, mail):
        db = _db()
        r = svc.start(db, GOOD, "1.1.1.1", now=NOW)
        assert mail[0][0] == "ada@example.com"
        row = db.rows("site_partner_applications")[0]
        assert row["status"] == "pending_code" and _code(mail) not in row["code_hash"]
        assert r["email_hint"].startswith("a***@")

    def test_correct_code_marks_applied(self, mail):
        db = _db()
        rid = _apply(db, mail)
        assert db.rows("site_partner_applications")[0]["status"] == "applied"
        assert rid

    def test_wrong_code_counts_attempts_then_blocks(self, mail):
        db = _db()
        r = svc.start(db, GOOD, "1.1.1.1", now=NOW)
        for _ in range(4):
            with pytest.raises(svc.ApplyError):
                svc.verify(db, r["request_id"], "000000", now=NOW)
        with pytest.raises(svc.ApplyError):
            svc.verify(db, r["request_id"], "000000", now=NOW)
        assert db.rows("site_partner_applications")[0]["status"] == "blocked"

    def test_expired_code(self, mail):
        db = _db()
        r = svc.start(db, GOOD, "1.1.1.1", now=NOW)
        with pytest.raises(svc.ApplyError):
            svc.verify(db, r["request_id"], _code(mail), now=NOW + timedelta(minutes=30))

    @pytest.mark.parametrize("bad", [{"full_name": "A"}, {"email": "nope"}, {"phone": "12"}, {"accept_terms": False}])
    def test_validation(self, mail, bad):
        with pytest.raises(svc.ApplyError):
            svc.start(_db(), {**GOOD, **bad}, "1.1.1.1", now=NOW)
        assert mail == []

    def test_honeypot_creates_nothing(self, mail):
        db = _db()
        svc.start(db, {**GOOD, "website": "x"}, "1.1.1.1", now=NOW)
        assert db.rows("site_partner_applications") == [] and mail == []

    def test_rate_limit_per_ip(self, mail):
        db = _db()
        for i in range(5):
            svc.start(db, {**GOOD, "email": f"a{i}@x.com", "phone": f"0803000010{i}"}, "9.9.9.9", now=NOW)
        with pytest.raises(svc.ApplyRateLimited):
            svc.start(db, {**GOOD, "email": "z@x.com", "phone": "08030000199"}, "9.9.9.9", now=NOW)

    def test_existing_partner_gets_no_code_but_a_sign_in_link(self, mail):
        db = _db()
        svc.site_partner_service.create_partner(db, ORG, "Ada Obi", "08030000001", "ada@example.com")
        links = []
        svc.start(db, GOOD, "1.1.1.1", send_login_link=links.append, now=NOW)
        assert mail == [] and links == ["ada@example.com"]
        assert db.rows("site_partner_applications")[0]["status"] == "blocked"


class TestDecision:
    def test_approve_creates_partner_and_marks_application(self, mail):
        db = _db()
        rid = _apply(db, mail)
        links = []
        partner = svc.approve(db, ORG, rid, send_login_link=links.append)
        assert partner["email"] == "ada@example.com" and partner["status"] == "active"
        app = db.rows("site_partner_applications")[0]
        assert app["status"] == "approved" and app["partner_id"] == partner["id"]
        assert links == ["ada@example.com"]
        assert any("approved" in m[1] for m in mail)

    def test_cannot_approve_twice_or_unverified(self, mail):
        db = _db()
        rid = _apply(db, mail)
        svc.approve(db, ORG, rid)
        with pytest.raises(svc.ApplyError):
            svc.approve(db, ORG, rid)

    def test_other_org_cannot_approve(self, mail):
        db = _db()
        rid = _apply(db, mail)
        with pytest.raises(svc.ApplyError):
            svc.approve(db, "other-org", rid)

    def test_decline(self, mail):
        db = _db()
        rid = _apply(db, mail)
        svc.decline(db, ORG, rid)
        assert db.rows("site_partner_applications")[0]["status"] == "declined"
        with pytest.raises(svc.ApplyError):
            svc.decline(db, ORG, rid)

    def test_list_hides_hashes(self, mail):
        db = _db()
        _apply(db, mail)
        rows = svc.list_applications(db, ORG)
        assert len(rows) == 1 and "code_hash" not in rows[0] and "ip_hash" not in rows[0]


class TestSignInAndReferrals:
    def test_find_by_email_or_phone_active_only(self, mail):
        db = _db()
        p = svc.site_partner_service.create_partner(db, ORG, "Ada Obi", "08030000001", "ada@example.com")
        assert svc.find_active_partner(db, "ADA@example.com")["id"] == p["id"]
        assert svc.find_active_partner(db, "0803 000 0001")["id"] == p["id"]
        assert svc.find_active_partner(db, "nobody@example.com") is None
        svc.site_partner_service.set_status(db, ORG, p["id"], "suspended")
        assert svc.find_active_partner(db, "ada@example.com") is None

    def test_referrals_only_this_partners_clients(self):
        db = _db()
        p = svc.site_partner_service.create_partner(db, ORG, "Ada Obi", "08030000001", "ada@example.com")
        db.table("sites").insert({"id": "s1", "org_id": ORG, "builder_id": p["builder_id"], "client_business_name": "Zed Shop",
                                  "slug": "zed", "status": "preview_ready", "deleted_at": None, "created_at": NOW.isoformat(),
                                  "content": {"business": {"whatsapp_e164": "+2348090000000"}}, "live_url": None}).execute()
        db.table("sites").insert({"id": "s2", "org_id": ORG, "builder_id": "someone-else", "client_business_name": "Other",
                                  "slug": "o", "status": "live", "deleted_at": None, "created_at": NOW.isoformat()}).execute()
        out = svc.referrals(db, p)
        assert len(out) == 1
        assert out[0]["business_name"] == "Zed Shop" and out[0]["phone"] == "+2348090000000"
        assert out[0]["status_label"] == "Preview ready" and out[0]["preview_path"] == "/s/zed"
