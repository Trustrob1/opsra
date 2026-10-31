"""BOOKING-2A - WhatsApp sends for booking (token fix, 24h window, templates) and the once-per-lead auto-send."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.services import whatsapp_service as ws
from app.services import booking_service as bk

ORG, LEAD = "org-1", "lead-1"
LEAD_ROW = {"id": LEAD, "full_name": "Ada Obi", "whatsapp": "2348012345678"}


class Q:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload = db, name, "select", None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def insert(self, p): self.op, self.payload = "insert", p; return self
    def execute(self):
        if self.op == "insert":
            self.db.inserts.append((self.name, self.payload))
            return MagicMock(data=[self.payload])
        return MagicMock(data=self.db.rows.get(self.name, []))


class FakeDB:
    def __init__(self, **rows): self.rows, self.inserts = rows, []
    def table(self, name): return Q(self, name)


def _inbound(hours_ago):
    return [{"created_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()}]


def _send(db, **kw):
    with patch.object(ws, "_get_lead_wa_credentials", return_value=("pid", "tok", "waba")), \
         patch.object(ws, "_call_meta_send") as m:
        out = ws.send_booking_message(db, ORG, LEAD_ROW, "hello", **kw)
    return out, m


def test_window_open_sends_text_with_the_org_token():
    out, m = _send(FakeDB(whatsapp_messages=_inbound(2)))
    assert out == {"sent": True, "via": "text", "reason": None}
    assert m.call_args.kwargs["token"] == "tok"          # the Phase 1 bug: token was never passed
    assert m.call_args.args[1]["type"] == "text"


def test_window_closed_with_template_sends_template_positional():
    out, m = _send(FakeDB(whatsapp_messages=_inbound(30)), template_name="booking_cancelled", template_vars=["Ada", "consultation", "Mon 10:00"])
    assert out["via"] == "template" and out["sent"]
    tpl = m.call_args.args[1]["template"]
    assert tpl["name"] == "booking_cancelled"
    assert [p["text"] for p in tpl["components"][0]["parameters"]] == ["Ada", "consultation", "Mon 10:00"]


def test_window_closed_without_template_sends_nothing():
    out, m = _send(FakeDB(whatsapp_messages=[]))
    assert out == {"sent": False, "via": None, "reason": "window_closed"}
    m.assert_not_called()


def test_template_rejected_by_meta_is_reported_not_raised():
    db = FakeDB(whatsapp_messages=_inbound(30))
    with patch.object(ws, "_get_lead_wa_credentials", return_value=("pid", "tok", None)), \
         patch.object(ws, "_call_meta_send", side_effect=Exception("template not approved")):
        out = ws.send_booking_message(db, ORG, LEAD_ROW, "x", template_name="booking_link_invite", template_vars=["a"])
    assert out == {"sent": False, "via": None, "reason": "template_failed"}
    assert db.inserts == []


def test_no_credentials_and_no_number():
    db = FakeDB(whatsapp_messages=_inbound(1))
    with patch.object(ws, "_get_lead_wa_credentials", return_value=(None, None, None)):
        assert ws.send_booking_message(db, ORG, LEAD_ROW, "x")["reason"] == "no_whatsapp"
    assert ws.send_booking_message(db, ORG, {"id": LEAD}, "x")["reason"] == "no_number"


def test_sent_message_is_logged_with_real_window_expiry():
    db = FakeDB(whatsapp_messages=_inbound(2))
    _send(db)
    row = [p for n, p in db.inserts if n == "whatsapp_messages"][0]
    assert row["direction"] == "outbound" and row["window_open"] is True


# ---- auto-send once per lead ----
def _auto(db, settings, send_result=None):
    ds = MagicMock()
    ds._confirm_lead_in_org.return_value = LEAD_ROW
    ds._auto_send_wa.return_value = send_result or {"sent": True, "via": "text", "reason": None}
    with patch.object(bk, "get_settings", return_value=settings), \
         patch.object(bk, "create_link", return_value="tok123") as cl, \
         patch.dict("sys.modules", {}), patch("app.services.demo_service._confirm_lead_in_org", ds._confirm_lead_in_org), \
         patch("app.services.demo_service._auto_send_wa", ds._auto_send_wa), \
         patch("app.services.demo_service._log_timeline", ds._log_timeline):
        return bk.auto_send_link_for_lead(db, ORG, LEAD), cl, ds


ON = {"native_enabled": True, "auto_send_link": True, "label": "consultation"}


def test_auto_send_off_does_nothing():
    out, cl, _ = _auto(FakeDB(), {**ON, "auto_send_link": False})
    assert out["reason"] == "off"; cl.assert_not_called()


def test_auto_send_skips_when_booking_or_earlier_link_exists():
    out, cl, _ = _auto(FakeDB(lead_demos=[{"id": "d1"}]), ON)
    assert out["reason"] == "has_booking"
    out, cl, _ = _auto(FakeDB(lead_demos=[], booking_links=[{"id": "l1"}]), ON)
    assert out["reason"] == "already_sent"; cl.assert_not_called()


def test_auto_send_creates_marker_link_and_sends_once():
    out, cl, ds = _auto(FakeDB(lead_demos=[], booking_links=[]), ON)
    assert out["sent"] is True
    cl.assert_called_once_with(ANY := cl.call_args.args[0], ORG, LEAD, None, None)
    kw = ds._auto_send_wa.call_args.kwargs
    assert kw["template_name"] == bk.BOOKING_LINK_TEMPLATE and "/b/tok123" in ds._auto_send_wa.call_args.args[3]
