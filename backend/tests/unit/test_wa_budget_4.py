"""WA-BUDGET-4: an empty credit balance also switches WhatsApp customers to web chat (when 'chat' is chosen)."""
from tests.unit.test_credits_1 import ORG, _metered_db


def test_empty_balance_switches_without_a_budget():
    from app.services.credit_service import wa_over_budget
    assert wa_over_budget(_metered_db(wallet={"balance_kobo": 0}), ORG) is True
    assert wa_over_budget(_metered_db(wallet={"balance_kobo": -500}), ORG) is True


def test_money_left_and_no_budget_does_not_switch():
    from app.services.credit_service import wa_over_budget
    assert wa_over_budget(_metered_db(wallet={"balance_kobo": 1}), ORG) is False


def test_keep_sending_choice_ignores_empty_balance():
    from app.services.credit_service import wa_over_budget
    assert wa_over_budget(_metered_db(wallet={"balance_kobo": 0, "wa_over_budget_action": "continue"}), ORG) is False


def test_not_metered_ignores_empty_balance():
    from app.services.credit_service import wa_over_budget
    assert wa_over_budget(_metered_db(wallet={"balance_kobo": 0, "metering_enabled": False}), ORG) is False


def test_out_of_credit_helper():
    from app.services.credit_service import out_of_credit
    assert out_of_credit({"metering_enabled": True, "balance_kobo": 0}) is True
    assert out_of_credit({"metering_enabled": True, "balance_kobo": 10}) is False
    assert out_of_credit({"metering_enabled": False, "balance_kobo": 0}) is False
    assert out_of_credit(None) is False
