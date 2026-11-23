"""BASIC-Q-1: a basic question about the product being viewed is answered from the catalogue text, not turned into a team hand-over."""
from unittest.mock import patch

from tests.unit.test_webchat_3 import _db, _session, _cfg, _no_rate_limit, ORG  # noqa: F401
from app.services import webchat_flow_service as f
from app.services import webchat_shop_service as shop
from app.services import webchat_ai_service as ai

HANDOFF = {"reply": "A team member will reply.", "handoff": True, "products": [], "offer_team": False}


def _setup(**cfg_over):
    db = _db(answer_first=True)
    s, cfg = _session(db, contact=False), _cfg(db)
    cfg.update({"ai_enabled": True, "shop_enabled": True, "contact_in_chat": True, **cfg_over})
    return db, s, cfg


def test_handoff_with_a_viewed_product_answers_from_its_text_and_asks_for_nothing():
    db, s, cfg = _setup()
    with patch.object(ai, "answer", return_value=HANDOFF), patch.object(shop, "product_answer", return_value="Here is what we have on Black: organic latex."):
        r = f.handle_message(db, s, cfg, kind="text", text="what is it made up of?")
    texts = [m["text"] for m in r["messages"]]
    assert "Here is what we have on Black: organic latex." in texts and "A team member will reply." not in texts
    assert not r.get("contact_step") and r["human"] is False and not s["state"].get("human")


def test_handoff_without_a_product_text_still_calls_the_team():
    db, s, cfg = _setup()
    with patch.object(ai, "answer", return_value=HANDOFF), patch.object(shop, "product_answer", return_value=None):
        r = f.handle_message(db, s, cfg, kind="text", text="do you deliver to Abuja?")
    assert r["human"] is True and r.get("contact_step") == "name"


def test_no_shop_and_no_products_read_keeps_the_old_hand_over():
    db, s, cfg = _setup(shop_enabled=False, products_read=False)
    with patch.object(ai, "answer", return_value=HANDOFF), patch.object(shop, "product_answer", return_value="X") as pa:
        r = f.handle_message(db, s, cfg, kind="text", text="what is it made up of?")
    assert not pa.called and r["human"] is True
