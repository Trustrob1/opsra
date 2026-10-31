"""BOOKING-2C - WhatsApp slot picker: list building, tamper-proof replies, booking through the guarded path, cancel, expiry."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import booking_service as bk
from app.services import booking_wa_service as bw

ORG_ID, LEAD_ID = "org-1", "lead-1"
ORG = {"id": ORG_ID, "timezone": "Africa/Lagos"}
CFG = {"native_enabled": True, "label": "consultation", "cancel_cutoff_hours": 24}
SVC = {"id": "svc-1", "name": "Consultation", "duration_minutes": 30}
LEAD = {"id": LEAD_ID, "full_name": "Ada Obi", "whatsapp": "2348012345678"}
T0 = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)      # 09:00 Lagos


class Q:
    def __init__(self, db, name): self.db, self.name, self.f, self.op, self.p = db, name, [], "select", None
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f.append(("eq", k, v)); return self
    def gte(self, k, v): self.f.append(("gte", k, v)); return self
    def is_(self, k, v): self.f.append(("is", k, v)); return self
    def in_(self, *a): return self
    def limit(self, *a): return self
    def order(self, *a, **k): return self
    def insert(self, p): self.op, self.p = "insert", p; return self
    def update(self, p): self.op, self.p = "update", p; return self
    def _match(self, r):
        for kind, k, v in self.f:
            if kind == "eq" and r.get(k) != v: return False
            if kind == "gte" and str(r.get(k) or "") < str(v): return False
            if kind == "is" and v == "null" and r.get(k) is not None: return False
        return True
    def execute(self):
        t = self.db.t.setdefault(self.name, [])
        if self.op == "insert":
            row = {"id": f"{self.name}-{len(t)+1}", "created_at": datetime.now(timezone.utc).isoformat(), **self.p}
            t.append(row); return MagicMock(data=[row])
        if self.op == "update":
            hit = [r for r in t if self._match(r)]
            for r in hit: r.update(self.p)
            return MagicMock(data=hit)
        return MagicMock(data=[r for r in t if self._match(r)])


class DB:
    def __init__(self, **t): self.t = {k: list(v) for k, v in t.items()}
    def table(self, n): return Q(self, n)


def _sess(db, **kw):
    row = {"id": "s1", "org_id": ORG_ID, "lead_id": LEAD_ID, "service_id": "svc-1", "demo_id": None, "step": "day", "status": "active",
           "offered": {"days": ["2026-11-03", "2026-11-04"], "times": [], "date": None}, "chosen_start": None,
           "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(), **kw}
    db.t.setdefault("booking_wa_sessions", []).append(row)
    return row


@pytest.fixture
def env():
    sent = []
    with patch("app.services.demo_service._confirm_lead_in_org", return_value=LEAD), \
         patch.object(bk, "get_org", return_value=ORG), patch.object(bk, "get_settings", return_value=CFG), \
         patch.object(bk, "get_service", return_value=SVC), patch.object(bk, "list_services", return_value=[SVC]), \
         patch.object(bw, "_send_interactive", side_effect=lambda db, o, lead, inter, log: sent.append(("i", inter)) or True), \
         patch.object(bw, "_send_text", side_effect=lambda db, o, lead, text: sent.append(("t", text)) or True):
        yield sent


def _rows(sent):
    return [r["id"] for k, i in sent if k == "i" and i["type"] == "list" for r in i["action"]["sections"][0]["rows"]]


def test_reply_id_from_list_button_and_template_quick_reply():
    assert bw.reply_id_from_message({"interactive": {"list_reply": {"id": "bk:d:0", "title": "Mon"}}}) == ("bk:d:0", "Mon")
    assert bw.reply_id_from_message({"interactive": {"button_reply": {"id": "bk:ok", "title": "Confirm"}}}) == ("bk:ok", "Confirm")
    assert bw.reply_id_from_message({"type": "button", "button": {"payload": "bk:cx:d1", "text": "Cancel"}}) == ("bk:cx:d1", "Cancel")
    assert bw.is_picker_reply("bk:ok") and not bw.is_picker_reply("triage:menu_1") and not bw.is_picker_reply(None)


def test_day_list_has_at_most_ten_rows_with_more_days(env):
    db = DB()
    days = [date(2026, 11, 3) + timedelta(days=i) for i in range(14)]
    sess = _sess(db, offered={"days": [d.isoformat() for d in days], "times": [], "date": None})
    bw._send_day_list(db, ORG_ID, LEAD, ORG, CFG, sess, 0)
    ids = _rows(env)
    assert len(ids) == 10 and ids[-1] == "bk:md:9" and ids[0] == "bk:d:0"
    env.clear(); bw._send_day_list(db, ORG_ID, LEAD, ORG, CFG, sess, 9)
    assert _rows(env) == ["bk:d:9", "bk:d:10", "bk:d:11", "bk:d:12", "bk:d:13"]


def test_time_list_pages_and_always_offers_other_day(env):
    times = [T0 + timedelta(minutes=30 * i) for i in range(20)]
    bw._send_time_list(DB(), ORG_ID, LEAD, ORG, CFG, {}, date(2026, 11, 3), times, 0)
    ids = _rows(env)
    assert len(ids) == 10 and ids[-2:] == ["bk:mt:8", "bk:back"]
    env.clear(); bw._send_time_list(DB(), ORG_ID, LEAD, ORG, CFG, {}, date(2026, 11, 3), times[:9], 0)
    assert len(_rows(env)) == 10 and _rows(env)[-1] == "bk:back"
    env.clear(); bw._send_time_list(DB(), ORG_ID, LEAD, ORG, CFG, {}, date(2026, 11, 3), times, 0)
    assert all(len(r["title"]) <= 24 for k, i in env if i["type"] == "list" for r in i["action"]["sections"][0]["rows"])


def test_choosing_a_day_shows_that_days_times_and_remembers_them(env):
    db = DB(); _sess(db)
    with patch.object(bw, "_times_on", return_value=[T0, T0 + timedelta(hours=1)]):
        assert bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:d:0") is True
    s = db.t["booking_wa_sessions"][0]
    assert s["step"] == "time" and s["offered"]["date"] == "2026-11-03" and len(s["offered"]["times"]) == 2
    assert _rows(env) == ["bk:t:0", "bk:t:1", "bk:back"]


def test_tampered_reply_ids_never_book_and_restart_the_day_list(env):
    db = DB(); _sess(db, step="time", offered={"days": ["2026-11-03"], "times": [T0.isoformat()], "date": "2026-11-03"})
    with patch.object(bk, "book_slot") as book:
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:t:99")        # index outside what was offered
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:ok")          # confirm without having chosen a time
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:t:abc")
    book.assert_not_called()


def test_confirm_books_the_stored_time_not_anything_from_the_reply(env):
    db = DB(); _sess(db, step="confirm", chosen_start=T0.isoformat(), offered={"days": ["2026-11-03"], "times": [T0.isoformat()], "date": "2026-11-03"})
    with patch.object(bk, "book_slot", return_value={"id": "demo-1", "status": "confirmed"}) as book:
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:ok")
    assert book.call_args.args[4] == T0 and book.call_args.kwargs["source"] == "whatsapp"
    assert db.t["booking_wa_sessions"][0]["status"] == "done"
    assert any(k == "i" and i["type"] == "button" and i["action"]["buttons"][0]["reply"]["id"] == "bk:rs:demo-1" for k, i in env)


def test_approval_needed_service_says_it_will_confirm_later(env):
    db = DB(); _sess(db, step="confirm", chosen_start=T0.isoformat(), offered={"days": [], "times": [], "date": None})
    with patch.object(bk, "book_slot", return_value={"id": "demo-1", "status": "pending_assignment"}):
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:ok")
    assert any(k == "t" and "confirm it shortly" in t for k, t in env)
    assert not any(k == "i" for k, _ in env)


def test_time_just_taken_reoffers_fresh_times(env):
    db = DB(); _sess(db, step="confirm", chosen_start=T0.isoformat(), offered={"days": ["2026-11-03"], "times": [T0.isoformat()], "date": "2026-11-03"})
    with patch.object(bk, "book_slot", side_effect=bk._err(409, "SLOT_TAKEN", "x")), \
         patch.object(bw, "_times_on", return_value=[T0 + timedelta(hours=2)]):
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:ok")
    assert any(k == "t" and "just taken" in t for k, t in env) and _rows(env)[0] == "bk:t:0"
    assert db.t["booking_wa_sessions"][0]["status"] == "active"


def test_cancel_only_works_on_this_leads_own_booking(env):
    live = {"id": "d1", "org_id": ORG_ID, "lead_id": LEAD_ID, "status": "confirmed", "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}
    other = {**live, "id": "d2", "lead_id": "someone-else"}
    db = DB(lead_demos=[live, other])
    with patch.object(bk, "_check_cutoff"), patch.object(bk, "cancel_booking") as cancel:
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:cxy:d2")       # another lead's booking: refused
        cancel.assert_not_called()
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:cx:d1")        # asks "are you sure?" first
        cancel.assert_not_called()
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:cxy:d1")
    cancel.assert_called_once()
    assert cancel.call_args.kwargs["by"] == "lead"


def test_cutoff_blocks_change_with_the_businesss_message(env):
    db = DB(lead_demos=[{"id": "d1", "org_id": ORG_ID, "lead_id": LEAD_ID, "status": "confirmed"}])
    with patch.object(bk, "_check_cutoff", side_effect=bk._err(400, "TOO_LATE", "Bookings can only be changed 24 hours ahead.")), \
         patch.object(bk, "cancel_booking") as cancel:
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:cxy:d1")
    cancel.assert_not_called()
    assert any(k == "t" and "24 hours" in t for k, t in env)


def test_expired_conversation_starts_again(env):
    db = DB(); _sess(db, expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    with patch.object(bw, "start_picker") as start:
        bw.handle_reply(db, ORG_ID, LEAD_ID, "bk:d:0")
    start.assert_called_once()
    assert db.t["booking_wa_sessions"][0]["status"] == "expired"


def test_free_text_ends_the_conversation():
    db = DB(); _sess(db)
    bw.abandon_if_active(db, ORG_ID, LEAD_ID)
    assert db.t["booking_wa_sessions"][0]["status"] == "expired"
    bw.abandon_if_active(db, ORG_ID, None)      # no lead: does nothing, does not raise


def test_window_closed_sends_the_link_instead_of_a_list(env):
    db = DB()
    with patch("app.services.whatsapp_service._last_inbound_window", return_value=None), \
         patch.object(bw, "_send_link", return_value={"reason": None, "fallback": "link", "url": "u", "sent": True}) as link:
        out = bw.start_picker(db, ORG_ID, LEAD_ID)
    link.assert_called_once()
    assert out["started"] is False and out["fallback"] == "link" and "booking_wa_sessions" not in db.t


def test_no_more_than_five_starts_a_day(env):
    db = DB(booking_wa_sessions=[{"id": str(i), "lead_id": LEAD_ID, "status": "expired", "created_at": datetime.now(timezone.utc).isoformat()} for i in range(5)])
    with patch("app.services.whatsapp_service._last_inbound_window", return_value=datetime.now(timezone.utc) + timedelta(hours=5)):
        assert bw.start_picker(db, ORG_ID, LEAD_ID)["reason"] == "too_many"
