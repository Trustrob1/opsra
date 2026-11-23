"""WEBCHAT-CATALOG-1: Storefront chat button (chat_info), product context (viewing), richer AI product facts."""
import json

from app.services import catalog_storefront_service as sf
from app.services import webchat_plan_service as plan
from app.services import webchat_service as wc
from app.services import webchat_shop_service as shop

ORG = "org-1"
PRODUCTS = [
    {"id": "p1", "org_id": ORG, "title": "Silk Bonnet", "price": 4500, "variants": [], "catalog_images": ["https://x/y.jpg"],
     "description": "Soft satin-lined bonnet. " + "Keeps hair smooth. " * 30, "catalog_description": None, "available": True},
    {"id": "p2", "org_id": ORG, "title": "Hair Oil", "price": 6500, "variants": [], "catalog_images": [],
     "description": "Light oil.", "catalog_description": None, "available": False},
]


class _Q:
    def __init__(self, db, table): self.db, self.t, self.f = db, table, {}
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def limit(self, *a, **k): return self
    def execute(self):
        rows = [r for r in self.db.tables.get(self.t, []) if all(str(r.get(k)) == str(v) for k, v in self.f.items())]
        return type("R", (), {"data": rows})


class _DB:
    def __init__(self, keys=True, products=None):
        self.tables = {"webchat_keys": [{"org_id": ORG, "key": "wc_abcdefgh12", "active": True}] if keys else [],
                       "products": list(PRODUCTS if products is None else products)}
    def table(self, n): return _Q(self, n)


def _live(monkeypatch, enabled=True, allowed=True):
    monkeypatch.setattr(wc, "get_config", lambda db, o: {"enabled": enabled, "shop_enabled": True})
    monkeypatch.setattr(plan, "apply", lambda db, o, c: (dict(c) if allowed else None))


# ── CATCHAT-1: chat_info ─────────────────────────────────────────────────────────────

def test_chat_info_gives_the_key_when_everything_allows(monkeypatch):
    _live(monkeypatch)
    assert sf.chat_info(_DB(), ORG, {}) == {"key": "wc_abcdefgh12", "shop": True}
    assert sf.chat_info(_DB(), ORG, None) == {"key": "wc_abcdefgh12", "shop": True}              # default on
    assert sf.chat_info(_DB(), ORG, {"chat_button": True}) == {"key": "wc_abcdefgh12", "shop": True}


def test_chat_info_off_cases(monkeypatch):
    _live(monkeypatch)
    assert sf.chat_info(_DB(), ORG, {"chat_button": False}) is None                # owner switched it off
    assert sf.chat_info(_DB(keys=False), ORG, {}) is None                           # no key yet: never creates one
    _live(monkeypatch, enabled=False)
    assert sf.chat_info(_DB(), ORG, {}) is None                                     # web chat off
    _live(monkeypatch, allowed=False)
    assert sf.chat_info(_DB(), ORG, {}) is None                                     # plan lacks webchat_basic


def test_chat_info_does_not_need_the_shop(monkeypatch):
    monkeypatch.setattr(wc, "get_config", lambda db, o: {"enabled": True, "shop_enabled": False})
    monkeypatch.setattr(plan, "apply", lambda db, o, c: dict(c))
    assert sf.chat_info(_DB(), ORG, {}) == {"key": "wc_abcdefgh12", "shop": False}


def test_chat_info_never_raises(monkeypatch):
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(wc, "get_config", boom)
    assert sf.chat_info(_DB(), ORG, {}) is None


def test_public_extras_chat_only_on_storefront(monkeypatch):
    _live(monkeypatch)
    monkeypatch.setattr(sf, "shop_info", lambda db, o: None)
    monkeypatch.setattr(sf, "resolve_template", lambda db, o, c: "storefront")
    assert sf.public_extras(_DB(), ORG, {})["chat"] == {"key": "wc_abcdefgh12", "shop": True}
    monkeypatch.setattr(sf, "resolve_template", lambda db, o, c: "classic")
    assert sf.public_extras(_DB(), ORG, {})["chat"] is None


def test_owner_switch_is_accepted_and_false_is_kept():
    from app.routers.catalog import CatalogConfigUpdate
    assert CatalogConfigUpdate(chat_button=False).model_dump(exclude_none=True) == {"chat_button": False}
    assert CatalogConfigUpdate().model_dump(exclude_none=True) == {}


# ── CATCHAT-2: viewing ────────────────────────────────────────────────────────────────

class _Sess(dict):
    pass


def _s(state=None):
    return _Sess({"id": "s1", "org_id": ORG, "state": dict(state or {})})


def _patch_msgs(monkeypatch):
    sent = []
    monkeypatch.setattr(wc, "append_message", lambda db, s, role, text, **k: (sent.append((role, text)) or {"id": f"m{len(sent)}", "role": role, "text": text}))
    def set_state(db, s, **kv):
        s["state"].update(kv)
        return s
    monkeypatch.setattr(wc, "set_state", set_state)
    return sent


def test_viewing_opens_with_the_product_card(monkeypatch):
    sent = _patch_msgs(monkeypatch)
    s = _s()
    r = shop.viewing(_DB(), s, {"shop_enabled": True}, "p1")
    assert sent and sent[0][0] == "bot" and "Silk Bonnet" in sent[0][1] and "add it to your cart" in sent[0][1]
    assert [c["id"] for c in r["cards"]] == ["p1"] and r["messages"]
    assert s["state"]["viewing"] == "p1" and s["state"]["viewing_title"] == "Silk Bonnet"


def test_viewing_same_product_is_said_once(monkeypatch):
    sent = _patch_msgs(monkeypatch)
    s = _s({"viewing": "p1"})
    assert shop.viewing(_DB(), s, {"shop_enabled": True}, "p1") == {"messages": [], "cards": []}
    assert not sent


def test_viewing_ignores_unknown_foreign_and_odd_ids(monkeypatch):
    sent = _patch_msgs(monkeypatch)
    foreign = [dict(PRODUCTS[0], id="other", org_id="other-org")]
    for pid in ("nope", "", None, "other", "x" * 200):
        r = shop.viewing(_DB(products=PRODUCTS + foreign), _s(), {"shop_enabled": True}, pid)
        assert r == {"messages": [], "cards": []}
    assert not sent


def test_viewing_with_shop_off_is_text_and_price_only(monkeypatch):
    sent = _patch_msgs(monkeypatch)
    r = shop.viewing(_DB(), _s(), {"shop_enabled": False}, "p1")
    assert r["cards"] == [] and "4,500" in sent[0][1] and "cart" not in sent[0][1]


def test_viewing_out_of_stock_has_no_card(monkeypatch):
    sent = _patch_msgs(monkeypatch)
    r = shop.viewing(_DB(), _s(), {"shop_enabled": True}, "p2")
    assert r["cards"] == [] and "out of stock" in sent[0][1]


def test_viewing_never_raises(monkeypatch):
    class Bad:
        def table(self, n): raise RuntimeError("db down")
    assert shop.viewing(Bad(), _s(), {"shop_enabled": True}, "p1") == {"messages": [], "cards": []}


def test_viewing_route_checks_session_and_calls_shop(monkeypatch):
    from app.routers import public_webchat as r
    monkeypatch.setattr(wc, "resolve_key", lambda db, k: {"org_id": ORG, "config": {"shop_enabled": False}})
    monkeypatch.setattr(wc, "authenticate", lambda db, org, tok: {"id": "s1", "org_id": ORG, "state": {}})
    monkeypatch.setattr(wc, "rate_limited", lambda *a, **k: False)
    seen = {}
    monkeypatch.setattr(shop, "viewing", lambda db, s, cfg, pid: seen.update(pid=pid) or {"messages": [], "cards": []})
    class Resp:
        headers = {}
    out = r.post_viewing("wc_abcdefgh12", r.ViewingBody(product="p1"), Resp(), "Bearer tok", None)
    assert seen["pid"] == "p1" and out.success is True
    monkeypatch.setattr(wc, "authenticate", lambda db, org, tok: None)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        r.post_viewing("wc_abcdefgh12", r.ViewingBody(product="p1"), Resp(), None, None)
    assert e.value.status_code == 401


# ── CATCHAT-3: richer facts for the AI ─────────────────────────────────────────────────

def test_facts_have_stock_and_a_short_description():
    facts = shop.facts_for_prompt(_DB(), ORG, "")
    by = {f["id"]: f for f in facts}
    assert by["p1"]["in_stock"] is True and by["p2"]["in_stock"] is False
    assert 0 < len(by["p1"]["blurb"]) <= 300 and by["p1"]["blurb"].startswith("Soft satin-lined bonnet.")


def test_facts_put_the_viewed_product_first_even_if_it_does_not_match():
    facts = shop.facts_for_prompt(_DB(), ORG, "bonnet", viewing_id="p2")
    assert facts[0]["id"] == "p2" and {f["id"] for f in facts} == {"p1", "p2"}


def test_facts_never_raise():
    class Bad:
        def table(self, n): raise RuntimeError("x")
    assert shop.facts_for_prompt(Bad(), ORG, "x") == []


def test_prompt_has_cache_split_facts_and_the_viewed_product(monkeypatch):
    from app.services import ai_service
    from app.services import webchat_ai_service as ai
    monkeypatch.setattr(ai, "_knowledge", lambda *a, **k: "Open 8 to 5.")
    db = _DB()
    cfg = {"business_name": "Royal Rest", "shop_enabled": True}
    p = ai.build_system_prompt(db, {"org_id": ORG, "state": {"viewing": "p2"}}, cfg, "is it available")
    stable, _, changing = p.partition(ai_service.CACHE_SPLIT)
    assert changing and "You are Chioma" in stable and "<products>" not in stable.replace("<business_info> and <products>", "")
    assert "id=p1 | Silk Bonnet | N4,500 | in stock | Soft satin-lined bonnet." in changing
    assert "id=p2 | Hair Oil | N6,500 | out of stock" in changing
    assert "opened this chat from the page of Hair Oil" in changing
    assert changing.rstrip().endswith("}.") and "Never say an item is in stock" in changing
    off = ai.build_system_prompt(db, {"org_id": ORG, "state": {"viewing": "p2"}}, {"business_name": "X", "shop_enabled": False}, "hi")
    assert "<products>" not in off and "opened this chat from" not in off


def test_prompt_ignores_a_viewed_id_that_is_not_in_the_list(monkeypatch):
    from app.services import webchat_ai_service as ai
    monkeypatch.setattr(ai, "_knowledge", lambda *a, **k: "x")
    p = ai.build_system_prompt(_DB(), {"org_id": ORG, "state": {"viewing": "ghost"}}, {"business_name": "X", "shop_enabled": True}, "hi")
    assert "opened this chat from" not in p


# ── WEBCHAT-CATALOG-1b: answer from the catalogue when no AI answer is possible ─────────────

LATEX = {"id": "m1", "org_id": ORG, "title": "Holiday Sleep Mattress", "price": 705000, "available": True,
         "variants": [{"id": "v1", "price": 705000}, {"id": "v2", "price": 945000}], "catalog_images": [],
         "description": "Made from natural Malaysian latex, cotton and bamboo wood. It has two sides. Natural anti mosquito lemon grass treatment. " * 6,
         "catalog_description": None}


def test_product_answer_uses_the_catalogue_text_price_and_stock():
    s = _s({"viewing": "m1"})
    t = shop.product_answer(_DB(products=[LATEX]), s, {}, "what is the mattress made of?")
    assert t.startswith("Here is what we have on Holiday Sleep Mattress:") and "natural Malaysian latex" in t
    assert "From ₦705,000. In stock." in t and t.endswith(wc.SCRIPTED_TAIL)
    assert len(t) < 700


def test_product_answer_is_honest_when_the_question_is_not_in_the_text():
    t = shop.product_answer(_DB(products=[LATEX]), _s({"viewing": "m1"}), {}, "do you deliver to Abuja?")
    assert t.startswith("I do not have that exact detail. Here is what we have on Holiday Sleep Mattress:")


def test_product_answer_cuts_at_a_sentence():
    t = shop.product_answer(_DB(products=[LATEX]), _s({"viewing": "m1"}), {}, "latex")
    body = t.split(":", 1)[1].split(" From ")[0].strip()
    assert body.endswith(".") and not body.endswith("...")


def test_product_answer_out_of_stock_and_nothing_to_say():
    out = dict(LATEX, available=False)
    assert "Out of stock right now." in shop.product_answer(_DB(products=[out]), _s({"viewing": "m1"}), {}, "latex")
    bare = dict(LATEX, description="", price=0)
    assert shop.product_answer(_DB(products=[bare]), _s({"viewing": "m1"}), {}, "latex") is None


def test_product_answer_needs_a_viewed_product_from_this_business_and_never_raises():
    assert shop.product_answer(_DB(), _s(), {}, "x") is None
    assert shop.product_answer(_DB(products=[dict(LATEX, org_id="other")]), _s({"viewing": "m1"}), {}, "x") is None
    class Bad:
        def table(self, n): raise RuntimeError("x")
    assert shop.product_answer(Bad(), _s({"viewing": "m1"}), {}, "x") is None


def test_public_view_carries_the_tail():
    assert wc.public_view(dict(wc.DEFAULT_CONFIG, business_name="X", _call_org={}))["scripted_tail"] == wc.SCRIPTED_TAIL


def test_post_message_swaps_in_the_product_text_only_for_typed_questions_on_a_product(monkeypatch):
    from app.routers import public_webchat as r
    from app.services import webchat_flow_service as flow
    seen = {}
    sess = {"id": "s1", "org_id": ORG, "state": {"viewing": "m1"}}
    monkeypatch.setattr(wc, "resolve_key", lambda db, k: {"org_id": ORG, "config": {"fallback": "STOCK", "shop_enabled": False}})
    monkeypatch.setattr(wc, "authenticate", lambda db, org, tok: sess)
    monkeypatch.setattr(wc, "rate_limited", lambda *a, **k: False)
    monkeypatch.setattr(flow, "handle_message", lambda db, s, cfg, **k: seen.update(fallback=cfg["fallback"]) or {"messages": []})
    monkeypatch.setattr(shop, "product_answer", lambda db, s, cfg, q: "PRODUCT TEXT")
    class Resp:
        headers = {}
    r.post_message("wc_abcdefgh12", r.MessageBody(kind="text", text="what is it made of"), Resp(), "Bearer t", None)
    assert seen["fallback"] == "PRODUCT TEXT"
    r.post_message("wc_abcdefgh12", r.MessageBody(kind="menu", menu_id="a"), Resp(), "Bearer t", None)
    assert seen["fallback"] == "STOCK"                                   # a tapped menu item never gets the product text
    sess["state"] = {}
    r.post_message("wc_abcdefgh12", r.MessageBody(kind="text", text="hello"), Resp(), "Bearer t", None)
    assert seen["fallback"] == "STOCK"                                   # no product being viewed: unchanged
