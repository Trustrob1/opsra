"""BOOKING-3C - Calendly intake: signature, idempotency, lead matching, cancel/reschedule, no leaks."""
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import booking_service as bk
from app.services import calendly_service as cal

KEY = "signing-key-123"


def _sig(raw: bytes, key=KEY, t=None):
    t = str(int(t if t is not None else time.time()))
    return f"t={t},v1=" + hmac.new(key.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()


def _db(tables):
    db = MagicMock(); log = []
    def table(name):
        q = MagicMock()
        for m in ("select", "eq", "is_", "limit", "in_", "order"):
            getattr(q, m).return_value = q
        q.execute.return_value = MagicMock(data=tables.get(name, []))
        q.insert.side_effect = lambda p, _n=name: (log.append(("insert", _n, p)), q)[1]
        q.update.side_effect = lambda p, _n=name: (log.append(("update", _n, p)), q)[1]
        return q
    db.table.side_effect = table; db.log = log
    return db


def test_signature_valid():
    raw = b'{"a":1}'
    assert cal.verify_signature(KEY, _sig(raw), raw)


def test_signature_wrong_key_body_or_missing():
    raw = b'{"a":1}'
    assert not cal.verify_signature(KEY, _sig(raw, key="other"), raw)
    assert not cal.verify_signature(KEY, _sig(raw), b'{"a":2}')
    assert not cal.verify_signature(KEY, None, raw)
    assert not cal.verify_signature(KEY, "garbage", raw)


def test_signature_replay_rejected():
    raw = b"{}"
    assert not cal.verify_signature(KEY, _sig(raw, t=time.time() - 3600), raw)


def test_webhook_unknown_token_is_401():
    with patch.object(cal, "_integration_by_token", return_value=None):
        with pytest.raises(HTTPException) as e:
            cal.handle_webhook(MagicMock(), "nope", b"{}", "t=1,v1=x")
    assert e.value.status_code == 401


def test_webhook_bad_signature_is_401_and_does_nothing():
    integ = {"org_id": "o", "credentials": {"signing_key": KEY}}
    with patch.object(cal, "_integration_by_token", return_value=integ), patch.object(cal, "on_created") as oc:
        with pytest.raises(HTTPException) as e:
            cal.handle_webhook(MagicMock(), "tok", b'{"event":"invitee.created"}', _sig(b'{"event":"invitee.created"}', key="evil"))
    assert e.value.status_code == 401
    oc.assert_not_called()


def test_webhook_dispatches_with_org_from_token_not_body():
    raw = json.dumps({"event": "invitee.created", "payload": {"org_id": "attacker-org", "uri": "u"}}).encode()
    integ = {"org_id": "real-org", "credentials": {"signing_key": KEY}}
    with patch.object(cal, "_integration_by_token", return_value=integ), patch.object(cal, "on_created", return_value={"ok": True}) as oc:
        cal.handle_webhook(MagicMock(), "tok", raw, _sig(raw))
    assert oc.call_args[0][1] == "real-org"


def test_webhook_unknown_event_ignored():
    raw = json.dumps({"event": "routing_form_submission.created", "payload": {}}).encode()
    integ = {"org_id": "o", "credentials": {"signing_key": KEY}}
    with patch.object(cal, "_integration_by_token", return_value=integ):
        assert cal.handle_webhook(MagicMock(), "tok", raw, _sig(raw))["ignored"]


PAYLOAD = {"uri": "https://api.calendly.com/scheduled_events/E1/invitees/I1", "name": "Ada Obi", "email": "Ada@x.com",
           "text_reminder_number": "08031234567", "timezone": "Africa/Lagos",
           "cancel_url": "https://calendly.com/cancel/I1", "reschedule_url": "https://calendly.com/reschedule/I1",
           "scheduled_event": {"uri": "https://api.calendly.com/scheduled_events/E1", "name": "Intro call",
                               "start_time": "2026-11-05T09:00:00Z", "end_time": "2026-11-05T09:30:00Z",
                               "location": {"type": "zoom", "join_url": "https://zoom.us/j/1"},
                               "event_memberships": [{"user_email": "host@biz.com"}]}}


def test_created_duplicate_is_idempotent():
    db = _db({"lead_demos": [{"id": "existing"}]})
    assert cal.on_created(db, "o", PAYLOAD) == {"ok": True, "duplicate": True}
    assert not [c for c in db.log if c[0] == "insert"]


def test_created_inserts_outside_guards_and_confirms():
    db = _db({"lead_demos": []})
    with patch.object(cal, "find_or_create_lead", return_value={"id": "l1", "full_name": "Ada Obi"}), \
         patch.object(cal, "_owner_for", return_value="rep1"), patch.object(bk, "get_org", return_value={"id": "o", "timezone": "UTC"}), \
         patch("app.services.demo_service.confirm_demo") as conf, patch("app.services.demo_service._log_timeline"):
        out = cal.on_created(db, "o", PAYLOAD)
    row = [c for c in db.log if c[0] == "insert" and c[1] == "lead_demos"][0][2]
    assert row["source"] == "calendly" and row["guard_scope"] == "ext" and row["external_id"] == PAYLOAD["uri"]
    assert row["slot_end"].startswith("2026-11-05T09:30") and row["duration_minutes"] == 30 and row["org_id"] == "o"
    assert row["external_meta"]["reschedule_url"] == PAYLOAD["reschedule_url"]
    conf.assert_called_once()
    assert out["ok"]


def test_created_without_rep_goes_to_manager_not_lost():
    db = _db({"lead_demos": []})
    with patch.object(cal, "find_or_create_lead", return_value={"id": "l1"}), patch.object(cal, "_owner_for", return_value=None), \
         patch.object(bk, "get_org", return_value={"id": "o", "timezone": "UTC"}), patch.object(bk, "_notify_approval_needed") as na, \
         patch("app.services.demo_service.confirm_demo") as conf, patch("app.services.demo_service._log_timeline"):
        cal.on_created(db, "o", PAYLOAD)
    na.assert_called_once(); conf.assert_not_called()


def test_incomplete_payload_ignored():
    assert cal.on_created(_db({}), "o", {"uri": "x"})["ignored"] == "incomplete"


def test_phone_taken_from_form_answer():
    p = {"questions_and_answers": [{"question": "Your WhatsApp number", "answer": "08031234567"}]}
    assert cal._phone_from(p)
    assert cal._phone_from({}) is None


def test_medium_mapping():
    assert cal._medium({"location": {"type": "physical"}}) == "in_person"
    assert cal._medium({"location": {"type": "outbound_call"}}) == "phone"
    assert cal._medium({"location": {"type": "zoom"}}) == "virtual"
    assert cal._medium({}) == "virtual"


def test_find_lead_matches_by_email_first():
    db = _db({"leads": [{"id": "l9"}]})
    assert cal.find_or_create_lead(db, "o", "Ada", "ADA@x.com", None)["id"] == "l9"


def test_canceled_cancels_live_booking_without_calling_back():
    db = _db({"lead_demos": [{"id": "d1", "status": "confirmed"}]})
    with patch.object(bk, "cancel_booking") as cb:
        cal.on_canceled(db, "o", {"uri": "u", "rescheduled": False})
    kw = cb.call_args.kwargs
    assert kw["from_calendly"] is True and kw["notify_lead"] is True


def test_canceled_for_reschedule_stays_quiet():
    db = _db({"lead_demos": [{"id": "d1", "status": "confirmed"}]})
    with patch.object(bk, "cancel_booking") as cb:
        cal.on_canceled(db, "o", {"uri": "u", "rescheduled": True})
    assert cb.call_args.kwargs["notify_lead"] is False


def test_canceled_unknown_or_dead_booking_ignored():
    with patch.object(bk, "cancel_booking") as cb:
        assert cal.on_canceled(_db({"lead_demos": []}), "o", {"uri": "u"})["ignored"]
        assert cal.on_canceled(_db({"lead_demos": [{"id": "d1", "status": "cancelled"}]}), "o", {"uri": "u"})["ignored"]
    cb.assert_not_called()


def test_opsra_cancel_of_calendly_booking_calls_calendly():
    demo = {"id": "d1", "status": "confirmed", "source": "calendly", "lead_id": "l1", "scheduled_at": "2026-12-01T09:00:00+00:00"}
    with patch("app.services.demo_service._fetch_demo_by_id", return_value=demo), patch.object(bk, "get_org", return_value={"id": "o", "timezone": "UTC"}), \
         patch.object(bk, "get_settings", return_value={"label": "call", "cancel_cutoff_hours": 0}), \
         patch("app.services.demo_service._confirm_lead_in_org", return_value={"id": "l1", "full_name": "A B"}), \
         patch("app.services.demo_service._log_timeline"), patch("app.services.demo_service._auto_send_wa"), patch("app.services.demo_service._insert_notification"), \
         patch.object(cal, "cancel_remote", return_value=True) as cr:
        bk.cancel_booking(_db({}), "o", "d1", "staff", "no longer needed")
    cr.assert_called_once()


def test_calendly_cancel_does_not_loop_back():
    demo = {"id": "d1", "status": "confirmed", "source": "calendly", "lead_id": "l1", "scheduled_at": "2026-12-01T09:00:00+00:00"}
    with patch("app.services.demo_service._fetch_demo_by_id", return_value=demo), patch.object(bk, "get_org", return_value={"id": "o", "timezone": "UTC"}), \
         patch.object(bk, "get_settings", return_value={"label": "call", "cancel_cutoff_hours": 0}), \
         patch("app.services.demo_service._confirm_lead_in_org", return_value={"id": "l1", "full_name": "A B"}), \
         patch("app.services.demo_service._log_timeline"), patch("app.services.demo_service._auto_send_wa") as wa, patch("app.services.demo_service._insert_notification"), \
         patch.object(cal, "cancel_remote") as cr:
        bk.cancel_booking(_db({}), "o", "d1", "lead", "x", from_calendly=True, notify_lead=False)
    cr.assert_not_called(); wa.assert_not_called()


def test_reschedule_blocked_for_calendly_booking():
    demo = {"id": "d1", "status": "confirmed", "source": "calendly"}
    with patch("app.services.demo_service._fetch_demo_by_id", return_value=demo):
        with pytest.raises(HTTPException) as e:
            bk.reschedule_booking(_db({}), "o", "d1", __import__("datetime").datetime.now(), "staff")
    assert e.value.status_code == 409


def test_connect_rejects_short_token():
    with pytest.raises(HTTPException):
        cal.connect(MagicMock(), "o", "short")


def test_status_never_returns_secrets():
    row = {"status": "connected", "connected_at": "t", "credentials": {"access_token": "SECRET", "signing_key": "SK", "webhook_token": "WT", "scope": "organization", "user_name": "Ada"}}
    with patch.object(cal, "_row", return_value=row):
        out = json.dumps(cal.status(MagicMock(), "o"))
    assert "SECRET" not in out and "SK" not in out and "WT" not in out
