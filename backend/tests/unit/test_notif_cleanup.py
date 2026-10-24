"""NOTIF-CLEANUP: each SLA / aging alert is sent once per lead (not every run), and old notifications are trimmed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.workers import churn_worker as churn
from app.workers import lead_sla_worker as sla
from app.workers import notification_retention_worker as ret
from tests.unit.test_wa_auto_4a import KDB

ORG = "00000000-0000-0000-0000-00000000aa01"
HOURS = {"hot": 1, "warm": 4, "cold": 24}


def _now():
    return datetime.now(timezone.utc)


def _lead(hours_old, **extra):
    return {"id": "L1", "org_id": ORG, "full_name": "Ada", "score": "hot", "assigned_to": "rep1",
            "created_at": (_now() - timedelta(hours=hours_old)).isoformat(), **extra}


def _db(lead):
    return KDB(leads=[dict(lead)], notifications=[])


@pytest.fixture(autouse=True)
def _manager(monkeypatch):
    monkeypatch.setattr(sla, "_get_org_manager_id", lambda db, org, exclude_user_id=None: "mgr1")


def _run(db, times=1):
    for _ in range(times):
        lead = dict(db.tables["leads"][0])      # the worker reads the lead fresh each run
        sla._process_lead(db, lead, HOURS)


def _types(db):
    return sorted((n["type"], n["user_id"]) for n in db.tables["notifications"])


def test_first_threshold_alerts_the_rep_once_however_many_runs():
    db = _db(_lead(1.5))
    _run(db, 50)
    assert _types(db) == [("lead_sla_breach", "rep1")]
    assert db.tables["leads"][0]["sla_breach_notified_at"]


def test_second_threshold_adds_one_escalation_once():
    db = _db(_lead(1.5))
    _run(db, 5)
    db.tables["leads"][0]["created_at"] = (_now() - timedelta(hours=3)).isoformat()      # time passes: now past 2x
    _run(db, 50)
    assert _types(db) == [("lead_sla_breach", "rep1"), ("lead_sla_escalation", "mgr1")]
    assert db.tables["leads"][0]["sla_escalated_at"]


def test_a_lead_first_seen_past_2x_gets_one_of_each():
    db = _db(_lead(5))
    _run(db, 20)
    assert _types(db) == [("lead_sla_breach", "rep1"), ("lead_sla_escalation", "mgr1")]


def test_already_alerted_leads_send_nothing_new_but_a_missing_escalation_still_goes_once():
    marked = _now().isoformat()
    db = _db(_lead(5, sla_breach_notified_at=marked))
    _run(db, 10)
    assert _types(db) == [("lead_sla_escalation", "mgr1")]
    db2 = _db(_lead(5, sla_breach_notified_at=marked, sla_escalated_at=marked))
    _run(db2, 10)
    assert db2.tables["notifications"] == []


def test_no_manager_does_not_mean_a_lookup_every_run(monkeypatch):
    calls = []
    monkeypatch.setattr(sla, "_get_org_manager_id", lambda *a, **k: calls.append(1))
    db = _db(_lead(5, sla_breach_notified_at=_now().isoformat()))
    _run(db, 10)
    assert len(calls) == 1 and db.tables["notifications"] == []


def test_a_failed_insert_is_retried_next_run_not_marked(monkeypatch):
    db = _db(_lead(1.5))
    real = sla._insert_notification
    monkeypatch.setattr(sla, "_insert_notification", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    _run(db)
    assert "sla_breach_notified_at" not in db.tables["leads"][0] or not db.tables["leads"][0]["sla_breach_notified_at"]
    monkeypatch.setattr(sla, "_insert_notification", real)
    _run(db)
    assert _types(db) == [("lead_sla_breach", "rep1")]


def test_leads_under_the_threshold_and_without_a_rep_are_untouched():
    db = _db(_lead(0.2))
    _run(db, 3)
    assert db.tables["notifications"] == []
    db2 = _db(_lead(1.5, assigned_to=None))
    _run(db2, 3)
    assert db2.tables["notifications"] == [] and not db2.tables["leads"][0].get("sla_breach_notified_at")


def test_the_worker_reads_the_marker_columns():
    import inspect
    assert "sla_breach_notified_at, sla_escalated_at" in inspect.getsource(sla.run_lead_sla_check)


# -- aging ----------------------------------------------------------------------------------------------------------
class _Self:
    """Lets run_lead_aging_checker run without Celery (it only uses self.retry on a fatal error)."""
    def retry(self, **k):
        raise RuntimeError("retry")


def _aging(db, monkeypatch):
    monkeypatch.setattr(churn, "get_supabase", lambda: db)
    churn.run_lead_aging_checker.run.__wrapped__(_Self()) if hasattr(churn.run_lead_aging_checker.run, "__wrapped__") else churn.run_lead_aging_checker.run.__func__(_Self())


def _aging_db(**lead):
    old = (_now() - timedelta(days=10)).isoformat()
    return KDB(organisations=[{"id": ORG}], notifications=[], tasks=[],
               leads=[{"id": "L1", "org_id": ORG, "full_name": "Ada", "assigned_to": "rep1", "last_activity_at": old, "stage": "new", **lead}])


def test_a_stale_lead_is_flagged_once_not_every_day(monkeypatch):
    db = _aging_db()
    for _ in range(5):
        _aging(db, monkeypatch)
    assert len(db.tables["notifications"]) == 1 and len(db.tables["tasks"]) == 1
    assert db.tables["leads"][0]["aging_notified_at"]


def test_a_stale_lead_is_flagged_again_after_a_week(monkeypatch):
    db = _aging_db(aging_notified_at=(_now() - timedelta(days=8)).isoformat())
    _aging(db, monkeypatch)
    assert len(db.tables["notifications"]) == 1
    db2 = _aging_db(aging_notified_at=(_now() - timedelta(days=2)).isoformat())
    _aging(db2, monkeypatch)
    assert db2.tables["notifications"] == []


# -- retention ------------------------------------------------------------------------------------------------------
class RpcDB:
    def __init__(self, counts, boom=False):
        self.counts, self.calls, self.boom = list(counts), [], boom

    def rpc(self, name, params):
        db = self

        class R:
            def execute(_s):
                db.calls.append((name, params))
                if db.boom:
                    raise RuntimeError("down")
                return SimpleNamespace(data=db.counts.pop(0))
        return R()


def test_retention_loops_until_a_short_batch():
    db = RpcDB([5000, 5000, 1200, 99])
    assert ret.purge(db) == {"deleted": 11200, "failed": 0}
    assert len(db.calls) == 3 and db.calls[0] == ("purge_old_notifications", {"p_batch": 5000})


def test_retention_is_capped_per_run_and_never_raises():
    db = RpcDB([5000] * 50)
    assert ret.purge(db)["deleted"] == 5000 * ret.MAX_BATCHES
    bad = RpcDB([], boom=True)
    assert ret.purge(bad) == {"deleted": 0, "failed": 1}


def test_retention_is_scheduled():
    from app.workers.celery_app import celery_app
    assert celery_app.conf.beat_schedule["notification-retention"]["task"] == "app.workers.notification_retention_worker.run_notification_retention"


def test_sql_files_do_what_they_say():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3] / "supabase"
    a = (root / "migrations" / "2026_10_24_notif_cleanup_1.sql").read_text()
    for col in ("sla_breach_notified_at", "sla_escalated_at", "aging_notified_at"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in a
    assert "purge_old_notifications" in a and "REVOKE ALL ON FUNCTION" in a
    b = (root / "maintenance" / "2026_10_24_notif_cleanup_2_RUN_AFTER_DEPLOY.sql").read_text()
    assert "LOCK TABLE public.notifications IN EXCLUSIVE MODE" in b and "TRUNCATE public.notifications" in b
    assert b.index("\nBEGIN;") < b.index("\nTRUNCATE public.notifications;") < b.index("\nCOMMIT;") and "DELETE FROM" not in b
    assert "type NOT IN ('lead_sla_breach', 'lead_sla_escalation', 'lead_aging')" in b
