"""WEBCHAT-STAFF-1: team members reply to a message, edit/delete their own, and send files in a web chat."""
import io
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import webchat as r
from app.services import webchat_msg_service as ms
from app.services import webchat_service as wc

JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
uid = lambda: str(uuid.uuid4())
iso = lambda d: d.isoformat()


class Q:
    def __init__(self, db, t): self.db, self.t, self.f, self.upd, self.ins = db, t, {}, None, None
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, v): self.f[k] = list(v); return self
    def is_(self, *a): return self
    def limit(self, *a): return self
    def order(self, *a, **k): return self
    def update(self, d): self.upd = d; return self
    def insert(self, d): self.ins = d; return self
    def execute(self):
        rows = self.db.t[self.t]
        if self.ins is not None:
            rows.append(self.ins); return SimpleNamespace(data=[self.ins])
        sel = [x for x in rows if all((x.get(k) == v) if not isinstance(v, list) else (x.get(k) in v) for k, v in self.f.items())]
        if self.upd is not None:
            for x in sel: x.update(self.upd)
        return SimpleNamespace(data=[dict(x) for x in sel])


class Bucket:
    def __init__(self): self.up = []
    def upload(self, path, file, file_options): self.up.append(path)
    def create_signed_url(self, path, expires_in): return {"signedUrl": "https://f/" + path}


class DB:
    def __init__(self):
        self.t = {"whatsapp_messages": [], "leads": [{"id": "l1", "org_id": "o1"}],
                  "webchat_sessions": [{"id": "s1", "org_id": "o1", "lead_id": "l1", "status": "active", "state": {}}]}
        self.b = Bucket()
        self.storage = SimpleNamespace(from_=lambda n: self.b)
    def table(self, n): return Q(self, n)


ORG = {"org_id": "o1", "id": "u1"}


def msg(db, text, direction="outbound", sent_by="u1", age=1, **kw):
    m = {"id": uid(), "org_id": "o1", "webchat_session_id": "s1", "lead_id": "l1", "channel": "webchat", "direction": direction,
         "sent_by": sent_by, "content": text, "message_type": "text",
         "created_at": iso(datetime.now(timezone.utc) - timedelta(minutes=age))}
    m.update(kw); db.t["whatsapp_messages"].append(m); return m


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(wc, "rate_limited", lambda *a, **k: False)
    monkeypatch.setattr(wc, "set_state", lambda db, s, **kv: s)
    monkeypatch.setattr(wc, "get_config", lambda db, o: {})
    from app.services import webchat_followup_service as fu
    monkeypatch.setattr(fu, "notify_rep_reply", lambda *a, **k: None)


def test_text_reply_quotes_earlier_message():
    db = DB(); v = msg(db, "Do you open Sunday?", direction="inbound", sent_by=None)
    out = wc.rep_send(db, "o1", "l1", "Yes, from 10am", "u1", reply_to=v["id"])
    assert out["reply"]["text"] == "Do you open Sunday?" and out["reply"]["role"] == "visitor"
    assert db.t["whatsapp_messages"][-1]["reply_to_id"] == v["id"]


def test_reply_to_unknown_message_is_dropped():
    db = DB()
    out = wc.rep_send(db, "o1", "l1", "hi", "u1", reply_to=uid())
    assert "reply" not in out and "reply_to_id" not in db.t["whatsapp_messages"][-1]


def test_staff_edit_own_and_keeps_original():
    db = DB(); m = msg(db, "Friday?")
    res = r.edit_webchat_message(m["id"], r.WebchatEdit(message="Saturday?"), db=db, org=ORG)
    assert res.data["text"] == "Saturday?" and res.data["edited"] and res.data["role"] == "rep"
    assert db.t["whatsapp_messages"][0]["original_content"] == "Friday?"


def test_staff_cannot_edit_colleague_bot_visitor_or_late():
    db = DB()
    colleague = msg(db, "hi", sent_by="u2"); bot = msg(db, "hi", sent_by=None)
    visitor = msg(db, "hi", direction="inbound", sent_by=None); late = msg(db, "old", age=20)
    for m in (colleague, bot, visitor):
        with pytest.raises(HTTPException) as e:
            r.edit_webchat_message(m["id"], r.WebchatEdit(message="x"), db=db, org=ORG)
        assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        r.edit_webchat_message(late["id"], r.WebchatEdit(message="x"), db=db, org=ORG)
    assert "15 minutes" in e.value.detail


def test_staff_delete_own_any_time_not_others():
    db = DB(); mine = msg(db, "oops", age=900); other = msg(db, "x", sent_by="u2")
    res = r.delete_webchat_message(mine["id"], db=db, org=ORG)
    assert res.data["deleted"] and res.data["text"] == ""
    assert db.t["whatsapp_messages"][0]["original_content"] == "oops"
    with pytest.raises(HTTPException):
        r.delete_webchat_message(other["id"], db=db, org=ORG)


def test_message_of_another_business_is_not_found():
    db = DB(); m = msg(db, "x", org_id="other")
    for call in (lambda: r.delete_webchat_message(m["id"], db=db, org=ORG),
                 lambda: r.edit_webchat_message(m["id"], r.WebchatEdit(message="y"), db=db, org=ORG)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        r.delete_webchat_message("nope", db=db, org=ORG)
    assert e.value.status_code == 404


def up(data, name="bed.jpg"):
    return SimpleNamespace(file=io.BytesIO(data), filename=name)


def test_staff_upload_photo_is_outbound_team_message():
    db = DB(); v = msg(db, "see this?", direction="inbound", sent_by=None)
    res = r.upload_webchat_file(lead_id="l1", kind="image", reply_to=v["id"], file=up(JPEG), db=db, org=ORG).data
    row = db.t["whatsapp_messages"][-1]
    assert row["direction"] == "outbound" and row["sent_by"] == "u1" and row["message_type"] == "image"
    assert row["reply_to_id"] == v["id"] and row["storage_path"].startswith("o1/webchat/s1/")
    assert res["role"] == "rep" and res["attachment"]["kind"] == "image" and res["reply"]["text"] == "see this?"


def test_staff_upload_rejects_fake_file_ended_chat_and_other_lead():
    db = DB()
    with pytest.raises(HTTPException) as e:
        r.upload_webchat_file(lead_id="l1", kind="image", reply_to=None, file=up(b"<svg onload=x>"), db=db, org=ORG)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        r.upload_webchat_file(lead_id="zzz", kind="image", reply_to=None, file=up(JPEG), db=db, org=ORG)
    assert e.value.status_code == 404
    db.t["webchat_sessions"][0]["status"] = "ended"
    with pytest.raises(HTTPException) as e:
        r.upload_webchat_file(lead_id="l1", kind="image", reply_to=None, file=up(JPEG), db=db, org=ORG)
    assert e.value.status_code == 400
    assert db.b.up == []


def test_staff_can_edit_text_but_not_a_file():
    db = DB(); f = msg(db, "bed.jpg", message_type="image", media_url="https://x")
    with pytest.raises(HTTPException):
        r.edit_webchat_message(f["id"], r.WebchatEdit(message="x"), db=db, org=ORG)
    assert r.delete_webchat_message(f["id"], db=db, org=ORG).data["deleted"]


def test_visitor_rules_unchanged():
    db = DB(); rep = msg(db, "hello")
    s = db.t["webchat_sessions"][0]
    assert ms.delete(db, s, rep["id"])[1]               # a visitor still cannot delete a team message
