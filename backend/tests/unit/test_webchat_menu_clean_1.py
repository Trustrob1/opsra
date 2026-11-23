"""MENU-CLEAN-1: one list in the shop menu, Call us under Need a person, one close button, rows never squashed."""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src" / "pages" / "WebChatPage.jsx").read_text(encoding="utf-8")


def test_all_products_is_the_first_row_of_the_owner_list():
    assert "{panel === 'menu' && (cfg.shop_enabled || cfg.menu.some((m) => m.id !== humanItem?.id)) && (" in SRC
    assert "<span style={{ flex: 1 }}>All products</span>" in SRC
    assert "borderTop: (n || cfg.shop_enabled) ?" in SRC


def test_old_separate_shop_block_is_gone():
    assert "{panel === 'menu' && cfg.shop_enabled && (" not in SRC


def test_call_us_sits_under_need_a_person():
    assert "{panel === 'menu' && (humanItem || (cfg.shop_enabled && call)) && (" in SRC


def test_sheet_close_button_hidden_for_the_menu():
    assert "{panel !== 'menu' && (" in SRC


def test_menu_blocks_do_not_shrink():
    assert SRC.count("flex: 'none'") >= 2
    assert "flexDirection: 'column', flex: 'none', border:" in SRC
