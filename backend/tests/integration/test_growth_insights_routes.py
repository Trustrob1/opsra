"""
GPM-2 — Integration tests: growth_insights.py routes
~12 tests
Pattern 61: _ORG_PAYLOAD uses "id" not "user_id"
Pattern 44: override get_current_org directly
Pattern 62: db via Depends(get_supabase)
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_org, get_supabase

# ── Constants ─────────────────────────────────────────────────────────────────

ORG_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_OWNER_ORG = {
    "id": USER_ID,           # Pattern 61 — "id" not "user_id"
    "org_id": ORG_ID,
    "is_active": True,
    "roles": {
        "template": "owner",
        "permissions": {},
    },
}

_SALES_AGENT_ORG = {
    "id": USER_ID,
    "org_id": ORG_ID,
    "is_active": True,
    "roles": {
        "template": "sales_agent",
        "permissions": {},
    },
}

_EMPTY_SECTION_DATA = {
    "overview": {"total_revenue": 100000, "lead_count": 50, "close_rate_pct": 20, "cac": 500},
    "team_performance": {"teams": []},
    "funnel": {"stages": []},
    "sales_reps": {"reps": []},
    "channels": {"channels": []},
    "velocity": {"weeks": []},
    "pipeline_at_risk": {"total_at_risk": 3, "buckets": []},
    "win_loss": {"won": 10, "lost": 5, "win_rate_pct": 66.7, "top_loss_reasons": []},
}

_MOCK_INSIGHT = {"headline": "Strong week", "detail": "Revenue up.", "action": "Keep pushing."}


def _make_db():
    db = MagicMock()
    org_resp = MagicMock()
    org_resp.data = {"growth_insights": {}, "growth_anomaly_state": {}}
    db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = org_resp
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return db


@pytest.fixture
def client():
    return TestClient(app)


def _override_owner(db):
    app.dependency_overrides[get_current_org] = lambda: _OWNER_ORG
    app.dependency_overrides[get_supabase] = lambda: db


def _override_agent(db):
    app.dependency_overrides[get_current_org] = lambda: _SALES_AGENT_ORG
    app.dependency_overrides[get_supabase] = lambda: db


def _clear():
    app.dependency_overrides.clear()


# ── GET /insights/sections ────────────────────────────────────────────────────

@patch("app.routers.growth_insights._fetch_all_section_data", return_value=_EMPTY_SECTION_DATA)
@patch("app.routers.growth_insights.generate_section_insight", return_value=_MOCK_INSIGHT)
@patch("app.routers.growth_insights.get_cached_insights", return_value=None)
@patch("app.routers.growth_insights.save_cached_insights")
def test_get_sections_returns_8_sections(mock_save, mock_cache, mock_insight, mock_fetch, client):
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/sections?date_from=2026-04-01&date_to=2026-04-25")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "sections" in data
        assert len(data["sections"]) == 8
    finally:
        _clear()


@patch("app.routers.growth_insights.get_cached_insights")
def test_get_sections_cache_hit_returns_without_new_calls(mock_cache, client):
    cached_sections = {k: _MOCK_INSIGHT for k in [
        "overview", "team_performance", "funnel", "sales_reps",
        "channels", "velocity", "pipeline_at_risk", "win_loss"
    ]}
    mock_cache.return_value = cached_sections
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/sections?date_from=2026-04-01&date_to=2026-04-25")
        assert resp.status_code == 200
        assert resp.json()["data"]["from_cache"] is True
    finally:
        _clear()


@patch("app.routers.growth_insights._fetch_all_section_data", return_value=_EMPTY_SECTION_DATA)
@patch("app.routers.growth_insights.generate_section_insight")
@patch("app.routers.growth_insights.get_cached_insights", return_value=None)
@patch("app.routers.growth_insights.save_cached_insights")
def test_get_sections_partial_failure_returns_null_for_that_section(
    mock_save, mock_cache, mock_insight, mock_fetch, client
):
    # First call fails, rest succeed
    def _side(key, data):
        if key == "overview":
            raise RuntimeError("Haiku timeout")
        return _MOCK_INSIGHT

    mock_insight.side_effect = _side
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/sections")
        assert resp.status_code == 200
        sections = resp.json()["data"]["sections"]
        assert sections["overview"] is None
        assert sections["funnel"] == _MOCK_INSIGHT
    finally:
        _clear()


def test_get_sections_non_owner_gets_403(client):
    db = _make_db()
    _override_agent(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/sections")
        assert resp.status_code == 403
    finally:
        _clear()


# ── POST /insights/panel ──────────────────────────────────────────────────────

@patch("app.routers.growth_insights._fetch_all_section_data", return_value=_EMPTY_SECTION_DATA)
@patch("app.routers.growth_insights.generate_panel_narrative", return_value={
    "narrative": "Business performing well.",
    "top_priorities": ["Action 1", "Action 2", "Action 3"],
})
def test_post_panel_returns_narrative_and_priorities(mock_narrative, mock_fetch, client):
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.post("/api/v1/analytics/growth/insights/panel?date_from=2026-04-01&date_to=2026-04-25")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "narrative" in data
        assert len(data["top_priorities"]) == 3
    finally:
        _clear()


@patch("app.routers.growth_insights._fetch_all_section_data", return_value=_EMPTY_SECTION_DATA)
@patch("app.routers.growth_insights.generate_panel_narrative", return_value=None)
def test_post_panel_503_when_haiku_fails(mock_narrative, mock_fetch, client):
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.post("/api/v1/analytics/growth/insights/panel")
        assert resp.status_code == 503
    finally:
        _clear()


@patch("app.routers.growth_insights._fetch_all_section_data", return_value=_EMPTY_SECTION_DATA)
@patch("app.routers.growth_insights.generate_panel_narrative", return_value={
    "narrative": "ok", "top_priorities": []
})
def test_post_panel_rate_limit_enforced(mock_narrative, mock_fetch, client):
    db = _make_db()
    _override_owner(db)
    # Clear rate limit state for this org
    from app.routers.growth_insights import _panel_rate
    _panel_rate.pop(ORG_ID, None)
    try:
        for _ in range(10):
            resp = client.post("/api/v1/analytics/growth/insights/panel")
            assert resp.status_code == 200
        # 11th call should be rate limited
        resp = client.post("/api/v1/analytics/growth/insights/panel")
        assert resp.status_code == 429
    finally:
        _clear()
        _panel_rate.pop(ORG_ID, None)


def test_post_panel_non_owner_gets_403(client):
    db = _make_db()
    _override_agent(db)
    try:
        resp = client.post("/api/v1/analytics/growth/insights/panel")
        assert resp.status_code == 403
    finally:
        _clear()


# ── GET /insights/anomalies ───────────────────────────────────────────────────

@patch("app.routers.growth_insights.get_active_anomalies", return_value=[])
def test_get_anomalies_returns_empty_list_when_none(mock_anomalies, client):
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/anomalies")
        assert resp.status_code == 200
        assert resp.json()["data"]["alerts"] == []
    finally:
        _clear()


@patch("app.routers.growth_insights.get_active_anomalies", return_value=[
    {"type": "velocity_drop", "title": "Lead Drop", "detail": "Down 35%", "severity": "high", "fired_at": "2026-04-25T08:00:00+00:00"}
])
def test_get_anomalies_returns_active_alerts(mock_anomalies, client):
    db = _make_db()
    _override_owner(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/anomalies")
        assert resp.status_code == 200
        alerts = resp.json()["data"]["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["type"] == "velocity_drop"
    finally:
        _clear()


def test_get_anomalies_non_owner_gets_403(client):
    db = _make_db()
    _override_agent(db)
    try:
        resp = client.get("/api/v1/analytics/growth/insights/anomalies")
        assert resp.status_code == 403
    finally:
        _clear()
