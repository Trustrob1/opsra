"""COEXIST-1 - phone-app echoes (smb_message_echoes)."""
from unittest.mock import MagicMock, patch

from app.services import phone_app_echo_service as svc

ORG = "org-1"


def _db(dup=False):
    db = MagicMock()
    q = db.table.return_value
    for m in ("select", "eq", "limit", "insert", "update"):
        getattr(q, m).return_value = q
    q.execute.return_value = MagicMock(data=[{"id": "x"}] if dup else [])
    return db


def _echo(**kw):
    e = {"from": "2348000000000", "to": "2348111111111", "id": "wamid.1",
         "timestamp": "1760000000", "type": "text", "text": {"body": "Hello, how can I help?"}}
    e.update(kw)
    return {"message_echoes": [e]}


def _insert_rows(db):
    return [c.args[0] for c in db.table.return_value.insert.call_args_list]


def test_lead_echo_stored_and_stamped():
    db = _db()
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)), \
         patch("app.services.whatsapp_service.set_ai_paused") as pause, \
         patch("app.services.lead_service.stamp_first_contacted") as stamp:
        assert svc.handle_echoes(db, ORG, _echo()) == 1
    row = _insert_rows(db)[0]
    assert row["direction"] == "outbound" and row["lead_id"] == "L1"
    assert row["content"] == "Hello, how can I help?"
    assert row["meta_category"] == "phone_app" and row["meta_billable"] is False
    assert row["sent_by"] is None and row["meta_message_id"] == "wamid.1"
    pause.assert_called_once()
    assert pause.call_args.kwargs["contact_type"] == "lead" and pause.call_args.kwargs["paused"] is True
    stamp.assert_called_once_with(db, ORG, "L1")


def test_customer_echo_pauses_customer_no_stamp():
    db = _db()
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, "C1", None, None)), \
         patch("app.services.whatsapp_service.set_ai_paused") as pause, \
         patch("app.services.lead_service.stamp_first_contacted") as stamp:
        assert svc.handle_echoes(db, ORG, _echo()) == 1
    assert _insert_rows(db)[0]["customer_id"] == "C1"
    assert pause.call_args.kwargs["contact_type"] == "customer"
    stamp.assert_not_called()


def test_duplicate_skipped():
    db = _db(dup=True)
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)):
        assert svc.handle_echoes(db, ORG, _echo()) == 0
    assert _insert_rows(db) == []


def test_unknown_number_ignored():
    db = _db()
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(None, None, None, None)):
        assert svc.handle_echoes(db, ORG, _echo()) == 0
    assert _insert_rows(db) == []


def test_media_echo_placeholder():
    db = _db()
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)), \
         patch("app.services.whatsapp_service.set_ai_paused"), \
         patch("app.services.lead_service.stamp_first_contacted"):
        svc.handle_echoes(db, ORG, _echo(type="image", image={"id": "m1"}, text=None))
    row = _insert_rows(db)[0]
    assert row["message_type"] == "image" and row["content"] == "[image]"


def test_never_raises():
    db = MagicMock()
    db.table.side_effect = RuntimeError("boom")
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)):
        assert svc.handle_echoes(db, ORG, _echo()) == 0


# ---- COEXIST-2 ----
def _hist(msgs, tid="2348111111111"):
    return {"metadata": {"display_phone_number": "2348000000000"},
            "history": [{"threads": [{"id": tid, "messages": msgs}]}]}


def test_history_imports_both_directions_without_pausing():
    db = _db()
    msgs = [
        {"from": "2348111111111", "id": "h1", "timestamp": "1750000000", "type": "text", "text": {"body": "hi"}},
        {"from": "2348000000000", "id": "h2", "timestamp": "1750000100", "type": "text", "text": {"body": "hello"},
         "history_context": {"status": "READ"}},
    ]
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)), \
         patch("app.services.whatsapp_service.set_ai_paused") as pause, \
         patch("app.services.lead_service.stamp_first_contacted") as stamp:
        assert svc.handle_history(db, ORG, _hist(msgs)) == 2
    rows = _insert_rows(db)[0]
    assert [r["direction"] for r in rows] == ["inbound", "outbound"]
    assert rows[1]["status"] == "read" and rows[0]["lead_id"] == "L1"
    pause.assert_not_called()
    stamp.assert_not_called()


def test_history_skips_unknown_contact_and_never_raises():
    db = _db()
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(None, None, None, None)):
        assert svc.handle_history(db, ORG, _hist([{"from": "x", "id": "h1", "type": "text", "text": {"body": "a"}}])) == 0
    bad = MagicMock()
    bad.table.side_effect = RuntimeError("boom")
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)):
        assert svc.handle_history(bad, ORG, _hist([{"id": "h1"}])) == 0


def test_state_sync_fills_blank_lead_name_only():
    db = _db()
    db.table.return_value.execute.return_value = MagicMock(data=[{"full_name": ""}])
    v = {"state_sync": [{"type": "contact", "action": "add",
                         "contact": {"full_name": "Ada O", "phone_number": "2348111111111"}}]}
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)):
        assert svc.handle_state_sync(db, ORG, v) == 1
    db.table.return_value.update.assert_called_once_with({"full_name": "Ada O"})
    db2 = _db()
    db2.table.return_value.execute.return_value = MagicMock(data=[{"full_name": "Existing"}])
    with patch("app.routers.webhooks._lookup_record_by_phone", return_value=(ORG, None, "L1", None)):
        assert svc.handle_state_sync(db2, ORG, v) == 0


def test_account_update_events():
    assert svc.handle_account_update({"event": "PARTNER_REMOVED", "waba_info": {"waba_id": "1"}}) == "PARTNER_REMOVED"
    assert svc.handle_account_update({"event": "OTHER"}) is None
