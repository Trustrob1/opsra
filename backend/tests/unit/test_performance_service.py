"""
tests/unit/test_performance_service.py
----------------------------------------
Unit tests for PERF-1A performance_service.py.

Covers:
  - Health score formula (all 4 components)
  - KPI achievement % calculation
  - Pace status logic
  - Cache invalidation triggers
  - verify_owner_session_token round-trip
  - PIN hash/verify round-trip
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

import app.services.performance_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    db = MagicMock()
    db.table.return_value = db
    db.select.return_value = db
    db.insert.return_value = db
    db.update.return_value = db
    db.eq.return_value = db
    db.limit.return_value = db
    db.order.return_value = db
    db.single.return_value = db
    db.execute.return_value = MagicMock(data=[])
    return db


ORG_ID   = "11111111-1111-1111-1111-111111111111"
USER_ID  = "22222222-2222-2222-2222-222222222222"
TOKEN    = "tok_abc123"


# ---------------------------------------------------------------------------
# KPI achievement %
# ---------------------------------------------------------------------------

def test_kpi_achievement_pct_full():
    assert svc._kpi_achievement_pct(100, 100) == 100.0


def test_kpi_achievement_pct_over_target():
    assert svc._kpi_achievement_pct(150, 100) == 100.0  # capped at 100


def test_kpi_achievement_pct_partial():
    assert svc._kpi_achievement_pct(50, 100) == 50.0


def test_kpi_achievement_pct_none_actual():
    assert svc._kpi_achievement_pct(None, 100) == 0.0


def test_kpi_achievement_pct_zero_target():
    assert svc._kpi_achievement_pct(50, 0) == 0.0


# ---------------------------------------------------------------------------
# Pace status
# ---------------------------------------------------------------------------

def test_pace_ahead():
    # 80% done with 50% of month elapsed = ahead
    assert svc._pace_status(80, 100, 15, 30) == "Ahead"


def test_pace_on_track():
    # 95% of pace → on track
    assert svc._pace_status(47.5, 100, 50, 100) == "On Track"


def test_pace_behind():
    # 50% done with 80% of month elapsed = behind
    assert svc._pace_status(50, 100, 80, 100) == "Behind"


def test_pace_zero_target():
    assert svc._pace_status(0, 0, 15, 30) == "On Track"


# ---------------------------------------------------------------------------
# Health score formula
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_score_all_perfect():
    """All components at 100 → health = 100."""
    with patch.object(svc, "_cache_get", return_value=None), \
         patch.object(svc, "_cache_set"), \
         patch.object(svc, "_async_fetch") as mock_fetch:

        today = date.today()
        month_str = str(date(today.year, today.month, 1))

        def _side(db, table, select, filters):
            if table == "organisations":
                return [{"id": ORG_ID, "health_score_weights": {"sales": 35, "staff": 25, "tasks": 20, "support": 20},
                          "monthly_revenue_target": 0}]
            if table == "staff_kpi_targets":
                return [{"target_value": 100, "actual_value": 100, "month_start": month_str}]
            if table == "tasks":
                return [{"id": "t1", "status": "completed", "due_date": str(today)}]
            if table == "tickets":
                return [{"id": "tk1", "status": "resolved", "created_at": str(today)}]
            if table == "leads":
                return []
            return []

        mock_fetch.side_effect = _side

        result = await svc.get_health_score(MagicMock(), ORG_ID)
        assert result["health_score"] == 100.0
        assert result["colour"] == "green"


@pytest.mark.asyncio
async def test_health_score_colour_amber():
    """
    Force a degraded score by setting a revenue target with zero actual revenue
    (so sales_score is low), low staff achievement, and low task completion.
    With weights sales=35, staff=25, tasks=20, support=20:
      sales_score   ≈ 0   (revenue target set, no deals closed)
      staff_score   = 40  (40% KPI achievement)
      tasks_score   = 40  (2 of 5 tasks complete)
      support_score = 100 (no tickets)
    health = 0*0.35 + 40*0.25 + 40*0.20 + 100*0.20 = 0 + 10 + 8 + 20 = 38 → red
    Test asserts colour is amber or red (degraded).
    """
    with patch.object(svc, "_cache_get", return_value=None), \
         patch.object(svc, "_cache_set"), \
         patch.object(svc, "_async_fetch") as mock_fetch:

        from datetime import date
        today = date.today()
        month_str = str(date(today.year, today.month, 1))

        def _side(db, table, select, filters):
            if table == "organisations":
                return [{"id": ORG_ID,
                         "health_score_weights": {"sales": 35, "staff": 25, "tasks": 20, "support": 20},
                         "monthly_revenue_target": 100000}]  # target set, forces pace calc
            if table == "staff_kpi_targets":
                return [{"target_value": 100, "actual_value": 40, "month_start": month_str}]
            if table == "tasks":
                return [
                    {"id": "t1", "status": "completed", "due_date": str(today)},
                    {"id": "t2", "status": "completed", "due_date": str(today)},
                    {"id": "t3", "status": "open",      "due_date": str(today)},
                    {"id": "t4", "status": "open",      "due_date": str(today)},
                    {"id": "t5", "status": "open",      "due_date": str(today)},
                ]
            if table == "tickets":
                return []
            if table == "leads":
                return []  # no conversions → sales_score driven to 0 by pace
            return []

        mock_fetch.side_effect = _side
        result = await svc.get_health_score(MagicMock(), ORG_ID)
        assert result["colour"] in ("amber", "red")


@pytest.mark.asyncio
async def test_health_score_uses_cache():
    cached = {"health_score": 77.5, "colour": "green", "components": {}, "weights": {}}
    with patch.object(svc, "_cache_get", return_value=cached) as mock_get:
        result = await svc.get_health_score(MagicMock(), ORG_ID)
        assert result["health_score"] == 77.5
        mock_get.assert_called_once_with(f"perf:health:{ORG_ID}")


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------

def test_invalidate_clears_correct_keys():
    with patch.object(svc, "_cache_delete") as mock_del:
        svc._invalidate_org_perf_cache(ORG_ID, USER_ID, "2026-06")
        args = mock_del.call_args[0]
        assert f"perf:health:{ORG_ID}" in args
        assert f"perf:owner_dash:{ORG_ID}" in args
        assert f"perf:scorecard:{ORG_ID}:2026-06" in args
        assert f"perf:staff:{ORG_ID}:{USER_ID}:2026-06" in args


def test_invalidate_no_user_skips_staff_key():
    with patch.object(svc, "_cache_delete") as mock_del:
        svc._invalidate_org_perf_cache(ORG_ID)
        args = mock_del.call_args[0]
        assert not any("perf:staff:" in k for k in args)


# ---------------------------------------------------------------------------
# Session token round-trip
# ---------------------------------------------------------------------------

def test_session_token_round_trip():
    token = svc.generate_owner_session_token(ORG_ID, TOKEN)
    assert svc.verify_owner_session_token(token, ORG_ID, TOKEN)


def test_session_token_wrong_org():
    token = svc.generate_owner_session_token(ORG_ID, TOKEN)
    assert not svc.verify_owner_session_token(token, "other-org", TOKEN)


def test_session_token_wrong_dashboard_token():
    token = svc.generate_owner_session_token(ORG_ID, TOKEN)
    assert not svc.verify_owner_session_token(token, ORG_ID, "wrong_token")


def test_session_token_malformed():
    assert not svc.verify_owner_session_token("bad:token", ORG_ID, TOKEN)


# ---------------------------------------------------------------------------
# PIN hash/verify
# ---------------------------------------------------------------------------

def test_pin_hash_and_verify():
    db = _make_db()
    db.execute.return_value = MagicMock(data=[])
    svc.set_owner_dashboard_pin(db, ORG_ID, "1234")
    # Verify the hash was passed to update
    update_call = db.update.call_args
    assert update_call is not None
    hashed = update_call[0][0]["owner_dashboard_pin"]
    import bcrypt as _bcrypt_lib
    assert _bcrypt_lib.checkpw(b"1234", hashed.encode())


# ---------------------------------------------------------------------------
# Seed templates — no duplicate insertion
# ---------------------------------------------------------------------------

def test_seed_kpi_templates_skips_existing():
    db = _make_db()
    db.execute.return_value = MagicMock(data=[
        {"role_template": "sales_agent", "kpi_name": "Leads Contacted"},
    ])
    svc._seed_kpi_templates(db, ORG_ID)
    insert_call = db.insert.call_args
    if insert_call:
        rows = insert_call[0][0]
        # Ensure "Leads Contacted" for sales_agent is NOT re-inserted
        for r in rows:
            assert not (r["role_template"] == "sales_agent" and r["kpi_name"] == "Leads Contacted")


def test_month_start_parsing():
    d = svc._month_start("2026-06")
    assert d.day == 1
    assert d.month == 6
    assert d.year == 2026


def test_score_colour():
    assert svc._score_colour(80) == "green"
    assert svc._score_colour(60) == "amber"
    assert svc._score_colour(40) == "red"
    assert svc._score_colour(75) == "green"
    assert svc._score_colour(50) == "amber"
