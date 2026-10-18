"""
tests/unit/test_webchat_1.py
----------------------------
WEBCHAT-1/2: config, keys, sessions, hand-off, scripted flow, contact capture,
rep replies, WhatsApp redirect, public routes, sweep, wiring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def _db(enabled=True, menu=None, **extra):
    cfg = {"enabled": enabled, "menu": menu if menu is not None else [
        {"id": "hours", "label": "Opening hours", "answer": "We open 9 to 6.", "keywords": ["hours", "open"]},
        {"id": "book", "label": "Book an appointment", "action": "booking", "keywords": ["book"]},
        {"id": "team", "label": "Talk to us", "action": "human", "keywords": ["human"]},
    ]}
    return FakeDB(organisations=[{"id": ORG, "name": "Glow Salon", "webchat_config": cfg},
                                 {"id": OTHER, "name": "Other", "webchat_config": {"enabled": True}}], **extra)


@pytest.fixture(autouse=True)
def _no_rate_limit():
    from app.services import webchat_service as wc
    with patch.object(wc, "rate_limited", return_value=False):
        yield


# ═════════════════════════ config ═══════════════════════════════════════════

class TestConfig:
    def test_defaults_off_and_business_name_falls_back(self):
        from app.services import webchat_service as wc
        db = FakeDB(organisations=[{"id": ORG, "name": "Glow Salon", "webchat_config": {}}])
        cfg = wc.get_config(db, ORG)
        assert cfg["enabled"] is False and cfg["business_name"] == "Glow Salon"

    def test_sanitise_drops_bad_links_and_caps_menu(self):
        from app.services import webchat_service as wc
        raw = {"menu": [{"id": f"i{n}", "label": f"Item {n}", "answer": "x",
                         "link": {"label": "go", "url": "javascript:alert(1)"}} for n in range(30)],
               "brand_color": "red; background:url(x)"}
        out = wc.sanitise_config(raw)
        assert len(out["menu"]) <= wc.MENU_MAX
        assert all(not (m.get("link") or {}).get("url", "").startswith("javascript") for m in out["menu"])
        assert out.get("brand_color", "#028090").startswith("#")

    def test_public_view_hides_private_settings(self):
        from app.services import webchat_service as wc
        v = wc.public_view(wc.get_config(_db(), ORG))
        assert "redirect_text" not in v and "enabled" not in v
        assert all(set(m) == {"id", "label"} for m in v["menu"])

    def test_save_config_merges(self):
        from app.services import webchat_service as wc
        db = _db()
        wc.save_config(db, ORG, {"greeting": "Welcome!"})
        cfg = wc.get_config(db, ORG)
        assert cfg["greeting"] == "Welcome!" and cfg["enabled"] is True and len(cfg["menu"]) == 3


# ═════════════════════════ keys ═════════════════════════════════════════════

class TestKeys:
    def test_key_is_stable_and_resolves_org(self):
        from app.services import webchat_service as wc
        db = _db()
        k1 = wc.get_or_create_key(db, ORG)
        assert k1.startswith("wc_") and wc.get_or_create_key(db, ORG) == k1
        assert wc.resolve_key(db, k1)["org_id"] == ORG
        assert wc.get_or_create_key(db, OTHER) != k1

    def test_disabled_org_or_bad_key_does_not_resolve(self):
        from app.services import webchat_service as wc
        db = _db(enabled=False)
        k = wc.get_or_create_key(db, ORG)
        assert wc.resolve_key(db, k) is None
        assert wc.resolve_key(db, "../etc/passwd") is None
        assert wc.resolve_key(db, "wc_doesnotexist123") is None

    def test_chat_link_has_source_tag(self):
        from app.services import webchat_service as wc
        db = _db()
        with patch.object(wc, "public_base", return_value="https://app.example"):
            link = wc.chat_link(db, ORG, "instagram")
        assert link.startswith("https://app.example/c/wc_") and link.endswith("?s=instagram")


# ═════════════════════════ sessions ═════════════════════════════════════════

class TestSessions:
    def test_token_stored_hashed_and_org_scoped(self):
        from app.services import webchat_service as wc
        db = _db()
        s, token = wc.create_session(db, ORG, source="Instagram!!")
        assert s["source"] == "instagram"
        stored = db.rows("webchat_sessions")[0]
        assert token not in str(stored) and stored["token_hash"] == wc.hash_token(token)
        assert wc.authenticate(db, ORG, token)["id"] == s["id"]
        assert wc.authenticate(db, OTHER, token) is None      # another business cannot use it
        assert wc.authenticate(db, ORG, "x" * 30) is None
        assert wc.authenticate(db, ORG, None) is None

    def test_expired_and_closed_sessions_rejected(self):
        from app.services import webchat_service as wc
        db = _db()
        s, token = wc.create_session(db, ORG)
        db.rows("webchat_sessions")[0]["expires_at"] = _iso(_now() - timedelta(minutes=1))
        assert wc.authenticate(db, ORG, token) is None
        db.rows("webchat_sessions")[0].update(expires_at=_iso(_now() + timedelta(days=1)), status="closed")
        assert wc.authenticate(db, ORG, token) is None

    def test_expiry_slides_forward_when_used(self):
        from app.services import webchat_service as wc
        db = _db()
        s, token = wc.create_session(db, ORG)
        row = db.rows("webchat_sessions")[0]
        row["last_activity_at"] = _iso(_now() - timedelta(hours=2))
        row["expires_at"] = _iso(_now() + timedelta(days=2))
        wc.authenticate(db, ORG, token)
        assert row["expires_at"] > _iso(_now() + timedelta(days=29))

    def test_handoff_is_single_use(self):
        from app.services import webchat_service as wc
        db = _db()
        with patch.object(wc, "public_base", return_value="https://x.test"):
            link = wc.create_handoff(db, ORG, lead_id="L1", phone="2348030000000", name="Ada", key="wc_abcdefgh12")
        token = link.split("?h=")[1]
        first = wc.exchange_handoff(db, ORG, token)
        assert first is not None and first[0]["lead_id"] == "L1"
        assert wc.authenticate(db, ORG, first[1])["lead_id"] == "L1"
        assert wc.exchange_handoff(db, ORG, token) is None          # second tap fails
        assert any(e["kind"] == "handoff_sent" for e in db.rows("webchat_events"))

    def test_handoff_expired_or_wrong_org(self):
        from app.services import webchat_service as wc
        db = _db()
        with patch.object(wc, "public_base", return_value="https://x.test"):
            link = wc.create_handoff(db, ORG, lead_id="L1", phone="2348030000000", name="Ada", key="wc_abcdefgh12")
        token = link.split("?h=")[1]
        assert wc.exchange_handoff(db, OTHER, token) is None
        db.rows("webchat_sessions")[0]["handoff_expires_at"] = _iso(_now() - timedelta(hours=1))
        assert wc.exchange_handoff(db, ORG, token) is None
        assert wc.exchange_handoff(db, ORG, "short") is None


# ═════════════════════════ contact ══════════════════════════════════════════

class TestContact:
    def test_phone_normalisation(self):
        from app.services.webchat_service import normalise_phone
        assert normalise_phone("0803 123 4567") == "2348031234567"
        assert normalise_phone("+234 803 123 4567") == "2348031234567"
        assert normalise_phone("12345") is None and normalise_phone(None) is None

    def test_validation_messages(self):
        from app.services.webchat_service import validate_contact as v
        assert v("A", "08031234567", None, True)[1]                      # name too short
        assert v("Ada", "123", None, True)[1]                            # bad phone
        assert v("Ada", None, "bad", True)[1]                            # bad email
        assert v("Ada", None, None, True)[1]                             # nothing to reach them on
        assert v("Ada", "08031234567", None, False)[1]                   # no consent
        clean, err = v("Ada", "08031234567", "A@B.com", True)
        assert err is None and clean["email"] == "a@b.com" and clean["phone"] == "2348031234567"
        assert v(None, None, "a@b.com", True, require_name=False)[1] is None

    def test_save_contact_creates_lead_and_flushes_history(self):
        from app.services import webchat_service as wc
        db = _db()
        s, _ = wc.create_session(db, ORG, source="qr")
        wc.append_message(db, s, "bot", "Hi")
        wc.append_message(db, s, "visitor", "What time do you open?")
        assert len(s["history"]) == 2 and not db.rows("whatsapp_messages")
        clean, _ = wc.validate_contact("Ada Obi", "08031234567", None, True)
        with patch("app.services.funnel_service._find_org_lead", return_value=None), \
             patch("app.services.lead_service.create_lead", return_value={"id": "LEAD1"}) as cl:
            s = wc.save_contact(db, s, clean)
        assert s["lead_id"] == "LEAD1" and s["history"] == []
        assert cl.call_args.kwargs["user_id"] is None
        assert cl.call_args.kwargs["payload"].source == "landing_page"
        msgs = db.rows("whatsapp_messages")
        assert len(msgs) == 2 and all(m["channel"] == "webchat" and m["lead_id"] == "LEAD1" for m in msgs)
        assert {m["direction"] for m in msgs} == {"inbound", "outbound"}
        lead_patch = [c for c in db.calls if c[0] == "leads" and c[1] == "update"][0][2]
        assert lead_patch["source_detail"] == "webchat:qr" and lead_patch["consent_version"] == wc.CONSENT_VERSION

    def test_existing_lead_reused(self):
        from app.services import webchat_service as wc
        db = _db()
        s, _ = wc.create_session(db, ORG)
        clean, _ = wc.validate_contact("Ada Obi", "08031234567", None, True)
        with patch("app.services.funnel_service._find_org_lead", return_value="EXIST"), \
             patch("app.services.lead_service.create_lead") as cl:
            s = wc.save_contact(db, s, clean)
        assert s["lead_id"] == "EXIST" and not cl.called


# ═════════════════════════ flow ═════════════════════════════════════════════

def _session(db, **kw):
    from app.services import webchat_service as wc
    s, _ = wc.create_session(db, ORG, source="link")
    s.update(kw)
    return s


class TestFlow:
    def test_menu_tap_answers_then_asks_for_contact(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        r = f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
        assert [m["role"] for m in r["messages"]] == ["visitor", "bot"]
        assert r["messages"][1]["text"] == "We open 9 to 6."
        assert r["ask_contact"] is True and r["human"] is False
        assert any(e["kind"] == "started" for e in db.rows("webchat_events"))

    def test_typed_keyword_matches_and_unknown_gets_fallback(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        r = f.handle_message(db, s, cfg, kind="text", text="what are your opening hours?")
        assert r["messages"][1]["text"] == "We open 9 to 6."
        r = f.handle_message(db, s, cfg, kind="text", text="zzzz qqqq")
        assert r["messages"][1]["text"] == cfg["fallback"]

    def test_unknown_menu_id_and_empty_text_do_nothing(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        assert f.handle_message(db, s, cfg, kind="menu", menu_id="nope")["messages"] == []
        assert f.handle_message(db, s, cfg, kind="text", text="   ")["messages"] == []
        assert s.get("history") == []

    def test_booking_needs_contact_first_then_shows_form(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        r = f.handle_message(db, s, cfg, kind="menu", menu_id="book")
        assert r["ask_contact"] is True and r["form"] is None and s["state"]["pending"] == "booking"
        with patch("app.services.funnel_service._find_org_lead", return_value=None), \
             patch("app.services.lead_service.create_lead", return_value={"id": "L9"}):
            res = f.handle_contact(db, s, cfg, name="Ada Obi", phone="08031234567", email=None, consent=True)
        assert res["form"] == "booking" and s["state"].get("pending") is None

    def test_contact_error_returned_not_raised(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        assert "error" in f.handle_contact(db, s, cfg, name="Ada", phone="08031234567", email=None, consent=False)

    def test_booking_saves_notifies_and_logs(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db, lead_id="L1"), wc.get_config(db, ORG)
        with patch.object(wc, "notify_managers") as nm, patch("app.services.lead_service.write_timeline_event") as tl:
            r = f.handle_booking(db, s, cfg, {"service": "Braids", "when": "Sat 10am"})
        assert "error" not in r and nm.called and tl.called
        assert any(e["kind"] == "booked" for e in db.rows("webchat_events"))
        assert r["messages"][-1]["text"] == cfg["booking_done"]

    def test_booking_requires_fields_and_contact(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        cfg = wc.get_config(db, ORG)
        assert "error" in f.handle_booking(db, _session(db), cfg, {"service": "x", "when": "y"})
        assert "error" in f.handle_booking(db, _session(db, lead_id="L1"), cfg, {"service": "x"})

    def test_talk_to_us_takes_over_and_notifies_once(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db), wc.get_config(db, ORG)
        with patch.object(wc, "notify_managers") as nm:
            r = f.handle_message(db, s, cfg, kind="menu", menu_id="team")
            assert r["human"] is True and s["state"]["human"] is True
            f.handle_message(db, s, cfg, kind="text", text="hello?")      # bot stays quiet
            f.handle_message(db, s, cfg, kind="text", text="anyone?")
        assert nm.call_count == 1                                          # 10-minute throttle
        bot = [m for m in s["history"] if m["role"] == "bot"]
        assert len(bot) == 1                                               # only the hand-over line

    def test_email_asked_once_for_whatsapp_verified(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db, lead_id="L1", phone_verified=True), wc.get_config(db, ORG)
        r1 = f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
        r2 = f.handle_message(db, s, cfg, kind="menu", menu_id="hours")
        assert r1["ask_email"] is True and r1["ask_contact"] is False
        assert r2["ask_email"] is False

    def test_turn_cap(self):
        from app.services import webchat_flow_service as f, webchat_service as wc
        db = _db()
        s, cfg = _session(db, turn_count=f.MAX_TURNS_PER_SESSION), wc.get_config(db, ORG)
        r = f.handle_message(db, s, cfg, kind="text", text="hi")
        assert r["human"] is True and "limit" in r["messages"][0]["text"]


# ═════════════════════════ rep reply ════════════════════════════════════════

class TestRepSend:
    def test_reply_stored_without_any_meta_call(self):
        from app.services import webchat_service as wc
        db = _db()
        s, _ = wc.create_session(db, ORG, lead_id="L1")
        with patch("app.services.whatsapp_service._call_meta_send") as meta:
            msg = wc.rep_send(db, ORG, "L1", "Hello Ada", "USER1")
        assert not meta.called and msg["role"] == "rep"
        row = db.rows("whatsapp_messages")[0]
        assert row["channel"] == "webchat" and row["direction"] == "outbound" and row["sent_by"] == "USER1"
        assert db.rows("webchat_sessions")[0]["state"]["human"] is True
        # the visitor's poll sees it as a rep message
        assert wc.list_messages(db, db.rows("webchat_sessions")[0])[0]["role"] == "rep"

    def test_no_chat_or_ended_chat(self):
        from app.services import webchat_service as wc
        db = _db()
        with pytest.raises(LookupError):
            wc.rep_send(db, ORG, "L1", "hi", "U")
        wc.create_session(db, ORG, lead_id="L1")
        db.rows("webchat_sessions")[0]["status"] = "expired"
        with pytest.raises(PermissionError):
            wc.rep_send(db, ORG, "L1", "hi", "U")


# ═════════════════════════ WhatsApp redirect ════════════════════════════════

NUMBER = {"org_id": ORG, "phone_id": "PID", "access_token": "tok", "wa_sales_mode": "webchat_redirect"}


class TestRedirect:
    def test_compose_text(self):
        from app.services.webchat_redirect_service import compose_text
        t = compose_text({"redirect_text": "Hi {name}, chat here {link}", "redirect_mode": "always", "menu": []},
                         "Ada Obi", "https://x/c/k")
        assert t == "Hi Ada, chat here https://x/c/k"
        t = compose_text({"redirect_text": "Hello", "redirect_mode": "always", "menu": []}, None, "https://x/c/k")
        assert t.endswith("\nhttps://x/c/k")
        t = compose_text({"redirect_text": "Hi {name} {link}", "redirect_mode": "menu_first",
                          "menu": [{"label": "Prices"}, {"label": "Book"}]}, "Ada", "https://x/c/k")
        assert "• Prices" in t and "• Book" in t and t.endswith("https://x/c/k")

    def _run(self, db, text="hi"):
        from app.services import webchat_redirect_service as r
        with patch("app.services.funnel_service._get_or_create_lead", return_value="L1"), \
             patch("app.services.whatsapp_service.send_agent_text_message") as send, \
             patch("app.services.webchat_service.notify_managers") as nm, \
             patch("app.services.webchat_service.public_base", return_value="https://x.test"):
            r.handle_inbound(db, NUMBER, "2348031234567", "Ada Obi", "text", text, "wamid.1")
        return send, nm

    def test_first_message_gets_exactly_one_link_reply(self):
        db = _db()
        send, nm = self._run(db)
        assert send.call_count == 1
        kw = send.call_args.kwargs
        assert kw["org_id"] == ORG and kw["phone_id"] == "PID" and "/c/wc_" in kw["message"] and "?h=" in kw["message"]
        assert db.rows("webchat_redirects")[0]["sent_count"] == 1
        assert db.rows("whatsapp_messages")[0]["direction"] == "inbound"        # their message kept
        assert any(e["kind"] == "redirect_sent" for e in db.rows("webchat_events"))
        assert not nm.called

    def test_second_message_within_a_day_notifies_only(self):
        db = _db()
        self._run(db)
        send, nm = self._run(db, "are you there?")
        assert send.call_count == 0 and nm.call_count == 1
        assert db.rows("webchat_redirects")[0]["sent_count"] == 1

    def test_notifications_are_throttled(self):
        db = _db()
        self._run(db)
        self._run(db, "one")
        send, nm = self._run(db, "two")
        assert nm.call_count == 0

    def test_resend_after_cooldown(self):
        db = _db()
        self._run(db)
        db.rows("webchat_redirects")[0]["last_sent_at"] = _iso(_now() - timedelta(hours=25))
        send, _ = self._run(db, "hello again")
        assert send.call_count == 1 and db.rows("webchat_redirects")[0]["sent_count"] == 2

    def test_chat_switched_off_never_sends(self):
        db = _db(enabled=False)
        send, nm = self._run(db)
        assert send.call_count == 0 and nm.call_count == 1

    def test_never_raises(self):
        from app.services import webchat_redirect_service as r
        with patch("app.services.funnel_service._get_or_create_lead", side_effect=RuntimeError("boom")):
            r.handle_inbound(_db(), NUMBER, "2348031234567", None, "text", "hi", None)


# ═════════════════════════ public routes ════════════════════════════════════

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_supabase
    from app.routers import public_webchat
    app = FastAPI()
    app.include_router(public_webchat.router, prefix="/api/v1")
    db = _db()
    app.dependency_overrides[get_supabase] = lambda: db
    from app.services import webchat_service as wc
    key = wc.get_or_create_key(db, ORG)
    c = TestClient(app)
    c.db, c.key = db, key
    return c


def _start(c, **body):
    r = c.post(f"/api/v1/public/webchat/{c.key}/session", json=body)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    return d, {"Authorization": f"Bearer {d['token']}"}


class TestPublicRoutes:
    def test_unknown_or_disabled_key_is_404(self, client):
        assert client.get("/api/v1/public/webchat/wc_nothere12345/config").status_code == 404
        client.db.rows("organisations")[0]["webchat_config"]["enabled"] = False
        assert client.get(f"/api/v1/public/webchat/{client.key}/config").status_code == 404

    def test_config_is_public_view_with_privacy_headers(self, client):
        r = client.get(f"/api/v1/public/webchat/{client.key}/config")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
        assert "redirect_text" not in r.json()["data"]

    def test_session_starts_with_greeting_and_token(self, client):
        d, _ = _start(client, source="instagram")
        assert d["token"] and d["messages"][0]["role"] == "bot" and d["has_contact"] is False
        assert [e["kind"] for e in client.db.rows("webchat_events")] == ["visit"]

    def test_message_requires_valid_token(self, client):
        url = f"/api/v1/public/webchat/{client.key}/message"
        assert client.post(url, json={"kind": "text", "text": "hi"}).status_code == 401
        assert client.post(url, json={"kind": "text", "text": "hi"}, headers={"Authorization": "Bearer " + "z" * 30}).status_code == 401

    def test_full_conversation(self, client):
        d, h = _start(client)
        r = client.post(f"/api/v1/public/webchat/{client.key}/message", json={"kind": "menu", "menu_id": "hours"}, headers=h)
        assert r.status_code == 200 and r.json()["data"]["ask_contact"] is True
        with patch("app.services.funnel_service._find_org_lead", return_value=None), \
             patch("app.services.lead_service.create_lead", return_value={"id": "L7"}):
            r = client.post(f"/api/v1/public/webchat/{client.key}/contact", headers=h,
                            json={"name": "Ada Obi", "phone": "08031234567", "consent": True})
        assert r.status_code == 200
        r = client.get(f"/api/v1/public/webchat/{client.key}/messages", headers=h)
        texts = [m["text"] for m in r.json()["data"]["messages"]]
        assert "We open 9 to 6." in texts and "Thank you. We have your details." in texts
        r = client.get(f"/api/v1/public/webchat/{client.key}/session", headers=h)
        assert r.json()["data"]["has_contact"] is True

    def test_bad_contact_is_422_and_honeypot_is_silent(self, client):
        d, h = _start(client)
        url = f"/api/v1/public/webchat/{client.key}/contact"
        r = client.post(url, headers=h, json={"name": "Ada Obi", "phone": "08031234567", "consent": False})
        assert r.status_code == 422
        with patch("app.services.lead_service.create_lead") as cl:
            r = client.post(url, headers=h, json={"name": "Bot", "phone": "08031234567", "consent": True, "website": "http://spam"})
        assert r.status_code == 200 and not cl.called

    def test_session_of_one_business_is_useless_at_another(self, client):
        from app.services import webchat_service as wc
        d, h = _start(client)
        other_key = wc.get_or_create_key(client.db, OTHER)
        assert client.get(f"/api/v1/public/webchat/{other_key}/session", headers=h).status_code == 401

    def test_handoff_link_logs_the_visitor_in(self, client):
        from app.services import webchat_service as wc
        with patch.object(wc, "public_base", return_value="https://x.test"):
            link = wc.create_handoff(client.db, ORG, lead_id="L1", phone="2348031234567", name="Ada Obi", key=client.key)
        tok = link.split("?h=")[1]
        d, h = _start(client, handoff=tok)
        assert d["has_contact"] is True and d["verified_phone"] is True and d["needs_email"] is True
        d2 = client.post(f"/api/v1/public/webchat/{client.key}/session", json={"handoff": tok}).json()["data"]
        assert d2["has_contact"] is False                      # reused link gives a fresh anonymous chat

    def test_rate_limit_returns_429(self, client):
        from app.services import webchat_service as wc
        with patch.object(wc, "rate_limited", return_value=True):
            assert client.post(f"/api/v1/public/webchat/{client.key}/session", json={}).status_code == 429


# ═════════════════════════ sweep + worker ═══════════════════════════════════

class TestSweep:
    def _db(self):
        past, future = _iso(_now() - timedelta(days=1)), _iso(_now() + timedelta(days=1))
        return FakeDB(webchat_sessions=[
            {"id": "a", "status": "active", "expires_at": past, "lead_id": None, "history": [{"x": 1}]},
            {"id": "b", "status": "active", "expires_at": past, "lead_id": "L1", "history": []},
            {"id": "c", "status": "active", "expires_at": future, "lead_id": None, "history": [{"x": 1}]},
        ])

    def test_dry_run_changes_nothing(self):
        from app.services import webchat_service as wc
        db = self._db()
        assert wc.sweep(db, dry_run=True)["expired"] == 2
        assert all(r["status"] == "active" for r in db.rows("webchat_sessions"))

    def test_expires_and_clears_anonymous_history(self):
        from app.services import webchat_service as wc
        db = self._db()
        wc.sweep(db)
        by = {r["id"]: r for r in db.rows("webchat_sessions")}
        assert by["a"]["status"] == "expired" and by["a"]["history"] == []
        assert by["b"]["status"] == "expired" and by["c"]["status"] == "active" and by["c"]["history"]

    def test_worker_never_raises(self):
        from app.workers import webchat_worker as w
        with patch.object(w, "get_supabase", return_value=self._db()), patch.object(w, "write_worker_log"):
            assert w.run_webchat_sweep(dry_run=True)["expired"] == 2
        with patch.object(w, "get_supabase", return_value=MagicMock()), \
             patch.object(w.webchat_service, "sweep", side_effect=RuntimeError("x")), patch.object(w, "write_worker_log"):
            assert "error" in w.run_webchat_sweep()


# ═════════════════════════ wiring ═══════════════════════════════════════════

class TestWiring:
    def test_meta_msg_id_helper(self):
        from app.services.whatsapp_service import _meta_msg_id
        assert _meta_msg_id({"messages": [{"id": "wamid.X"}]}) == "wamid.X"
        assert _meta_msg_id({}) is None and _meta_msg_id(None) is None and _meta_msg_id({"messages": []}) is None

    def test_webhook_has_redirect_intercept_before_funnel(self):
        import inspect
        from app.routers import webhooks
        src = inspect.getsource(webhooks)
        a, b = src.index("WEBCHAT-2: WhatsApp redirect numbers"), src.index("FUNNEL-1A: Event Funnel numbers")
        assert a < b and "webchat_redirect_service" in src[a:b] and "_is_org_owner" in src[a:b]

    def test_admin_accepts_webchat_redirect_mode(self):
        import inspect
        from app.routers import admin
        assert inspect.getsource(admin).count("webchat_redirect") >= 2

    def test_routes_and_beat_registered(self):
        import app.main as m
        from app.workers.celery_app import celery_app
        paths = {r.path for r in m.app.routes}
        assert "/api/v1/public/webchat/{key}/message" in paths and "/api/v1/conversations/webchat/send" in paths
        assert "webchat-sweep" in celery_app.conf.beat_schedule

    def test_staff_routes_need_manager_role(self):
        from fastapi import HTTPException
        from app.routers import webchat
        with pytest.raises(HTTPException) as e:
            webchat._require_manager({"roles": {"template": "sales_agent"}})
        assert e.value.status_code == 403
