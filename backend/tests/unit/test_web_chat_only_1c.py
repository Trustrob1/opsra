"""WEB-ONLY-1c: a web-chat-only business with no chat credit is paused; the owner is told when it is low and when it stops."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services import chat_pause_service as pause
from app.services import product_mode as pm
from tests.unit.test_account_plans_1 import FakeDB, _Q

if not hasattr(_Q, "maybe_single"):
    _Q.maybe_single = lambda self: self

ORG = "00000000-0000-0000-0000-00000000cc01"
OTHER = "00000000-0000-0000-0000-00000000cc02"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _db(mode="web_chat", balance=100_000, metering=True, low=None, **extra):
    wallet = {"org_id": ORG, "balance_kobo": balance, "metering_enabled": metering}
    if low is not None:
        wallet["low_balance_kobo"] = low
    return FakeDB(organisations=[{"id": ORG, "product_mode": mode}], credit_wallets=[wallet],
                  users=[{"id": "u1", "org_id": ORG, "email": "o@x.test", "roles": {"template": "owner"}}],
                  notifications=[], **extra)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pm.invalidate()
    monkeypatch.setattr(pause, "_plan_line", lambda db: "choose the Chioma plan")
    yield
    pm.invalidate()


@pytest.fixture
def sent(monkeypatch):
    out = []
    from app.services import site_addon_billing_service as sab
    monkeypatch.setattr(sab, "_send_email", lambda to, subject, text: out.append((to, subject, text)) or True)
    from app.services import funnel_service
    notes = []
    monkeypatch.setattr(funnel_service, "notify_managers",
                        lambda db, org, title, body, ntype, lead: (notes.append((ntype, title, body)),
                                                                   db.tables["notifications"].append({"org_id": org, "type": ntype, "created_at": NOW.isoformat()})))
    return out, notes


# -- status --------------------------------------------------------------------------------------------------------
def test_empty_wallet_on_web_chat_is_paused():
    st = pause.status(_db(balance=0), ORG)
    assert st["paused"] is True and st["low"] is False and st["chat_only"] is True


def test_positive_balance_is_not_paused():
    assert pause.is_paused(_db(balance=100), ORG) is False


def test_low_line_defaults_to_400_naira():
    assert pause.status(_db(balance=40_000), ORG)["low"] is True
    assert pause.status(_db(balance=40_001), ORG)["low"] is False


def test_wallet_low_line_overrides_default():
    assert pause.status(_db(balance=90_000, low=100_000), ORG)["low"] is True


def test_other_product_modes_are_never_paused():
    for mode in ("full", "wa_automation"):
        pm.invalidate()
        assert pause.is_paused(_db(mode=mode, balance=0), ORG) is False


def test_unmetered_wallet_is_not_paused():
    assert pause.is_paused(_db(balance=0, metering=False), ORG) is False


def test_no_wallet_is_not_paused():
    db = _db()
    db.tables["credit_wallets"] = []
    assert pause.is_paused(db, ORG) is False


def test_status_never_raises():
    class Boom:
        def table(self, *_):
            raise RuntimeError("down")
    assert pause.status(Boom(), ORG)["paused"] is False
    assert pause.status(_db(), None)["paused"] is False


# -- notices -------------------------------------------------------------------------------------------------------
def test_low_balance_sends_low_note_and_email(sent):
    out, notes = sent
    assert pause.notify_after_charge(_db(balance=30_000), ORG, NOW) == "low"
    assert notes[0][0] == "chat_credit_low" and "₦300" in notes[0][2]
    assert out and out[0][0] == "o@x.test"


def test_empty_sends_paused_note(sent):
    out, notes = sent
    assert pause.notify_after_charge(_db(balance=0), ORG, NOW) == "empty"
    assert notes[0][0] == "chat_credit_empty" and "paused" in notes[0][2]


def test_healthy_balance_sends_nothing(sent):
    out, notes = sent
    assert pause.notify_after_charge(_db(balance=500_000), ORG, NOW) is None and not notes and not out


def test_same_note_not_repeated_within_three_days(sent):
    out, notes = sent
    db = _db(balance=30_000)
    assert pause.notify_after_charge(db, ORG, NOW) == "low"
    assert pause.notify_after_charge(db, ORG, NOW + timedelta(days=2)) is None
    assert len(notes) == 1
    assert pause.notify_after_charge(db, ORG, NOW + timedelta(days=4)) == "low"


def test_empty_note_is_separate_from_low_note(sent):
    out, notes = sent
    db = _db(balance=30_000)
    pause.notify_after_charge(db, ORG, NOW)
    db.tables["credit_wallets"][0]["balance_kobo"] = 0
    assert pause.notify_after_charge(db, ORG, NOW + timedelta(hours=1)) == "empty"


def test_notice_skipped_for_non_chat_only_business(sent):
    out, notes = sent
    assert pause.notify_after_charge(_db(mode="full", balance=0), ORG, NOW) is None and not notes


def test_notice_never_raises_when_notifying_fails(monkeypatch):
    from app.services import funnel_service
    monkeypatch.setattr(funnel_service, "notify_managers", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert pause.notify_after_charge(_db(balance=0), ORG, NOW) is None


def test_plan_line_uses_pricing_never_a_hardcoded_price(monkeypatch):
    monkeypatch.undo()
    from app.services import account_entitlement_service as acc
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"chioma": {"monthly_ngn": 12000, "included_credit_ngn": 5000}}})
    assert "₦12,000" in pause._plan_line(None) and "₦5,000" in pause._plan_line(None)
    monkeypatch.setattr(acc, "plan_config", lambda db: {"tiers": {"chioma": {"monthly_ngn": 0}}})
    assert pause._plan_line(None) == "top up in Billing"


# -- the public chat routes ----------------------------------------------------------------------------------------
def test_routes_refuse_when_paused(monkeypatch):
    from fastapi import HTTPException
    from app.routers import public_webchat as r
    monkeypatch.setattr(pause, "is_paused", lambda db, org: True)
    with pytest.raises(HTTPException) as e:
        r._pause_guard(None, ORG)
    assert e.value.status_code == 503 and e.value.detail["code"] == "CHAT_PAUSED"
    monkeypatch.setattr(pause, "is_paused", lambda db, org: False)
    r._pause_guard(None, ORG)


def test_billing_credit_block_flags_pause(monkeypatch):
    from app.services import account_plan_billing_service as bill
    from app.services import credit_order_service as cos
    monkeypatch.setattr(cos, "summary", lambda db, org: {"balance_kobo": 0, "low_balance_kobo": 0, "metering_enabled": True, "month_spend_total_kobo": 0})
    db = _db(balance=0)
    blk = bill.credit_block(db, ORG, {"tiers": {}}, None, NOW)
    assert blk["chat_paused"] is True
    pm.invalidate()
    blk = bill.credit_block(_db(mode="full", balance=0), ORG, {"tiers": {}}, None, NOW)
    assert blk["chat_paused"] is False


def test_when_the_dedupe_check_fails_stay_quiet(sent):
    out, notes = sent

    class Q(FakeDB):
        def table(self, name):
            if name == "notifications":
                raise RuntimeError("down")
            return super().table(name)
    db = Q(**_db(balance=0).tables)
    assert pause.notify_after_charge(db, ORG, NOW) is None and not notes
