"""
tests/unit/test_webchat_4b.py
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




CFG = dict(wa_followups=True, wa_template_name="chat_reply_v1", email_followups=True)
NUMBER = {"id": "n1", "org_id": ORG, "phone_id": "111", "access_token": "tok", "wa_sales_mode": "human"}


def _s(db, email=True, phone="08031234567", away=True, **state):
    from app.services import webchat_service as wc
    s, _ = wc.create_session(db, ORG, source="link", lead_id="L1", name="Ada Obi")
    s.update({"contact_phone": wc.normalise_phone(phone), "consent_at": _iso(_now()),
              "contact_email": "ada@example.com" if email else None,
              "last_activity_at": _iso(_now() - timedelta(minutes=30 if away else 1))})
    s["state"] = dict(state)
    for r in db.tables.setdefault("webchat_sessions", []):
        if r["id"] == s["id"]:
            r.update(s)
    return s


def _wadb(**cfg):
    db = _db(**{**CFG, **cfg})
    db.tables["whatsapp_numbers"] = [dict(NUMBER)]
    return db


def _mail():
    return patch("app.services.site_addon_billing_service._send_email", return_value=True)


def _fm():
    from contextlib import ExitStack
    st = ExitStack()
    m = SimpleNamespace(
        tpl=st.enter_context(patch("app.services.funnel_messaging.send_template", return_value=True)),
        cta=st.enter_context(patch("app.services.funnel_messaging.send_cta_url", return_value=True)),
        txt=st.enter_context(patch("app.services.funnel_messaging.send_text", return_value=True)),
    )
    m.close = st.close
    return m


def _open_window(db):
    db.tables["whatsapp_messages"] = [{"id": "w1", "org_id": ORG, "lead_id": "L1", "direction": "inbound", "channel": "whatsapp",
                                       "created_at": _iso(_now() - timedelta(hours=2))}]


class TestOptIn:
    def test_off_by_default(self):
        from app.services import webchat_service as wc
        assert wc.DEFAULT_CONFIG["wa_followups"] is False and wc.DEFAULT_CONFIG["wa_template_name"] == ""
        from app.services import webchat_whatsapp_service as wa
        db = _db(); s = _s(db)
        assert wa.can_whatsapp(s, _cfg(db)) is False

    def test_needs_switch_template_number_and_consent(self):
        from app.services import webchat_whatsapp_service as wa
        db = _wadb(); cfg = _cfg(db); s = _s(db)
        assert wa.can_whatsapp(s, cfg) is True
        assert wa.can_whatsapp(s, dict(cfg, wa_template_name="")) is False
        assert wa.can_whatsapp(dict(s, contact_phone=None), cfg) is False
        assert wa.can_whatsapp(dict(s, consent_at=None, phone_verified=False), cfg) is False
        assert wa.can_whatsapp(dict(s, consent_at=None, phone_verified=True), cfg) is True
        assert wa.can_whatsapp(dict(s, state={"wa_optout": True}), cfg) is False

    def test_settings_are_sanitised(self):
        from app.services import webchat_service as wc
        c = wc.sanitise_config({"wa_template_name": "Chat Reply-V1!", "wa_monthly_cap": 99999, "wa_followup_mode": "x",
                                "wa_template_lang": "en_GB; drop", "wa_followups": 1})
        assert c["wa_template_name"] == "chatreplyv1" and c["wa_monthly_cap"] == 5000
        assert c["wa_followup_mode"] == "fallback" and c["wa_template_lang"] == "en_GB" and c["wa_followups"] is True


class TestChannelChoice:
    def test_email_first_by_default(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db); fm = _fm()
        try:
            with _mail() as m:
                assert fu.notify_rep_reply(db, s, _cfg(db), "Tuesday 5pm works") == "email"
            assert m.called and not fm.tpl.called
        finally:
            fm.close()

    def test_whatsapp_when_no_email(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db, email=False); fm = _fm()
        try:
            with _mail() as m:
                assert fu.notify_rep_reply(db, s, _cfg(db), "hi") == "whatsapp"
            args, kw = fm.tpl.call_args
            assert not m.called and args[3] == "2348031234567" and args[4] == "chat_reply_v1"
            assert args[5][0] == "Ada" and args[5][2].startswith("http") and "?h=" in args[5][2]
            assert s["state"]["wa_count"] == 1
        finally:
            fm.close()

    def test_prefer_mode_uses_whatsapp_first(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(wa_followup_mode="prefer"); s = _s(db); fm = _fm()
        try:
            with _mail() as m:
                assert fu.notify_rep_reply(db, s, _cfg(db), "hi") == "whatsapp"
            assert not m.called
        finally:
            fm.close()

    def test_prefer_mode_falls_back_to_email_if_whatsapp_unavailable(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(wa_followup_mode="prefer"); db.tables["whatsapp_numbers"] = []; s = _s(db); fm = _fm()
        try:
            with _mail():
                assert fu.notify_rep_reply(db, s, _cfg(db), "hi") == "email"
        finally:
            fm.close()

    def test_never_two_channels_for_one_reply(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db); fm = _fm()
        try:
            with _mail() as m:
                fu.notify_rep_reply(db, s, _cfg(db), "one")
                assert fu.notify_rep_reply(db, s, _cfg(db), "two") is None
            assert m.call_count == 1 and not fm.tpl.called
        finally:
            fm.close()

    def test_visitor_still_on_page_gets_nothing(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db, away=False); fm = _fm()
        try:
            with _mail() as m:
                assert fu.notify_rep_reply(db, s, _cfg(db), "hi") is None
            assert not m.called and not fm.tpl.called
        finally:
            fm.close()


class TestWindowAndCosts:
    def test_open_window_uses_free_message_not_template(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); _open_window(db); s = _s(db, email=False); fm = _fm()
        try:
            assert fu.notify_rep_reply(db, s, _cfg(db), "Come at five") == "whatsapp"
            assert fm.cta.called and not fm.tpl.called
            assert "Come at five" in fm.cta.call_args.args[4]
        finally:
            fm.close()

    def test_closed_window_old_message_uses_template(self):
        from app.services import webchat_whatsapp_service as wa
        db = _wadb()
        db.tables["whatsapp_messages"] = [{"id": "w1", "org_id": ORG, "lead_id": "L1", "direction": "inbound", "channel": "whatsapp",
                                           "created_at": _iso(_now() - timedelta(hours=30))}]
        assert wa.window_open(db, _s(db)) is False

    def test_monthly_cap_stops_templates(self):
        from app.services import webchat_followup_service as fu, webchat_service as wc
        db = _wadb(wa_monthly_cap=1); fm = _fm()
        try:
            with patch.object(wc, "rate_limited", side_effect=[False, True]):     # first allowed, second over the cap
                assert fu.notify_rep_reply(db, _s(db, email=False), _cfg(db), "a") == "whatsapp"
                assert fu.notify_rep_reply(db, _s(db, email=False), _cfg(db), "b") is None
            assert fm.tpl.call_count == 1
        finally:
            fm.close()

    def test_three_templates_per_chat_max(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db, email=False, wa_count=3); fm = _fm()
        try:
            assert fu.notify_rep_reply(db, s, _cfg(db), "a") is None
            assert not fm.tpl.called
        finally:
            fm.close()

    def test_empty_metered_wallet_blocks_templates(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); db.tables["credit_wallets"] = [{"org_id": ORG, "balance_kobo": 0, "metering_enabled": True}]
        s = _s(db, email=False); fm = _fm()
        try:
            assert fu.notify_rep_reply(db, s, _cfg(db), "a") is None
            assert not fm.tpl.called
        finally:
            fm.close()

    def test_unmetered_business_is_not_blocked_by_wallet(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db, email=False); fm = _fm()
        try:
            assert fu.notify_rep_reply(db, s, _cfg(db), "a") == "whatsapp"
        finally:
            fm.close()

    def test_failed_send_does_not_count(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); s = _s(db, email=False)
        with patch("app.services.funnel_messaging.send_template", return_value=False):
            assert fu.notify_rep_reply(db, s, _cfg(db), "a") is None
        assert not s["state"].get("wa_count") and not s["state"].get("followup_reply_at")


class TestOtherMessages:
    def test_booking_confirmation_by_whatsapp_only_in_window_and_without_email(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); _open_window(db); s = _s(db, email=False); fm = _fm()
        try:
            fu.send_booking_confirmation(db, s, _cfg(db), "Braids; Tuesday 5pm")
            assert fm.txt.called and not fm.tpl.called
        finally:
            fm.close()
        db2 = _wadb(); s2 = _s(db2, email=False); fm2 = _fm()          # no window: nothing, no template
        try:
            fu.send_booking_confirmation(db2, s2, _cfg(db2), "Braids")
            assert not fm2.txt.called and not fm2.tpl.called
        finally:
            fm2.close()

    def test_order_link_by_whatsapp_has_a_pay_button(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); _open_window(db); s = _s(db, email=False); fm = _fm()
        try:
            fu.send_order_link(db, s, _cfg(db), "Silk Bonnet x1 = N5,000", "https://paystack.test/x")
            assert fm.cta.call_args.args[5:7] == ("Pay now", "https://paystack.test/x")
        finally:
            fm.close()

    def test_email_is_used_when_available(self):
        from app.services import webchat_followup_service as fu
        db = _wadb(); _open_window(db); s = _s(db); fm = _fm()
        try:
            with _mail() as m:
                fu.send_order_link(db, s, _cfg(db), "x", "https://paystack.test/x")
            assert m.called and not fm.cta.called
        finally:
            fm.close()


class TestOptOutAndTest:
    def test_stop_followups_stops_whatsapp_too(self):
        from app.services import webchat_email_service as em, webchat_followup_service as fu
        db = _wadb(); s = _s(db, email=False); fm = _fm()
        try:
            em.opt_out(db, s)
            assert fu.notify_rep_reply(db, s, _cfg(db), "a") is None and not fm.tpl.called
        finally:
            fm.close()

    def test_send_test_validates_and_sends_the_template(self):
        from app.services import webchat_whatsapp_service as wa
        db = _wadb(); cfg = _cfg(db)
        assert "template name" in wa.send_test(db, ORG, dict(cfg, wa_template_name=""), "08031234567")["error"]
        assert "phone" in wa.send_test(db, ORG, cfg, "abc")["error"]
        fm = _fm()
        try:
            assert wa.send_test(db, ORG, cfg, "08031234567") == {"sent": True}
            assert fm.tpl.call_args.args[4] == "chat_reply_v1"
        finally:
            fm.close()
        with patch("app.services.funnel_messaging.send_template", return_value=False):
            assert "approved" in wa.send_test(db, ORG, cfg, "08031234567")["error"]
        db.tables["whatsapp_numbers"] = []
        assert "no connected" in wa.send_test(db, ORG, cfg, "08031234567")["error"]

    def test_rep_send_still_triggers_followup(self):
        from app.services import webchat_service as wc
        db = _wadb(); s = _s(db, email=False); fm = _fm()
        try:
            wc.rep_send(db, ORG, "L1", "see you at five", "u1")
            assert fm.tpl.called
        finally:
            fm.close()
