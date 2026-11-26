"""STORE-CHIOMA-1: with Chioma on, the storefront shows Buy now / Speak to Chioma (no WhatsApp order button)."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SF = os.path.join(ROOT, "frontend", "src", "catalog", "storefront")


def _r(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def test_item_page_swaps_whatsapp_for_chioma():
    s = _r(SF, "StorefrontItemPage.jsx")
    assert "chiomaChat" in s and "askChioma({ action: 'buy'" in s and "Speak to Chioma" in s
    assert "chioma ? (" in s                                   # the chioma branch comes before the cart / WhatsApp branches
    assert s.index("chioma ? (") < s.index(") : cartOn ? (")
    assert "const chiomaShop = chioma && !!chiomaChat.shop && !catalogConfig?.price_on_request" in s   # no Buy now when prices are on request


def test_list_page_has_card_buttons_banner_and_help():
    s = _r(SF, "StorefrontListPage.jsx")
    assert "const quick = chioma ? null" in s                 # the storefront's own quick-add is hidden
    for w in ("Buy now", "Choose size", "Ask Chioma", "Need help choosing", "Speak to Chioma"):   # STOREFRONT-3 renamed the help banner
        assert w in s, w
    assert "(waHelp || chioma)" in s


def test_shell_only_passes_chioma_for_storefront_template():
    s = _r(SF, "..", "PublicCatalogShell.jsx")
    assert "const chiomaChat = catalogData.template === 'storefront' && canShowChat(catalogData.chat) ? catalogData.chat : null" in s
    assert s.count("chiomaChat={chiomaChat}") == 2


def test_chat_page_buy_is_checked_by_the_server_cart():
    s = _r(ROOT, "frontend", "src", "pages", "WebChatPage.jsx")
    assert "runBuy" in s and "changeChatCart" in s and "setPanel('cart')" in s
