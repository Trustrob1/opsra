from datetime import datetime, timezone
from app.services import webchat_call_service as call

BH = {"mon": {"start": "08:00", "end": "17:00"}, "tue": {"start": "08:00", "end": "17:00"}, "wed": {"start": "08:00", "end": "17:00"},
      "thu": {"start": "08:00", "end": "17:00"}, "fri": {"start": "08:00", "end": "17:00"}, "sat": {"start": "09:00", "end": "13:00"},
      "sun": {"start": None, "end": None}}
TZ = "Africa/Lagos"  # UTC+1


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def cfg(**kw):
    base = {"call_enabled": True, "call_number": "", "_call_org": {"business_hours": BH, "timezone": TZ, "fallback_number": "2348054313945"}}
    base.update(kw)
    return base


def test_hours_text_groups_days():
    assert call.hours_text(BH) == "Mon to Fri 8:00 am to 5:00 pm, Sat 9:00 am to 1:00 pm"


def test_open_midweek():
    # Mon 16 Nov 2026 10:00 UTC = 11:00 Lagos
    st = call.status(cfg(), utc(2026, 11, 16, 10))
    assert st["open"] and st["closes"] == "5:00 pm" and st["display"] == "0805 431 3945"


def test_closed_evening_reopens_tomorrow():
    # Sun 15 Nov 18:40 UTC = Sun 19:40 Lagos -> closed, reopens Monday 8:00
    st = call.status(cfg(), utc(2026, 11, 15, 18, 40))
    assert not st["open"] and st["reopens"] == "tomorrow at 8:00 am"


def test_after_close_same_day_then_next():
    # Mon 18:00 Lagos
    st = call.status(cfg(), utc(2026, 11, 16, 17))
    assert not st["open"] and st["reopens"] == "tomorrow at 8:00 am"


def test_before_open_same_day():
    # Mon 06:00 Lagos
    st = call.status(cfg(), utc(2026, 11, 16, 5))
    assert not st["open"] and st["reopens"] == "today at 8:00 am"


def test_saturday_afternoon_reopens_monday():
    # Sat 14:00 Lagos
    st = call.status(cfg(), utc(2026, 11, 21, 13))
    assert not st["open"] and st["reopens"] == "Monday at 8:00 am"


def test_off_and_no_number():
    assert call.status(cfg(call_enabled=False)) is None
    assert call.status(cfg(_call_org={"business_hours": BH, "timezone": TZ, "fallback_number": ""})) is None


def test_own_number_beats_fallback():
    assert call.status(cfg(call_number="2348031112222"), utc(2026, 11, 16, 10))["number"] == "2348031112222"


def test_no_hours_means_closed():
    st = call.status(cfg(_call_org={"business_hours": {}, "timezone": TZ, "fallback_number": "2348054313945"}))
    assert st["open"] is False and st["reopens"] == ""


class _Q:
    def __init__(self, store, name): self.s, self.n = store, name; self.rows = None
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def insert(self, row): self.s.setdefault(self.n, []).append(row); return self
    def execute(self):
        class R: data = [{"assigned_to": "rep-1"}]
        return R()


class _DB:
    def __init__(self): self.store = {}
    def table(self, n): return _Q(self.store, n)


def test_callback_needs_phone_or_uses_session_phone(monkeypatch):
    from app.services import webchat_service as wc
    monkeypatch.setattr(wc, "append_message", lambda db, s, role, text, sent_by=None: {"role": role, "text": text})
    monkeypatch.setattr(wc, "notify_managers", lambda *a, **k: None)
    db = _DB()
    s = {"id": "s1", "org_id": "o1", "lead_id": "l1", "contact_name": "Ada", "contact_phone": None}
    r = call.request_callback(db, s, cfg(), None)
    assert r.get("need_phone")
    r = call.request_callback(db, s, cfg(), "0803 000 0000")
    assert len(r["messages"]) == 2 and "0803 000 0000" in r["messages"][1]["text"]
    task = db.store["tasks"][0]
    assert task["assigned_to"] == "rep-1" and task["status"] == "open" and task["due_at"]


def test_callback_needs_lead():
    assert "contact details" in call.request_callback(_DB(), {"id": "s", "org_id": "o"}, cfg(), "08030000000")["error"]
