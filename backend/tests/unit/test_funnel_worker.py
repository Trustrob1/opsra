"""
tests/unit/test_funnel_worker.py
FUNNEL-1A — funnel_worker.process_funnel / run_funnel_sequence.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from app.workers import funnel_worker
from tests.funnel_fake_db import FakeDB
from tests.unit.test_funnel_service import (
    NOW, NUMBER, ORG_ID, base_db, make_funnel, make_reg,
)

ORG_ROW = {"id": ORG_ID, "subscription_status": "active", "quiet_hours_start": None,
           "quiet_hours_end": None, "timezone": "Africa/Lagos"}


def _db(**kw):
    db = base_db(organisations=[dict(ORG_ROW)], **kw)
    return db


class TestFunnelWorker:
    def test_FUN_W_01_sends_due_step_once(self):
        db = _db(funnel_registrations=[make_reg()])
        t = NOW + timedelta(hours=3, minutes=2)
        with patch("app.services.funnel_messaging._call_meta_send", return_value={}) as meta:
            s1 = funnel_worker.process_funnel(db, make_funnel(), t)
            s2 = funnel_worker.process_funnel(db, make_funnel(), t + timedelta(minutes=5))
        assert s1["sent"] == 1 and s1["failed"] == 0
        assert s2["sent"] == 0
        assert meta.call_count == 1

    def test_FUN_W_02_inactive_org_skipped(self):
        db = _db(funnel_registrations=[make_reg()])
        db.tables["organisations"][0]["subscription_status"] = "suspended"
        with patch("app.services.funnel_messaging._call_meta_send") as meta:
            s = funnel_worker.process_funnel(db, make_funnel(), NOW + timedelta(hours=3, minutes=2))
        assert s["skipped"] == 1 and meta.call_count == 0

    def test_FUN_W_03_number_not_in_funnel_mode_skipped(self):
        db = _db(funnel_registrations=[make_reg()])
        db.tables["whatsapp_numbers"][0]["wa_sales_mode"] = "human"
        with patch("app.services.funnel_messaging._call_meta_send") as meta:
            s = funnel_worker.process_funnel(db, make_funnel(), NOW + timedelta(hours=3, minutes=2))
        assert s["skipped"] == 1 and meta.call_count == 0

    def test_FUN_W_04_one_bad_registration_does_not_stop_loop(self):
        good = make_reg(id="12121212-1212-1212-1212-121212121212", phone="2348011111111", pay_token="t2",
                        ref_code="CD5678")
        bad = make_reg(first_message_at="not-a-date")
        db = _db(funnel_registrations=[bad, good])
        with patch("app.services.funnel_messaging._call_meta_send", return_value={}):
            s = funnel_worker.process_funnel(db, make_funnel(), NOW + timedelta(hours=3, minutes=2))
        assert s["sent"] == 1

    def test_FUN_W_05_run_task_summary(self):
        db = _db(funnel_registrations=[make_reg()], worker_run_log=[])
        with patch("app.workers.funnel_worker.get_supabase", return_value=db), \
             patch("app.services.funnel_messaging._call_meta_send", return_value={}):
            out = funnel_worker.run_funnel_sequence()
        assert out["funnels"] == 1 and out["failed"] == 0
