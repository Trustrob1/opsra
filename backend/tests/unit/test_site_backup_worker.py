"""
tests/unit/test_site_backup_worker.py
--------------------------------------
SITE-BACKUP — the Celery tasks around the backup service: run_site_backup (alerts on failure) and
run_site_backup_watchdog. In-memory fakes only; push sending is stubbed out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import site_backup_service as bk
from app.workers import site_worker as sw
from tests.unit.test_site_backup_service import D1, D2, FakeDB, FakeS3, r2_with

ORG = "11111111-1111-1111-1111-111111111111"
MGR = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    db.table("site_orders").insert({"id": "o1", "org_id": ORG, "domain": D1}).execute()
    db.table("users").insert({"id": MGR, "org_id": ORG, "roles": {"template": "owner"}}).execute()
    pushes = []
    monkeypatch.setattr(sw, "get_supabase", lambda: db)
    monkeypatch.setattr(sw, "_push", lambda db_, uid, title, body: pushes.append((uid, title)))
    monkeypatch.setattr(sw, "write_worker_log", lambda *a, **k: None)
    return db, pushes


def _use_clients(monkeypatch, r2, b2):
    monkeypatch.setattr(bk.sp, "make_client", lambda: r2)
    monkeypatch.setattr(bk.sp, "_bucket", lambda: "opsra-sites")
    monkeypatch.setattr(bk, "make_backup_client", lambda: b2)
    monkeypatch.setattr(bk, "_backup_bucket", lambda: "backups")


def _alerts(db):
    return [n for n in db.tables.get("notifications", []) if n["type"] == "site_backup_alert"]


def test_successful_run_sends_no_alert(env, monkeypatch):
    db, pushes = env
    _use_clients(monkeypatch, r2_with(D1, D2), FakeS3())
    out = sw.run_site_backup()
    assert out["status"] == "ok" and out["domains_backed_up"] == 2
    assert _alerts(db) == [] and pushes == []


def test_not_configured_run_alerts_the_managers(env):
    db, pushes = env
    out = sw.run_site_backup()                      # BACKUP_S3_* unset in tests
    assert out["status"] == "failed"
    a = _alerts(db)
    assert len(a) == 1 and a[0]["user_id"] == MGR and a[0]["org_id"] == ORG
    assert pushes == [(MGR, "Site backup failed")]


def test_partial_run_alerts_with_the_site_name(env, monkeypatch):
    db, pushes = env
    r2 = r2_with(D1, D2); r2.fail_get = D2
    _use_clients(monkeypatch, r2, FakeS3())
    out = sw.run_site_backup()
    assert out["status"] == "partial"
    assert D2 in _alerts(db)[0]["body"] and pushes[0][1] == "Site backup incomplete"


def test_crash_inside_the_service_still_alerts(env, monkeypatch):
    db, _ = env
    monkeypatch.setattr(bk, "run_backup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")))
    out = sw.run_site_backup()
    assert out["status"] == "failed" and "kaboom" in out["error"] and len(_alerts(db)) == 1


def test_watchdog_alerts_when_no_backup_ever_ran(env):
    db, pushes = env
    out = sw.run_site_backup_watchdog()
    assert "ever run" in out["problem"] and out["alerted_orgs"] == 1 and len(_alerts(db)) == 1


def test_watchdog_is_quiet_when_last_run_is_healthy(env):
    db, pushes = env
    db.table("site_backup_runs").insert({"status": "ok", "started_at": datetime.now(timezone.utc).isoformat()}).execute()
    assert sw.run_site_backup_watchdog()["problem"] is None and _alerts(db) == []


def test_alert_is_not_repeated_within_20_hours(env):
    db, pushes = env
    sw.run_site_backup()                            # failed run -> alert
    sw.run_site_backup_watchdog()                   # morning watchdog sees the same failure
    assert len(_alerts(db)) == 1 and len(pushes) == 1


def test_watchdog_stays_silent_before_any_site_order_exists(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(sw, "get_supabase", lambda: db)
    monkeypatch.setattr(sw, "write_worker_log", lambda *a, **k: None)
    assert sw.run_site_backup_watchdog()["problem"] is None


def test_tasks_are_scheduled():
    from app.workers.celery_app import celery_app
    sched = {v["task"]: v["schedule"] for v in celery_app.conf.beat_schedule.values()}
    assert "app.workers.site_worker.run_site_backup" in sched
    assert "app.workers.site_worker.run_site_backup_watchdog" in sched
    assert 1 in sched["app.workers.site_worker.run_site_backup"].hour


def test_alert_still_goes_out_when_the_dedup_lookup_times_out(env, monkeypatch):
    db, pushes = env
    real_table = db.table

    def flaky(name):
        if name == "notifications":
            q = real_table(name)
            orig = q.execute
            def boom():
                if q.op == "select":
                    raise RuntimeError("canceling statement due to statement timeout")
                return orig()
            q.execute = boom
            return q
        return real_table(name)

    monkeypatch.setattr(db, "table", flaky)
    sw.run_site_backup()                            # BACKUP_S3_* unset in tests -> failed run
    assert len(_alerts(db)) == 1 and pushes == [(MGR, "Site backup failed")]
