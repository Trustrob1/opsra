"""WA-PRICE-GUARD-1: the WhatsApp AI must not answer a price complaint with something cheaper (smaller size, lower variant, cheaper product)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import ai_price_guard as pg

CAT = [
    {"id": "p-elite", "title": "Premium Organic Mattress - Elite Cool", "price": 1100000,
     "variants": [{"id": "v-67", "label": "6x7", "price": 1100000}, {"id": "v-66", "label": "6x6", "price": 950000}, {"id": "v-single", "label": "Single", "price": 600000}]},
    {"id": "p-hybrid", "title": "Luxury Hybrid Royal Rest Black", "price": 565000, "variants": []},
    {"id": "p-cloud", "title": "Cloud Mattress", "price": 485000, "variants": []},
]
ORG = "11111111-1111-1111-1111-111111111111"


def _act(msg, action="respond", **data):
    return {"action": action, "message": msg, "data": data}


# ── detection ──
@pytest.mark.parametrize("text", ["That 1m plus is high for me", "it is too expensive", "do you have a cheaper one?", "Can you reduce the price",
                                  "my budget is small", "last price please", "I can't afford it", "any discount?"])
def test_price_complaints_are_recognised(text):
    assert pg.is_price_complaint(text)


@pytest.mark.parametrize("text", ["what size is the king", "how long is delivery", "do you have a smaller one", "what else is good for back pain"])
def test_other_questions_are_not_price_complaints(text):
    assert not pg.is_price_complaint(text)


def test_model_labelling_the_objection_as_price_counts():
    assert pg.is_price_complaint("hmm okay", {"objection_type": "price"})


# ── what an item is ──
def test_product_found_by_its_distinctive_words():
    assert pg.mentioned_prices("apart from this Elite cool 6/7 mattress", CAT) == [1100000]
    assert pg.mentioned_prices("the Luxury Hybrid Royal Rest Black at 565,000", CAT) == [565000]
    assert pg.mentioned_prices("a mattress please", CAT) == []          # generic words alone name nothing


def test_variant_found_by_its_label_only_as_a_whole_word():
    assert 600000 in pg.mentioned_prices("the Single size", CAT)
    assert pg.mentioned_prices("a singleton", CAT) == []


# ── the guard ──
def test_screenshot_case_is_handed_to_the_team():
    """Customer on Elite Cool says 1m+ is high; the AI offers Hybrid (565k) and the Cloud (485k) as the budget option."""
    reply = _act("Next is the Luxury Hybrid Royal Rest Black at 565,000. We also have the Cloud Mattress (485,000) if you want something more budget-friendly.")
    out = pg.check("Please apart from this Elite cool 6/7 mattress which one comes next for back pain. That 1m plus is high for me", reply, None, [], CAT)
    assert out and out["action"] == "escalate" and out["data"]["reason"] == "price_objection"


def test_smaller_size_of_the_same_mattress_is_blocked():
    history = [{"role": "user", "content": "I want the Elite Cool 6x7"}, {"role": "assistant", "content": "Great choice"}]
    reply = _act("The Elite Cool in Single is 600,000", "recommend_product", product_id="p-elite", variant_id="v-single")
    out = pg.check("that is too expensive", reply, None, history, CAT)
    assert out and out["data"]["reason"] == "price_objection"


def test_variant_chosen_in_data_is_checked_even_if_the_text_names_nothing():
    reply = _act("Here you go", "recommend_product", product_id="p-elite", variant_id="v-66")
    assert pg.check("too expensive", reply, 1100000, [], CAT)


def test_value_reframe_on_the_same_item_passes():
    reply = _act("The Elite Cool 6x7 has pocket coils and a 10-year warranty, which is why it holds up so well.")
    assert pg.check("the Elite Cool 6x7 is too expensive", reply, None, [], CAT) is None


def test_saved_anchor_is_used_when_this_message_names_nothing():
    reply = _act("Try the Cloud Mattress at 485,000")
    assert pg.check("it is too expensive", reply, 1100000, [], CAT)
    assert pg.check("it is too expensive", reply, None, [], CAT) is None      # no anchor anywhere -> prompt rule only


def test_no_complaint_no_block():
    reply = _act("The Single is 600,000", "recommend_product", product_id="p-elite", variant_id="v-single")
    assert pg.check("do you have a smaller one", reply, 1100000, [], CAT) is None


def test_already_escalating_is_left_alone():
    assert pg.check("too expensive", _act("Let me get our team", "escalate", reason="x"), 1100000, [], CAT) is None


def test_a_dearer_alternative_is_fine():
    reply = _act("The Hybrid at 565,000 is firmer", "recommend_product", product_id="p-hybrid")
    assert pg.check("that is too expensive", reply, 400000, [], CAT) is None


def test_anchor_is_not_lowered_by_a_complaint_turn():
    assert pg.next_anchor("too expensive", _act("ok", "recommend_product", product_id="p-cloud"), 1100000, CAT) == 1100000
    assert pg.next_anchor("tell me about Cloud Mattress", _act("ok"), 1100000, CAT) == 485000
    assert pg.next_anchor("hi", _act("ok", "recommend_product", product_id="p-hybrid"), None, CAT) == 565000


# ── the prompt ──
def test_prompt_carries_the_rule():
    from app.services.ai_agent_service import build_agent_system_prompt
    import inspect
    src = inspect.getsource(build_agent_system_prompt)
    assert "PRICE COMPLAINTS" in src and "price_objection" in src and "NEVER" in src


# ── wired into the turn ──
def _chain(data):
    c = MagicMock()
    for m in ("select", "eq", "in_", "limit", "order", "maybe_single", "insert", "update", "gte", "is_", "neq"):
        getattr(c, m).return_value = c
    c.execute.return_value = MagicMock(data=data)
    return c


def _turn(inbound, model_reply, session_data=None, history=None):
    from app.services.ai_agent_service import run_agent_turn
    db = MagicMock()
    db.table.side_effect = lambda name: _chain({"name": "Royal Rest", "ai_agent_config": {}, "commerce_config": {}} if name == "organisations" else [])
    session = {"id": "s1", "phone_number": "+2348000000000", "session_data": dict(session_data or {}), "conversation_history": list(history or [])}
    with patch("app.services.ai_agent_service._fetch_catalog_products", return_value=CAT), \
         patch("app.services.ai_agent_service.call_claude", return_value=json.dumps(model_reply)):
        return run_agent_turn(db, ORG, session, {"id": "l1"}, inbound), session, db


def test_turn_replaces_a_downgrade_with_a_handover():
    out, session, _ = _turn("That 1m plus Elite cool is high for me",
                            {"action": "respond", "message": "Try the Cloud Mattress (485,000), more budget-friendly", "data": {}})
    assert out["action"] == "escalate" and out["data"]["reason"] == "price_objection"
    assert "Cloud" not in out["message"]


def test_turn_remembers_what_the_customer_was_looking_at():
    out, session, _ = _turn("tell me about the Elite Cool 6x7", {"action": "respond", "message": "It is a great mattress", "data": {}},
                            session_data={"seen": True})
    assert out["action"] == "respond"
    assert session["session_data"]["price_anchor"] == 1100000


# ── web chat (Chioma) ──
WEB_CAT = [{"id": "p-elite", "title": "Premium Organic Mattress - Elite Cool", "price": 1100000, "in_stock": True, "blurb": "pocket coils"},
           {"id": "p-cloud", "title": "Cloud Mattress", "price": 485000, "in_stock": True, "blurb": ""}]


def test_chat_check_blocks_a_cheaper_card_for_the_viewed_product():
    assert pg.check_chat("this is too expensive", "Have a look at this one", ["p-cloud"], "p-elite", "", WEB_CAT)


def test_chat_check_blocks_a_cheaper_product_named_in_the_reply():
    assert pg.check_chat("too expensive for me", "The Cloud Mattress is more budget-friendly", [], "p-elite", "", WEB_CAT)


def test_chat_check_allows_value_talk_and_dearer_items():
    assert not pg.check_chat("too expensive", "The Elite Cool has pocket coils for lasting support.", ["p-elite"], "p-elite", "", WEB_CAT)
    assert not pg.check_chat("what else do you have", "The Cloud Mattress is another option", ["p-cloud"], "p-elite", "", WEB_CAT)


def test_chat_check_without_an_anchor_does_not_block():
    assert not pg.check_chat("too expensive", "Try the Cloud Mattress", [], None, "", WEB_CAT)


def test_chat_check_uses_earlier_conversation_when_nothing_is_being_viewed():
    assert pg.check_chat("it is too expensive", "Try the Cloud Mattress", [], None, "visitor: tell me about the Elite Cool", WEB_CAT)


def test_chioma_prompt_carries_the_rule():
    import inspect
    from app.services import webchat_ai_service as ai
    src = inspect.getsource(ai.build_system_prompt)
    assert "NEVER suggest a smaller size" in src and "offer_team" in src


def _chioma(visitor, raw_reply, viewing="p-elite"):
    from app.services import webchat_ai_service as ai
    from app.services import ai_service, credit_service, webchat_service as wc
    s = {"id": "s1", "org_id": ORG, "state": {"viewing": viewing}}

    def _prompt(db, sess, cfg, text):
        sess["_price_catalog"] = WEB_CAT
        return "stable" + ai_service.CACHE_SPLIT + "Elite Cool N1,100,000 Cloud Mattress N485,000"

    with patch.object(ai, "can_use_ai", return_value=(True, "")), patch.object(ai, "build_system_prompt", side_effect=_prompt), \
         patch.object(ai, "_history", return_value=""), patch.object(ai_service, "call_claude", return_value=json.dumps(raw_reply)), \
         patch.object(credit_service, "get_ai_level", return_value="ok"), patch("app.services.webchat_plan_service.use_ai_allowance", return_value=True), \
         patch.object(wc, "set_state"):
        return ai.answer(MagicMock(), s, {"ai_enabled": True, "shop_enabled": True, "business_name": "Royal Rest"}, visitor)


def test_chioma_downgrade_becomes_an_offer_to_pass_to_the_team():
    out = _chioma("this is too expensive", {"reply": "The Cloud Mattress is more budget-friendly", "handoff": False, "offer_team": False, "products": ["p-cloud"]})
    assert out["offer_team"] is True and out["handoff"] is False and "Cloud" not in out["reply"] and not out.get("products")


def test_chioma_normal_answer_is_untouched():
    out = _chioma("how much is it", {"reply": "The Elite Cool is N1,100,000.", "handoff": False, "offer_team": False})
    assert "1,100,000" in out["reply"]
