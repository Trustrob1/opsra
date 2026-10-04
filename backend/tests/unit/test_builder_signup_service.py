"""
tests/unit/test_builder_signup_service.py
-----------------------------------------
SITE-WEB-1 - web sign-up: the open/closed switch, validation, durable rate limits, the emailed code (stored only as
a hash), existing numbers staying private, and the account created on a correct code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import builder_signup_service as su
from app.services import site_access_service
from tests.funnel_fake_db import FakeDB

ORG = "org-1"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
IP = "102.89.1.1"

GOOD = {"full_name": "Ada Obi", "email": "Ada@Example.com", "phone": "0803 000 0001", "account_type": "builder",
        "accept_terms": True}


def _db(open_signup=True, builders=None, requests=None, pricing=None):
    return FakeDB(
        whatsapp_numbers=[{"id": "n1", "org_id": ORG, "wa_sales_mode": "site_builder"}],
        site_builder_settings=[{"org_id": ORG, "enabled": True, "members_only": not open_signup, "pricing": pricing or {}}],
        site_builders=builders or [], site_signup_requests=requests or [], site_events=[],
    )


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(su, "_send_code_email", lambda email, first, code: sent.append((email, first, code)) or True)

    def fake_lead(db, org, b):
        b["lead_id"] = "lead-1"
        db.table("site_builders").update({"lead_id": "lead-1"}).eq("id", b["id"]).execute()
        return "lead-1"
    monkeypatch.setattr(site_access_service, "ensure_lead", fake_lead)
    return sent


def _start(db, payload=None, ip=IP, now=NOW, link=None):
    return su.start(db, {**GOOD, **(payload or {})}, ip, send_login_link=link, now=now)


# -- open or closed ------------------------------------------------------------

def test_closed_when_the_owner_has_not_opened_sign_up(mail):
    with pytest.raises(su.SignupClosed):
        _start(_db(open_signup=False))
    assert mail == []


def test_closed_when_no_org_runs_the_site_builder(mail):
    db = FakeDB(whatsapp_numbers=[], site_builder_settings=[], site_builders=[], site_signup_requests=[])
    with pytest.raises(su.SignupClosed):
        _start(db)


def test_org_is_found_from_the_only_enabled_settings_row_when_no_number(mail):
    db = FakeDB(whatsapp_numbers=[], site_builder_settings=[{"org_id": ORG, "enabled": True, "members_only": False, "pricing": {}}],
                site_builders=[], site_signup_requests=[], site_events=[])
    assert _start(db)["request_id"]


# -- validation ---------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"full_name": "A"}, {"email": "nope"}, {"email": "a@b"}, {"phone": "123"}, {"phone": ""},
    {"account_type": "admin"}, {"accept_terms": False}, {"accept_terms": "yes"},
])
def test_bad_details_are_refused(mail, bad):
    db = _db()
    with pytest.raises(su.SignupError):
        _start(db, bad)
    assert mail == [] and db.rows("site_signup_requests") == []


def test_honeypot_creates_nothing(mail):
    db = _db()
    out = _start(db, {"website": "http://spam"})
    assert out["email_hint"] == "***" and mail == [] and db.rows("site_signup_requests") == []


# -- the code ------------------------------------------------------------------------

def test_start_emails_a_code_and_stores_only_its_hash(mail):
    db = _db()
    out = _start(db)
    (email, first, code), = mail
    assert email == "ada@example.com" and first == "Ada" and len(code) == 6 and code.isdigit()
    row = db.rows("site_signup_requests")[0]
    assert row["id"] == out["request_id"] and row["status"] == "pending" and row["phone_number"] == "2348030000001"
    assert code not in str(row) and row["code_hash"] == su._code_hash(row["id"], code)
    assert out["email_hint"] == "a***@example.com"
    assert row["ip_hash"] == su.hash_ip(IP) and IP not in str(row)


def test_if_the_email_cannot_be_sent_nothing_is_kept(monkeypatch):
    monkeypatch.setattr(su, "_send_code_email", lambda *a: False)
    db = _db()
    with pytest.raises(su.SignupUnavailable):
        _start(db)
    assert db.rows("site_signup_requests") == []


# -- rate limits ------------------------------------------------------------------------

def test_per_ip_limit(mail):
    db = _db()
    for i in range(su.PER_IP_HOUR):
        _start(db, {"email": f"u{i}@example.com", "phone": f"080300001{i:02d}"})
    with pytest.raises(su.SignupRateLimited):
        _start(db, {"email": "late@example.com", "phone": "08030009999"})


def test_per_email_limit(mail):
    db = _db()
    for i in range(su.PER_EMAIL_HOUR):
        _start(db, {"phone": f"080300002{i:02d}"}, ip=f"1.1.1.{i}")
    with pytest.raises(su.SignupRateLimited):
        _start(db, {"phone": "08030002999"}, ip="9.9.9.9")


def test_per_phone_limit(mail):
    db = _db()
    for i in range(su.PER_PHONE_HOUR):
        _start(db, {"email": f"p{i}@example.com"}, ip=f"2.2.2.{i}")
    with pytest.raises(su.SignupRateLimited):
        _start(db, {"email": "p9@example.com"}, ip="9.9.9.9")


def test_old_attempts_stop_counting_after_an_hour(mail):
    db = _db()
    for i in range(su.PER_IP_HOUR):
        _start(db, {"email": f"u{i}@example.com", "phone": f"080300003{i:02d}"})
    later = NOW + timedelta(hours=1, minutes=1)
    assert _start(db, {"email": "fresh@example.com", "phone": "08030003999"}, now=later)["request_id"]


def test_daily_cap_on_verified_signups(mail):
    verified = [{"id": f"v{i}", "org_id": ORG, "status": "verified", "verified_at": (NOW - timedelta(hours=2)).isoformat(),
                 "created_at": (NOW - timedelta(hours=2)).isoformat(), "email": f"v{i}@x.com", "phone_number": f"2348{i}", "ip_hash": f"h{i}"}
                for i in range(3)]
    db = _db(requests=verified, pricing={"builder_access": {"signup_daily_cap": 3}})
    with pytest.raises(su.SignupClosed):
        _start(db)


# -- an existing number stays private ------------------------------------------------------

def _existing(status="active", phone="2348030000001"):
    return {"id": "b-1", "org_id": ORG, "phone_number": phone, "full_name": "Old", "status": status}


def test_existing_number_gets_a_sign_in_link_not_a_code(mail):
    calls = []
    db = _db(builders=[_existing()])
    out = _start(db, link=calls.append)
    assert mail == [] and calls == ["2348030000001"]
    assert set(out) == {"request_id", "email_hint"}                       # same reply shape as a new sign-up
    assert db.rows("site_signup_requests")[0]["status"] == "blocked"      # logged for the rate limit


def test_existing_number_in_plus_form_is_also_found(mail):
    calls = []
    _start(_db(builders=[_existing(phone="+2348030000001")]), link=calls.append)
    assert calls == ["2348030000001"]


def test_suspended_account_gets_nothing(mail):
    calls = []
    _start(_db(builders=[_existing("suspended")]), link=calls.append)
    assert mail == [] and calls == []


def test_a_blocked_placeholder_row_cannot_be_verified(mail):
    db = _db(builders=[_existing()])
    out = _start(db)
    with pytest.raises(su.SignupError):
        su.verify(db, out["request_id"], "000000", NOW)


# -- verify ----------------------------------------------------------------------------------

def _go(db, mail):
    out = _start(db)
    return out["request_id"], mail[-1][2]


def test_correct_code_creates_the_account(mail):
    db = _db()
    rid, code = _go(db, mail)
    b = su.verify(db, rid, code, NOW + timedelta(minutes=2))
    row = db.rows("site_builders")[0]
    assert row["status"] == "active" and row["source"] == "web_signup" and row["account_type"] == "builder"
    assert row["phone_number"] == "2348030000001" and row["email"] == "ada@example.com" and row["full_name"] == "Ada Obi"
    assert row["lead_id"] == "lead-1" and b["id"] == row["id"]
    assert db.rows("site_signup_requests")[0]["status"] == "verified"
    assert db.rows("site_events")[0]["event"] == "builder_signed_up"


def test_owner_account_type_is_kept(mail):
    db = _db()
    out = _start(db, {"account_type": "owner"})
    su.verify(db, out["request_id"], mail[-1][2], NOW)
    assert db.rows("site_builders")[0]["account_type"] == "owner"


def test_code_with_spaces_is_accepted(mail):
    db = _db()
    rid, code = _go(db, mail)
    assert su.verify(db, rid, f" {code[:3]} {code[3:]} ", NOW)


def test_wrong_code_counts_and_five_block_the_request(mail):
    db = _db()
    rid, code = _go(db, mail)
    wrong = "000000" if code != "000000" else "111111"
    for i in range(su.MAX_ATTEMPTS - 1):
        with pytest.raises(su.SignupError, match="isn't right"):
            su.verify(db, rid, wrong, NOW)
    with pytest.raises(su.SignupError, match="Too many"):
        su.verify(db, rid, wrong, NOW)
    assert db.rows("site_signup_requests")[0]["status"] == "blocked"
    with pytest.raises(su.SignupError):
        su.verify(db, rid, code, NOW)                                      # even the right code is dead now
    assert db.rows("site_builders") == []


def test_expired_code(mail):
    db = _db()
    rid, code = _go(db, mail)
    with pytest.raises(su.SignupError, match="expired"):
        su.verify(db, rid, code, NOW + timedelta(minutes=su.CODE_MINUTES + 1))
    assert db.rows("site_builders") == []


def test_a_code_works_once(mail):
    db = _db()
    rid, code = _go(db, mail)
    su.verify(db, rid, code, NOW)
    with pytest.raises(su.SignupError):
        su.verify(db, rid, code, NOW)
    assert len(db.rows("site_builders")) == 1


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", None])
def test_malformed_codes(mail, code):
    db = _db()
    rid, _ = _go(db, mail)
    with pytest.raises(su.SignupError):
        su.verify(db, rid, code, NOW)


def test_unknown_request_id(mail):
    with pytest.raises(su.SignupError):
        su.verify(_db(), "does-not-exist", "123456", NOW)


def test_number_registered_between_start_and_verify(mail):
    db = _db()
    rid, code = _go(db, mail)
    db.tables["site_builders"].append(_existing())
    with pytest.raises(su.SignupError, match="already has an account"):
        su.verify(db, rid, code, NOW)
    assert len(db.rows("site_builders")) == 1


def test_a_bot_placeholder_is_claimed(mail):
    pending = {"id": "b-9", "org_id": ORG, "phone_number": "2348030000001", "full_name": "Pending builder", "status": "pending", "source": "whatsapp"}
    db = _db(builders=[pending])
    rid, code = _go(db, mail)                                              # not treated as an existing account
    assert mail
    b = su.verify(db, rid, code, NOW)
    rows = db.rows("site_builders")
    assert len(rows) == 1 and rows[0]["id"] == "b-9" and rows[0]["status"] == "active"
    assert rows[0]["full_name"] == "Ada Obi" and rows[0]["source"] == "web_signup" and b["id"] == "b-9"


def test_a_lead_failure_never_loses_the_account(mail, monkeypatch):
    def boom(db, org, b):
        raise RuntimeError("leads down")
    monkeypatch.setattr(site_access_service, "ensure_lead", boom)
    db = _db()
    rid, code = _go(db, mail)
    su.verify(db, rid, code, NOW)
    assert db.rows("site_builders")[0]["status"] == "active"


def test_helpers():
    assert su.mask_email("ada@example.com") == "a***@example.com"
    assert su.is_open({"enabled": True, "members_only": False}) is True
    assert su.is_open({"enabled": True, "members_only": True}) is False
    assert su.is_open({"enabled": True}) is False
    assert su.is_open({"enabled": False, "members_only": False}) is False
    assert su._daily_cap({}) == su.DEFAULT_DAILY_CAP
