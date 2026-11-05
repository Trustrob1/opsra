"""
tests/unit/test_site_import_threadpool.py
------------------------------------------
IMPORT-TIMEOUT-1 - the import route must not block the server's event loop while a big site uploads (gunicorn kills a
worker that cannot answer its heartbeat for 60 seconds). No network, no database.
"""
from __future__ import annotations

import asyncio
import time

from app.routers import sites as routes


class _Upload:
    filename = "site.zip"

    async def read(self, _n=-1):
        return b""          # _read_capped stops at the first empty chunk


def test_a_slow_import_runs_off_the_event_loop(monkeypatch):
    monkeypatch.setattr(routes, "_import_org", lambda org, db, roles: ("org-1", {}))
    monkeypatch.setattr(routes, "_get_site", lambda db, org_id, site_id: {"id": site_id})
    monkeypatch.setattr(routes.site_import_service, "settings_for", lambda settings: {"max_mb": 25})
    monkeypatch.setattr(routes, "_log_event", lambda *a, **k: None)

    def slow_import(*_a, **_k):
        time.sleep(0.6)                     # a blocking upload loop
        return {"saved": False, "report": {}}

    monkeypatch.setattr(routes.site_import_service, "import_site", slow_import)

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        t = asyncio.create_task(ticker())
        await routes.import_site_upload("site-1", file=_Upload(), dry_run=True, accepted="", org={"id": "u", "org_id": "org-1"}, db=object())
        t.cancel()
        return ticks

    ticks = asyncio.run(run())
    assert ticks >= 8, f"the event loop was blocked during the import (only {ticks} ticks)"
