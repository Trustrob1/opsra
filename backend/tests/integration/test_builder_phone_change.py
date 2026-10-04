"""
tests/integration/test_builder_phone_change.py
SITE-WEB-2 - a signed-in builder changes their WhatsApp number (code emailed to the address on the account),
the portal's WhatsApp state flags on GET /me, and the bot matching both spellings of a number.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.routers import builder_portal
from app.services import builder_phone_service as ph, builder_signup_service as su, site_chat_service
from tests.funnel_fake_db import FakeDB

ORG = "00000000-0000-0000-0000-000000003333"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def _builder(i="b-1", phone="2348030000001", email="ada@example.com"):
    return {"id": i, "org_id": ORG, "phone_number": phone, "full_name": "Ada Obi", "email": email,
            "status": "active", "account_type": "builder"}


def _db(builders=None, chats=None):
    return FakeDB(site_builders=builders if builders is not None else [_builder()], site_phone_changes=[],
                  site_editor_tokens=[], site_chats=chats or [], sites=[], site_events=[])


@pytest.fixture
def api(monkeypatch):
    sent = []
    monkeypatch.setattr(ph, "_send_code_email", lambda email, first, code, phone: sent.append((email, code, phone)) or True)
    holder = {"sent": sent}

    def use(db, builder_id="b-1"):
        holder["db"] = db
        app.dependency_overrides[get_supabase] = lambda: db
        c = TestClient(app, raise_server_exceptions=False)
        b = next(r for r in db.rows("site_builders") if r["id"] == builder_id)
        builder_portal._exchange_hits.clear()
        raw = su.mint_login_token(db, b)
        tok = c.post("/api/v1/builder/auth/exchange", json={"token": raw}).json()["data"]["access_token"]
        holder["h"] = {"Authorization": f"Bearer {tok}"}
        return c
    holder["use"] = use
    yield holder
    app.dependency_overrides.pop(get_supabase, None)


def _start(c, api, phone="08030000009"):
    return c.post("/api/v1/builder/me/phone/start", json={"phone": phone}, headers=api["h"])


def test_change_number_end_to_end(api):
    c = api["use"](_db())
    r = _start(c, api)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["email_hint"] == "a***@example.com"
    email, code, phone = api["sent"][0]
    assert email == "ada@example.com" and phone == "2348030000009"       # the code goes to the account email
    assert api["db"].rows("site_builders")[0]["phone_number"] == "2348030000001"   # nothing changes yet
    v = c.post("/api/v1/builder/me/phone/verify", json={"request_id": r.json()["data"]["request_id"], "code": code}, headers=api["h"])
    assert v.status_code == 200, v.text
    assert api["db"].rows("site_builders")[0]["phone_number"] == "2348030000009"
    me = c.get("/api/v1/builder/me", headers=api["h"]).json()["data"]
    assert me["phone_number"] == "2348030000009"
    # the code can't be used twice
    again = c.post("/api/v1/builder/me/phone/verify", json={"request_id": r.json()["data"]["request_id"], "code": code}, headers=api["h"])
    assert again.status_code == 422


def test_needs_a_session(api):
    api["use"](_db())
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/api/v1/builder/me/phone/start", json={"phone": "08030000009"}).status_code == 401
    assert c.post("/api/v1/builder/me/phone/verify", json={"request_id": "x", "code": "123456"}).status_code == 401


def test_no_email_on_the_account_is_a_422(api):
    c = api["use"](_db([_builder(email=None)]))
    r = _start(c, api)
    assert r.status_code == 422 and "email" in r.json()["detail"]["message"].lower()
    assert api["sent"] == []


def test_same_number_and_bad_number_are_422(api):
    c = api["use"](_db())
    assert _start(c, api, "+234 803 000 0001").status_code == 422
    assert _start(c, api, "abc").status_code == 422
    assert api["sent"] == []


def test_a_number_used_by_someone_else_is_refused_in_either_spelling(api):
    other = _builder("b-2", phone="+2348030000009", email="x@example.com")
    c = api["use"](_db([_builder(), other]))
    r = _start(c, api, "08030000009")
    assert r.status_code == 422 and "already used" in r.json()["detail"]["message"]
    assert api["sent"] == []


def test_wrong_code_changes_nothing_and_five_wrong_blocks_it(api):
    c = api["use"](_db())
    rid = _start(c, api).json()["data"]["request_id"]
    code = api["sent"][0][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(ph.MAX_ATTEMPTS):
        assert c.post("/api/v1/builder/me/phone/verify", json={"request_id": rid, "code": wrong}, headers=api["h"]).status_code == 422
    assert api["db"].rows("site_phone_changes")[0]["status"] == "blocked"
    ok_code = c.post("/api/v1/builder/me/phone/verify", json={"request_id": rid, "code": code}, headers=api["h"])
    assert ok_code.status_code == 422                                      # blocked even with the right code now
    assert api["db"].rows("site_builders")[0]["phone_number"] == "2348030000001"


def test_another_builders_request_cannot_be_used(api):
    db = _db([_builder(), _builder("b-2", phone="2348030000002", email="b@example.com")])
    c = api["use"](db, "b-1")
    rid = _start(c, api).json()["data"]["request_id"]
    code = api["sent"][0][1]
    h1 = api["h"]
    api["use"](db, "b-2")
    r = c.post("/api/v1/builder/me/phone/verify", json={"request_id": rid, "code": code}, headers=api["h"])
    assert r.status_code == 422
    assert db.rows("site_builders")[0]["phone_number"] == "2348030000001"
    assert h1 != api["h"]


def test_an_expired_code_is_refused(monkeypatch):
    db = _db()
    b = db.rows("site_builders")[0]
    monkeypatch.setattr(ph, "_send_code_email", lambda *a, **k: True)
    monkeypatch.setattr(ph.secrets, "randbelow", lambda n: 123456)
    data = ph.start(db, b, "08030000009", now=NOW)
    with pytest.raises(su.SignupError):
        ph.verify(db, b, data["request_id"], "123456", now=NOW + timedelta(minutes=ph.CODE_MINUTES + 1))
    assert db.rows("site_builders")[0]["phone_number"] == "2348030000001"
    # still good inside the window
    assert ph.verify(db, b, data["request_id"], "123456", now=NOW + timedelta(minutes=5))["phone_number"] == "2348030000009"


def test_rate_limit_is_three_an_hour(api):
    c = api["use"](_db())
    for i in range(ph.PER_BUILDER_HOUR):
        assert _start(c, api, f"0803000010{i}").status_code == 200
    assert _start(c, api, "08030000199").status_code == 429


def test_email_failure_is_a_503_and_logs_no_request(api, monkeypatch):
    c = api["use"](_db())
    monkeypatch.setattr(ph, "_send_code_email", lambda *a, **k: False)
    r = _start(c, api)
    assert r.status_code == 503 and api["db"].rows("site_phone_changes") == []


# ── WhatsApp state flags on /me ─────────────────────────────────────────────

def _chat(ago_hours):
    return {"id": "c1", "org_id": ORG, "phone_number": "2348030000001",
            "last_inbound_at": (datetime.now(timezone.utc) - timedelta(hours=ago_hours)).isoformat()}


def test_me_whatsapp_flags(api):
    c = api["use"](_db())
    d = c.get("/api/v1/builder/me", headers=api["h"]).json()["data"]
    assert d["whatsapp_ever"] is False and d["whatsapp_open"] is False and d["account_type"] == "builder"
    c = api["use"](_db(chats=[_chat(1)]))
    d = c.get("/api/v1/builder/me", headers=api["h"]).json()["data"]
    assert d["whatsapp_ever"] is True and d["whatsapp_open"] is True
    c = api["use"](_db(chats=[_chat(30)]))
    d = c.get("/api/v1/builder/me", headers=api["h"]).json()["data"]
    assert d["whatsapp_ever"] is True and d["whatsapp_open"] is False


# ── the bot finds a builder by either spelling of the number ───────────────

@pytest.mark.parametrize("stored,sender", [("2348030000001", "2348030000001"), ("+2348030000001", "2348030000001"),
                                           ("2348030000001", "+2348030000001")])
def test_bot_matches_either_spelling(stored, sender):
    db = _db([_builder(phone=stored)])
    assert site_chat_service._get_builder(db, ORG, sender)["id"] == "b-1"
    assert site_chat_service._get_builder(db, ORG, "2348039999999") is None
    assert site_chat_service._get_builder(db, "other-org", sender) is None
