"""WA-AUTO-3: the first-login wizard for WhatsApp-automation-only businesses."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services import product_mode as pm
from app.services import wa_onboarding_service as svc
from tests.unit.test_account_plans_1 import FakeDB
from tests.unit.test_wa_auto_4a import KDB

if True:
    from tests.unit.test_account_plans_1 import _Q
    if not hasattr(_Q, "maybe_single"):
        _Q.maybe_single = lambda self: self

ORG = "00000000-0000-0000-0000-00000000aa01"
FULL = "00000000-0000-0000-0000-00000000aa02"
PLAT = "00000000-0000-0000-0000-0000000000aa"


def _db(connected=False, **extra):
    org = {"id": ORG, "name": "Glow Salon", "product_mode": "wa_automation",
           "whatsapp_phone_id": "123" if connected else None, "whatsapp_access_token": "tok" if connected else None}
    return KDB(organisations=[org, {"id": FULL, "name": "Full", "product_mode": "full"}, {"id": PLAT, "name": "Opsra"}],
                  wa_onboarding=[], knowledge_base_articles=[], notifications=[], whatsapp_messages=[],
                  users=[{"id": "p1", "org_id": PLAT, "roles": {"template": "owner"}},
                         {"id": "p2", "org_id": PLAT, "roles": {"template": "sales_agent"}}],
                  site_builder_settings=[{"org_id": PLAT, "enabled": True, "pricing": {}}], **extra)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLAT)
    pm.invalidate()
    yield
    pm.invalidate()
    from app.main import app
    app.dependency_overrides.clear()


def test_basics_are_saved_and_given_to_the_bot_once():
    db = _db()
    out = svc.save_basics(db, ORG, "  Braids and wigs ", "Mon-Sat 9-6", "English", "u1")
    assert out == {"what_you_sell": "Braids and wigs", "hours": "Mon-Sat 9-6", "language": "English"}
    svc.save_basics(db, ORG, "Braids, wigs and nails", "Mon-Sat 9-6", "Pidgin", "u1")
    srcs = db.tables["knowledge_sources"]
    assert len(srcs) == 1                                   # replaced, not duplicated
    assert srcs[0]["status"] == "active" and srcs[0]["title"] == svc.BASICS_TITLE
    text = " ".join(c["content"] for c in db.tables["knowledge_chunks"])
    assert "nails" in text and "Pidgin" in text and "Braids and wigs" not in text
    assert len(db.tables["wa_onboarding"]) == 1


@pytest.mark.parametrize("sell,hours,lang", [("", "9-5", "English"), ("x", "", "English"), ("x", "9-5", "Klingon"),
                                              ("x" * 1501, "9-5", "English")])
def test_bad_basics_are_refused(sell, hours, lang):
    with pytest.raises(HTTPException) as e:
        svc.save_basics(_db(), ORG, sell, hours, lang)
    assert e.value.status_code == 422


def test_a_knowledge_problem_does_not_lose_the_basics():
    class Broken(FakeDB):
        def table(self, name):
            if name == "knowledge_sources":
                raise RuntimeError("down")
            return super().table(name)
    db = Broken(wa_onboarding=[], organisations=[{"id": ORG}])
    svc.save_basics(db, ORG, "x", "y", "English")
    assert db.tables["wa_onboarding"][0]["basics"]["what_you_sell"] == "x"


def test_setup_request_is_recorded_and_only_platform_owners_are_told():
    db = _db()
    out = svc.request_setup(db, ORG, "u1", "2348012345678", "evening please")
    assert out == {"requested": True, "notified": 1}
    n = db.tables["notifications"]
    assert len(n) == 1 and n[0]["user_id"] == "p1" and n[0]["org_id"] == PLAT and "Glow Salon" in n[0]["title"]
    assert db.tables["wa_onboarding"][0]["setup_phone"] == "2348012345678"


def test_setup_request_needs_a_real_number():
    for bad in ("", "abc", "123"):
        with pytest.raises(HTTPException):
            svc.request_setup(_db(), ORG, "u1", bad, "")


def test_notification_failure_does_not_fail_the_request():
    class Broken(FakeDB):
        def table(self, name):
            if name == "notifications":
                raise RuntimeError("down")
            return super().table(name)
    base = _db()
    db = Broken(**base.tables)
    assert svc.request_setup(db, ORG, "u1", "2348012345678", "")["requested"] is True


def test_state_reports_connection_and_never_the_token():
    s = svc.state(_db(connected=True), ORG)
    assert s["connected"] is True and s["phone_id"] == "123"
    assert "tok" not in str(s)
    assert svc.state(_db(connected=False), ORG)["connected"] is False


def test_complete_needs_a_connected_number():
    with pytest.raises(HTTPException) as e:
        svc.complete(_db(connected=False), ORG)
    assert e.value.status_code == 409
    db = _db(connected=True)
    assert svc.complete(db, ORG) == {"completed": True}
    assert svc.state(db, ORG)["completed"] is True


def test_test_status_needs_a_message_in_and_a_reply_out():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db = _db(connected=True)
    db.tables["whatsapp_messages"] += [{"org_id": ORG, "direction": "inbound", "created_at": now}]
    assert svc.test_status(db, ORG)["ok"] is False
    db.tables["whatsapp_messages"] += [{"org_id": ORG, "direction": "outbound", "created_at": now}]
    assert svc.test_status(db, ORG)["ok"] is True


def _client(db, template="owner", org_id=ORG):
    from app.main import app
    from app.database import get_supabase
    from app.dependencies import get_current_org
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_org] = lambda: {"org_id": org_id, "id": "u1", "roles": {"template": template}}
    return TestClient(app)


def test_routes_through_the_real_app():
    db = _db(connected=True)
    c = _client(db)
    assert c.get("/api/v1/wa-onboarding").json()["data"]["business_name"] == "Glow Salon"
    r = c.put("/api/v1/wa-onboarding/basics", json={"what_you_sell": "Wigs", "hours": "9-5", "language": "English"})
    assert r.status_code == 200
    assert c.post("/api/v1/wa-onboarding/request-setup", json={"phone": "2348012345678"}).status_code == 200
    assert c.get("/api/v1/wa-onboarding/test-status").status_code == 200
    assert c.post("/api/v1/wa-onboarding/complete").json()["data"]["completed"] is True


def test_normal_businesses_get_not_found_and_staff_are_refused():
    assert _client(_db(), org_id=FULL).get("/api/v1/wa-onboarding").status_code == 404
    assert _client(_db(), template="sales_agent").get("/api/v1/wa-onboarding").status_code == 403
    assert _client(_db(), template="ops_manager").get("/api/v1/wa-onboarding").status_code == 200


def test_wizard_routes_stay_open_to_whatsapp_only_businesses():
    import app.main as m
    for r in m.app.routes:
        if getattr(r, "path", "").startswith("/api/v1/wa-onboarding"):
            assert not any(d.call is pm.crm_only for d in r.dependant.dependencies)
