"""
GPM-2 — Unit tests: growth_insights_service.py
~14 tests
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.growth_insights_service import (
    _can_fire,
    _find_biggest_funnel_drop,
    _find_top_channel,
    _make_cache_key,
    _median,
    _velocity_trend,
    build_section_context,
    check_and_fire_anomalies,
    generate_panel_narrative,
    generate_section_insight,
    generate_weekly_digest,
    get_cached_insights,
    save_cached_insights,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_db_with_org(growth_insights=None, growth_anomaly_state=None):
    db = MagicMock()
    org_data = {}
    if growth_insights is not None:
        org_data["growth_insights"] = growth_insights
    if growth_anomaly_state is not None:
        org_data["growth_anomaly_state"] = growth_anomaly_state
    db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = org_data
    return db


# ── build_section_context: strips PII ────────────────────────────────────────

def test_build_section_context_overview_strips_pii():
    data = {
        "total_revenue": 50000,
        "total_leads": 100,
        "overall_conversion_rate": 12.5,  # correct field name from get_overview_metrics()
        "cac": 250,
        "some_pii_field": "John Doe",
    }
    ctx = build_section_context("overview", data)
    assert "some_pii_field" not in ctx
    assert ctx["total_revenue"] == 50000
    assert ctx["close_rate_pct"] == 12.5  # mapped to close_rate_pct in context builder


def test_build_section_context_sales_reps_no_names():
    data = [
        {"close_rate": 25, "revenue_closed": 10000, "leads_assigned": 10,
         "avg_response_time_mins": 5.0, "demo_show_rate": 80.0},
        {"close_rate": 15, "revenue_closed": 5000, "leads_assigned": 8,
         "avg_response_time_mins": 8.0, "demo_show_rate": 60.0},
    ]
    ctx = build_section_context("sales_reps", data)
    # No names in context — analytics service strips names via _as_list
    assert "name" not in str(ctx)
    assert ctx["rep_count"] == 2
    # Context returns per-rep list, not aggregated stats
    assert ctx["reps"][0]["close_rate_pct"] == 25


def test_build_section_context_team_performance_anonymised():
    data = {
        "teams": [
            {"name": "Sales A", "lead_count": 50, "converted": 10, "revenue": 20000, "close_rate_pct": 20},
        ]
    }
    ctx = build_section_context("team_performance", data)
    assert ctx["teams"][0]["team_label"] == "Team 1"
    assert "name" not in ctx["teams"][0]


# ── Cache helpers ─────────────────────────────────────────────────────────────

def test_get_cached_insights_returns_none_on_key_mismatch():
    db = _mock_db_with_org(growth_insights={
        "cache_key": "2026-01-01|2026-01-31",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {"overview": {"headline": "ok"}},
    })
    result = get_cached_insights(db, "org-1", "2026-02-01|2026-02-28")
    assert result is None


def test_get_cached_insights_returns_none_when_stale():
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    db = _mock_db_with_org(growth_insights={
        "cache_key": "2026-01-01|2026-01-31",
        "generated_at": stale_time,
        "sections": {"overview": {}},
    })
    result = get_cached_insights(db, "org-1", "2026-01-01|2026-01-31")
    assert result is None


def test_get_cached_insights_returns_sections_on_hit():
    fresh_time = datetime.now(timezone.utc).isoformat()
    sections = {"overview": {"headline": "Great week"}}
    db = _mock_db_with_org(growth_insights={
        "cache_key": "2026-04-01|2026-04-25",
        "generated_at": fresh_time,
        "sections": sections,
    })
    result = get_cached_insights(db, "org-1", "2026-04-01|2026-04-25")
    assert result == sections


def test_get_cached_insights_returns_none_on_db_error():
    db = MagicMock()
    db.table.side_effect = Exception("DB down")
    result = get_cached_insights(db, "org-1", "2026-04-01|2026-04-25")
    assert result is None


# ── generate_section_insight ──────────────────────────────────────────────────

def test_generate_section_insight_returns_dict_on_success():
    mock_response = json.dumps({
        "headline": "Strong revenue week",
        "detail": "Revenue up 20% driven by enterprise segment.",
        "action": "Double down on enterprise outreach.",
    })
    with patch("app.services.growth_insights_service._call_haiku", return_value=mock_response):
        result = generate_section_insight("overview", {"total_revenue": 50000, "lead_count": 100})
    assert result is not None
    assert "headline" in result
    assert "detail" in result
    assert "action" in result


def test_generate_section_insight_returns_none_on_haiku_failure():
    with patch("app.services.growth_insights_service._call_haiku", return_value=None):
        result = generate_section_insight("overview", {"total_revenue": 50000})
    assert result is None


def test_generate_section_insight_returns_none_for_unknown_section():
    result = generate_section_insight("nonexistent_section", {})
    assert result is None


# ── generate_panel_narrative ──────────────────────────────────────────────────

def test_generate_panel_narrative_returns_narrative_and_priorities():
    mock_response = json.dumps({
        "narrative": "Business is performing well. Revenue is up. Pipeline looks healthy.",
        "top_priorities": ["Increase enterprise leads", "Fix funnel drop at proposal", "Reduce CAC"],
    })
    with patch("app.services.growth_insights_service._call_haiku", return_value=mock_response):
        result = generate_panel_narrative({"overview": {"total_revenue": 50000}})
    assert result is not None
    assert len(result["top_priorities"]) == 3


def test_generate_panel_narrative_returns_none_on_failure():
    with patch("app.services.growth_insights_service._call_haiku", return_value=None):
        result = generate_panel_narrative({})
    assert result is None


# ── _can_fire anomaly cooldown ────────────────────────────────────────────────

def test_can_fire_returns_true_when_no_prior_alert():
    assert _can_fire("velocity_drop", {}) is True


def test_can_fire_returns_false_within_cooldown():
    recent = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    state = {"last_velocity_drop_alert": recent}
    assert _can_fire("velocity_drop", state) is False


def test_can_fire_returns_true_after_cooldown_elapsed():
    old = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    state = {"last_velocity_drop_alert": old}
    assert _can_fire("velocity_drop", state) is True


# ── Internal helpers ──────────────────────────────────────────────────────────

def test_median_even():
    assert _median([1, 3, 5, 7]) == 4.0


def test_median_odd():
    assert _median([1, 2, 3]) == 2


def test_find_biggest_funnel_drop_returns_worst_stage():
    stages = [
        {"stage": "new", "pct_from_previous": 100},
        {"stage": "contacted", "pct_from_previous": 60},
        {"stage": "meeting_done", "pct_from_previous": 20},  # worst
    ]
    result = _find_biggest_funnel_drop(stages)
    assert result["stage"] == "meeting_done"


def test_velocity_trend_up():
    weeks = [{"lead_count": 10}, {"lead_count": 15}, {"lead_count": 20}]
    assert _velocity_trend(weeks) == "up"


def test_velocity_trend_down():
    weeks = [{"lead_count": 30}, {"lead_count": 20}, {"lead_count": 10}]
    assert _velocity_trend(weeks) == "down"
