"""SHOP-A-1: fewer buttons in a shop chat. Static checks of WebChatPage.jsx (no browser here)."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = open(os.path.join(ROOT, "frontend", "src", "pages", "WebChatPage.jsx"), encoding="utf-8").read()


def test_the_shop_and_cart_row_is_gone_from_the_dock():
    dock = SRC[SRC.index("<div style={S.dock}>"):SRC.index("{rec ? (")]
    assert "openShop" not in dock and "Cart (" not in dock


def test_cart_icon_only_when_something_is_in_the_cart():
    assert "{cfg.shop_enabled && cart.count > 0 && (" in SRC and "Open your cart," in SRC


def test_phone_moves_into_the_menu_in_shop_mode():
    assert "{call && !cfg.shop_enabled && (" in SRC
    assert "[['All products', openShop, 'bag'], ...(call ? [['Call us', openCall, 'phone']] : [])]" in SRC


def test_all_products_chip_and_added_notice():
    assert ">All products</button>}" in SRC
    assert "added.at === messages.length" in SRC and ">View cart</button>" in SRC and ">Keep shopping</button>" in SRC


def test_placeholder_asks_chioma_until_a_person_takes_over():
    assert "human ? 'Type your message' : 'Type to ask Chioma'" in SRC
