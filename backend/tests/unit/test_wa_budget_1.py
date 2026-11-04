"""WA-BUDGET-1: WhatsApp budget switch to chat, and the per-conversation web chat fee."""
from datetime import datetime, timezone

from tests.unit.test_credits_1 import ORG, _metered_db, _rule


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ledger(kind, unit, amount):
    return {"org_id": ORG, "kind": kind, "unit": unit, "amount_kobo": amount, "created_at": _now()}


class TestWaBudget:
    def test_no_budget_means_never_over(self):
        from app.services.credit_service import wa_over_budget
        assert wa_over_budget(_metered_db(credit_ledger=[_ledger("meta", "wa_marketing", -9999)]), ORG) is False

    def test_over_when_wa_spend_reaches_budget(self):
        from app.services.credit_service import wa_over_budget, month_wa_spend_kobo
        db = _metered_db(wallet={"wa_monthly_budget_kobo": 10000},
                         credit_ledger=[_ledger("meta", "wa_marketing", -7400), _ledger("fee", "fee:wa_marketing", -2600),
                                        _ledger("ai", "x", -50000)])
        assert month_wa_spend_kobo(db, ORG) == 10000   # AI spend is not WhatsApp spend
        assert wa_over_budget(db, ORG) is True

    def test_booking_fee_not_counted(self):
        from app.services.credit_service import month_wa_spend_kobo
        db = _metered_db(credit_ledger=[_ledger("fee", "fee:booking_overage", -10000)])
        assert month_wa_spend_kobo(db, ORG) == 0

    def test_keep_sending_choice_is_never_over(self):
        from app.services.credit_service import wa_over_budget
        db = _metered_db(wallet={"wa_monthly_budget_kobo": 100, "wa_over_budget_action": "continue"},
                         credit_ledger=[_ledger("meta", "wa_marketing", -9999)])
        assert wa_over_budget(db, ORG) is False

    def test_not_metered_is_never_over(self):
        from app.services.credit_service import wa_over_budget
        db = _metered_db(wallet={"metering_enabled": False, "wa_monthly_budget_kobo": 100},
                         credit_ledger=[_ledger("meta", "wa_marketing", -9999)])
        assert wa_over_budget(db, ORG) is False


class TestWebchatConversationFee:
    def test_charges_flat_fee_once_per_session_ref(self):
        from app.services.credit_service import meter_webchat_conversation
        db = _metered_db(automation_fee_rules=[_rule(event_type="webchat_conversation", value=2000)])
        assert meter_webchat_conversation(db, ORG, "sess1") == 2000
        assert db.rpcs[0][1]["p_ref"] == "fee:wc:sess1" and db.rpcs[0][1]["p_kind"] == "fee"

    def test_no_rule_no_charge(self):
        from app.services.credit_service import meter_webchat_conversation
        assert meter_webchat_conversation(_metered_db(automation_fee_rules=[]), ORG, "s") == 0


class TestMarketingPause:
    def _db(self, category, spent=9999):
        return _metered_db(wallet={"wa_monthly_budget_kobo": 100},
                           credit_ledger=[_ledger("meta", "wa_marketing", -spent)],
                           whatsapp_templates=[{"org_id": ORG, "name": "promo", "category": category}])

    def test_marketing_template_paused_when_over(self):
        from app.services.credit_service import marketing_paused
        assert marketing_paused(self._db("MARKETING"), ORG, "promo") is True

    def test_utility_template_still_allowed(self):
        from app.services.credit_service import marketing_paused
        assert marketing_paused(self._db("UTILITY"), ORG, "promo") is False

    def test_not_paused_under_budget(self):
        from app.services.credit_service import marketing_paused
        assert marketing_paused(self._db("MARKETING", spent=10), ORG, "promo") is False


class TestSetBudget:
    def test_rejects_bad_action(self):
        import pytest
        from app.services.credit_service import set_wa_budget
        with pytest.raises(ValueError):
            set_wa_budget(_metered_db(), ORG, 5000, "stop")
