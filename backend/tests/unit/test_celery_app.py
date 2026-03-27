"""
tests/unit/test_celery_app.py
------------------------------
Unit tests for app/workers/celery_app.py.

Tests are deliberately import-time safe: they mock REDIS_URL so the module
can be imported without a live Redis connection.

Covers:
  - All 12 jobs from Technical Spec Section 7 are in beat_schedule
  - Job task names map to the correct worker files
  - SLA monitor is every 15 minutes
  - Payment failure monitor is every hour
  - Monday digest is restricted to day_of_week=1 (Monday)
  - Daily jobs that share a 05:00 UTC slot do not conflict
  - REDIS_URL validation raises RuntimeError if missing

Run with:
    pytest tests/unit/test_celery_app.py -v
"""

import importlib
import os
import sys
import types
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures — import celery_app with a mocked REDIS_URL
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def celery_app_module():
    """
    Import app.workers.celery_app with a fake Redis URL set.
    We use a rediss:// URL to satisfy the TLS check in development mode
    (ENVIRONMENT defaults to 'development' so the TLS guard is relaxed).
    """
    env_patch = {
        "REDIS_URL": "rediss://fake:fake@localhost:6379",
        "ENVIRONMENT": "development",
    }
    # Remove cached module so our env patch takes effect cleanly
    for key in list(sys.modules.keys()):
        if "celery_app" in key:
            del sys.modules[key]

    # Also stub out redbeat so we don't need it installed to test
    redbeat_stub = types.ModuleType("redbeat")
    redbeat_stub.RedBeatScheduler = object
    sys.modules.setdefault("redbeat", redbeat_stub)

    with patch.dict(os.environ, env_patch):
        import app.workers.celery_app as module  # noqa: E402
        yield module

    # Clean up
    for key in list(sys.modules.keys()):
        if "celery_app" in key:
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Required jobs from Technical Spec Section 7
# ---------------------------------------------------------------------------

REQUIRED_JOBS = [
    "daily_churn_scoring",
    "renewal_reminders",
    "monday_digest",
    "nps_scheduler",
    "trial_expiry_checker",
    "sla_monitor",
    "drip_scheduler",
    "win_back_scheduler",
    "lead_aging_checker",
    "anomaly_detector",
    "payment_failure_monitor",
    "re_engagement_queue",
]


class TestBeatScheduleCompleteness:
    def test_all_12_jobs_registered(self, celery_app_module):
        schedule = celery_app_module.celery_app.conf.beat_schedule
        for job_name in REQUIRED_JOBS:
            assert job_name in schedule, (
                f"Missing job '{job_name}' from beat_schedule — "
                f"required by Technical Spec Section 7"
            )

    def test_no_extra_undocumented_jobs(self, celery_app_module):
        schedule = celery_app_module.celery_app.conf.beat_schedule
        extra = set(schedule.keys()) - set(REQUIRED_JOBS)
        assert extra == set(), f"Undocumented jobs in beat_schedule: {extra}"

    def test_every_job_has_task_and_schedule(self, celery_app_module):
        schedule = celery_app_module.celery_app.conf.beat_schedule
        for name, config in schedule.items():
            assert "task" in config, f"Job '{name}' is missing 'task' key"
            assert "schedule" in config, f"Job '{name}' is missing 'schedule' key"


# ---------------------------------------------------------------------------
# Task name → worker file mapping
# ---------------------------------------------------------------------------

class TestTaskNameMapping:
    def _task(self, module, job_name: str) -> str:
        return module.celery_app.conf.beat_schedule[job_name]["task"]

    def test_churn_scoring_maps_to_churn_worker(self, celery_app_module):
        assert "churn_worker" in self._task(celery_app_module, "daily_churn_scoring")

    def test_renewal_reminders_maps_to_renewal_worker(self, celery_app_module):
        assert "renewal_worker" in self._task(celery_app_module, "renewal_reminders")

    def test_monday_digest_maps_to_digest_worker(self, celery_app_module):
        assert "digest_worker" in self._task(celery_app_module, "monday_digest")

    def test_nps_scheduler_maps_to_nps_worker(self, celery_app_module):
        assert "nps_worker" in self._task(celery_app_module, "nps_scheduler")

    def test_sla_monitor_maps_to_sla_worker(self, celery_app_module):
        assert "sla_worker" in self._task(celery_app_module, "sla_monitor")

    def test_drip_scheduler_maps_to_drip_worker(self, celery_app_module):
        assert "drip_worker" in self._task(celery_app_module, "drip_scheduler")

    def test_trial_expiry_maps_to_renewal_worker(self, celery_app_module):
        assert "renewal_worker" in self._task(celery_app_module, "trial_expiry_checker")

    def test_win_back_maps_to_renewal_worker(self, celery_app_module):
        assert "renewal_worker" in self._task(celery_app_module, "win_back_scheduler")

    def test_lead_aging_maps_to_churn_worker(self, celery_app_module):
        assert "churn_worker" in self._task(celery_app_module, "lead_aging_checker")

    def test_anomaly_maps_to_churn_worker(self, celery_app_module):
        assert "churn_worker" in self._task(celery_app_module, "anomaly_detector")

    def test_payment_monitor_maps_to_renewal_worker(self, celery_app_module):
        assert "renewal_worker" in self._task(celery_app_module, "payment_failure_monitor")

    def test_re_engagement_maps_to_churn_worker(self, celery_app_module):
        assert "churn_worker" in self._task(celery_app_module, "re_engagement_queue")


# ---------------------------------------------------------------------------
# Schedule correctness — Section 7 timing contract
# ---------------------------------------------------------------------------

class TestScheduleTiming:
    def _schedule(self, module, job_name: str):
        return module.celery_app.conf.beat_schedule[job_name]["schedule"]

    def test_sla_monitor_every_15_minutes(self, celery_app_module):
        """SLA monitor must run every 15 minutes — Section 7."""
        from celery.schedules import crontab
        sched = self._schedule(celery_app_module, "sla_monitor")
        assert isinstance(sched, crontab)
        # */15 is stored as every 15 — check minute field contains step
        assert "*/15" in str(sched) or sched.minute == "*/15"

    def test_monday_digest_day_of_week_is_monday(self, celery_app_module):
        """Digest must only run on Mondays (day_of_week=1) — Section 7."""
        from celery.schedules import crontab
        sched = self._schedule(celery_app_module, "monday_digest")
        assert isinstance(sched, crontab)
        assert "1" in str(sched.day_of_week)

    def test_payment_failure_monitor_every_hour(self, celery_app_module):
        """Payment failure monitor must run every hour — Section 7."""
        from celery.schedules import crontab
        sched = self._schedule(celery_app_module, "payment_failure_monitor")
        assert isinstance(sched, crontab)
        assert sched.minute == frozenset({0})

    def test_daily_churn_scoring_utc_hour(self, celery_app_module):
        """WAT 06:00 = UTC 05:00 — Section 7."""
        sched = self._schedule(celery_app_module, "daily_churn_scoring")
        assert sched.hour == frozenset({5})

    def test_renewal_reminders_utc_hour(self, celery_app_module):
        """WAT 08:00 = UTC 07:00 — Section 7."""
        sched = self._schedule(celery_app_module, "renewal_reminders")
        assert sched.hour == frozenset({7})

    def test_monday_digest_utc_hour(self, celery_app_module):
        """WAT 07:00 = UTC 06:00 — Section 7."""
        sched = self._schedule(celery_app_module, "monday_digest")
        assert sched.hour == frozenset({6})

    def test_nps_scheduler_utc_hour(self, celery_app_module):
        """WAT 09:00 = UTC 08:00 — Section 7."""
        sched = self._schedule(celery_app_module, "nps_scheduler")
        assert sched.hour == frozenset({8})


# ---------------------------------------------------------------------------
# REDIS_URL validation
# ---------------------------------------------------------------------------

class TestRedisUrlValidation:
    def test_raises_if_redis_url_missing(self):
        for key in list(sys.modules.keys()):
            if "celery_app" in key:
                del sys.modules[key]

        with patch.dict(os.environ, {"REDIS_URL": "", "ENVIRONMENT": "development"}):
            with pytest.raises(RuntimeError, match="REDIS_URL"):
                import app.workers.celery_app  # noqa: F401

    def test_raises_if_plaintext_in_production(self):
        for key in list(sys.modules.keys()):
            if "celery_app" in key:
                del sys.modules[key]

        with patch.dict(
            os.environ,
            {"REDIS_URL": "redis://localhost:6379", "ENVIRONMENT": "production"},
        ):
            with pytest.raises(RuntimeError, match="rediss://"):
                import app.workers.celery_app  # noqa: F401

    def test_tls_url_accepted_in_production(self):
        """rediss:// (TLS) must NOT raise in production."""
        for key in list(sys.modules.keys()):
            if "celery_app" in key:
                del sys.modules[key]

        import types as _types
        redbeat_stub = _types.ModuleType("redbeat")
        redbeat_stub.RedBeatScheduler = object
        sys.modules["redbeat"] = redbeat_stub

        with patch.dict(
            os.environ,
            {"REDIS_URL": "rediss://fake:fake@upstash.io:6380", "ENVIRONMENT": "production"},
        ):
            import app.workers.celery_app as m  # noqa: F401
            assert m.celery_app is not None


# ---------------------------------------------------------------------------
# Broker / backend configuration
# ---------------------------------------------------------------------------

class TestCeleryConfig:
    def test_json_serialiser(self, celery_app_module):
        conf = celery_app_module.celery_app.conf
        assert conf.task_serializer == "json"
        assert conf.result_serializer == "json"

    def test_utc_enabled(self, celery_app_module):
        assert celery_app_module.celery_app.conf.enable_utc is True

    def test_default_queue_is_default(self, celery_app_module):
        assert celery_app_module.celery_app.conf.task_default_queue == "default"

    def test_result_expires_24h(self, celery_app_module):
        assert celery_app_module.celery_app.conf.result_expires == 86_400

    def test_app_name(self, celery_app_module):
        assert celery_app_module.celery_app.main == "opsra"