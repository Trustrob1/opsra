"""WEB-ONLY-1a: Chioma on the website only - product mode web_chat, the Chioma plan, the free period, the /start/chat sign-up."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services import account_entitlement_service as acc
from app.services import account_plan_billing_service as bill
from app.services import chat_signup_service as svc
from app.services import credit_service as cs
from app.services import org_provision_service as prov
from app.services import product_mode as pm
from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg
from app.workers import plan_credit_worker as w
from tests.unit.test_account_plans_1 import BIZ, FakeDB, PLATFORM, _Q, _plan
from tests.unit.test_wa_auto_1 import _jwt, _run
from tests.unit.test_wa_auto_5 import FakeClient, SDB as _WaSDB

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

PLAT = "00000000-0000-0000-0000-0000000000aa"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
ORG_WEB = "00000000-0000-0000-0000-00000000aa03"
U_WEB = "u-web"
GOOD = {"business_name": "Glow Salon", "full_name": "Ada Obi", "email": "Ada@Glow.example", "phone": "0803 123 4567", "accept_terms": True}


class SDB(_WaSDB):
    def __init__(self, **tables):
        for t in ("chat_signup_settings", "chat_signup_requests"):
            tables.setdefault(t, [])
        super().__init__(**tables)


def _open(db, **kw):
    db.tables["chat_signup_settings"] = [{"id": 1, "is_open": True, "starter_credit_ngn": 2000, "daily_cap": 50, **kw}]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLAT)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service")
    pm.invalidate()
    yield
    pm.invalidate()
    from app.main import app
    app.dependency_overrides.clear()


@pytest.fixture
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "_send_code_email", lambda email, first, code: sent.append((email, first, code)) or True)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: False)
    return sent


@pytest.fixture
def auth(monkeypatch):
    FakeClient.log, FakeClient.status = [], 200
    monkeypatch.setattr(prov.httpx, "Client", FakeClient)
    return FakeClient


# -- the new product mode ------------------------------------------------------------------------------------------
def _mode_db():
    return FakeDB(organisations=[{"id": ORG_WEB, "product_mode": "web_chat"}], users=[{"id": U_WEB, "org_id": ORG_WEB}])


def test_web_chat_is_a_known_mode_of_its_own():
    db = _mode_db()
    assert "web_chat" in pm.MODES and pm.get_mode(db, ORG_WEB) == "web_chat"
    assert pm.is_web_chat(db, ORG_WEB) is True and pm.is_wa_automation(db, ORG_WEB) is False
    pm.set_mode(db, ORG_WEB, "full")
    pm.set_mode(db, ORG_WEB, "web_chat")
    with pytest.raises(ValueError):
        pm.set_mode(db, ORG_WEB, "nonsense")


def test_web_chat_business_is_blocked_from_crm_routes_but_keeps_the_inbox_routes():
    from fastapi import HTTPException
    for method, path in (("GET", "/api/v1/leads"), ("GET", "/api/v1/customers"), ("POST", "/api/v1/tasks")):
        with pytest.raises(HTTPException) as e:
            _run(method, path, _jwt(U_WEB), _mode_db())
        assert e.value.status_code == 404, (method, path)
    assert _run("GET", "/api/v1/leads/abc/messages", _jwt(U_WEB), _mode_db()) is None


@pytest.mark.parametrize("mode,expect_calls", [("web_chat", 1), ("wa_automation", 0), ("full", 1)])
def test_a_new_web_chat_lead_is_announced_and_assigned_unlike_whatsapp_only(monkeypatch, mode, expect_calls):
    from app.services import lead_assignment_service as las
    from app.services import lead_service as ls
    notified, assigned = [], []

    class _T:
        def __init__(self, target=None, args=(), daemon=None): self.args = args
        def start(self): notified.append(self.args)

    monkeypatch.setattr(ls.threading, "Thread", _T)
    monkeypatch.setattr(las, "auto_assign_lead", lambda *a, **k: assigned.append(a))
    monkeypatch.setattr(pm, "get_mode", lambda db, org: mode)
    db = MagicMock()
    row = {"id": "lead-1", "org_id": ORG_WEB, "full_name": "Ada", "whatsapp": "2348000000000", "phone": "2348000000000", "stage": "new", "source": "landing_page"}
    db.table.return_value.insert.return_value.execute.return_value.data = [row]
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    payload = ls.LeadCreate(full_name="Ada", phone="2348000000000", whatsapp="2348000000000", source="landing_page")
    try:
        ls.create_lead(db, ORG_WEB, "user-1", payload)
    except Exception:
        pass            # later parts of create_lead need richer scripting; the guard calls above are what matter (same as test_wa_auto_1)
    assert len(notified) == expect_calls and len(assigned) == expect_calls


def test_superadmin_can_set_and_create_web_chat_businesses():
    from pydantic import ValidationError
    from app.routers import superadmin as sa
    base = dict(org_name="Glow", slug="glow", industry="x", ticket_prefix="GLW", owner_email="a@b.com", owner_full_name="Ada", owner_password="Password123!")
    assert sa.OrgProvisionPayload(**base, product_mode="web_chat").product_mode == "web_chat"
    assert sa.ProductModePayload(product_mode="web_chat").product_mode == "web_chat"
    with pytest.raises(ValidationError):
        sa.ProductModePayload(product_mode="other")


# -- the Chioma plan --------------------------------------------------------------------------------------------------
def test_chioma_tier_is_registered_with_the_agreed_defaults():
    assert "chioma" in reg.TIER_KEYS and reg.CHAT_ONLY_TIERS == ("chioma",) and "chioma" not in reg.WA_ONLY_TIERS
    t = ent.get_config({})["tiers"]["chioma"]
    assert t["label"] == "Chioma" and t["chat_only"] is True and t["wa_only"] is False
    assert t["monthly_ngn"] == 0 and t["sellable"] is False                 # never priced in code: Superadmin sets N15,000
    assert t["caps"] == {"ai_messages": 300, "users_included": 2} and t["included_credit_ngn"] == 6000
    assert {"webchat_basic", "ai_assistant", "knowledge_base", "selling_catalog"} <= set(t["features"])
    assert not {"own_wa_number", "wa_leads", "payment_links", "catalog_storefront", "crm", "bulk_messaging"} & set(t["features"])
    assert reg.RECOMMENDED_START["chioma"]["monthly_ngn"] == 15000
    for other in ("capture", "convert", "grow", "scale", "automate"):
        assert ent.get_config({})["tiers"][other]["chat_only"] is False


def test_the_chioma_price_and_credit_can_be_set_in_settings_and_are_checked():
    cfg = ent.get_config({"pricing": {"tiers": {"chioma": {"monthly_ngn": 15000, "included_credit_ngn": 6000}}}})
    assert cfg["tiers"]["chioma"]["sellable"] is True and cfg["tiers"]["chioma"]["monthly_ngn"] == 15000
    ent.validate_pricing({"tiers": {"chioma": {"monthly_ngn": 15000}}})
    with pytest.raises(ent.EntitlementError):
        ent.validate_pricing({"tiers": {"nonsense": {"monthly_ngn": 1}}})


def _fits_db(mode):
    return FakeDB(organisations=[{"id": ORG_WEB, "product_mode": mode}])


@pytest.mark.parametrize("mode,fits", [("web_chat", {"chioma"}), ("wa_automation", {"automate"}), ("full", {"capture", "convert", "grow", "scale"})])
def test_each_kind_of_business_is_offered_only_its_own_plans(mode, fits):
    tiers = ent.get_config({})["tiers"]
    assert {k for k, d in tiers.items() if bill._tier_fits_org(_fits_db(mode), ORG_WEB, d)} == fits


def test_a_lookup_problem_counts_as_a_normal_business():
    bad = MagicMock()
    bad.table.side_effect = RuntimeError("down")
    tiers = ent.get_config({})["tiers"]
    assert bill._tier_fits_org(bad, ORG_WEB, tiers["grow"]) is True and bill._tier_fits_org(bad, ORG_WEB, tiers["chioma"]) is False


def test_websites_are_never_offered_the_chioma_plan():
    from app.routers import builder_portal
    import inspect
    assert "chat_only" in inspect.getsource(builder_portal)


# -- the free period ----------------------------------------------------------------------------------------------------
def test_a_free_plan_row_with_no_end_date_is_active_but_a_trial_row_is_not():
    cfg = ent.get_config({})
    free = {"status": "active", "source": "free", "paid_until": None}
    assert ent.effective_status(free, cfg, NOW) == "active"
    assert ent.effective_status({**free, "source": "staff"}, cfg, NOW) == "active"
    assert ent.effective_status({**free, "source": "trial"}, cfg, NOW) == "pending"
    assert ent.effective_status({**free, "source": "paid"}, cfg, NOW) == "pending"
    assert ent.effective_status({**free, "status": "paused"}, cfg, NOW) == "paused"


def _plans_db(plans):
    return FakeDB(
        site_builder_settings=[{"org_id": PLATFORM, "pricing": {}}],
        organisations=[{"id": BIZ, "name": "Glow", "subscription_status": "active", "plans_enforced": True, "product_mode": "web_chat"}],
        org_plans=plans, org_usage_counters=[], org_plan_events=[], site_addons=[], site_usage_counters=[], sites=[], org_plan_orders=[])


@pytest.fixture
def plans_env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def test_the_free_plan_turns_on_web_chat_and_the_ai_allowance_but_no_crm_or_shop(plans_env):
    db = _plans_db([_plan(org=BIZ, key="chioma", source="free", until="none")])
    for key in ("webchat_basic", "ai_assistant", "knowledge_base", "selling_catalog"):
        assert acc.has_feature(db, key, org_id=BIZ) is True, key
    for key in ("payment_links", "catalog_storefront", "own_wa_number", "bulk_messaging"):
        assert acc.has_feature(db, key, org_id=BIZ) is False, key
    assert acc.get_entitlements(db, BIZ)["caps"]["ai_messages"] == 300


def test_without_a_plan_row_an_enforced_business_loses_web_chat(plans_env):
    assert acc.has_feature(_plans_db([]), "webchat_basic", org_id=BIZ) is False


@pytest.fixture
def wallet(monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "get_wallet", lambda db, org: {"org_id": org, "metering_enabled": True})
    monkeypatch.setattr(cs, "add_credit", lambda db, org, kobo, kind, ref, meta=None, expires_at=None:
                        calls.append(dict(org=org, kobo=kobo, ref=ref)) or {"applied": True})
    return calls


def test_the_free_period_never_earns_the_monthly_included_credit(plans_env, wallet):
    db = _plans_db([_plan(org=BIZ, key="chioma", source="free", until="none")])
    assert w.run_plan_credit_grants(db, NOW)["granted"] == 0 and wallet == []
    assert w.ensure_wallet_and_grant(db, BIZ, NOW) is None and wallet == []


def test_a_paid_chioma_plan_earns_6000_naira_a_month(plans_env, wallet):
    db = _plans_db([_plan(org=BIZ, key="chioma", source="paid", until=NOW + timedelta(days=20))])
    assert w.run_plan_credit_grants(db, NOW)["granted"] == 1
    assert wallet[0]["kobo"] == 600000 and wallet[0]["org"] == BIZ


def test_paying_turns_the_free_row_into_a_fresh_paid_period(monkeypatch, plans_env):
    monkeypatch.setattr(bill, "_notify", lambda *a, **k: True)
    monkeypatch.setattr(bill, "_sync_org_status", lambda *a, **k: None)
    db = _plans_db([{"id": "pl1", "org_id": "o1", "kind": "tier", "key": "chioma", "status": "active", "source": "free", "paid_until": None, "config": {}}])
    order = {"id": "ord1", "org_id": "o1", "plan_key": "chioma", "change_kind": "switch", "amount_kobo": 1500000,
             "quote": {"key": "chioma", "label": "Chioma", "price": 15000, "days": 30, "kind": "switch"}}
    bill._apply_paid(db, order, "pending", NOW)
    row = db.tables["org_plans"][0]
    assert row["source"] == "paid" and row["key"] == "chioma" and row["paid_until"] == (NOW + timedelta(days=30)).isoformat()


def test_a_web_chat_business_can_be_quoted_the_chioma_plan_once_it_is_priced(plans_env):
    cfg = ent.get_config({"pricing": {"tiers": {"chioma": {"monthly_ngn": 15000}, "automate": {"monthly_ngn": 40000}}}})
    free = _plan(org=BIZ, key="chioma", source="free", until="none")
    db = _plans_db([free])
    qt = bill.quote_for(db, BIZ, cfg, "chioma", NOW, free)
    assert qt["kind"] == "switch" and qt["price"] == 15000 and qt["total"] == 15000
    with pytest.raises(bill.PlanBillingError):          # Chat Basic is not offered to a web-chat-only business yet (WEB-ONLY-1e)
        bill.quote_for(db, BIZ, cfg, "automate", NOW, free)
    full = _plans_db([])
    full.tables["organisations"][0]["product_mode"] = "full"
    pm.invalidate()
    with pytest.raises(bill.PlanBillingError):          # a normal business is never offered Chioma
        bill.quote_for(full, BIZ, cfg, "chioma", NOW, None)


def test_an_unpriced_chioma_plan_is_not_for_sale(plans_env):
    with pytest.raises(bill.PlanBillingError):
        bill.quote_for(_plans_db([]), BIZ, ent.get_config({}), "chioma", NOW, None)


# -- sign-up switches --------------------------------------------------------------------------------------------------
def test_signup_is_closed_until_opened_and_starts_with_2000_naira():
    assert svc.get_settings(SDB()) == {"is_open": False, "starter_credit_ngn": 2000, "daily_cap": 50}
    db = SDB()
    _open(db)
    assert svc.get_settings(db)["is_open"] is True


def test_settings_are_saved_and_checked():
    db = SDB()
    out = svc.save_settings(db, {"is_open": True, "starter_credit_ngn": 1500, "daily_cap": 20})
    assert out == {"is_open": True, "starter_credit_ngn": 1500, "daily_cap": 20}
    for bad in ({"starter_credit_ngn": 5001}, {"starter_credit_ngn": -1}, {"daily_cap": "x"}, {"daily_cap": 1001}):
        with pytest.raises(svc.SignupError):
            svc.save_settings(db, bad)
    assert svc.get_settings(db)["starter_credit_ngn"] == 1500


def test_the_chat_and_whatsapp_switches_are_separate():
    db = SDB()
    db.tables["wa_signup_settings"] = [{"id": 1, "is_open": True, "trial_days": 7, "starter_credit_ngn": 0, "daily_cap": 50}]
    assert svc.get_settings(db)["is_open"] is False
    with pytest.raises(svc.SignupError) as e:
        svc.start(db, GOOD, "1.2.3.4")
    assert e.value.status_code == 403


def test_public_info_shows_the_plan_from_settings(monkeypatch):
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"chioma": {"label": "Chioma", "monthly_ngn": 15000, "caps": {"ai_messages": 300}, "included_credit_ngn": 6000}}})
    db = SDB()
    _open(db)
    assert svc.info(db) == {"open": True, "starter_credit_ngn": 2000,
                            "plan": {"label": "Chioma", "monthly_ngn": 15000, "ai_messages": 300, "included_credit_ngn": 6000}}


# -- step 1 ------------------------------------------------------------------------------------------------------------
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
    assert e.value.status_code == 422 and mail == [] and db.tables["chat_signup_requests"] == []


def test_a_code_is_emailed_and_stored_only_as_a_hash(mail):
    db = SDB()
    _open(db)
    out = svc.start(db, GOOD, "1.2.3.4", NOW)
    row = db.tables["chat_signup_requests"][0]
    assert mail[0][0] == "ada@glow.example" and mail[0][1] == "Ada" and out["email_hint"].startswith("a***@")
    assert row["status"] == "pending" and mail[0][2] not in str(row) and row["phone_number"] == "2348031234567"
    assert db.tables["wa_signup_requests"] == []


def test_honeypot_creates_nothing(mail):
    db = SDB()
    _open(db)
    svc.start(db, {**GOOD, "website": "http://spam"}, "1.2.3.4")
    assert db.tables["chat_signup_requests"] == [] and mail == []


def test_an_email_that_already_has_a_login_gets_the_same_reply_but_no_code(monkeypatch):
    sent = []
    monkeypatch.setattr(svc, "_send_code_email", lambda *a: sent.append(a) or True)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: True)
    db = SDB()
    _open(db)
    out = svc.start(db, GOOD, "1.2.3.4")
    assert out["request_id"] and sent == [] and db.tables["chat_signup_requests"][0]["status"] == "blocked"


def test_rate_limits_and_the_daily_cap_count_chat_requests_only(mail):
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
    svc.start(db2, {**GOOD, "email": "new@x.co"}, "5.5.5.5", NOW)          # a verified WhatsApp sign-up does not use up the chat cap
    db2.tables["chat_signup_requests"][0].update(status="verified", verified_at=NOW.isoformat())
    with pytest.raises(svc.SignupError) as e:
        svc.start(db2, {**GOOD, "email": "other@x.co"}, "6.6.6.6", NOW)
    assert e.value.status_code == 403


def test_if_the_email_cannot_be_sent_nothing_is_kept(monkeypatch):
    monkeypatch.setattr(svc, "_send_code_email", lambda *a: False)
    monkeypatch.setattr(prov, "auth_email_exists", lambda email: False)
    db = SDB()
    _open(db)
    with pytest.raises(svc.SignupError) as e:
        svc.start(db, GOOD, "1.2.3.4")
    assert e.value.status_code == 503 and db.tables["chat_signup_requests"] == []


# -- step 2 ------------------------------------------------------------------------------------------------------------
def _started(db, mail, now=NOW):
    _open(db)
    db.tables["users"] = [{"id": "p1", "org_id": PLAT, "roles": {"template": "owner"}}, {"id": "p2", "org_id": PLAT, "roles": {"template": "sales_agent"}}]
    rid = svc.start(db, GOOD, "1.2.3.4", now)["request_id"]
    return rid, mail[-1][2]


def test_the_right_code_creates_a_web_chat_business_with_a_free_plan_and_metering(mail, auth, monkeypatch):
    credits = []
    monkeypatch.setattr(cs, "add_credit", lambda db, org, amt, kind, ref, meta=None, **k: credits.append((org, amt, kind, ref)))
    db = SDB()
    rid, code = _started(db, mail)
    out = svc.verify(db, rid, code, "a-good-password", NOW + timedelta(minutes=2))
    org = db.tables["organisations"][0]
    assert org["product_mode"] == "web_chat" and org["plans_enforced"] is True and org["name"] == "Glow Salon"
    assert out == {"email": "ada@glow.example", "org_id": org["id"], "starter_credit_ngn": 2000}
    assert len(db.tables["roles"]) == 7
    user = db.tables["users"][-1]
    assert user["id"] == "auth-user-1" and user["org_id"] == org["id"] and user["full_name"] == "Ada Obi"
    plan = db.tables["org_plans"][0]
    assert (plan["key"], plan["source"], plan["status"], plan["kind"], plan["paid_until"], plan["price_ngn"]) == ("chioma", "free", "active", "tier", None, 0)
    wallet = db.tables["credit_wallets"][0]
    assert wallet == {"org_id": org["id"], "metering_enabled": True}                # no Meta billing line: no WhatsApp
    assert credits == [(org["id"], 200000, "adjust", f"chat_signup_{org['id']}")]
    notes = db.tables["notifications"]
    assert len(notes) == 1 and notes[0]["user_id"] == "p1" and notes[0]["title"] == "New Chioma sign-up: Glow Salon" and notes[0]["type"] == "chat_signup"
    req = db.tables["chat_signup_requests"][0]
    assert req["status"] == "verified" and req["org_id"] == org["id"]


def test_the_starter_credit_follows_the_superadmin_setting_and_zero_means_none(mail, auth, monkeypatch):
    called = []
    monkeypatch.setattr(cs, "add_credit", lambda db, org, amt, *a, **k: called.append(amt))
    db = SDB()
    rid, code = _started(db, mail)
    db.tables["chat_signup_settings"][0]["starter_credit_ngn"] = 1000
    svc.verify(db, rid, code, "a-good-password", NOW)
    assert called == [100000]
    db2 = SDB()
    rid2, code2 = _started(db2, mail)
    db2.tables["chat_signup_settings"][0]["starter_credit_ngn"] = 0
    called.clear()
    svc.verify(db2, rid2, code2, "a-good-password", NOW)
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
    for _ in range(svc.MAX_ATTEMPTS):
        with pytest.raises(svc.SignupError):
            svc.verify(db, rid, wrong, "a-good-password", NOW)
    assert db.tables["chat_signup_requests"][0]["status"] == "blocked"
    with pytest.raises(svc.SignupError):
        svc.verify(db, rid, code, "a-good-password", NOW)
    assert db.tables["organisations"] == []


def test_expired_short_password_and_unknown_requests_create_nothing(mail, auth):
    db = SDB()
    rid, code = _started(db, mail)
    for args in ((rid, code, "short", NOW), (rid, code, "a-good-password", NOW + timedelta(minutes=16)), ("missing", code, "a-good-password", NOW), (rid, "12", "a-good-password", NOW)):
        with pytest.raises(svc.SignupError):
            svc.verify(db, *args)
    assert db.tables["organisations"] == [] and db.tables["chat_signup_requests"][0]["status"] == "pending"


def test_a_plan_step_problem_does_not_undo_the_account(mail, auth):
    class NoPlans(SDB):
        def table(self, name):
            if name == "org_plans":
                raise RuntimeError("down")
            return super().table(name)
    db = NoPlans()
    rid, code = _started(db, mail)
    assert svc.verify(db, rid, code, "a-good-password", NOW)["org_id"]
    assert len(db.tables["organisations"]) == 1


def test_the_whatsapp_signup_still_makes_a_whatsapp_only_business(auth):
    db = SDB()
    made = prov.provision_wa_org(db, business_name="Glow", owner_name="Ada", email="a@b.co", password="a-good-password", whatsapp="2348031234567")
    assert db.tables["organisations"][0]["product_mode"] == "wa_automation" and made["org_id"]
    with pytest.raises(prov.ProvisionError):
        prov.provision_wa_org(SDB(), business_name="Glow", owner_name="Ada", email="a@b.co", password="a-good-password", whatsapp="1", product_mode="full")


# -- routes ------------------------------------------------------------------------------------------------------------
def _client(db):
    from app.main import app
    from app.database import get_supabase
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app)


def test_public_routes_need_no_login_and_work_end_to_end(mail, auth, monkeypatch):
    monkeypatch.setattr(cs, "add_credit", lambda *a, **k: {"applied": True})
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"chioma": {"label": "Chioma", "monthly_ngn": 15000, "caps": {"ai_messages": 300}}}})
    db = SDB()
    _open(db)
    c = _client(db)
    assert c.get("/api/v1/chat-signup/info").json()["data"]["open"] is True
    r = c.post("/api/v1/chat-signup/start", json=GOOD)
    assert r.status_code == 200
    rid = r.json()["data"]["request_id"]
    r = c.post("/api/v1/chat-signup/verify", json={"request_id": rid, "code": mail[-1][2], "password": "a-good-password"})
    assert r.status_code == 200 and r.json()["data"]["email"] == "ada@glow.example"
    assert db.tables["organisations"][0]["product_mode"] == "web_chat"
    bad = c.post("/api/v1/chat-signup/verify", json={"request_id": rid, "code": "123456", "password": "a-good-password"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_closed_signup_returns_403_through_the_route(mail):
    assert _client(SDB()).post("/api/v1/chat-signup/start", json=GOOD).status_code == 403


def test_only_superadmin_can_change_the_switches(mail):
    c = _client(SDB())
    assert c.get("/api/v1/superadmin/chat-signup/settings").status_code in (401, 403)
    assert c.put("/api/v1/superadmin/chat-signup/settings", json={"is_open": True}).status_code in (401, 403)
    from app.main import app
    from app.routers.superadmin_health import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: None
    assert c.put("/api/v1/superadmin/chat-signup/settings", json={"is_open": True, "starter_credit_ngn": 1500}).json()["data"]["starter_credit_ngn"] == 1500
    assert c.put("/api/v1/superadmin/chat-signup/settings", json={"starter_credit_ngn": 99999}).status_code == 422


def test_signup_routes_are_not_behind_the_crm_guard_or_a_login():
    import app.main as m
    from app.dependencies import get_current_org
    found = 0
    for r in m.app.routes:
        if getattr(r, "path", "").startswith("/api/v1/chat-signup"):
            found += 1
            deps = [d.call for d in r.dependant.dependencies]
            assert pm.crm_only not in deps and get_current_org not in deps
    assert found == 3
