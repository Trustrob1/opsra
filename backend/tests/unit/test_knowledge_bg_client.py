"""Website / Google Doc reads run after the response, when the request's database client is already closed: they must use a fresh one."""
from __future__ import annotations

from app.routers import knowledge as kr


class _Tasks:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *args, **kw):
        self.calls.append((fn, args, kw))


REQUEST_DB = object()
FRESH_DB = object()


def _patch(monkeypatch):
    monkeypatch.setattr(kr.ks, "list_sources", lambda db, org: [])
    monkeypatch.setattr(kr.ks, "new_source", lambda *a, **k: "sid-1")
    monkeypatch.setattr(kr.ks, "preview", lambda *a, **k: {})
    monkeypatch.setattr(kr, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(kr, "get_supabase", lambda: FRESH_DB)


def test_website_read_is_queued_without_the_request_client(monkeypatch):
    _patch(monkeypatch)
    tasks, ran = _Tasks(), []
    monkeypatch.setattr(kr.web, "run_website", lambda db, org, sid, addr: ran.append((db, org, sid, addr)))
    kr._start_web_job("url", kr.UrlPayload(url="https://example.com"), tasks, {"org_id": "o1", "id": "u1"}, REQUEST_DB)
    fn, args, _ = tasks.calls[0]
    assert REQUEST_DB not in args
    fn(*args)
    assert ran and ran[0][0] is FRESH_DB and ran[0][1:3] == ("o1", "sid-1")


def test_google_doc_read_uses_a_fresh_client_too(monkeypatch):
    _patch(monkeypatch)
    tasks, ran = _Tasks(), []
    monkeypatch.setattr(kr.web, "run_gdoc", lambda db, org, sid, url: ran.append(db))
    kr._start_web_job("gdoc", kr.UrlPayload(url="https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit"), tasks, {"org_id": "o1", "id": "u1"}, REQUEST_DB)
    fn, args, _ = tasks.calls[0]
    assert REQUEST_DB not in args
    fn(*args)
    assert ran == [FRESH_DB]


def test_run_in_background_passes_a_new_client_first(monkeypatch):
    monkeypatch.setattr(kr, "get_supabase", lambda: FRESH_DB)
    got = []
    kr._run_in_background(lambda db, a, b: got.append((db, a, b)), 1, 2)
    assert got == [(FRESH_DB, 1, 2)]
