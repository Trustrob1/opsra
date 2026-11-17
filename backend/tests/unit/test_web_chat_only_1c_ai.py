"""WEB-ONLY-1c: a new web-chat-only business starts with Chioma's AI answers switched on."""
from __future__ import annotations

from app.services import chat_signup_service as svc
from tests.unit.test_account_plans_1 import FakeDB, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

ORG = "00000000-0000-0000-0000-00000000dd01"


def _cfg(db):
    return db.tables["organisations"][0]["webchat_config"]


def test_ai_is_switched_on_for_a_new_business_with_no_config():
    db = FakeDB(organisations=[{"id": ORG, "webchat_config": None}])
    svc._turn_on_ai(db, ORG)
    assert _cfg(db) == {"ai_enabled": True, "answer_first": True}


def test_existing_settings_are_kept():
    db = FakeDB(organisations=[{"id": ORG, "webchat_config": {"ai_enabled": False, "ai_model": "haiku", "greeting": "Hello"}}])
    svc._turn_on_ai(db, ORG)
    assert _cfg(db) == {"ai_enabled": True, "answer_first": True, "ai_model": "haiku", "greeting": "Hello"}


def test_never_raises_when_the_database_fails():
    class Boom:
        def table(self, *_):
            raise RuntimeError("down")
    svc._turn_on_ai(Boom(), ORG)


def test_verify_calls_it(monkeypatch):
    src = open(svc.__file__, encoding="utf-8").read()
    assert "_turn_on_ai(db, org_id)" in src.split("def verify")[1].split("def _start_free_plan")[0]
