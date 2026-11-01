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
