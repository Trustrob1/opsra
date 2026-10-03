"""
tests/unit/test_site_premium_worker.py - SITE-PREMIUM P2: the Celery tasks (generation job wrapper and the stale sweep).
The pipeline and the sweep logic are tested in test_site_premium_generation.py; here only the task wrappers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.workers import site_premium_worker as w
from app.workers.celery_app import celery_app
from tests.funnel_fake_db import FakeDB


def _db(rows=()):
    return FakeDB(site_designs=list(rows))


class TestRegistration:
    def test_module_is_included_and_tasks_are_registered(self):
        assert "app.workers.site_premium_worker" in celery_app.conf.include or "app.workers.site_premium_worker" in (celery_app.conf.get("include") or [])
        assert w.run_premium_generation.name == "app.workers.site_premium_worker.run_premium_generation"
        assert w.run_premium_stale_sweep.name == "app.workers.site_premium_worker.run_premium_stale_sweep"

    def test_sweep_is_scheduled_every_ten_minutes(self):
        entry = celery_app.conf.beat_schedule["site-premium-stale-sweep"]
        assert entry["task"] == "app.workers.site_premium_worker.run_premium_stale_sweep"
        assert str(entry["schedule"].minute) == "{0, 10, 20, 30, 40, 50}" or "*/10" in repr(entry["schedule"])

    def test_generation_has_a_hard_time_limit(self):
        assert w.run_premium_generation.time_limit == 540 and w.run_premium_generation.soft_time_limit == 480


class TestStaleSweepTask:
    def test_dry_run_shape_with_nothing_to_do(self):
        with patch.object(w, "get_supabase", return_value=_db()), patch.object(w, "write_worker_log") as log:
            assert w.run_premium_stale_sweep() == {"swept": 0, "failed": 0}
        assert log.call_args.kwargs["status"] == "passed"

    def test_sweeps_stuck_rows(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db = _db([{"id": "a", "org_id": "o", "site_id": "s", "status": "generating", "created_at": old}])
        with patch.object(w, "get_supabase", return_value=db), patch.object(w, "write_worker_log"):
            assert w.run_premium_stale_sweep() == {"swept": 1, "failed": 0}
        assert db.rows("site_designs")[0]["status"] == "failed"

    def test_a_crash_is_counted_not_raised(self):
        with patch.object(w, "get_supabase", return_value=_db()), patch.object(w, "write_worker_log") as log, \
             patch("app.services.site_premium_generation_service.sweep_stale", side_effect=RuntimeError("db")):
            out = w.run_premium_stale_sweep()
        assert out == {"swept": 0, "failed": 1} and log.call_args.kwargs["status"] == "failed"


class TestGenerationTask:
    def test_runs_the_job_and_logs(self):
        with patch.object(w, "get_supabase", return_value=_db()), patch.object(w, "write_worker_log") as log, \
             patch("app.services.site_premium_generation_service.run_generation", return_value={"ok": True, "design_id": "d1", "outcome": "premium"}) as run:
            out = w.run_premium_generation("d1")
        assert out["outcome"] == "premium" and run.call_args.args[1] == "d1" and log.call_args.kwargs["status"] == "passed"

    def test_a_fallback_to_standard_is_a_normal_outcome_not_a_worker_failure(self):
        with patch.object(w, "get_supabase", return_value=_db()), patch.object(w, "write_worker_log") as log, \
             patch("app.services.site_premium_generation_service.run_generation", return_value={"ok": False, "outcome": "fallback_standard", "errors": ["x"]}):
            w.run_premium_generation("d1")
        assert log.call_args.kwargs["status"] == "passed"

    def test_a_crash_is_caught(self):
        with patch.object(w, "get_supabase", return_value=_db()), patch.object(w, "write_worker_log") as log, \
             patch("app.services.site_premium_generation_service.run_generation", side_effect=RuntimeError("x")):
            out = w.run_premium_generation("d1")
        assert out["outcome"] == "crashed" and log.call_args.kwargs["status"] == "failed"
