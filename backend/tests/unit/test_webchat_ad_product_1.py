"""AD-PRODUCT-1: an ad can be about one catalogue product. The chat knows the product, shows its card, and a shortcut answers for it."""
from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from app.routers import public_webchat as pub
from app.services import webchat_flow_service as flow
from app.services import webchat_service as wc
from app.services import webchat_shop_service as shop
from tests.unit.test_webchat_3b import _cfg, _session, _shop_db

FE = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"

MENU = [
    {"id": "firm", "label": "Soft or firm?", "answer": "It is both."},
    {"id": "delivery", "label": "Delivery and shipping", "answer": "We deliver in 2 days."},
    {"id": "prices", "label": "Prices", "answer": "See the shop."},
    {"id": "human", "label": "Talk to the team", "action": "human"},
]
SHORTCUTS = [{"id": "firm", "label": "Soft or firm?", "answer": ""}, {"id": "delivery", "label": "", "answer": ""}, {"id": "prices", "label": "", "answer": ""}]


@pytest.fixture(autouse=True)
def _quiet():
    with patch.object(wc, "rate_limited", return_value=False):
        yield


def _setup(product="p1", shop_on=True, shortcuts=None, source="elite"):
    db = _shop_db(shop=shop_on)
    s = _session(db)
    s["source"] = source
    camp = {"tag": "elite", "label": "Elite", "main": "shop" if shop_on else "prices", "product": product,
            "shortcuts": SHORTCUTS if shortcuts is None else shortcuts}
    cfg = {**_cfg(db), "shop_enabled": shop_on, "menu": MENU, "campaigns": wc.clean_campaigns([camp])}
    return db, s, cfg


def _tap(db, s, cfg, menu_id):
    return flow.handle_message(db, s, cfg, kind="menu", menu_id=menu_id, text=None)


def _bot(res):
    return [m for m in res["messages"] if m["role"] == "bot"][-1]["text"]


def test_campaign_keeps_a_good_product_id_and_the_per_ad_answers():
    c = wc.clean_campaigns([{"tag": "t", "main": "shop", "product": " p1 ", "shortcuts": [{"id": "firm", "answer": "Medium firm." + "x" * 700}]}])[0]
    assert c["product"] == "p1" and c["shortcuts"][0]["answer"].startswith("Medium firm.") and len(c["shortcuts"][0]["answer"]) == 600
    assert wc.clean_campaigns([{"tag": "t", "product": "bad id!"}])[0]["product"] == ""
    assert wc.clean_campaigns([{"tag": "t"}])[0]["product"] == ""
    assert wc.sanitise_config({"campaigns": [{"tag": "t", "main": "shop", "product": "p1"}]})["campaigns"][0]["product"] == "p1"


def test_ad_product_remembers_the_product_and_returns_its_card():
    db, s, cfg = _setup()
    card = shop.ad_product(db, s, cfg)
    assert card["id"] == "p1" and card["title"] == "Silk Bonnet" and card["price"] == 5000
    assert s["state"]["viewing"] == "p1" and s["state"]["viewing_title"] == "Silk Bonnet"


def test_ad_product_ignores_unknown_other_business_and_ad_without_product():
    for pid in ("nope", "other", ""):
        db, s, cfg = _setup(product=pid)
        assert shop.ad_product(db, s, cfg) is None
        assert "viewing" not in s["state"]
    db, s, cfg = _setup(source="link")                            # a visitor who did not come from the ad
    assert shop.ad_product(db, s, cfg) is None and "viewing" not in s["state"]


def test_shop_off_still_knows_the_product_but_shows_no_card():
    db, s, cfg = _setup(shop_on=False)
    assert shop.ad_product(db, s, cfg) is None
    assert s["state"]["viewing"] == "p1"


def test_out_of_stock_product_shows_no_card():
    db, s, cfg = _setup()
    for p in db.tables["products"]:
        if p["id"] == "p1":
            p["available"] = False
    assert shop.ad_product(db, s, cfg) is None
    assert s["state"]["viewing"] == "p1"


def test_shortcut_uses_the_owners_answer_for_this_ad_when_there_is_one():
    db, s, cfg = _setup(shortcuts=[{"id": "firm", "label": "Soft or firm?", "answer": "The Silk Bonnet is one size."}, {"id": "delivery", "label": "", "answer": ""}])
    res = _tap(db, s, cfg, "firm")
    assert _bot(res) == "The Silk Bonnet is one size."
    assert "About the" not in _bot(res) and "It is both." not in _bot(res)


def test_shortcut_without_its_own_answer_gives_the_general_answer_then_a_catalogue_line():
    db, s, cfg = _setup()
    text = _bot(_tap(db, s, cfg, "firm"))
    assert text.startswith("It is both.")
    assert "About the Silk Bonnet:" in text and "Soft silk bonnet" in text and "₦5,000" in text and "In stock" in text


def test_an_ad_with_no_product_gives_only_the_general_answer():
    db, s, cfg = _setup(product="")
    assert _bot(_tap(db, s, cfg, "firm")) == "It is both."


def test_buttons_under_the_answer_are_the_ads_other_shortcuts_then_see_other_products_and_more_options():
    db, s, cfg = _setup()
    ch = _tap(db, s, cfg, "firm")["choices"]
    assert [c.get("menu_id") for c in ch[:2]] == ["delivery", "prices"]
    assert [(c["id"], c["label"]) for c in ch[2:]] == [("shop", "See other products"), ("menu", "More options")]


def test_no_see_other_products_button_when_the_shop_is_off():
    db, s, cfg = _setup(shop_on=False)
    ch = _tap(db, s, cfg, "firm")["choices"]
    assert [c["id"] for c in ch] == ["item", "menu"] and ch[0]["menu_id"] == "delivery"          # Prices is this ad's main button here, so not repeated


def test_a_chat_that_did_not_come_from_the_ad_is_unchanged():
    db, s, cfg = _setup(source="link")
    res = _tap(db, s, cfg, "firm")
    assert _bot(res) == "It is both."
    assert not any(c["id"] == "shop" for c in res.get("choices") or [])


def test_a_menu_button_that_is_not_one_of_the_ads_shortcuts_keeps_the_normal_flow():
    db, s, cfg = _setup(shortcuts=[{"id": "delivery", "label": "", "answer": ""}])
    res = _tap(db, s, cfg, "firm")
    assert _bot(res) == "It is both."


def test_snapshot_carries_the_ad_product_card():
    db, s, cfg = _setup()
    card = shop.ad_product(db, s, cfg)
    assert pub._snapshot(s, cfg, [], card)["ad_product"] == card
    assert pub._snapshot(s, cfg, [])["ad_product"] is None


def test_staff_product_list_endpoint_exists():
    r = (pathlib.Path(__file__).resolve().parents[2] / "app" / "routers" / "webchat.py").read_text(encoding="utf-8")
    assert '@router.get("/webchat/products")' in r


def test_frontend_wiring():
    p = (FE / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "setAdProduct(snap.ad_product || null)" in p
    assert "{adProduct && !visitorSpoke && !panel && !contactStep && (" in p
    assert "pairOpening.main.kind !== 'shop' && <button" in p and ">See other products</button>" in p
    assert "call: openCall, shop: openShop }" in p
    assert "'say', 'shop'" in (FE / "utils" / "webchatChoices.js").read_text(encoding="utf-8")
    a = (FE / "modules" / "admin" / "WebChatAdLinks.jsx").read_text(encoding="utf-8")
    assert "Product this ad is about (optional)" in a and "getWebchatProducts().then(" in a
    assert "Answer to ${m.label} for this ad" in a and "maxLength={600}" in a
    assert "api.get('/api/v1/webchat/products')" in (FE / "services" / "webchat.service.js").read_text(encoding="utf-8")
