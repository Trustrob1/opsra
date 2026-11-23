"""ORDER-CONFIRM-1: owner can have a team member confirm stock before payment; checkout continues after the contact questions."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import webchat_service as wc
from app.services import webchat_flow_service as flow
from app.services import webchat_shop_service as shop
from tests.unit.test_webchat_3b import ORG, _cfg, _session, _shop_db


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch.object(wc, "rate_limited", return_value=False):
        yield


def _cart(db):
    s = _session(db)
    shop.add(db, s, "p1", None)
    return s


def test_config_defaults_and_sanitising():
    assert wc.DEFAULT_CONFIG["order_mode"] == "link"
    assert wc.sanitise_config({"order_mode": "team"})["order_mode"] == "team"
    assert wc.sanitise_config({"order_mode": "weird"})["order_mode"] == "link"
    assert wc.sanitise_config({"payment_instructions": "GTB 0123456789"})["payment_instructions"] == "GTB 0123456789"


def test_team_mode_holds_the_order_and_never_makes_a_link():
    db = _shop_db(); s = _cart(db)
    cfg = {**_cfg(db), "order_mode": "team", "payment_instructions": "GTB 0123456789 Royal Rest"}
    with patch("app.services.paystack_storefront_service.generate_payment_link") as gen, \
         patch("app.services.webchat_service.notify_managers") as nm, patch("app.services.lead_service.write_timeline_event"):
        res = shop.checkout(db, s, cfg)
    gen.assert_not_called()
    assert res["human"] is True and res["held"] is True and res["cart"]["count"] == 0
    assert s["state"]["pending_order"]["status"] == "awaiting_stock"
    bot = res["messages"][-1]["body"] if "body" in res["messages"][-1] else str(res["messages"][-1])
    assert "confirming that everything is in stock" in bot and "receipt" in bot
    assert "GTB 0123456789" in nm.call_args[0][3]                      # the saved bank details reach the team, not the customer
    assert "GTB 0123456789" not in bot
    assert len([r for r in db.rows("webchat_events") if r["kind"] == "order"]) == 1


def test_link_mode_without_paystack_also_holds_for_the_team():
    db = _shop_db(); s = _cart(db)
    with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=RuntimeError("no keys")), \
         patch("app.services.webchat_service.notify_managers"), patch("app.services.lead_service.write_timeline_event"):
        res = shop.checkout(db, s, _cfg(db))
    assert res["held"] is True and s["state"]["pending_order"]["total"] > 0


def test_link_mode_with_paystack_is_unchanged():
    db = _shop_db(); s = _cart(db)
    with patch("app.services.paystack_storefront_service.generate_payment_link",
               return_value={"checkout_url": "https://p.test/x", "reference": "r1", "payment_link_id": "pl"}), \
         patch("app.services.lead_service.write_timeline_event"), patch("app.services.webchat_service.notify_managers"):
        res = shop.checkout(db, s, _cfg(db))
    assert res.get("checkout_url") == "https://p.test/x" and not res.get("held")


def test_details_asked_for_checkout_carry_on_to_checkout():
    db = _shop_db(); s = _cart(db)
    s["state"]["contact_resume"] = "checkout"
    cfg = {**_cfg(db), "order_mode": "team"}
    with patch.object(wc, "validate_contact", return_value=({"name": "Jake", "phone": "+2348000000000"}, None)), \
         patch.object(wc, "save_contact", return_value=s), patch("app.services.webchat_service.notify_managers"), \
         patch("app.services.lead_service.write_timeline_event"):
        s["lead_id"] = "lead-1"
        res = flow.handle_contact(db, s, cfg, name="Jake", phone="+2348000000000", email=None, consent=True)
    assert res["cart"]["count"] == 0 and res["human"] is True
    assert s["state"].get("pending_order")


def test_details_not_asked_for_checkout_do_not_start_one():
    db = _shop_db(); s = _cart(db)
    with patch.object(wc, "validate_contact", return_value=({"name": "Jake", "phone": "+2348000000000"}, None)), \
         patch.object(wc, "save_contact", return_value=s):
        res = flow.handle_contact(db, s, _cfg(db), name="Jake", phone="+2348000000000", email=None, consent=True)
    assert "cart" not in res and not (s["state"].get("pending_order"))


def test_static_wiring():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    c = (root / "services" / "webchat_contact_service.py").read_text(encoding="utf-8")
    assert 'contact_resume=("checkout" if why == "checkout" else "")' in c
    r = (root / "routers" / "public_webchat.py").read_text(encoding="utf-8")
    assert 'if po and kind in ("image", "document"):' in r
    assert "We received your payment receipt" in r


def test_frontend_wiring():
    import pathlib
    fe = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"
    page = (fe / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")
    assert "if (res.cart) { setCart(res.cart); setPanel(null); setCards([]) }" in page
    st = (fe / "modules" / "admin" / "WebChatSettings.jsx").read_text(encoding="utf-8")
    assert "set('order_mode', 'team')" in st and "set('order_mode', 'link')" in st
    assert "set('payment_instructions', e.target.value)" in st
    assert "{cfg.shop_enabled && (\n        <div style={card}>\n          <strong style={{ fontSize: 14, color: ds.dark }}>When a customer checks out" in st
