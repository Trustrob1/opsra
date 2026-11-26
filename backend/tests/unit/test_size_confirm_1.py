"""SIZE-CONFIRM-1: Chioma reads sizes the way visitors type them and confirms the size before giving any price."""
import pytest

from app.services import webchat_size_service as z
from app.services import webchat_shop_service as shop
from app.services import webchat_service as wc

SIZES = ["Emperor king: 7/7 ft.", "Grand king 80×80 (6/6.7×6/6.7)", "California king: 6/7 ft.", "RV King: 6/6.7 ft.",
         "Standard king: 6/6 ft.", "Queen: 5/6 ft.", "Double: 4.5/6 ft."]


def _p(pid, title, base, sizes, step=50000):
    return {"id": pid, "title": title, "price": base, "available": True,
            "variants": [{"id": f"{pid}-{i}", "title": t, "price": str(base + i * step), "inventory_management": None} for i, t in enumerate(sizes)]}


ROWS = [_p("p1", "Cloud Mattress", 625000, ["Standard king: 6/6 ft.", "Queen: 5/6 ft.", "Single 3/6 ft"]),
        _p("p2", "Luxury Hybrid Royal Rest Black", 825000, SIZES),
        _p("p3", "Luxury Hybrid Royal Rest - Black", 825000, SIZES),          # same product listed twice
        {"id": "p4", "title": "Hotel Pillow", "price": 45000, "variants": [{"id": "v", "title": "Default Title", "price": "45000"}]}]


@pytest.fixture
def chat(monkeypatch):
    s = {"id": "s1", "org_id": "o1", "state": {}}
    monkeypatch.setattr(shop, "_fetch_all", lambda db, org: ROWS)
    def set_state(db, sess, **kw):
        sess["state"] = {**(sess.get("state") or {}), **kw}
    monkeypatch.setattr(wc, "set_state", set_state)
    return s


CFG = {"shop_enabled": True}


@pytest.mark.parametrize("text,dims", [
    ("Do you have 7*7 size", (7.0, 7.0)), ("6*6 and 7*7", (6.0, 6.0)), ("6 by 6 14inchi", (6.0, 6.0)), ("6x6", (6.0, 6.0)),
    ("6ft by 7ft", (6.0, 7.0)), ("72x72", (6.0, 6.0)), ("183 x 203 cm", (6.0, 6.66)), ("i want 5 by 6", (5.0, 6.0)),
    ("6/6", (6.0, 6.0)), ("do you have 6/6?", (6.0, 6.0)), ("6/7 ft", (6.0, 7.0)), ("4.5/6", (4.5, 6.0)),
    ("I need 6 / 6 mattress", (6.0, 6.0)), ("price of 7/7", (7.0, 7.0)),
])
def test_reads_sizes_the_way_visitors_type_them(text, dims):
    assert z.parse_size(text)["dims"] == dims


@pytest.mark.parametrize("text", ["call 0816 878 2936", "price 625000", "12/6/2026", "Mattress and pillow prices", "hello", "1 by 1", ""])
def test_ignores_things_that_are_not_sizes(text):
    assert z.parse_size(text) is None


def test_thickness_is_kept():
    assert z.parse_size("6 by 6 14inchi")["thickness"] == 14
    assert z.parse_size("6/6 14 inches")["thickness"] == 14


def test_reads_the_business_size_labels():
    assert z.option_size("Standard king: 6/6 ft.") == (6.0, 6.0)
    assert z.option_size("Grand king 80×80 (6/6.7×6/6.7)") == (6.67, 6.67)
    assert z.option_size("Queen 152 × 203 × 35 cm") == (4.99, 6.66)
    assert z.option_size("Default Title") is None and z.option_size("Coolant pillow") is None
    assert z.size_name("Standard king: 6/6 ft.") == "Standard king" and z.size_name("Queen 152 × 203 × 35 cm") == "Queen"


def test_asks_to_confirm_before_any_price(chat):
    r = z.handle(None, chat, CFG, "Do you have 7*7 size")
    assert "Emperor king" in r["text"] and "7 by 7 ft" in r["text"] and "₦" not in r["text"]
    assert [c["label"] for c in r["choices"]] == ["Yes", "No"]
    assert chat["state"]["size_ask"]["name"] == "Emperor king"


def test_yes_gives_that_size_prices_once_per_product(chat):
    z.handle(None, chat, CFG, "6 by 6")
    r = z.handle(None, chat, CFG, "Yes")
    assert "Standard king" in r["text"] and "Cloud Mattress ₦625,000" in r["text"]
    assert r["text"].count("Luxury Hybrid") == 1                     # the duplicate listing is shown once
    assert "₦1,025,000" in r["text"]                                 # the Standard king option's own price, not the starting price
    assert r["cards_ids"][0] == "p1" and chat["state"]["size_ask"] is None


def test_correct_counts_as_yes_and_thickness_goes_to_team(chat):
    z.handle(None, chat, CFG, "6 by 6 14inchi")
    r = z.handle(None, chat, CFG, "correct")
    assert "₦" in r["text"] and "14-inch" in r["text"]


def test_no_shows_the_size_list_and_a_tap_is_the_confirmation(chat):
    z.handle(None, chat, CFG, "6*6")
    r = z.handle(None, chat, CFG, "No")
    labels = [c["label"] for c in r["choices"]]
    assert labels[0].startswith("Single") and "Queen: 5/6 ft." in labels and "₦" not in r["text"]
    r2 = z.handle(None, chat, CFG, "Queen: 5/6 ft.")
    assert "Queen" in r2["text"] and "₦" in r2["text"]


def test_no_with_a_new_size_reads_back_the_new_size(chat):
    z.handle(None, chat, CFG, "6*6")
    r = z.handle(None, chat, CFG, "no 6 by 7")
    assert "California king" in r["text"] and "₦" not in r["text"]


def test_size_we_do_not_have_lists_ours(chat):
    r = z.handle(None, chat, CFG, "do you have 8 by 9")
    assert "don't think we have 8 by 9 ft" in r["text"] and len(r["choices"]) >= 5
    r2 = z.handle(None, chat, CFG, "the standard king")
    assert "Standard king" in r2["text"] and "₦" in r2["text"]


def test_other_messages_carry_on_as_normal(chat):
    assert z.handle(None, chat, CFG, "Mattress and pillow prices") is None
    z.handle(None, chat, CFG, "6*6")
    assert z.handle(None, chat, CFG, "where is your shop") is None and chat["state"]["size_ask"] is None


def test_off_without_products_or_sized_options(chat, monkeypatch):
    assert z.handle(None, chat, {}, "6*6") is None
    monkeypatch.setattr(shop, "_fetch_all", lambda db, org: [ROWS[3]])
    assert z.handle(None, chat, CFG, "6*6") is None


def test_ai_gets_sizes_and_the_confirm_rule():
    assert z.sizes_for_prompt(ROWS[0]) == "Standard king 6 by 6 ft N625,000; Queen 5 by 6 ft N675,000; Single 3 by 6 ft N725,000"
    src = open(__import__("app.services.webchat_ai_service", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert "Just to be sure, you mean the Standard king size" in src and "sizes: " in src


def test_flow_runs_the_size_step_before_the_ai():
    src = open(__import__("app.services.webchat_flow_service", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert src.index("size_step.handle(") < src.index("offer_item = _open_offer_item(cfg, s)") < src.index("webchat_ai_service.answer(")


# SIZE-CONFIRM-2: "show me all sizes", "bigger size", and replies to Chioma's own question
@pytest.mark.parametrize("text", ["Show me all sizes and types", "what sizes do you have", "which sizes are available", "sizes do you have?"])
def test_asking_for_sizes_shows_the_size_list_without_prices(chat, text):
    r = z.handle(None, chat, CFG, text)
    assert "sizes" in r["text"] and "₦" not in r["text"] and r["choices"][0]["label"].startswith("Single")
    r2 = z.handle(None, chat, CFG, r["choices"][-1]["label"])            # tapping a size is the confirmation
    assert "₦" in r2["text"]


def test_bigger_size_with_nothing_chosen_asks_which(chat):
    r = z.handle(None, chat, CFG, "How much is the bigger size")
    assert "Which size" in r["text"] and "₦" not in r["text"] and len(r["choices"]) >= 5


def test_bigger_size_after_a_confirmed_size_reads_back_the_next_one(chat):
    z.handle(None, chat, CFG, "5 by 6")
    z.handle(None, chat, CFG, "yes")
    assert chat["state"]["size_last"] == "Queen"
    r = z.handle(None, chat, CFG, "how much is the bigger size")
    assert "Standard king" in r["text"] and "₦" not in r["text"] and [c["label"] for c in r["choices"]] == ["Yes", "No"]
    r2 = z.handle(None, chat, CFG, "smaller")
    assert r2 is None or "₦" not in r2["text"]


def test_biggest_size_says_so(chat):
    z.handle(None, chat, CFG, "7 by 7")
    z.handle(None, chat, CFG, "yes")
    r = z.handle(None, chat, CFG, "do you have a bigger size")
    assert "biggest" in r["text"]


def test_a_reply_to_chiomas_question_is_not_keyword_matched():
    from app.services import webchat_flow_service as f
    assert f._ASKS_VISITOR.search("Happy to help. Tell me how you sleep (on your back, on your side, or both), and I will suggest the best fit.")
    assert f._ASKS_VISITOR.search("What is your budget?")
    assert not f._ASKS_VISITOR.search("Shipping is free nationwide. Lagos and Abuja get same-day delivery.")
    src = open(f.__file__, encoding="utf-8").read()
    assert src.index("if not ai and asked_before") < src.index("elif not ai and loose_item")
