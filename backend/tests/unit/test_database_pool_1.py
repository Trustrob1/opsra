"""
DB-POOL-1: get_supabase() clients share one bounded connection pool (no new TLS connection per call).
Uses a real local HTTP server and counts how many TCP connections the clients open.
"""
import base64
import json
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import database


def _jwt():
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'HS256', 'typ': 'JWT'})}.{b({'role': 'service_role'})}.sig"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"            # keep-alive allowed

    def do_GET(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)               # postgrest 0.16 sends an empty {} body even on GET; a real server reads it
        body = b"[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *a, **k):
        self.connections = 0
        super().__init__(*a, **k)

    def get_request(self):
        r = super().get_request()
        self.connections += 1
        return r


@pytest.fixture()
def server(monkeypatch):
    srv = _Server(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(database.settings, "SUPABASE_URL", f"http://127.0.0.1:{srv.server_address[1]}", raising=False)
    monkeypatch.setattr(database.settings, "SUPABASE_SERVICE_KEY", _jwt(), raising=False)
    database._pool_transport = None
    yield srv
    srv.shutdown()
    srv.server_close()
    database._pool_transport = None


def _one_request_like_the_app():
    """What the request middleware does: new client, query, then close the client's sessions."""
    c = database.get_supabase()
    c.table("organisations").select("id").limit(1).execute()
    database.close_client_sessions(c)


def test_connections_are_reused_between_clients(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_POOL", "1")
    for _ in range(6):
        _one_request_like_the_app()
    assert server.connections == 1


def test_switch_off_gives_a_new_connection_each_time(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_POOL", "0")
    for _ in range(4):
        _one_request_like_the_app()
    assert server.connections == 4


def test_closing_a_client_does_not_close_the_pool(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_POOL", "1")
    a = database.get_supabase()
    a.table("t").select("id").execute()
    database.close_client_sessions(a)
    b = database.get_supabase()
    assert b.table("t").select("id").execute().data == []


def test_clients_still_have_their_own_headers_and_builders(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_POOL", "1")
    a, b = database.get_supabase(), database.get_supabase()
    assert a.postgrest.session is not b.postgrest.session
    a.postgrest.auth("user-token-a")
    assert b.postgrest.session.headers.get("authorization") != "Bearer user-token-a"


def test_concurrent_use_is_safe_and_bounded(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_POOL", "1")
    errors = []

    def work():
        try:
            for _ in range(10):
                _one_request_like_the_app()
        except Exception as e:           # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert server.connections <= 40


def test_a_forked_process_builds_its_own_pool(monkeypatch):
    t1 = database._shared_transport()
    real_pid = os.getpid()
    monkeypatch.setattr(database.os, "getpid", lambda: real_pid + 1)
    t2 = database._shared_transport()
    assert t1 is not t2


def test_pool_problem_falls_back_to_private_session(monkeypatch):
    monkeypatch.setattr(database, "_shared_transport", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(database.settings, "SUPABASE_URL", "http://127.0.0.1:9", raising=False)
    monkeypatch.setattr(database.settings, "SUPABASE_SERVICE_KEY", _jwt(), raising=False)
    c = database.get_supabase()          # must not raise
    assert c.postgrest.session is not None


def test_tls_setup_is_built_once_and_reused(monkeypatch):
    import httpx._transports.default as hd
    monkeypatch.setenv("SUPABASE_SSL_CACHE", "1")
    database._ssl_cache.clear()
    a = hd.create_ssl_context(verify=True, cert=None, trust_env=True)
    b = hd.create_ssl_context(verify=True, cert=None, trust_env=True)
    assert a is b


def test_tls_cache_does_not_touch_special_cases(monkeypatch):
    import httpx._transports.default as hd
    monkeypatch.setenv("SUPABASE_SSL_CACHE", "1")
    a = hd.create_ssl_context(verify=False, cert=None, trust_env=True)
    b = hd.create_ssl_context(verify=False, cert=None, trust_env=True)
    assert a is not b                     # verify=False is built fresh every time


def test_tls_cache_switch_off(monkeypatch):
    import httpx._transports.default as hd
    monkeypatch.setenv("SUPABASE_SSL_CACHE", "0")
    a = hd.create_ssl_context(verify=True, cert=None, trust_env=True)
    b = hd.create_ssl_context(verify=True, cert=None, trust_env=True)
    assert a is not b


def test_creating_a_client_is_now_fast(monkeypatch):
    import time
    monkeypatch.setenv("SUPABASE_SSL_CACHE", "1")
    monkeypatch.setattr(database.settings, "SUPABASE_URL", "https://abc.supabase.co", raising=False)
    monkeypatch.setattr(database.settings, "SUPABASE_SERVICE_KEY", _jwt(), raising=False)
    database.get_supabase()                                   # warm up
    t = time.perf_counter()
    for _ in range(10):
        database.get_supabase()
    avg_ms = (time.perf_counter() - t) * 100
    assert avg_ms < 60, f"get_supabase averaged {avg_ms:.0f} ms"
