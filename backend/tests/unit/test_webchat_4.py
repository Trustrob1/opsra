"""
tests/unit/test_webchat_4.py
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



def _s4(db, **over):
    from app.services import webchat_service as wc
    s, _ = wc.create_session(db, ORG, source="link", lead_id="L1", name="Ada Obi")
    s.update({"contact_email": "ada@example.com", "consent_at": _iso(_now()),
              "last_activity_at": _iso(_now() - timedelta(minutes=30))})
    s["state"] = {}
    s.update(over)
    db.tables.setdefault("webchat_sessions", [])
    for r in db.tables["webchat_sessions"]:
        if r["id"] == s["id"]:
            r.update(s)
    return s


def _mail():
    return patch("app.services.site_addon_billing_service._send_email", return_value=True)


class TestRules:
    def test_needs_email_and_consent_and_no_optout(self):
        from app.services import webchat_email_service as em
        db = _db(); cfg = _cfg(db); s = _s4(db)
        assert em.can_email(s, cfg) is True
        assert em.can_email(dict(s, contact_email=None), cfg) is False
        assert em.can_email(dict(s, consent_at=None), cfg) is False
        assert em.can_email(dict(s, state={"email_optout": True}), cfg) is False
        assert em.can_email(s, dict(cfg, email_followups=False)) is False

    def test_setting_default_on_and_public_flag(self):
        from app.services import webchat_service as wc
        db = _db()
        assert wc.DEFAULT_CONFIG["email_followups"] is True
        assert wc.public_view(_cfg(db))["email_enabled"] is True
        assert wc.sanitise_config({"email_followups": 0})["email_followups"] is False


class TestTeamReplyEmail:
    def test_emails_a_visitor_who_has_left(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db)
        with _mail() as m:
            assert em.notify_rep_reply(db, s, _cfg(db), "Your slot is Tuesday 5pm.") is True
        to, subject, body = m.call_args.args
        assert to == "ada@example.com" and "replied" in subject
        assert "Tuesday 5pm" in body and "/c/" in body and "?h=" in body and "Stop follow-ups" in body

    def test_not_while_the_visitor_is_still_on_the_page(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db, last_activity_at=_iso(_now() - timedelta(minutes=2)))
        with _mail() as m:
            assert em.notify_rep_reply(db, s, _cfg(db), "hi") is False
        assert not m.called

    def test_at_most_one_per_half_hour(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db); cfg = _cfg(db)
        with _mail() as m:
            assert em.notify_rep_reply(db, s, cfg, "one") is True
            assert em.notify_rep_reply(db, s, cfg, "two") is False
        assert m.call_count == 1

    def test_no_email_without_consent(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db, consent_at=None)
        with _mail() as m:
            assert em.notify_rep_reply(db, s, _cfg(db), "hi") is False
        assert not m.called

    def test_send_failure_does_not_raise_or_mark_sent(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db)
        with patch("app.services.site_addon_billing_service._send_email", return_value=False):
            assert em.notify_rep_reply(db, s, _cfg(db), "hi") is False
        assert not s["state"].get("email_reply_at")

    def test_rep_send_triggers_it(self):
        from app.services import webchat_service as wc
        db = _db(); s = _s4(db)
        db.tables["webchat_sessions"] = [s]
        with _mail() as m:
            wc.rep_send(db, ORG, "L1", "Come at 5pm", "u1")
        assert m.called


class TestResumeLink:
    def test_link_is_single_use_and_for_the_same_session(self):
        from app.services import webchat_email_service as em, webchat_service as wc
        db = _db(); s = _s4(db)
        db.tables["webchat_sessions"] = [s]
        url = em.resume_link(db, s)
        token = url.split("?h=")[1]
        got = wc.exchange_handoff(db, ORG, token)
        assert got and got[0]["id"] == s["id"]
        assert wc.exchange_handoff(db, ORG, token) is None            # already used

    def test_link_never_opens_another_business(self):
        from app.services import webchat_email_service as em, webchat_service as wc
        db = _db(); s = _s4(db)
        db.tables["webchat_sessions"] = [s]
        token = em.resume_link(db, s).split("?h=")[1]
        assert wc.exchange_handoff(db, "some-other-org", token) is None


class TestSaveChat:
    def test_needs_contact_consent_and_valid_email(self):
        from app.services import webchat_email_service as em
        db = _db(); cfg = _cfg(db)
        s0 = _s4(db); s0["lead_id"] = None
        assert "contact" in em.save_email(db, s0, cfg, "a@b.co", True)["error"]
        s = _s4(db, contact_email=None, consent_at=None)
        assert "look right" in em.save_email(db, s, cfg, "nope", True)["error"]
        assert "tick" in em.save_email(db, s, cfg, "a@b.co", False)["error"]

    def test_saves_email_and_sends_transcript(self):
        from app.services import webchat_email_service as em
        db = _db(); cfg = _cfg(db)
        s = _s4(db, contact_email=None, consent_at=None)
        db.tables["whatsapp_messages"] = [{"id": "m1", "org_id": ORG, "webchat_session_id": s["id"], "content": "What time do you open?",
                                           "created_at": _iso(_now()), "direction": "inbound", "sent_by": None}]
        with _mail() as m:
            res = em.save_email(db, s, cfg, "New@Example.com", True)
        assert res["emailed"] is True and s["contact_email"] == "new@example.com" and s["consent_at"]
        assert "What time do you open?" in m.call_args.args[2]

    def test_opt_out_stops_everything(self):
        from app.services import webchat_email_service as em
        db = _db(); s = _s4(db)
        em.opt_out(db, s)
        with _mail() as m:
            assert em.notify_rep_reply(db, s, _cfg(db), "hi") is False
            assert em.send_transcript(db, s, _cfg(db)) is False
        assert not m.called


class TestOtherEmails:
    def test_booking_confirmation(self):
        from app.services import webchat_flow_service as f
        db = _db(); s = _s4(db)
        cfg = _cfg(db)
        with _mail() as m, patch("app.services.lead_service.write_timeline_event"), patch("app.services.webchat_service.notify_managers"):
            f.handle_booking(db, s, cfg, {"service": "Braids", "when": "Tuesday 5pm"})
        assert m.called and "Braids" in m.call_args.args[2]

    def test_order_link_email(self):
        from app.services import webchat_shop_service as shop
        db = _db(shop_enabled=True); cfg = _cfg(db); s = _s4(db)
        db.tables["products"] = [{"id": "p1", "org_id": ORG, "title": "Silk Bonnet", "price": 5000, "variants": [], "catalog_images": []}]
        shop.add(db, s, "p1", None, 1)
        with _mail() as m, patch("app.services.paystack_storefront_service.generate_payment_link",
                                 return_value={"checkout_url": "https://paystack.test/x"}), \
             patch("app.services.lead_service.write_timeline_event"), patch("app.services.webchat_service.notify_managers"):
            shop.checkout(db, s, cfg)
        assert "https://paystack.test/x" in m.call_args.args[2] and "Silk Bonnet" in m.call_args.args[2]

    def test_routes_exist_and_need_a_session(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.database import get_supabase
        from app.routers import public_webchat as r
        from app.services import webchat_service as wc
        db = _db()
        app = FastAPI(); app.include_router(r.router, prefix="/api/v1")
        app.dependency_overrides[get_supabase] = lambda: db
        c = TestClient(app); key = wc.get_or_create_key(db, ORG)
        assert c.post(f"/api/v1/public/webchat/{key}/save-chat", json={"email": "a@b.co", "consent": True}).status_code == 401
        assert c.post(f"/api/v1/public/webchat/{key}/email-optout").status_code == 401
        tok = c.post(f"/api/v1/public/webchat/{key}/session", json={}).json()["data"]["token"]
        h = {"Authorization": f"Bearer {tok}"}
        assert c.post(f"/api/v1/public/webchat/{key}/save-chat", json={"email": "a@b.co", "consent": True}, headers=h).status_code == 422   # no contact yet
        assert c.post(f"/api/v1/public/webchat/{key}/email-optout", headers=h).status_code == 200
