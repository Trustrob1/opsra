"""WA-AUTO-5: public sign-up for WhatsApp-automation-only businesses, the free trial, metering from day one."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services import org_provision_service as prov
from app.services import wa_signup_service as svc
from tests.unit.test_wa_auto_4a import KDB, _KQ

PLAT = "00000000-0000-0000-0000-0000000000aa"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
GOOD = {"business_name": "Glow Salon", "full_name": "Ada Obi", "email": "Ada@Glow.example", "phone": "0803 123 4567", "accept_terms": True}


class _SQ(_KQ):
    def execute(self):
        if self.op == "upsert":
            rows = self.db.tables.setdefault(self.name, [])
            payload = dict(self.payload)
            key = payload.get("org_id") or payload.get("id")
            for r in rows:
                if (r.get("org_id") or r.get("id")) == key:
                    r.update(payload)
                    break
            else:
                rows.append(payload)
            return SimpleNamespace(data=[payload])
        return super().execute()


class SDB(KDB):
    def __init__(self, **tables):
        for t in ("wa_signup_settings", "wa_signup_requests", "org_plans", "credit_wallets", "notifications", "organisations", "roles", "users", "org_plan_events"):
            tables.setdefault(t, [])
        super().__init__(**tables)

    def table(self, name):
        return _SQ(self, name)


def _open(db, **kw):
    db.tables["wa_signup_settings"] = [{"id": 1, "is_open": True, "trial_days": 7, "starter_credit_ngn": 0, "daily_cap": 50, **kw}]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLAT)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service")
    yield
    from app.main import app
    app.dependency_overrides.clear()


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "_send_code_email", lambda email, first, code: sent.append((email, first, code)) or True)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: False)
    return sent


class FakeClient:
    """Stands in for httpx.Client talking to Supabase Auth."""
    log: list = []
    status = 200

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, headers=None, json=None):
        FakeClient.log.append(("POST", url))
        return SimpleNamespace(status_code=FakeClient.status, json=lambda: {"id": "auth-user-1"}, text="")

    def delete(self, url, headers=None):
        FakeClient.log.append(("DELETE", url))
        return SimpleNamespace(status_code=200)


@pytest.fixture
def auth(monkeypatch):
    FakeClient.log, FakeClient.status = [], 200
    monkeypatch.setattr(prov.httpx, "Client", FakeClient)
    return FakeClient


# -- switches -------------------------------------------------------------------------------------------------------
def test_signup_is_closed_until_opened():
    assert svc.get_settings(SDB())["is_open"] is False
    db = SDB()
    _open(db)
    assert svc.get_settings(db) == {"is_open": True, "trial_days": 7, "starter_credit_ngn": 0, "daily_cap": 50}


def test_settings_are_saved_and_checked():
    db = SDB()
    out = svc.save_settings(db, {"is_open": True, "trial_days": 14, "starter_credit_ngn": 500, "daily_cap": 20})
    assert out == {"is_open": True, "trial_days": 14, "starter_credit_ngn": 500, "daily_cap": 20}
    for bad in ({"trial_days": 0}, {"trial_days": 31}, {"starter_credit_ngn": 5001}, {"starter_credit_ngn": -1}, {"daily_cap": "x"}):
        with pytest.raises(svc.SignupError):
            svc.save_settings(db, bad)
    assert svc.get_settings(db)["trial_days"] == 14


def test_public_info_shows_the_plan_price_from_settings(monkeypatch):
    from app.services import account_entitlement_service as acc
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"automate": {"label": "Automate", "monthly_ngn": 25000, "caps": {"ai_messages": 400}}}})
    db = SDB()
    _open(db, trial_days=10)
    assert svc.info(db) == {"open": True, "trial_days": 10, "starter_credit_ngn": 0, "plan": {"label": "Automate", "monthly_ngn": 25000, "ai_messages": 400}}


# -- step 1 ----------------------------------------------------------------------------------------------------------
def test_closed_signup_refuses_and_sends_nothing(mail):
    with pytest.raises(svc.SignupError) as e:
        svc.start(SDB(), GOOD, "1.2.3.4")
    assert e.value.status_code == 403 and mail == []


@pytest.mark.parametrize("change", [{"business_name": "x"}, {"full_name": ""}, {"email": "nope"}, {"phone": "12"}, {"accept_terms": False}])
def test_bad_details_are_refused(mail, change):
    db = SDB()
    _open(db)
    with pytest.raises(svc.SignupError) as e:
        svc.start(db, {**GOOD, **change}, "1.2.3.4")
    assert e.value.status_code == 422 and mail == [] and db.tables["wa_signup_requests"] == []


def test_a_code_is_emailed_and_stored_only_as_a_hash(mail):
    db = SDB()
    _open(db)
    out = svc.start(db, GOOD, "1.2.3.4", NOW)
    row = db.tables["wa_signup_requests"][0]
    assert mail[0][0] == "ada@glow.example" and mail[0][1] == "Ada" and out["email_hint"].startswith("a***@")
    assert row["status"] == "pending" and mail[0][2] not in str(row) and row["phone_number"] == "2348031234567"


def test_honeypot_creates_nothing(mail):
    db = SDB()
    _open(db)
    svc.start(db, {**GOOD, "website": "http://spam"}, "1.2.3.4")
    assert db.tables["wa_signup_requests"] == [] and mail == []


def test_an_email_that_already_has_a_login_gets_the_same_reply_but_no_code(monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "_send_code_email", lambda *a: sent.append(a) or True)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: True)
    db = SDB()
    _open(db)
    out = svc.start(db, GOOD, "1.2.3.4")
    assert out["request_id"] and sent == [] and db.tables["wa_signup_requests"][0]["status"] == "blocked"


def test_rate_limits_and_the_daily_cap(mail):
    db = SDB()
    _open(db, daily_cap=1)
    for i in range(svc.PER_EMAIL_HOUR):
        svc.start(db, GOOD, f"9.9.9.{i}", NOW)
    with pytest.raises(svc.SignupError) as e:
        svc.start(db, GOOD, "9.9.9.9", NOW)
    assert e.value.status_code == 429
    db2 = SDB()
    _open(db2, daily_cap=1)
    db2.tables["wa_signup_requests"] = [{"id": "a", "status": "verified", "verified_at": NOW.isoformat(), "created_at": NOW.isoformat(),
                                         "email": "o@x.co", "ip_hash": "h", "phone_number": "1"}]
    with pytest.raises(svc.SignupError) as e:
        svc.start(db2, {**GOOD, "email": "new@x.co"}, "5.5.5.5", NOW)
    assert e.value.status_code == 403


def test_if_the_email_cannot_be_sent_nothing_is_kept(monkeypatch):
    monkeypatch.setattr(svc, "_send_code_email", lambda *a: False)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: False)
    db = SDB()
    _open(db)
    with pytest.raises(svc.SignupError) as e:
        svc.start(db, GOOD, "1.2.3.4")
    assert e.value.status_code == 503 and db.tables["wa_signup_requests"] == []


# -- step 2 -----------------------------------------------------------------------------------------------------------
def _started(db, mail, now=NOW):
    _open(db, starter_credit_ngn=200)
    db.tables["users"] = [{"id": "p1", "org_id": PLAT, "roles": {"template": "owner"}}, {"id": "p2", "org_id": PLAT, "roles": {"template": "sales_agent"}}]
    rid = svc.start(db, GOOD, "1.2.3.4", now)["request_id"]
    return rid, mail[-1][2]


def test_the_right_code_creates_a_whatsapp_only_business_with_a_trial_and_metering(mail, auth, monkeypatch):
    from app.services import credit_service
    credits = []
    monkeypatch.setattr(credit_service, "add_credit", lambda db, org, amt, kind, ref, meta=None, **k: credits.append((org, amt, kind, ref)))
    db = SDB()
    rid, code = _started(db, mail)
    out = svc.verify(db, rid, code, "a-good-password", NOW + timedelta(minutes=2))
    org = db.tables["organisations"][0]
    assert org["product_mode"] == "wa_automation" and org["plans_enforced"] is True and org["name"] == "Glow Salon"
    assert out["email"] == "ada@glow.example" and out["org_id"] == org["id"] and out["trial_days"] == 7
    assert len(db.tables["roles"]) == 7
    user = db.tables["users"][-1]
    assert user["id"] == "auth-user-1" and user["org_id"] == org["id"] and user["full_name"] == "Ada Obi"
    plan = db.tables["org_plans"][0]
    assert (plan["key"], plan["source"], plan["status"], plan["kind"]) == ("automate", "trial", "active", "tier")
    assert plan["paid_until"] == (NOW + timedelta(minutes=2) + timedelta(days=7)).isoformat()
    wallet = db.tables["credit_wallets"][0]
    assert wallet["org_id"] == org["id"] and wallet["metering_enabled"] is True
    assert credits == [(org["id"], 20000, "adjust", f"wa_signup_{org['id']}")]
    notes = [n for n in db.tables["notifications"]]
    assert len(notes) == 1 and notes[0]["user_id"] == "p1" and "Glow Salon" in notes[0]["title"]
    assert db.tables["wa_signup_requests"][0]["status"] == "verified" and db.tables["wa_signup_requests"][0]["org_id"] == org["id"]


def test_no_starter_credit_when_it_is_zero(mail, auth, monkeypatch):
    from app.services import credit_service
    called = []
    monkeypatch.setattr(credit_service, "add_credit", lambda *a, **k: called.append(a))
    db = SDB()
    rid, code = _started(db, mail)
    db.tables["wa_signup_settings"][0]["starter_credit_ngn"] = 0
    svc.verify(db, rid, code, "a-good-password", NOW)
    assert called == []


def test_a_code_works_once_only(mail, auth):
    db = SDB()
    rid, code = _started(db, mail)
    svc.verify(db, rid, code, "a-good-password", NOW)
    with pytest.raises(svc.SignupError):
        svc.verify(db, rid, code, "a-good-password", NOW)
    assert len(db.tables["organisations"]) == 1


def test_wrong_codes_count_and_block_after_five(mail, auth):
    db = SDB()
    rid, code = _started(db, mail)
    wrong = "000000" if code != "000000" else "111111"
    for i in range(svc.MAX_ATTEMPTS):
        with pytest.raises(svc.SignupError):
            svc.verify(db, rid, wrong, "a-good-password", NOW)
    assert db.tables["wa_signup_requests"][0]["status"] == "blocked"
    with pytest.raises(svc.SignupError):
        svc.verify(db, rid, code, "a-good-password", NOW)
    assert db.tables["organisations"] == []


def test_expired_short_password_and_unknown_requests_create_nothing(mail, auth):
    db = SDB()
    rid, code = _started(db, mail)
    for args in ((rid, code, "short", NOW), (rid, code, "a-good-password", NOW + timedelta(minutes=16)), ("missing", code, "a-good-password", NOW), (rid, "12", "a-good-password", NOW)):
        with pytest.raises(svc.SignupError):
            svc.verify(db, *args)
    assert db.tables["organisations"] == [] and db.tables["wa_signup_requests"][0]["status"] == "pending"


def test_a_trial_step_problem_does_not_undo_the_account(mail, auth):
    class NoPlans(SDB):
        def table(self, name):
            if name == "org_plans":
                raise RuntimeError("down")
            return super().table(name)
    db = NoPlans()
    rid, code = _started(db, mail)
    assert svc.verify(db, rid, code, "a-good-password", NOW)["org_id"]
    assert len(db.tables["organisations"]) == 1


# -- creating the business ------------------------------------------------------------------------------------------
def test_slug_and_ticket_prefix_are_safe():
    assert prov.slugify("  Glow & Co. Salon!! ") == "glow-co-salon" and prov.slugify("???") == "business"
    assert prov.ticket_prefix("glow salon") == "GLO" and prov.ticket_prefix("?") == "WA"
    db = SDB()
    s = prov.unique_slug(db, "Glow Salon")
    assert s.startswith("glow-salon-") and len(s) == len("glow-salon-") + 4


def test_a_failure_part_way_removes_the_business_and_the_login(auth):
    db = SDB()
    real = db.table

    class Boom(SDB):
        def table(self, name):
            if name == "users":
                raise RuntimeError("down")
            return super().table(name)
    boom = Boom()
    with pytest.raises(prov.ProvisionError):
        prov.provision_wa_org(boom, business_name="Glow", owner_name="Ada", email="a@b.co", password="a-good-password", whatsapp="2348031234567")
    assert boom.tables["organisations"] == [] and ("DELETE", "https://x.supabase.test/auth/v1/admin/users/auth-user-1") in auth.log


def test_a_taken_email_at_creation_time_is_refused_and_cleaned_up(auth):
    auth.status = 422
    db = SDB()
    with pytest.raises(prov.ProvisionError) as e:
        prov.provision_wa_org(db, business_name="Glow", owner_name="Ada", email="a@b.co", password="a-good-password", whatsapp="1")
    assert e.value.code == "EMAIL_TAKEN" and db.tables["organisations"] == []


# -- paying after the trial ----------------------------------------------------------------------------------------
def test_a_trial_is_replaced_by_a_fresh_paid_period_not_added_to_it(monkeypatch):
    from app.services import account_plan_billing_service as bill
    monkeypatch.setattr(bill, "_notify", lambda *a, **k: True)
    monkeypatch.setattr(bill, "_sync_org_status", lambda *a, **k: None)
    db = SDB()
    until = NOW + timedelta(days=3)
    db.tables["org_plans"] = [{"id": "pl1", "org_id": "o1", "kind": "tier", "key": "automate", "status": "active", "source": "trial", "paid_until": until.isoformat(), "config": {}}]
    order = {"id": "ord1", "org_id": "o1", "plan_key": "automate", "change_kind": "switch", "amount_kobo": 2000000, "quote": {"key": "automate", "label": "Automate", "price": 20000, "days": 30, "kind": "switch"}}
    bill._apply_paid(db, order, "pending", NOW)
    row = db.tables["org_plans"][0]
    assert row["source"] == "paid" and row["paid_until"] == (NOW + timedelta(days=30)).isoformat()


def test_an_ended_trial_loses_the_plan_after_the_grace_days():
    from app.services import site_entitlement_service as ent
    cfg = ent.get_config({})
    row = {"status": "active", "source": "trial", "paid_until": (NOW - timedelta(days=1)).isoformat()}
    assert ent.effective_status(row, cfg, NOW) == "grace"
    row["paid_until"] = (NOW - timedelta(days=cfg["billing"]["grace_days"] + 2)).isoformat()
    assert ent.effective_status(row, cfg, NOW) == "paused"


# -- routes ---------------------------------------------------------------------------------------------------------
def _client(db):
    from app.main import app
    from app.database import get_supabase
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def test_public_routes_need_no_login_and_work_end_to_end(mail, auth, monkeypatch):
    from app.services import account_entitlement_service as acc
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"automate": {"label": "Automate", "monthly_ngn": 20000, "caps": {"ai_messages": 300}}}})
    db = SDB()
    _open(db)
    c = _client(db)
    assert c.get("/api/v1/wa-signup/info").json()["data"]["open"] is True
    r = c.post("/api/v1/wa-signup/start", json=GOOD)
    assert r.status_code == 200
    rid = r.json()["data"]["request_id"]
    r = c.post("/api/v1/wa-signup/verify", json={"request_id": rid, "code": mail[-1][2], "password": "a-good-password"})
    assert r.status_code == 200 and r.json()["data"]["email"] == "ada@glow.example"
    assert db.tables["organisations"][0]["product_mode"] == "wa_automation"
    bad = c.post("/api/v1/wa-signup/verify", json={"request_id": rid, "code": "123456", "password": "a-good-password"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_closed_signup_returns_403_through_the_route(mail):
    assert _client(SDB()).post("/api/v1/wa-signup/start", json=GOOD).status_code == 403


def test_only_superadmin_can_change_the_switches(mail):
    c = _client(SDB())
    assert c.get("/api/v1/superadmin/wa-signup/settings").status_code in (401, 403)
    assert c.put("/api/v1/superadmin/wa-signup/settings", json={"is_open": True}).status_code in (401, 403)
    from app.main import app
    from app.routers.superadmin_health import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: None
    assert c.put("/api/v1/superadmin/wa-signup/settings", json={"is_open": True, "trial_days": 5}).json()["data"]["trial_days"] == 5
    assert c.put("/api/v1/superadmin/wa-signup/settings", json={"trial_days": 99}).status_code == 422


def test_signup_routes_are_not_behind_the_crm_guard_or_a_login():
    import app.main as m
    from app.services import product_mode as pm
    from app.dependencies import get_current_org
    for r in m.app.routes:
        if getattr(r, "path", "").startswith("/api/v1/wa-signup"):
            deps = [d.call for d in r.dependant.dependencies]
            assert pm.crm_only not in deps and get_current_org not in deps
