"""ONLY-1c-PRODUCTS: Chioma answers price and stock questions from the Products tab, as plain text, with no cards or cart."""
from __future__ import annotations

from unittest.mock import patch

from app.services import chat_signup_service as signup
from app.services import webchat_ai_service as ai
from app.services import webchat_service as wc
from tests.unit.test_webchat_3 import _cfg, _claude, _no_rate_limit, _session  # noqa: F401
from tests.unit.test_webchat_3b import ORG, _db, _shop_db


def _read_only_db():
    db = _shop_db(shop=False)
    cfg = dict(db.tables["organisations"][0]["webchat_config"])
    cfg["products_read"] = True
    db.tables["organisations"][0]["webchat_config"] = cfg
    return db


def _prompt(db, text="how much is the silk bonnet"):
    return ai.build_system_prompt(db, _session(db), _cfg(db), text)


def test_setting_is_off_by_default_and_saved_when_given():
    assert wc.DEFAULT_CONFIG["products_read"] is False
    assert wc.sanitise_config({"products_read": True})["products_read"] is True
    assert wc.sanitise_config({"products_read": 0})["products_read"] is False
    assert "products_read" not in wc.sanitise_config({"ai_enabled": True}) or wc.sanitise_config({"ai_enabled": True})["products_read"] is False


def test_read_only_prompt_lists_products_with_price_and_stock():
    p = _prompt(_read_only_db())
    assert "<products>" in p and "Silk Bonnet" in p and "N5,000" in p and "in stock" in p
    assert "<business_info> and <products>" in p


def test_read_only_prompt_has_no_card_or_cart_instructions():
    p = _prompt(_read_only_db())
    assert '"products"' not in p and "so they see product cards" not in p
    assert "cannot show product cards" in p
    assert "do not guess" in p and "handoff to true" in p


def test_nothing_listed_when_neither_setting_is_on():
    p = _prompt(_shop_db(shop=False))
    assert "<products>" not in p and "<business_info> and <products>" not in p


def test_shop_on_still_gets_cards_instruction():
    p = _prompt(_shop_db(shop=True))
    assert "so they see product cards" in p and '"products"' in p


def test_other_businesses_products_never_appear():
    p = _prompt(_read_only_db(), "other org item")
    assert "Other Org Item" not in p


def test_the_chat_never_returns_cards_for_read_only():
    from app.services import webchat_flow_service as f
    db = _read_only_db()
    s, cfg = _session(db), _cfg(db)
    with _claude('{"reply": "The Silk Bonnet is N5,000 and in stock.", "handoff": false, "products": ["p1"]}'):
        r = f.handle_message(db, s, cfg, kind="text", text="how much is the silk bonnet")
    assert r["cards"] == []
    assert [m["text"] for m in r["messages"] if m["role"] == "bot"] == ["The Silk Bonnet is N5,000 and in stock."]


def test_signup_turns_it_on_and_keeps_other_settings():
    from tests.unit.test_account_plans_1 import FakeDB
    db = FakeDB(organisations=[{"id": ORG, "webchat_config": {"greeting": "Hello"}}])
    signup._turn_on_ai(db, ORG)
    cfg = db.tables["organisations"][0]["webchat_config"]
    assert cfg["products_read"] is True and cfg["ai_enabled"] is True and cfg["greeting"] == "Hello"
