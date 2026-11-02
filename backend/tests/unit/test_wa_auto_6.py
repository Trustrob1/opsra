"""WA-AUTO-6: connect-WhatsApp requests - email alert, Superadmin list, mark connected."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services import wa_onboarding_service as onb
from app.services import wa_setup_queue_service as queue
from app.services import wa_signup_service as signup
from tests.unit.test_wa_auto_5 import SDB

PLAT = "00000000-0000-0000-0000-0000000000aa"
ORG = "00000000-0000-0000-0000-00000000aa01"
ORG2 = "00000000-0000-0000-0000-00000000aa02"


class Mailer:
    sent: list = []

    class Emails:
        @staticmethod
        def send(payload):
            Mailer.sent.append(payload)

    api_key = None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLAT)
    monkeypatch.setenv("RESEND_API_KEY", "key")
    Mailer.sent = []
    monkeypatch.setitem(sys.modules, "resend", Mailer)
    yield
    from app.main import app
    app.dependency_overrides.clear()


def _db(alert="trustrobert34@gmail.com"):
    return SDB(
        organisations=[{"id": ORG, "name": "DorameliI Hairs", "product_mode": "wa_automation", "whatsapp_phone_id": None},
                       {"id": ORG2, "name": "Glow Salon", "product_mode": "wa_automation", "whatsapp_phone_id": "123"}, {"id": PLAT, "name": "Opsra"}],
        wa_onboarding=[], wa_signup_settings=[{"id": 1, "is_open": True, "alert_email": alert}],
        users=[{"id": "p1", "org_id": PLAT, "roles": {"template": "owner"}}], notifications=[])


def test_a_request_emails_the_alert_address_with_the_details():
    db = _db()
    out = onb.request_setup(db, ORG, "u1", "2348109374720", "evenings please")
    assert out == {"requested": True, "notified": 1, "emailed": True}
    mail = Mailer.sent[0]
    assert mail["to"] == ["trustrobert34@gmail.com"] and "DorameliI Hairs" in mail["subject"]
    assert "2348109374720" in mail["text"] and "evenings please" in mail["text"]


def test_an_empty_address_turns_the_email_off_but_the_request_still_works():
    db = _db(alert="")
    out = onb.request_setup(db, ORG, "u1", "2348109374720", "")
    assert out["requested"] is True and out["emailed"] is False and Mailer.sent == []
    assert len(db.tables["notifications"]) == 1


def test_a_mail_failure_never_fails_the_request(monkeypatch):
    class Boom(Mailer):
        class Emails:
            @staticmethod
            def send(payload):
                raise RuntimeError("down")
    monkeypatch.setitem(sys.modules, "resend", Boom)
    db = _db()
    assert onb.request_setup(db, ORG, "u1", "2348109374720", "")["emailed"] is False
    assert db.tables["wa_onboarding"][0]["setup_phone"] == "2348109374720"


def test_no_mail_key_means_no_email(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY")
    assert onb.request_setup(_db(), ORG, "u1", "2348109374720", "")["emailed"] is False


def test_asking_again_puts_a_finished_request_back_in_the_queue():
    db = _db()
    onb.request_setup(db, ORG, "u1", "2348109374720", "")
    queue.mark_done(db, ORG)
    assert db.tables["wa_onboarding"][0]["setup_done_at"]
    onb.request_setup(db, ORG, "u1", "2348109374720", "again")
    assert db.tables["wa_onboarding"][0]["setup_done_at"] is None


def test_the_list_shows_waiting_first_then_connected_with_business_names():
    db = _db()
    onb.request_setup(db, ORG, "u1", "2348109374720", "")
    onb.request_setup(db, ORG2, "u2", "2348000000002", "hi")
    queue.mark_done(db, ORG2)
    rows = queue.list_requests(db)
    assert [r["business"] for r in rows] == ["DorameliI Hairs", "Glow Salon"]
    assert rows[0]["done"] is False and rows[1]["done"] is True and rows[1]["number_linked"] is True
    assert queue.mark_done(db, "nope") == {"found": False}


def test_businesses_that_never_asked_are_not_listed():
    db = _db()
    db.tables["wa_onboarding"] = [{"org_id": ORG, "basics": {}, "setup_requested_at": None}]
    assert queue.list_requests(db) == []


def test_alert_address_is_a_checked_superadmin_setting():
    db = _db()
    assert signup.save_settings(db, {"alert_email": " Me@Example.com "})["alert_email"] == "me@example.com"
    assert signup.save_settings(db, {"alert_email": ""})["alert_email"] == ""
    with pytest.raises(signup.SignupError):
        signup.save_settings(db, {"alert_email": "not an email"})
    assert signup.get_settings(SDB())["alert_email"] == "trustrobert34@gmail.com"


def _client(db):
    from app.main import app
    from app.database import get_supabase
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def test_only_superadmin_sees_and_changes_the_queue():
    db = _db()
    onb.request_setup(db, ORG, "u1", "2348109374720", "")
    c = _client(db)
    assert c.get("/api/v1/superadmin/wa-signup/setup-requests").status_code in (401, 403)
    assert c.post(f"/api/v1/superadmin/wa-signup/setup-requests/{ORG}/done").status_code in (401, 403)
    from app.main import app
    from app.routers.superadmin_health import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: None
    assert c.get("/api/v1/superadmin/wa-signup/setup-requests").json()["data"][0]["business"] == "DorameliI Hairs"
    assert c.post(f"/api/v1/superadmin/wa-signup/setup-requests/{ORG}/done").status_code == 200
    assert c.get("/api/v1/superadmin/wa-signup/setup-requests").json()["data"][0]["done"] is True
    assert c.post("/api/v1/superadmin/wa-signup/setup-requests/missing/done").status_code == 404
