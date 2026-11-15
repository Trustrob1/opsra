from datetime import datetime, timedelta, timezone
import uuid

from app.services import webchat_msg_service as ms
from app.services import webchat_service as wc


def iso(dt): return dt.isoformat()
def uid(): return str(uuid.uuid4())


class Q:
    def __init__(self, db): self.db, self.f, self.upd, self.ins = db, {}, None, None
    def select(self, *a, **k): return self
    def eq(self, k, v): self.f[k] = v; return self
    def in_(self, k, v): self.f[k] = list(v); return self
    def limit(self, *a): return self
    def order(self, *a, **k): return self
    def or_(self, *a): return self
    def update(self, d): self.upd = d; return self
    def insert(self, d): self.ins = d; return self
    def execute(self):
        rows = self.db.rows
        if self.ins is not None:
            rows.append(self.ins); return type("R", (), {"data": [self.ins]})
        sel = [r for r in rows if all((r.get(k) == v) if not isinstance(v, list) else (r.get(k) in v) for k, v in self.f.items())]
        if self.upd is not None:
            for r in sel: r.update(self.upd)
        return type("R", (), {"data": [dict(r) for r in sel]})


class DB:
    def __init__(self): self.rows = []
    def table(self, n): return Q(self)


def lead_session(): return {"id": "s1", "org_id": "o1", "lead_id": "l1"}


def mk(db, text, direction="inbound", sent_by=None, age_min=1, **kw):
    r = {"id": uid(), "org_id": "o1", "webchat_session_id": "s1", "lead_id": "l1", "direction": direction, "sent_by": sent_by,
         "content": text, "message_type": "text", "created_at": iso(datetime.now(timezone.utc) - timedelta(minutes=age_min))}
    r.update(kw); db.rows.append(r); return r


def test_edit_own_keeps_original():
    db = DB(); m = mk(db, "Friday?")
    out, err = ms.edit(db, lead_session(), m["id"], "Saturday?")
    assert not err and out["text"] == "Saturday?" and out["edited"]
    assert db.rows[0]["original_content"] == "Friday?"
    out, err = ms.edit(db, lead_session(), m["id"], "Sunday?")
    assert db.rows[0]["original_content"] == "Friday?"          # the very first words are kept


def test_edit_not_others_not_late_not_empty():
    db = DB(); bot = mk(db, "hi", direction="outbound"); rep = mk(db, "hello", direction="outbound", sent_by="u1"); old = mk(db, "old", age_min=20)
    assert ms.edit(db, lead_session(), bot["id"], "x")[1]
    assert ms.edit(db, lead_session(), rep["id"], "x")[1]
    assert "15 minutes" in ms.edit(db, lead_session(), old["id"], "x")[1]
    new = mk(db, "fresh")
    assert ms.edit(db, lead_session(), new["id"], "   ")[1]


def test_no_edit_of_files_but_delete_ok():
    db = DB(); f = mk(db, "photo.jpg", message_type="image", media_url="https://x")
    assert ms.edit(db, lead_session(), f["id"], "x")[1]
    out, err = ms.delete(db, lead_session(), f["id"])
    assert not err and out["deleted"] and out["text"] == "" and "attachment" not in out
    assert db.rows[0]["media_url"] is None and db.rows[0]["original_content"] == "photo.jpg"
    assert ms.delete(db, lead_session(), f["id"])[1]           # already deleted


def test_other_session_message_not_found():
    db = DB(); m = mk(db, "x", webchat_session_id="other")
    assert ms.delete(db, lead_session(), m["id"])[1]
    assert ms.delete(db, lead_session(), "not-a-uuid")[1]


def test_delete_after_any_time():
    db = DB(); m = mk(db, "old", age_min=500)
    assert ms.delete(db, lead_session(), m["id"])[1] is None


def test_history_messages_before_contact(monkeypatch):
    db = DB()
    mid = uid()
    sess = {"id": "s1", "org_id": "o1", "lead_id": None,
            "history": [{"id": mid, "role": "visitor", "text": "hello", "at": iso(datetime.now(timezone.utc))}]}
    updates = {}
    monkeypatch.setattr(wc, "update_session", lambda db_, s_, ch: updates.update(ch) or {**s_, **ch})
    out, err = ms.edit(db, sess, mid, "hello there")
    assert not err and out["text"] == "hello there" and updates["history"][0]["original"] == "hello"
    sess["history"] = updates["history"]
    out, err = ms.delete(db, sess, mid)
    assert not err and out["deleted"] and updates["history"][0]["deleted_at"]


def test_reply_quote_and_listing():
    db = DB()
    a = mk(db, "A queen is 148,000", direction="outbound")
    wc_q = wc.quote_for(db, lead_session(), a["id"])
    assert wc_q["role"] == "bot" and wc_q["text"].startswith("A queen")
    assert wc.quote_for(db, lead_session(), uid()) is None
    r = mk(db, "ok", reply_to_id=a["id"])
    msgs = wc.list_messages(db, lead_session())
    reply = next(m for m in msgs if m["id"] == r["id"])
    assert reply["reply"]["text"].startswith("A queen")


def test_deleted_quote_text_and_out_hides_content():
    row = {"id": "1", "content": "secret", "direction": "inbound", "deleted_at": "2026-11-15T10:00:00+00:00", "created_at": "x"}
    assert wc._out("visitor", row)["text"] == ""
    assert wc._quote_of("visitor", row)["text"] == "This message was deleted"
