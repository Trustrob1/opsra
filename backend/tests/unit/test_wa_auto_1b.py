"""WA-AUTO-1b: the Automate plan - priced in Superadmin settings, offered only to WhatsApp-automation-only businesses."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import account_plan_billing_service as bill
from app.services import product_mode as pm
from app.services import site_entitlement_service as ent
from app.services import site_feature_registry as reg
from tests.unit.test_account_plans_1 import FakeDB

ORG_WA = "00000000-0000-0000-0000-00000000aa01"
ORG_FULL = "00000000-0000-0000-0000-00000000aa02"
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    pm.invalidate()
    yield
    pm.invalidate()


def _db():
    return FakeDB(organisations=[{"id": ORG_WA, "product_mode": "wa_automation"}, {"id": ORG_FULL, "product_mode": "full"}],
                  org_plan_orders=[])


def _cfg(automate_price=0, **extra):
    return ent.get_config({"pricing": {"tiers": {"automate": {"monthly_ngn": automate_price, **extra},
                                                 "capture": {"monthly_ngn": 15000}}}})


def test_automate_tier_exists_with_no_hardcoded_price():
    t = _cfg()["tiers"]["automate"]
    assert t["label"] == "Automate" and t["monthly_ngn"] == 0 and t["sellable"] is False
    assert t["wa_only"] is True
    assert t["caps"] == {"ai_messages": 300, "users_included": 1}
    assert t["recommended"] == {"monthly_ngn": 20000, "ai_messages": 300, "users_included": 1}
    assert set(t["features"]) == {"wa_leads", "wa_menu", "ai_assistant", "own_wa_number", "webchat_basic"}


def test_price_and_caps_come_from_settings():
    t = _cfg(25000, caps={"ai_messages": 500, "users_included": 2})["tiers"]["automate"]
    assert t["monthly_ngn"] == 25000 and t["sellable"] is True
    assert t["caps"] == {"ai_messages": 500, "users_included": 2}


def test_other_tiers_are_not_wa_only_and_have_no_hint():
    for k in ("capture", "convert", "grow"):
        t = _cfg()["tiers"][k]
        assert t["wa_only"] is False and t["recommended"] is None


def test_validate_pricing_accepts_automate_and_rejects_unknown_tier():
    ent.validate_pricing({"tiers": {"automate": {"monthly_ngn": 20000, "caps": {"users_included": 1}}}})
    with pytest.raises(ent.EntitlementError):
        ent.validate_pricing({"tiers": {"platinum": {"monthly_ngn": 1}}})


def test_wa_org_can_only_buy_automate():
    cfg, db = _cfg(20000), _db()
    qt = bill.quote_for(db, ORG_WA, cfg, "automate", NOW)
    assert qt["price"] == 20000 and qt["kind"] == "new"
    with pytest.raises(bill.PlanBillingError):
        bill.quote_for(db, ORG_WA, cfg, "capture", NOW)


def test_full_org_can_never_buy_automate():
    cfg, db = _cfg(20000), _db()
    with pytest.raises(bill.PlanBillingError):
        bill.quote_for(db, ORG_FULL, cfg, "automate", NOW)
    assert bill.quote_for(db, ORG_FULL, cfg, "capture", NOW)["price"] == 15000


def test_automate_is_not_for_sale_until_a_price_is_set():
    with pytest.raises(bill.PlanBillingError):
        bill.quote_for(_db(), ORG_WA, _cfg(0), "automate", NOW)


def test_sites_never_offer_automate():
    import inspect
    from app.routers import builder_portal
    assert 'not d.get("wa_only")' in inspect.getsource(builder_portal)
