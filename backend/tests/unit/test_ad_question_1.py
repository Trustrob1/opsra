"""AD-Q-1: the preset questions on a click-to-WhatsApp ad are routed by what was asked."""
import pytest

from app.services import ad_question_service as adq

RULES = [
    {"question": "What sizes do you have and the prices?", "action": "bot_catalog", "reply": "Prices from..."},
    {"question": "If I order today, when will I get it?", "action": "rep", "reply": "Thanks"},
]


def test_match_ignores_case_punctuation_and_spacing():
    assert adq.match(RULES, "what sizes do you have and the prices")["action"] == "bot_catalog"
    assert adq.match(RULES, "  If I order today,   when will I get it?? ")["action"] == "rep"


def test_no_match_falls_through():
    assert adq.match(RULES, "How much is the Cloud Mattress?") is None
    assert adq.match(RULES, "") is None and adq.match([], "x") is None and adq.match(None, "x") is None


def test_clean_rules_accepts_and_trims():
    out = adq.clean_rules([{"question": " Q1? ", "action": "rep", "reply": " hi "}, {"question": "", "action": "rep"}])
    assert out == [{"question": "Q1?", "action": "rep", "reply": "hi"}]
    assert adq.clean_rules(None) == []


@pytest.mark.parametrize("bad", [
    [{"question": "Q", "action": "bogus"}],
    [{"question": "x" * 201, "action": "rep"}],
    [{"question": "Q", "action": "rep", "reply": "y" * 1001}],
    [{"question": f"Q{i}", "action": "rep"} for i in range(11)],
    "not a list",
])
def test_clean_rules_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        adq.clean_rules(bad)
