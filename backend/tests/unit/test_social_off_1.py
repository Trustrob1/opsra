"""SOCIAL-OFF-1 — Instagram and Messenger DMs are acknowledged but not processed while the flag is off."""
import asyncio
import json
from unittest.mock import MagicMock

from app.routers import webhooks as wh


class _Req:
    headers = {"X-Hub-Signature-256": "sha256=x"}

    async def body(self):
        return json.dumps({"object": "page", "entry": [{"messaging": [{"sender": {"id": "1"}}]}]}).encode()


def _run(handler, monkeypatch, flag):
    monkeypatch.setattr(wh, "SOCIAL_DM_INTAKE_ENABLED", flag)
    monkeypatch.setattr(wh, "_verify_messenger_signature", lambda *a, **k: True)
    monkeypatch.setattr(wh, "_verify_instagram_signature", lambda *a, **k: True)
    monkeypatch.setattr(wh, "_log_webhook", lambda *a, **k: None)
    enq = MagicMock()

    async def _enqueue(*a, **k):
        enq(*a, **k)

    monkeypatch.setattr(wh, "_enqueue_webhook", _enqueue)
    resp = asyncio.run(handler(_Req(), MagicMock()))
    return resp, enq


def test_messenger_dm_is_acknowledged_but_not_processed(monkeypatch):
    resp, enq = _run(wh.receive_messenger_message, monkeypatch, False)
    assert resp.status_code == 200 and not enq.called


def test_instagram_dm_is_acknowledged_but_not_processed(monkeypatch):
    resp, enq = _run(wh.receive_instagram_message, monkeypatch, False)
    assert resp.status_code == 200 and not enq.called


def test_flag_on_restores_processing(monkeypatch):
    resp, enq = _run(wh.receive_messenger_message, monkeypatch, True)
    assert resp.status_code == 200 and enq.called
