"""
tests/unit/test_webchat_3b.py
----------------------------
WEBCHAT-3a: AI answers in the web chat (text only): when it runs, what it may say, limits, model choice,
credit gate, injection handling, hand-over, and that the scripted flow is untouched when it is off.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ORG = "00000000-0000-0000-0000-0000000000aa"


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.filters, self.op, self.payload, self._limit = [], "select", None, None
        self._order = None

    def select(self, *_a, **_k): return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, row): self.op, self.payload = "update", row; return self
    def upsert(self, row, **_k): self.op, self.payload = "upsert", row; return self
    def _f(self, k, c, v): self.filters.append((k, c, v)); return self
    def eq(self, c, v): return self._f("eq", c, v)
    def neq(self, c, v): return self._f("neq", c, v)
    def lt(self, c, v): return self._f("lt", c, v)
    def gt(self, c, v): return self._f("gt", c, v)
    def lte(self, c, v): return self._f("lte", c, v)
    def gte(self, c, v): return self._f("gte", c, v)
    def in_(self, c, v): return self._f("in", c, v)
    def is_(self, c, v): return self._f("is", c, v)
    def order(self, col, desc=False, **_k): self._order = (col, desc); return self
    def limit(self, n): self._limit = n; return self

    def _match(self, r):
        for k, c, v in self.filters:
            x = r.get(c)
            if k == "eq" and x != v: return False
            if k == "neq" and x == v: return False
            if k == "in" and x not in v: return False
            if k == "is" and not ((x is None) if v == "null" else (x is not None)): return False
            if k == "lt" and not (x is not None and str(x) < str(v)): return False
            if k == "gt" and not (x is not None and str(x) > str(v)): return False
            if k == "lte" and not (x is not None and str(x) <= str(v)): return False
            if k == "gte" and not (x is not None and str(x) >= str(v)): return False
        return True

    def execute(self):
        self.db.calls.append((self.name, self.op, self.payload))
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for it in items:
                it = dict(it)
                it.setdefault("id", str(uuid.uuid4()))
                rows.append(it)
                out.append(dict(it))
            return SimpleNamespace(data=out)
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return SimpleNamespace(data=[dict(r) for r in hit])
        if self.op == "upsert":
            return SimpleNamespace(data=[])
        hit = [dict(r) for r in rows if self._match(r)]
        if self._order:
            hit.sort(key=lambda r: str(r.get(self._order[0]) or ""), reverse=self._order[1])
        if self._limit:
            hit = hit[: self._limit]
        return SimpleNamespace(data=hit)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls = []

    def table(self, name): return _Q(self, name)

    def rows(self, name): return self.tables.get(name, [])


def _iso(dt): return dt.astimezone(timezone.utc).isoformat()
def _now(): return datetime.now(timezone.utc)



def _iso(dt): return dt.astimezone(timezone.utc).isoformat()
def _now(): return datetime.now(timezone.utc)


MENU = [
    {"id": "hours", "label": "Opening hours", "answer": "We open 9 to 6, Monday to Saturday.", "keywords": ["hours", "open"]},
    {"id": "team", "label": "Talk to us", "action": "human", "keywords": ["human"]},
]


def _db(ai=True, **cfg_extra):
    cfg = {"enabled": True, "menu": MENU, "ai_enabled": ai, **cfg_extra}
    return FakeDB(organisations=[{"id": ORG, "name": "Glow Salon", "webchat_config": cfg}])


@pytest.fixture(autouse=True)
def _no_rate_limit():
    from app.services import webchat_service as wc
    with patch.object(wc, "rate_limited", return_value=False):
        yield


def _session(db, contact=True, **state):
    from app.services import webchat_service as wc
    s, _ = wc.create_session(db, ORG, source="link", lead_id="L1" if contact else None, name="Ada Obi" if contact else None)
    s["state"] = dict(state)
    return s


def _claude(text):
    return patch("app.services.ai_service.call_claude", return_value=text)


def _cfg(db):
    from app.services import webchat_service as wc
    return wc.get_config(db, ORG)



PRODUCTS = [
    {"id": "p1", "title": "Silk Bonnet", "price": 5000, "variants": [], "catalog_images": ["https://x.test/a.jpg"], "description": "Soft silk bonnet"},
    {"id": "p2", "title": "Body Oil", "price": 3000, "variants": [{"id": "v1", "title": "100ml", "price": 3000}, {"id": "v2", "title": "250ml", "price": 6500}], "catalog_images": [], "description": "Natural oil"},
    {"id": "p3", "title": "Free Sample", "price": 0, "variants": [], "catalog_images": [], "description": ""},
]


def _shop_db(shop=True, ai=True):
    db = _db(ai=ai, shop_enabled=shop)
    db.tables["products"] = [dict(p, org_id=ORG) for p in PRODUCTS] + [dict(PRODUCTS[0], id="other", org_id="other-org", title="Other Org Item")]
    return db


class TestConfig:
    def test_shop_off_by_default_and_exposed_publicly(self):
        from app.services import webchat_service as wc
        assert wc.sanitise_config({})  is not None
        assert wc.DEFAULT_CONFIG["shop_enabled"] is False
        db = _shop_db()
        assert wc.public_view(_cfg(db))["shop_enabled"] is True
        assert wc.public_view(_cfg(_db()))["shop_enabled"] is False


class TestCatalogue:
    def test_search_only_own_org_and_cards_shape(self):
        from app.services import webchat_shop_service as shop
        cards = shop.search(_shop_db(), ORG)
        assert {c["id"] for c in cards} == {"p1", "p2", "p3"}
        oil = next(c for c in cards if c["id"] == "p2")
        assert oil["variants"][1] == {"id": "v2", "label": "250ml", "price": 6500.0}

    def test_search_ranks_by_words(self):
        from app.services import webchat_shop_service as shop
        assert shop.search(_shop_db(), ORG, "silk bonnet")[0]["id"] == "p1"

    def test_cards_for_drops_unknown_and_other_org_ids(self):
        from app.services import webchat_shop_service as shop
        got = shop.cards_for(_shop_db(), ORG, ["p2", "nope", "other"])
        assert [c["id"] for c in got] == ["p2"]


class TestCart:
    def test_add_uses_database_price_not_client(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        v = shop.add(db, s, "p1", None, 2)
        assert v["total"] == 10000 and v["count"] == 2

    def test_variant_required_and_priced(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        assert "option" in shop.add(db, s, "p2", None)["error"]
        assert "option" in shop.add(db, s, "p2", "bogus")["error"]
        assert shop.add(db, s, "p2", "v2")["total"] == 6500

    def test_same_line_merges_and_qty_capped(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        for _ in range(4):
            shop.add(db, s, "p1", None, 5)
        v = shop.view(s)
        assert len(v["items"]) == 1 and v["items"][0]["qty"] == shop.MAX_QTY

    def test_zero_price_unknown_and_foreign_products_refused(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        assert shop.add(db, s, "p3", None).get("error")
        assert shop.add(db, s, "ghost", None).get("error")
        assert shop.add(db, s, "other", None).get("error")
        assert shop.view(s)["count"] == 0

    def test_remove_and_clear(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        shop.add(db, s, "p1", None); shop.add(db, s, "p2", "v1")
        assert shop.remove(db, s, "p1", None)["count"] == 1
        assert shop.clear(db, s)["count"] == 0

    def test_cart_full(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        s["state"]["cart"] = [{"pid": f"x{i}", "vid": None, "name": "x", "price": 1, "qty": 1} for i in range(shop.MAX_LINES)]
        assert "full" in shop.add(db, s, "p1", None)["error"]


class TestCheckout:
    def _link(self, url="https://paystack.test/pay"):
        return patch("app.services.paystack_storefront_service.generate_payment_link",
                     return_value={"checkout_url": url, "reference": "r", "payment_link_id": "pl"})

    def test_needs_contact(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db, contact=False)
        shop.add(db, s, "p1", None)
        assert shop.checkout(db, s, _cfg(db))["ask_contact"] is True

    def test_empty_cart(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        assert "empty" in shop.checkout(db, s, _cfg(db))["error"]

    def test_link_amount_comes_from_fresh_prices(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        shop.add(db, s, "p1", None, 2)
        s["state"]["cart"][0]["price"] = 1            # tampered / stale cart price
        db.tables["products"][0]["price"] = 5500       # business changed the price meanwhile
        with self._link() as g, patch("app.services.lead_service.write_timeline_event"), \
             patch("app.services.webchat_service.notify_managers"):
            res = shop.checkout(db, s, _cfg(db))
        assert g.call_args.kwargs["amount"] == 11000 and g.call_args.kwargs["org_id"] == ORG
        assert res["checkout_url"] == "https://paystack.test/pay"
        assert "https://paystack.test/pay" in res["messages"][-1]["text"]
        assert shop.view(s)["count"] == 0 and s["state"]["last_checkout"]["total"] == 11000

    def test_removed_product_is_dropped_not_charged(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        shop.add(db, s, "p1", None); shop.add(db, s, "p2", "v1")
        db.tables["products"] = [p for p in db.tables["products"] if p["id"] != "p1"]
        with self._link() as g, patch("app.services.lead_service.write_timeline_event"), \
             patch("app.services.webchat_service.notify_managers"):
            shop.checkout(db, s, _cfg(db))
        assert g.call_args.kwargs["amount"] == 3000

    def test_no_paystack_hands_over_to_a_person(self):
        from app.services import webchat_shop_service as shop
        db = _shop_db(); s = _session(db)
        shop.add(db, s, "p1", None)
        with patch("app.services.paystack_storefront_service.generate_payment_link", side_effect=RuntimeError("no keys")), \
             patch("app.services.webchat_service.notify_managers") as nm:
            res = shop.checkout(db, s, _cfg(db))
        assert res["human"] is True and s["state"]["human"] is True and nm.called and "checkout_url" not in res


class TestAiCards:
    def test_prompt_lists_catalogue_only_when_shop_on(self):
        from app.services import webchat_ai_service as ai
        on, off = _shop_db(shop=True), _shop_db(shop=False)
        assert "id=p1" in ai.build_system_prompt(on, _session(on), _cfg(on), "silk bonnet")
        p = ai.build_system_prompt(off, _session(off), _cfg(off), "silk bonnet")
        assert "<products>" not in p and '"products"' not in p

    def test_parse_keeps_up_to_three_ids(self):
        from app.services import webchat_ai_service as ai
        r = ai.parse_reply('{"reply": "Try these.", "handoff": false, "products": ["a","b","c","d"]}')
        assert r["products"] == ["a", "b", "c"]

    def test_flow_shows_cards_for_real_ids_only(self):
        from app.services import webchat_flow_service as f
        db = _shop_db(); s, cfg = _session(db), _cfg(db)
        with _claude('{"reply": "This one is lovely.", "handoff": false, "products": ["p1", "made-up"]}'):
            r = f.handle_message(db, s, cfg, kind="text", text="I need something for my hair at night")
        assert [c["id"] for c in r["cards"]] == ["p1"]

    def test_flow_no_cards_when_shop_off(self):
        from app.services import webchat_flow_service as f
        db = _shop_db(shop=False); s, cfg = _session(db), _cfg(db)
        with _claude('{"reply": "Maybe.", "handoff": false, "products": ["p1"]}'):
            r = f.handle_message(db, s, cfg, kind="text", text="something for my hair at night")
        assert r["cards"] == []


class TestRoutes:
    def _client(self, db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.database import get_supabase
        from app.routers import public_webchat as r
        app = FastAPI(); app.include_router(r.router, prefix="/api/v1")
        app.dependency_overrides[get_supabase] = lambda: db
        return TestClient(app)

    def _start(self, c, db):
        from app.services import webchat_service as wc
        key = wc.get_or_create_key(db, ORG)
        tok = c.post(f"/api/v1/public/webchat/{key}/session", json={}).json()["data"]["token"]
        return key, {"Authorization": f"Bearer {tok}"}

    def test_shop_routes_404_when_off(self):
        db = _shop_db(shop=False); c = self._client(db); key, h = self._start(c, db)
        assert c.get(f"/api/v1/public/webchat/{key}/products", headers=h).status_code == 404
        assert c.post(f"/api/v1/public/webchat/{key}/checkout", headers=h).status_code == 404

    def test_shop_routes_need_a_session(self):
        db = _shop_db(); c = self._client(db); key, _ = self._start(c, db)
        assert c.get(f"/api/v1/public/webchat/{key}/products").status_code == 401

    def test_browse_add_and_checkout_needs_contact(self):
        db = _shop_db(); c = self._client(db); key, h = self._start(c, db)
        assert len(c.get(f"/api/v1/public/webchat/{key}/products", headers=h).json()["data"]["products"]) == 3
        r = c.post(f"/api/v1/public/webchat/{key}/cart", headers=h, json={"action": "add", "product_id": "p1", "qty": 2})
        assert r.json()["data"]["total"] == 10000
        bad = c.post(f"/api/v1/public/webchat/{key}/cart", headers=h, json={"action": "add", "product_id": "p2"})
        assert bad.status_code == 422
        out = c.post(f"/api/v1/public/webchat/{key}/checkout", headers=h)
        assert out.status_code == 422


class TestBotComesBack:
    def _ago(self, minutes):
        return (_now() - timedelta(minutes=minutes)).isoformat()

    def test_recent_team_reply_keeps_bot_quiet(self):
        from app.services import webchat_flow_service as f
        db = _db(); s, cfg = _session(db, human=True, human_at=self._ago(5), rep_last_at=self._ago(2)), _cfg(db)
        with _claude('{"reply": "AI", "handoff": false}') as cc:
            r = f.handle_message(db, s, cfg, kind="text", text="are you there?")
        assert r["human"] is True and not cc.called

    def test_bot_resumes_after_team_silence(self):
        from app.services import webchat_flow_service as f
        db = _db(); s, cfg = _session(db, human=True, human_at=self._ago(90), rep_last_at=self._ago(45)), _cfg(db)
        with _claude('{"reply": "Back with you.", "handoff": false}'):
            r = f.handle_message(db, s, cfg, kind="text", text="what do you do?")
        assert r["human"] is False and r["messages"][-1]["text"] == "Back with you." and not s["state"].get("human")

    def test_no_reply_ever_still_lapses(self):
        from app.services import webchat_service as wc
        db = _db(); s, cfg = _session(db, human=True, human_at=self._ago(40)), _cfg(db)
        assert wc.is_human(s, cfg) is False
        s2 = _session(db, human=True, human_at=self._ago(3))
        assert wc.is_human(s2, cfg) is True

    def test_tapping_a_menu_option_brings_the_bot_back_early(self):
        from app.services import webchat_flow_service as f
        db = _db(); s, cfg = _session(db, human=True, human_at=self._ago(2), rep_last_at=self._ago(1)), _cfg(db)
        r = f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
        assert r["human"] is False and r["messages"][-1]["text"].startswith("We open 9 to 6")

    def test_talk_to_us_stays_with_the_team(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db(); s, cfg = _session(db, human=True, human_at=self._ago(2), rep_last_at=self._ago(1)), _cfg(db)
        with patch.object(wc, "notify_managers"):
            r = f.handle_message(db, s, cfg, kind="menu", menu_id="team")
        assert r["human"] is True

    def test_rep_send_stamps_the_time(self):
        from app.services import webchat_service as wc
        db = _db(); s = _session(db)
        db.tables.setdefault("webchat_sessions", []).append(s)
        wc.rep_send(db, ORG, "L1", "hello", "u1")
        assert wc.is_human(db.tables["webchat_sessions"][0], _cfg(db)) is True

    def test_resume_minutes_setting_is_bounded(self):
        from app.services import webchat_service as wc
        assert wc.sanitise_config({"human_resume_min": 1})["human_resume_min"] == 5
        assert wc.sanitise_config({"human_resume_min": 99999})["human_resume_min"] == 1440
