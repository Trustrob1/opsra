"""
tests/unit/test_webchat_5.py
---------------------------
WEBCHAT-5: analytics (funnel, by source, by day, chat facts, cost per chat, AI budget) and the QR route.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import webchat_analytics_service as an

ORG = "00000000-0000-0000-0000-0000000000aa"
OTHER = "00000000-0000-0000-0000-0000000000bb"


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
    def range(self, a, b): self._range = (a, b); return self

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
        if getattr(self, '_range', None):
            hit = hit[self._range[0]: self._range[1] + 1]
        if self._limit:
            hit = hit[: self._limit]
        return SimpleNamespace(data=hit)


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.calls = []

    def table(self, name): return _Q(self, name)

    def rows(self, name): return self.tables.get(name, [])


def _now(d=0):
    return (datetime.now(timezone.utc) - timedelta(days=d)).isoformat()


def _ev(kind, src="qr", org=ORG, d=0):
    return {"org_id": org, "kind": kind, "source": src, "created_at": _now(d), "session_id": "s"}


def _db():
    return FakeDB(
        webchat_events=[_ev("visit"), _ev("visit"), _ev("visit", "instagram"), _ev("started"), _ev("started", "instagram"),
                        _ev("contact"), _ev("booked"), _ev("visit", org=OTHER), _ev("visit", d=60), _ev("handoff_sent")],
        webchat_sessions=[
            {"org_id": ORG, "created_at": _now(), "lead_id": "l1", "turn_count": 4,
             "state": {"ai_turns": 3, "human_at": "x", "last_checkout": {"x": 1}, "wa_count": 2, "email_reply_at": "x"}},
            {"org_id": ORG, "created_at": _now(), "lead_id": None, "turn_count": 1, "state": {}},
            {"org_id": OTHER, "created_at": _now(), "lead_id": "z", "turn_count": 9, "state": {"ai_turns": 9}},
        ],
        claude_usage_log=[
            {"org_id": ORG, "function_name": "webchat_ai_turn", "estimated_cost_usd": 0.01, "called_at": _now()},
            {"org_id": ORG, "function_name": "webchat_ai_turn", "estimated_cost_usd": 0.01, "called_at": _now()},
            {"org_id": ORG, "function_name": "other_fn", "estimated_cost_usd": 5, "called_at": _now()},
            {"org_id": OTHER, "function_name": "webchat_ai_turn", "estimated_cost_usd": 1, "called_at": _now()},
        ],
        credit_ledger=[
            {"org_id": ORG, "kind": "ai", "amount_kobo": -1500, "meta": {"function": "webchat_ai_turn"}, "created_at": _now()},
            {"org_id": ORG, "kind": "ai", "amount_kobo": -900, "meta": {"function": "other_fn"}, "created_at": _now()},
        ],
        credit_rates=[{"effective_from": "2020-01-01T00:00:00+00:00", "fx_ngn_per_usd": 1500}],
        credit_wallets=[{"org_id": ORG, "balance_kobo": 250000, "metering_enabled": True, "ai_monthly_budget_kobo": 100000}],
    )


def test_funnel_totals_and_rates_are_org_and_window_scoped():
    out = an.analytics(_db(), ORG, 30)
    t = out["funnel"]["totals"]
    assert t["visit"] == 3 and t["started"] == 2 and t["contact"] == 1 and t["booked"] == 1
    r = out["funnel"]["rates"]
    assert r["started_of_visit"] == 66.7 and r["contact_of_started"] == 50.0 and r["booked_of_contact"] == 100.0


def test_by_source_sorted_by_visits():
    s = an.analytics(_db(), ORG, 30)["funnel"]["sources"]
    assert s[0]["source"] == "qr" and s[0]["visit"] == 2
    assert {x["source"] for x in s} == {"qr", "instagram"}


def test_daily_series_present():
    d = an.analytics(_db(), ORG, 30)["funnel"]["daily"]
    assert len(d) == 1 and d[0]["visit"] == 3


def test_chat_facts():
    c = an.analytics(_db(), ORG, 30)["chats"]
    assert c["chats"] == 2 and c["with_contact"] == 1 and c["handed_to_team"] == 1
    assert c["ai_chats"] == 1 and c["ai_turns"] == 3 and c["checkouts"] == 1
    assert c["whatsapp_templates"] == 2 and c["reply_emails"] == 1


def test_cost_only_counts_web_chat_ai_for_this_org():
    cost = an.analytics(_db(), ORG, 30)["cost"]
    assert cost["calls"] == 2 and cost["cost_usd"] == 0.02
    assert cost["cost_kobo"] == int(round(0.02 * 1500 * 100))
    assert cost["charged_kobo"] == 1500
    assert cost["per_chat_kobo"] == cost["cost_kobo"] // 2 or cost["per_chat_kobo"] == round(cost["cost_kobo"] / 2)


def test_per_chat_none_when_no_chats():
    out = an.analytics(FakeDB(), ORG, 30)
    assert out["cost"]["per_chat_kobo"] is None and out["funnel"]["rates"]["started_of_visit"] is None
    assert out["funnel"]["totals"]["visit"] == 0


def test_wallet_block():
    w = an.analytics(_db(), ORG, 30)["wallet"]
    assert w["balance_kobo"] == 250000 and w["metering_enabled"] is True
    assert w["month_ai_spend_kobo"] == 2400 and w["ai_monthly_budget_kobo"] == 100000


def test_days_clamped():
    assert an.analytics(_db(), ORG, 500)["days"] == 90
    assert an.analytics(_db(), ORG, 0)["days"] == 30 or an.analytics(_db(), ORG, 0)["days"] == 1


def test_failed_query_returns_zeros():
    class Boom(FakeDB):
        def table(self, name): raise RuntimeError("down")
    out = an.analytics(Boom(), ORG, 30)
    assert out["funnel"]["totals"]["visit"] == 0 and out["chats"]["chats"] == 0


def test_qr_route_returns_svg_and_tags_source():
    from app.routers import webchat as r
    with patch.object(r.wc, "get_or_create_key", return_value="abc123"), patch.object(r.wc, "public_base", return_value="https://x.test"):
        resp = r.qr_svg(s="Instagram!", download=True, db=object(), org={"org_id": ORG, "roles": {"template": "owner"}})
    assert resp.media_type == "image/svg+xml" and b"<svg" in resp.body
    assert "chat-qr-" in resp.headers["content-disposition"]


def test_qr_route_blocked_for_staff():
    from fastapi import HTTPException
    from app.routers import webchat as r
    with pytest.raises(HTTPException) as e:
        r.qr_svg(s="qr", download=False, db=object(), org={"org_id": ORG, "roles": {"template": "sales_agent"}})
    assert e.value.status_code == 403


def test_analytics_route_blocked_for_staff():
    from fastapi import HTTPException
    from app.routers import webchat as r
    with pytest.raises(HTTPException):
        r.analytics(days=30, db=object(), org={"org_id": ORG, "roles": {"template": "sales_agent"}})
