"""
tests/unit/test_growth_analytics_service.py
Unit tests for GPM-1A growth_analytics_service.py — 16 tests.

Pattern 24: all UUIDs are valid UUID4 format.
Pattern 33: Python-side grouping verified.
"""
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from app.services import growth_analytics_service as svc

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_ID = "11111111-1111-4111-a111-111111111111"

def _make_db(leads=None, subscriptions=None, direct_sales=None,
             campaign_spend=None, users=None):
    """
    Build a mock db with chained .table().select()...execute() responses.
    Each table call returns its mock list on .execute().data.
    """
    db = MagicMock()

    def _table(name):
        t = MagicMock()
        mapping = {
            "leads":           leads or [],
            "subscriptions":   subscriptions or [],
            "direct_sales":    direct_sales or [],
            "campaign_spend":  campaign_spend or [],
            "users":           users or [],
        }
        t.select.return_value = t
        t.eq.return_value = t
        t.is_.return_value = t
        t.order.return_value = t
        t.range.return_value = t
        t.execute.return_value.data = mapping.get(name, [])
        t.execute.return_value.count = len(mapping.get(name, []))
        return t

    db.table.side_effect = _table
    return db


def _lead(
    stage="new",
    created_at="2025-03-15",
    first_touch_team=None,
    utm_source=None,
    deal_value=0,
    assigned_to="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
    response_time_minutes=None,
    score="unscored",
    lost_reason=None,
    closed_at=None,
    converted_at=None,
):
    return {
        "id":                    "cccccccc-cccc-4ccc-cccc-cccccccccccc",
        "stage":                 stage,
        "created_at":            created_at,
        "closed_at":             closed_at,
        "converted_at":          converted_at,
        "score":                 score,
        "assigned_to":           assigned_to,
        "first_touch_team":      first_touch_team,
        "utm_source":            utm_source,
        "campaign_id":           None,
        "entry_path":            None,
        "response_time_minutes": response_time_minutes,
        "lost_reason":           lost_reason,
        "deal_value":            deal_value,
        "source_team":           first_touch_team,
    }


DF = date(2025, 3, 1)
DT = date(2025, 3, 31)

# ---------------------------------------------------------------------------
# 1. overview: revenue correctly sums all 3 sources
# ---------------------------------------------------------------------------

def test_overview_revenue_sums_all_sources():
    leads = [_lead(stage="converted", deal_value=100_000, created_at="2025-03-10", converted_at="2025-03-20")]
    subs  = [{"amount": 50_000, "renewal_date": "2025-03-15", "status": "renewed"}]
    ds    = [{"amount": 25_000, "sale_date": "2025-03-20"}]

    db = _make_db(leads=leads, subscriptions=subs, direct_sales=ds)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["total_revenue"] == 175_000.0
    assert result["revenue_breakdown"]["leads"] == 100_000.0
    assert result["revenue_breakdown"]["renewals"] == 50_000.0
    assert result["revenue_breakdown"]["direct_sales"] == 25_000.0


# ---------------------------------------------------------------------------
# 2. overview: revenue_breakdown splits correctly by source
# ---------------------------------------------------------------------------

def test_overview_revenue_breakdown_zero_when_no_renewals():
    leads = [_lead(stage="converted", deal_value=80_000, created_at="2025-03-05", converted_at="2025-03-15")]
    db = _make_db(leads=leads)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["revenue_breakdown"]["renewals"] == 0.0
    assert result["revenue_breakdown"]["direct_sales"] == 0.0
    assert result["revenue_breakdown"]["leads"] == 80_000.0


# ---------------------------------------------------------------------------
# 3. overview: correct conversion rate
# ---------------------------------------------------------------------------

def test_overview_conversion_rate():
    leads = [
        _lead(stage="converted", deal_value=10_000, created_at="2025-03-05", converted_at="2025-03-10"),
        _lead(stage="new", created_at="2025-03-08"),
        _lead(stage="new", created_at="2025-03-12"),
        _lead(stage="converted", deal_value=20_000, created_at="2025-03-14", converted_at="2025-03-20"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["total_leads"] == 4
    assert result["total_conversions"] == 2
    assert result["overall_conversion_rate"] == 50.0


# ---------------------------------------------------------------------------
# 4. overview: CAC is None when no spend records
# ---------------------------------------------------------------------------

def test_overview_cac_none_when_no_spend():
    leads = [_lead(stage="converted", deal_value=50_000, created_at="2025-03-10", converted_at="2025-03-15")]
    db = _make_db(leads=leads)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["cac"] is None
    assert result["total_spend"] == 0.0


# ---------------------------------------------------------------------------
# 5. overview: CAC calculates correctly when spend exists
# ---------------------------------------------------------------------------

def test_overview_cac_correct_with_spend():
    leads = [
        _lead(stage="converted", deal_value=50_000, created_at="2025-03-10", converted_at="2025-03-15"),
        _lead(stage="converted", deal_value=50_000, created_at="2025-03-12", converted_at="2025-03-18"),
    ]
    spend = [{"amount": 20_000, "period_start": "2025-03-01", "period_end": "2025-03-31"}]
    db = _make_db(leads=leads, campaign_spend=spend)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["total_spend"] == 20_000.0
    assert result["cac"] == 10_000.0  # 20_000 / 2 conversions


# ---------------------------------------------------------------------------
# 6. team_performance: groups correctly by first_touch_team
# ---------------------------------------------------------------------------

def test_team_performance_groups_by_first_touch_team():
    leads = [
        _lead(stage="converted", deal_value=100_000, created_at="2025-03-05", first_touch_team="Team A"),
        _lead(stage="new",       deal_value=0,        created_at="2025-03-08", first_touch_team="Team A"),
        _lead(stage="converted", deal_value=50_000,  created_at="2025-03-10", first_touch_team="Team B"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_team_performance(db, ORG_ID, DF, DT)

    team_names = [r["team_name"] for r in result]
    assert "Team A" in team_names
    assert "Team B" in team_names

    team_a = next(r for r in result if r["team_name"] == "Team A")
    assert team_a["leads_generated"] == 2
    assert team_a["conversions"] == 1
    assert team_a["conversion_rate"] == 50.0
    assert team_a["revenue_generated"] == 100_000.0


# ---------------------------------------------------------------------------
# 7. team_performance: null first_touch_team → "Unattributed"
# ---------------------------------------------------------------------------

def test_team_performance_null_team_is_unattributed():
    leads = [
        _lead(stage="new", created_at="2025-03-05", first_touch_team=None),
        _lead(stage="new", created_at="2025-03-10", first_touch_team=None),
    ]
    db = _make_db(leads=leads)
    result = svc.get_team_performance(db, ORG_ID, DF, DT)

    team_names = [r["team_name"] for r in result]
    assert "Unattributed" in team_names
    unattr = next(r for r in result if r["team_name"] == "Unattributed")
    assert unattr["leads_generated"] == 2


# ---------------------------------------------------------------------------
# 8. team_performance: cost_per_lead and CAC are None when no spend
# ---------------------------------------------------------------------------

def test_team_performance_no_spend_gives_null_cost_metrics():
    leads = [_lead(stage="converted", deal_value=10_000, created_at="2025-03-05", first_touch_team="Team A")]
    db = _make_db(leads=leads)
    result = svc.get_team_performance(db, ORG_ID, DF, DT)

    team_a = next(r for r in result if r["team_name"] == "Team A")
    assert team_a["cac"] is None
    assert team_a["cost_per_lead"] is None


# ---------------------------------------------------------------------------
# 9. funnel: stage percentages correct
# ---------------------------------------------------------------------------

def test_funnel_stage_percentages():
    leads = [
        _lead(stage="converted",     created_at="2025-03-05"),
        _lead(stage="converted",     created_at="2025-03-06"),
        _lead(stage="proposal_sent", created_at="2025-03-07"),
        _lead(stage="new",           created_at="2025-03-08"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_funnel_metrics(db, ORG_ID, DF, DT)

    assert result["total_leads"] == 4
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["new"]["count"] == 4
    assert stages["new"]["pct_from_top"] == 100.0
    # All 4 reached "new", 3 reached "proposal_sent" or beyond
    assert stages["proposal_sent"]["count"] == 3
    assert stages["converted"]["count"] == 2
    assert result["overall_close_rate"] == 50.0


# ---------------------------------------------------------------------------
# 10. funnel: team filter reduces dataset
# ---------------------------------------------------------------------------

def test_funnel_team_filter():
    leads = [
        _lead(stage="converted", created_at="2025-03-05", first_touch_team="Team A"),
        _lead(stage="new",       created_at="2025-03-08", first_touch_team="Team B"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_funnel_metrics(db, ORG_ID, DF, DT, team="Team A")

    assert result["total_leads"] == 1
    assert result["team"] == "Team A"


# ---------------------------------------------------------------------------
# 11. funnel: "Unattributed" team filter works
# ---------------------------------------------------------------------------

def test_funnel_unattributed_filter():
    leads = [
        _lead(stage="new", created_at="2025-03-05", first_touch_team=None),
        _lead(stage="new", created_at="2025-03-08", first_touch_team="Team A"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_funnel_metrics(db, ORG_ID, DF, DT, team="Unattributed")

    assert result["total_leads"] == 1


# ---------------------------------------------------------------------------
# 12. sales_reps: sales_agent role returns only own row
# ---------------------------------------------------------------------------

def test_sales_reps_scoped_for_sales_agent():
    rep_a = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    rep_b = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    leads = [
        _lead(stage="new", created_at="2025-03-05", assigned_to=rep_a),
        _lead(stage="new", created_at="2025-03-08", assigned_to=rep_b),
    ]
    users = [
        {"id": rep_a, "full_name": "Rep A", "roles": {"template": "sales_agent"}},
        {"id": rep_b, "full_name": "Rep B", "roles": {"template": "sales_agent"}},
    ]
    db = _make_db(leads=leads, users=users)
    result = svc.get_sales_rep_metrics(db, ORG_ID, DF, DT, rep_a, "sales_agent")

    assert len(result) == 1
    assert result[0]["rep_id"] == rep_a


# ---------------------------------------------------------------------------
# 13. sales_reps: owner role returns all reps
# ---------------------------------------------------------------------------

def test_sales_reps_owner_sees_all():
    rep_a = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    rep_b = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    leads = [
        _lead(stage="new", created_at="2025-03-05", assigned_to=rep_a),
        _lead(stage="new", created_at="2025-03-08", assigned_to=rep_b),
    ]
    users = [
        {"id": rep_a, "full_name": "Rep A", "roles": {"template": "sales_agent"}},
        {"id": rep_b, "full_name": "Rep B", "roles": {"template": "sales_agent"}},
    ]
    db = _make_db(leads=leads, users=users)
    result = svc.get_sales_rep_metrics(db, ORG_ID, DF, DT, rep_a, "owner")

    rep_ids = [r["rep_id"] for r in result]
    assert rep_a in rep_ids
    assert rep_b in rep_ids


# ---------------------------------------------------------------------------
# 14. sales_reps: reps with no leads return zero metrics
# ---------------------------------------------------------------------------

def test_sales_reps_zero_metrics_when_no_leads():
    rep_a = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    users = [{"id": rep_a, "full_name": "Rep A", "roles": {"template": "sales_agent"}}]
    db = _make_db(leads=[], users=users)
    result = svc.get_sales_rep_metrics(db, ORG_ID, DF, DT, rep_a, "owner")

    assert any(r["rep_id"] == rep_a for r in result)
    rep = next(r for r in result if r["rep_id"] == rep_a)
    assert rep["leads_assigned"] == 0
    assert rep["close_rate"] == 0.0
    assert rep["revenue_closed"] == 0.0


# ---------------------------------------------------------------------------
# 15. channels: groups by utm_source, includes 0-conversion channels
# ---------------------------------------------------------------------------

def test_channel_metrics_includes_zero_conversion_channels():
    leads = [
        _lead(stage="new",       created_at="2025-03-05", utm_source="facebook"),
        _lead(stage="converted", deal_value=50_000, created_at="2025-03-08",
              utm_source="google", converted_at="2025-03-15"),
    ]
    db = _make_db(leads=leads)
    result = svc.get_channel_metrics(db, ORG_ID, DF, DT)

    channels = {r["utm_source"]: r for r in result}
    assert "facebook" in channels
    assert "google" in channels
    assert channels["facebook"]["conversions"] == 0
    assert channels["facebook"]["conversion_rate"] == 0.0
    assert channels["google"]["conversions"] == 1


# ---------------------------------------------------------------------------
# 16. date range: excludes leads outside range
# ---------------------------------------------------------------------------

def test_date_range_excludes_outside_leads():
    leads = [
        _lead(stage="converted", deal_value=100_000, created_at="2025-02-10", converted_at="2025-02-20"),  # before range
        _lead(stage="converted", deal_value=50_000,  created_at="2025-03-10", converted_at="2025-03-20"),  # in range
        _lead(stage="converted", deal_value=75_000,  created_at="2025-04-05", converted_at="2025-04-10"),  # after range
    ]
    db = _make_db(leads=leads)
    result = svc.get_overview_metrics(db, ORG_ID, DF, DT)

    assert result["total_leads"] == 1
    assert result["revenue_breakdown"]["leads"] == 50_000.0
