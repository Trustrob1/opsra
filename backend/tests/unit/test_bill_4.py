"""BILL-4: the invoice-style Billing link (one active link per business, hashed token, expiry, revoke, scoped pay + verify)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.routers import billing_pay_link as router
from app.services import account_plan_billing_service as plans
from app.services import billing_pay_link_service as svc
from app.services import credit_order_service as cos
from tests.unit.test_account_plans_1 import BIZ, FakeDB, OTHER, PLATFORM, _Q, _plan
from tests.unit.test_account_plans_2 import _full_db

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ORG_ID", PLATFORM)


def _db(plans_rows=None):
    db = _full_db(plans=plans_rows or [])
    db.tables.setdefault("billing_pay_links", [])
    db.tables.setdefault("credit_lots", [])
    db.tables["organisations"][0]["name"] = "Glow Studio"
    return db


def _make(db, org=BIZ, **kw):
    return svc.create(db, org, user_id="u1", label="Ada", email="ada@glow.test", now=NOW, **kw)


def test_token_is_never_stored_only_its_hash():
    db = _db()
    made = _make(db)
    row = db.rows("billing_pay_links")[0]
    assert made["token"] not in str(row) and row["token_hash"] == svc.hash_token(made["token"])
    assert row["expires_at"].startswith("2026-11-21")                  # 7 days


def test_a_new_link_ends_the_old_one():
    db = _db()
    first = _make(db)
    second = _make(db)
    with pytest.raises(svc.LinkError):
        svc.resolve(db, first["token"], NOW)
    assert svc.resolve(db, second["token"], NOW)["org_id"] == BIZ
    assert sum(1 for r in db.rows("billing_pay_links") if not r.get("revoked_at")) == 1


def test_expired_revoked_and_garbage_tokens_all_give_the_same_error():
    db = _db()
    made = _make(db, days=1)
    for bad in (made["token"], "x", "", "a" * 40):
        with pytest.raises(svc.LinkError) as e:
            svc.resolve(db, bad, NOW + (timedelta(days=2) if bad == made["token"] else timedelta()))
        assert str(e.value) == svc.GENERIC
    svc.revoke(db, BIZ, NOW)
    with pytest.raises(svc.LinkError):
        svc.resolve(db, made["token"], NOW)


def test_days_are_capped_at_30():
    db = _db()
    _make(db, days=999)
    assert db.rows("billing_pay_links")[0]["expires_at"].startswith("2026-12-14")


def test_each_use_is_counted_and_status_never_reveals_the_token():
    db = _db()
    made = _make(db)
    svc.resolve(db, made["token"], NOW)
    svc.resolve(db, made["token"], NOW + timedelta(hours=1))
    st = svc.status(db, BIZ, NOW)
    assert st["use_count"] == 2 and "token" not in st and "token_hash" not in st
    assert svc.status(db, OTHER, NOW) is None


def test_public_view_is_small_and_scoped(monkeypatch):
    db = _db([_plan(key="grow", until=NOW + timedelta(days=10)), _plan(org=OTHER, key="convert", until=NOW + timedelta(days=10))])
    monkeypatch.setattr(cos, "summary", lambda d, o: {"balance_kobo": 100, "month_spend_total_kobo": 0, "low_balance_kobo": 0, "metering_enabled": True})
    monkeypatch.setattr(cos, "list_packs", lambda d: [{"id": "p1", "price_kobo": 500000, "credit_kobo": 500000, "name": "x"}])
    link = svc.resolve(db, _make(db)["token"], NOW)
    v = svc.public_view(db, link, NOW)
    assert v["business"] == "Glow Studio" and v["plan"]["label"] and v["packs"] == [{"id": "p1", "price_kobo": 500000, "credit_kobo": 500000}]
    assert set(v) == {"business", "expires_at", "plan", "credit", "renew", "packs", "min_custom_kobo", "max_order_kobo"}
    assert "team" not in str(v) and "orders" not in str(v) and OTHER not in str(v) and BIZ not in str(v)


def test_verify_only_touches_the_links_own_business(monkeypatch):
    seen = []
    monkeypatch.setattr(plans, "verify", lambda db, org, ref: seen.append(("plan", org, ref)) or {"status": "paid"})
    monkeypatch.setattr(cos, "verify", lambda db, org, ref: seen.append(("credit", org, ref)) or {"status": "paid"})
    link = {"org_id": BIZ}
    svc.verify(None, link, "cr_abc")
    svc.verify(None, link, "ap_abc")
    assert seen == [("credit", BIZ, "cr_abc"), ("plan", BIZ, "ap_abc")]


def test_renew_pays_the_plan_the_business_is_on_and_never_switches(monkeypatch):
    db = _db([_plan(key="grow", until=NOW + timedelta(days=3))])
    got = {}
    monkeypatch.setattr(plans, "checkout", lambda db, org, **kw: got.update(kw) or {"checkout_url": "https://pay", "reference": "ap_1"})
    out = svc.renew(db, {"org_id": BIZ, "payer_email": "ada@glow.test"}, "https://app/pay/t")
    assert got["key"] == "grow" and got["interval"] == "month" and got["email"] == "ada@glow.test" and got["callback_url"] == "https://app/pay/t"
    assert out == {"checkout_url": "https://pay", "reference": "ap_1"}


def test_renew_with_no_plan_is_refused():
    with pytest.raises(plans.PlanBillingError):
        svc.renew(_db(), {"org_id": BIZ}, "https://app/pay/t")


def test_public_routes_give_one_generic_404_for_bad_tokens():
    with pytest.raises(HTTPException) as e:
        router._link(_db(), "a" * 40)
    assert e.value.status_code == 404 and e.value.detail == svc.GENERIC


def test_staff_routes_need_a_manager_role():
    for role in ("owner", "admin", "ops_manager"):
        router._require_manager({"roles": {"template": role}})
    with pytest.raises(HTTPException) as e:
        router._require_manager({"roles": {"template": "sales_agent"}})
    assert e.value.status_code == 403


def test_callback_returns_to_the_same_link(monkeypatch):
    monkeypatch.setattr(router.settings, "FRONTEND_URL", "https://opsra.com.ng/")
    assert router._callback("tok") == "https://opsra.com.ng/pay/tok"
