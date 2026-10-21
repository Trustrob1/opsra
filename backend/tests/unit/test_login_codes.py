"""
tests/unit/test_login_codes.py
LOGIN-1 - sign in with an emailed 6-digit code: only a hash is stored, one code at a time, five wrong tries lock it,
it works once, it expires, and every failure says the same thing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import builder_login_service as svc
from tests.funnel_fake_db import FakeDB

BUILDER = {"id": "b1", "org_id": "org-1", "email": "ada@example.com", "full_name": "Ada Okafor", "status": "active",
           "phone_number": "+2348000000001"}


def _db(extra_builders=()):
    return FakeDB(site_builders=[dict(BUILDER), *extra_builders], site_login_codes=[], site_editor_tokens=[])


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(svc, "_send_code_email", lambda to, code, url, first: out.append({"to": to, "code": code, "url": url, "first": first}))
    return out


def _send(monkeypatch, db, email="ada@example.com"):
    monkeypatch.setattr("app.database.get_supabase", lambda: db)
    svc.send_login_code(email)


def test_clean_email():
    assert svc.clean_email("  Ada@Example.COM ") == "ada@example.com"
    assert svc.clean_email("not an email") == "" and svc.clean_email("") == ""


def test_code_is_emailed_and_only_a_hash_is_stored(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db)
    assert len(sent) == 1 and sent[0]["to"] == "ada@example.com" and len(sent[0]["code"]) == 6 and sent[0]["code"].isdigit()
    row = db.rows("site_login_codes")[0]
    assert sent[0]["code"] not in row["code_hash"] and len(row["code_hash"]) == 64 and row["status"] == "pending"
    assert "t=" in sent[0]["url"] and len(db.rows("site_editor_tokens")) == 1      # the one-click link is also made


def test_unknown_email_sends_nothing(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db, "nobody@example.com")
    assert sent == [] and db.rows("site_login_codes") == []


def test_inactive_builder_gets_nothing(monkeypatch, sent):
    db = FakeDB(site_builders=[{**BUILDER, "status": "suspended"}], site_login_codes=[], site_editor_tokens=[])
    _send(monkeypatch, db)
    assert sent == []


def test_mixed_case_email_on_file_still_matches(monkeypatch, sent):
    db = FakeDB(site_builders=[{**BUILDER, "email": "ADA@EXAMPLE.COM"}], site_login_codes=[], site_editor_tokens=[])
    _send(monkeypatch, db, "Ada@Example.com")
    assert len(sent) == 1


def test_correct_code_signs_in_once(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db)
    code = sent[0]["code"]
    assert svc.verify_login_code(db, "ada@example.com", code)["id"] == "b1"
    with pytest.raises(svc.LoginCodeError):
        svc.verify_login_code(db, "ada@example.com", code)           # used


def test_wrong_code_fails_and_five_wrong_tries_lock_it(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db)
    good = sent[0]["code"]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(svc.MAX_CODE_ATTEMPTS):
        with pytest.raises(svc.LoginCodeError):
            svc.verify_login_code(db, "ada@example.com", bad)
    assert db.rows("site_login_codes")[0]["status"] == "locked"
    with pytest.raises(svc.LoginCodeError):
        svc.verify_login_code(db, "ada@example.com", good)           # even the right code is dead now


def test_expired_code_fails(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db)
    later = datetime.now(timezone.utc) + timedelta(minutes=svc.CODE_MINUTES + 1)
    with pytest.raises(svc.LoginCodeError):
        svc.verify_login_code(db, "ada@example.com", sent[0]["code"], now=later)


def test_a_new_code_replaces_the_old_one(monkeypatch, sent):
    db = _db()
    _send(monkeypatch, db)
    _send(monkeypatch, db)
    first, second = sent[0]["code"], sent[1]["code"]
    if first != second:
        with pytest.raises(svc.LoginCodeError):
            svc.verify_login_code(db, "ada@example.com", first)
    assert svc.verify_login_code(db, "ada@example.com", second)["id"] == "b1"


@pytest.mark.parametrize("email,code", [("", "123456"), ("ada@example.com", ""), ("ada@example.com", "12345"), ("nobody@example.com", "123456")])
def test_bad_input_and_unknown_email_give_the_same_error(email, code):
    db = _db()
    with pytest.raises(svc.LoginCodeError) as e:
        svc.verify_login_code(db, email, code)
    assert "isn't right or has expired" in str(e.value)


def test_delivery_failure_never_raises(monkeypatch):
    db = _db()
    monkeypatch.setattr(svc, "_send_code_email", lambda *a: (_ for _ in ()).throw(RuntimeError("mail down")))
    _send(monkeypatch, db)
