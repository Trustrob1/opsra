"""
app/services/report_analytics_service.py
Management Reporting System — RPT-1A.

Computes all 12 report sections. Imports existing growth functions from
growth_analytics_service for sections that overlap with the Growth Dashboard.
Net-new computation added for sections 4, 7, 8, 9, 10, 11.

All functions:
  - Pattern 33: Python-side grouping/filtering — no ILIKE, no DB-side aggregation
  - Pattern 62: db passed in, never called directly
  - S14: individual section failures never crash the whole report
  - org_id always scoped — never cross-org leakage

Backwards-compatible with growth_analytics_service.py:
  - _as_list is NOT imported (does not exist in that module)
  - Imported functions accept Optional[date] objects; ISO strings are
    converted via _parse_date() before passing.

Column usage notes (confirmed against live schema):
  - whatsapp_messages: AI-sent = sent_by IS NULL on outbound rows
  - whatsapp_messages: window_open (boolean) used — no window_status column
  - organisations: SLA in sla_hot_hours / sla_warm_hours / sla_cold_hours
  - organisations: no logo_url — PDF uses Opsra wordmark fallback
  - tickets: urgency column used (no priority column)
  - customers: active = deleted_at IS NULL
  - customers: NPS via last_nps_score + last_nps_received_at
  - tasks: source_module used (no source column); AI task metrics skipped
  - direct_sales: no deleted_at column — all rows are live
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

from app.services.growth_analytics_service import (
    get_overview_metrics,
    get_team_performance,
    get_sales_rep_metrics,
    get_channel_metrics,
    get_win_loss_analysis,
    get_funnel_metrics,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(d: Optional[str]) -> Optional[date]:
    """Parse ISO date/datetime string to date object. Returns None on failure."""
    if not d:
        return None
    try:
        return date.fromisoformat(str(d)[:10])
    except (ValueError, TypeError):
        return None


def _safe_delta_pct(current: float, previous: float) -> Optional[float]:
    """
    Return percentage change from previous to current, rounded to 1dp.
    Returns None if previous is 0 to avoid misleading values.
    """
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _direction(current: float, previous: float, invert: bool = False) -> str:
    """
    Return "up", "down", or "flat" based on change direction.
    invert=True: lower is better (e.g. response time) — lower value = "up".
    """
    if current > previous:
        return "down" if invert else "up"
    if current < previous:
        return "up" if invert else "down"
    return "flat"


def _format_period_label(date_from: str, date_to: str) -> str:
    """
    Return a human-readable period label.
    Example: "1 May 2026 – 31 May 2026"
    S14: returns raw ISO strings on any parse failure.
    """
    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
        return f"{df.day} {df.strftime('%b %Y')} – {dt.day} {dt.strftime('%b %Y')}"
    except Exception:
        return f"{date_from} – {date_to}"


def _in_range(value: Optional[str], date_from: str, date_to: str) -> bool:
    """
    Return True if the ISO date/datetime string falls within
    [date_from, date_to] inclusive.
    """
    d = _parse_date(value)
    if d is None:
        return False
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df and d < df:
        return False
    if dt and d > dt:
        return False
    return True


def _metric_block(current, previous, invert: bool = False) -> dict:
    """
    Build a standard period-over-period metric comparison block.
    invert=True: lower is better (e.g. response time, avg close time).
    Preserves the original type of current/previous in the output.
    """
    curr_f = float(current)
    prev_f = float(previous)
    delta  = round(curr_f - prev_f, 2)
    return {
        "current":   current,
        "previous":  previous,
        "delta":     delta,
        "delta_pct": _safe_delta_pct(curr_f, prev_f),
        "direction": _direction(curr_f, prev_f, invert=invert),
    }


# ---------------------------------------------------------------------------
# Period computation helpers
# ---------------------------------------------------------------------------

def _compute_comparison_period(date_from: str, date_to: str) -> tuple[str, str]:
    """
    Given date_from and date_to (ISO date strings), return the equivalent
    prior period of the same length for period-over-period comparison.

    Example: date_from=2026-05-01, date_to=2026-05-31 (31 days)
             → returns ("2026-03-31", "2026-04-30")
    """
    df = date.fromisoformat(date_from)
    dt = date.fromisoformat(date_to)
    duration   = (dt - df).days + 1
    prior_to   = df - timedelta(days=1)
    prior_from = prior_to - timedelta(days=duration - 1)
    return prior_from.isoformat(), prior_to.isoformat()


def _compute_yoy_period(date_from: str, date_to: str) -> tuple[str, str]:
    """Return the same calendar period 365 days earlier (year-on-year)."""
    df = date.fromisoformat(date_from)
    dt = date.fromisoformat(date_to)
    return (df - timedelta(days=365)).isoformat(), (dt - timedelta(days=365)).isoformat()


def _resolve_period_preset(preset: str) -> tuple[str, str]:
    """
    Accepts a period_preset string and returns (date_from, date_to) as ISO
    date strings relative to today (UTC).

    Supported presets:
      today, yesterday, last_7d, last_30d, last_90d,
      this_month, last_month, this_quarter, this_year

    Raises ValueError for unknown preset string.
    "custom" is NOT valid here — callers pass date_from/date_to directly.
    """
    today = datetime.now(timezone.utc).date()

    if preset == "today":
        return today.isoformat(), today.isoformat()
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return y.isoformat(), y.isoformat()
    if preset == "last_7d":
        return (today - timedelta(days=7)).isoformat(), today.isoformat()
    if preset == "last_30d":
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    if preset == "last_90d":
        return (today - timedelta(days=90)).isoformat(), today.isoformat()
    if preset == "this_month":
        return today.replace(day=1).isoformat(), today.isoformat()
    if preset == "last_month":
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        return last_prev.replace(day=1).isoformat(), last_prev.isoformat()
    if preset == "this_quarter":
        qsm   = ((today.month - 1) // 3) * 3 + 1
        first = today.replace(month=qsm, day=1)
        return first.isoformat(), today.isoformat()
    if preset == "this_year":
        return today.replace(month=1, day=1).isoformat(), today.isoformat()

    raise ValueError(
        f"Unknown period preset: '{preset}'. "
        f"Valid presets: today, yesterday, last_7d, last_30d, last_90d, "
        f"this_month, last_month, this_quarter, this_year"
    )


# ---------------------------------------------------------------------------
# Internal fetch helpers
# ---------------------------------------------------------------------------

def _fetch_leads_in_period(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    team: Optional[str] = None,
) -> list[dict]:
    """
    Fetch non-deleted leads created (created_at) within the period.
    Pattern 33: Python-side date filtering.
    S14: returns [] on any DB failure.
    """
    try:
        result = (
            db.table("leads")
            .select(
                "id, stage, score, created_at, converted_at, lost_at, "
                "utm_source, entry_path, deal_value, first_touch_team, "
                "lost_reason, assigned_to, updated_at, "
                "attributed_to, attributed_to_secondary"
            )
            .eq("org_id", org_id)
            .is_("deleted_at", None)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in rows if _in_range(r.get("created_at"), date_from, date_to)]
        if team:
            rows = [r for r in rows if (r.get("first_touch_team") or "") == team]
        return rows
    except Exception as exc:
        logger.warning("_fetch_leads_in_period failed org=%s: %s", org_id, exc)
        return []


def _fetch_converted_leads_in_period(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    team: Optional[str] = None,
) -> list[dict]:
    """
    Fetch non-deleted leads where converted_at falls within the period.
    Revenue is recognised at closing date — not lead creation date.
    S14: returns [] on any DB failure.
    """
    try:
        result = (
            db.table("leads")
            .select(
                "id, stage, deal_value, converted_at, first_touch_team, assigned_to, "
                "attributed_to, attributed_to_secondary, attribution_split_pct"
            )
            .eq("org_id", org_id)
            .eq("stage", "converted")
            .is_("deleted_at", None)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in rows if _in_range(r.get("converted_at"), date_from, date_to)]
        if team:
            rows = [r for r in rows if (r.get("first_touch_team") or "") == team]
        return rows
    except Exception as exc:
        logger.warning("_fetch_converted_leads_in_period failed org=%s: %s", org_id, exc)
        return []


def _fetch_direct_sales_in_period(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """
    Fetch direct_sales rows where sale_date falls within the period.
    direct_sales has no deleted_at column — all rows are live.
    S14: returns [] on any DB failure.
    """
    try:
        result = (
            db.table("direct_sales")
            .select("id, amount, sale_date, utm_source, source_team")
            .eq("org_id", org_id)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]
        return [r for r in rows if _in_range(r.get("sale_date"), date_from, date_to)]
    except Exception as exc:
        logger.warning("_fetch_direct_sales_in_period failed org=%s: %s", org_id, exc)
        return []


def _get_lead_source(lead: dict) -> str:
    """
    Derive the acquisition channel for a lead.
    utm_source takes priority; falls back to entry_path mapping.
    Local equivalent of _get_lead_channel in growth_analytics_service —
    kept local to avoid importing a private function from that module.
    """
    utm = (lead.get("utm_source") or "").strip()
    if utm:
        return utm
    ep = (lead.get("entry_path") or "").strip().lower()
    mapping = {
        "whatsapp":     "WhatsApp",
        "web_form":     "Web Form",
        "meta_lead_ad": "Meta Lead Ad",
        "manual":       "Manual",
    }
    return mapping.get(ep, "Organic")


def _build_weekly_revenue_trend(
    closed_leads: list,
    direct_sales: list,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """
    Build weekly revenue buckets between date_from and date_to (inclusive).
    Leads bucketed by converted_at; direct_sales by sale_date.
    S14: returns [] on any failure.
    """
    try:
        df = _parse_date(date_from)
        dt = _parse_date(date_to)
        if not df or not dt:
            return []
        weeks: list = []
        cursor = df
        while cursor <= dt:
            week_end = min(cursor + timedelta(days=6), dt)
            weeks.append((cursor, week_end))
            cursor = week_end + timedelta(days=1)
        results = []
        for week_start, week_end in weeks:
            ws, we = week_start.isoformat(), week_end.isoformat()
            rev = 0.0
            for l in closed_leads:
                if _in_range(l.get("converted_at"), ws, we):
                    try:
                        rev += float(l.get("deal_value") or 0)
                    except (TypeError, ValueError):
                        pass
            for ds in direct_sales:
                if _in_range(ds.get("sale_date"), ws, we):
                    try:
                        rev += float(ds.get("amount") or 0)
                    except (TypeError, ValueError):
                        pass
            results.append({"week_start": ws, "week_end": we, "revenue": round(rev, 2)})
        return results
    except Exception as exc:
        logger.warning("_build_weekly_revenue_trend failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Section 1: Executive Summary
# ---------------------------------------------------------------------------

def get_executive_summary(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    team: Optional[str] = None,
) -> dict:
    """
    Top-level KPIs for the period and comparison period.

    Calls get_overview_metrics() for both periods.
    Note: get_overview_metrics is org-wide; team filter is not applied here
    (applied in team-specific sections).

    S14: returns error dict on any failure — never raises.
    """
    try:
        df  = _parse_date(date_from)
        dt  = _parse_date(date_to)
        cdf = _parse_date(compare_date_from)
        cdt = _parse_date(compare_date_to)

        curr = get_overview_metrics(db=db, org_id=org_id, date_from=df,  date_to=dt)
        prev = get_overview_metrics(db=db, org_id=org_id, date_from=cdf, date_to=cdt)

        def _f(key: str, src: dict) -> float:
            return float(src.get(key) or 0)

        # Revenue: use converted_at attribution (same as Revenue Summary section)
        # to avoid inflating figures with leads created but not yet closed in the period.
        # get_overview_metrics uses created_at which overstates revenue for short periods.
        def _revenue(date_f: str, date_t: str) -> float:
            leads  = _fetch_converted_leads_in_period(db, org_id, date_f, date_t)
            direct = _fetch_direct_sales_in_period(db, org_id, date_f, date_t)
            total  = 0.0
            for l in leads:
                try:
                    total += float(l.get("deal_value") or 0)
                except (TypeError, ValueError):
                    pass
            for ds in direct:
                try:
                    total += float(ds.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
            return round(total, 2)

        curr_revenue = _revenue(date_from, date_to)
        prev_revenue = _revenue(compare_date_from, compare_date_to)

        return {
            "period_label": _format_period_label(date_from, date_to),
            "comparison_period_label": _format_period_label(compare_date_from, compare_date_to),
            "metrics": {
                "total_revenue":      _metric_block(curr_revenue,                        prev_revenue),
                "total_leads":        _metric_block(_f("total_leads", curr),             _f("total_leads", prev)),
                "total_conversions":  _metric_block(_f("total_conversions", curr),       _f("total_conversions", prev)),
                "conversion_rate":    _metric_block(_f("overall_conversion_rate", curr), _f("overall_conversion_rate", prev)),
                "avg_close_time_days": _metric_block(_f("avg_close_time_days", curr),    _f("avg_close_time_days", prev), invert=True),
                "cac":                _metric_block(_f("cac", curr),                     _f("cac", prev),                invert=True),
            },
        }
    except Exception as exc:
        logger.warning("get_executive_summary failed org=%s: %s", org_id, exc)
        return {
            "error": "section unavailable",
            "period_label": _format_period_label(date_from, date_to),
        }


# ---------------------------------------------------------------------------
# Section 2: Lead & Pipeline Performance
# ---------------------------------------------------------------------------

def get_lead_pipeline_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    team: Optional[str] = None,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Leads received, by source, by score, funnel stage breakdown,
    leads lost with reasons, and pipeline value.

    Wraps get_funnel_metrics() and get_win_loss_analysis() for both periods.
    Adds lead_by_source and lead_by_score from direct lead queries.

    Pipeline value = sum of deal_value for leads in period not yet
    converted or lost.

    S14: returns error dict on any failure — never raises.
    """
    try:
        df  = _parse_date(date_from)
        dt  = _parse_date(date_to)
        cdf = _parse_date(compare_date_from)
        cdt = _parse_date(compare_date_to)

        curr_funnel = get_funnel_metrics(db=db, org_id=org_id, date_from=df,  date_to=dt,  team=team)
        prev_funnel = get_funnel_metrics(db=db, org_id=org_id, date_from=cdf, date_to=cdt, team=team)
        curr_wl     = get_win_loss_analysis(db=db, org_id=org_id, date_from=df,  date_to=dt)
        prev_wl     = get_win_loss_analysis(db=db, org_id=org_id, date_from=cdf, date_to=cdt)

        curr_leads = _fetch_leads_in_period(db, org_id, date_from, date_to, team=team)
        prev_leads = _fetch_leads_in_period(db, org_id, compare_date_from, compare_date_to, team=team)
        if rep_id:
            curr_leads = [l for l in curr_leads if l.get("assigned_to") == rep_id]
            prev_leads = [l for l in prev_leads if l.get("assigned_to") == rep_id]

        def _score_counts(leads: list) -> dict:
            counts: dict = {"hot": 0, "warm": 0, "cold": 0, "unscored": 0}
            for l in leads:
                s = (l.get("score") or "unscored").lower()
                counts[s] = counts.get(s, 0) + 1
            return counts

        def _pipeline_value(leads: list) -> float:
            closed_stages = {"converted", "lost", "not_ready"}
            total = 0.0
            for l in leads:
                if (l.get("stage") or "") in closed_stages:
                    continue
                try:
                    total += float(l.get("deal_value") or 0)
                except (TypeError, ValueError):
                    pass
            return round(total, 2)

        curr_scores = _score_counts(curr_leads)
        prev_scores = _score_counts(prev_leads)
        curr_total  = len(curr_leads)
        prev_total  = len(prev_leads)
        if rep_id:
            curr_lost = sum(1 for l in curr_leads if (l.get("stage") or "") == "lost")
            prev_lost = sum(1 for l in prev_leads if (l.get("stage") or "") == "lost")
        else:
            curr_lost = int(curr_wl.get("lost") or 0)
            prev_lost = int(prev_wl.get("lost") or 0)
        curr_pval   = _pipeline_value(curr_leads)
        prev_pval   = _pipeline_value(prev_leads)

        source_counts: dict = {}
        for lead in curr_leads:
            src = _get_lead_source(lead)
            source_counts[src] = source_counts.get(src, 0) + 1
        leads_by_source = [
            {"source": src, "count": cnt}
            for src, cnt in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "current": {
                "total_leads_received": curr_total,
                "hot_leads":     curr_scores.get("hot",  0),
                "warm_leads":    curr_scores.get("warm", 0),
                "cold_leads":    curr_scores.get("cold", 0),
                "total_lost":    curr_lost,
                "pipeline_value": curr_pval,
            },
            "previous": {
                "total_leads_received": prev_total,
                "hot_leads":     prev_scores.get("hot",  0),
                "warm_leads":    prev_scores.get("warm", 0),
                "cold_leads":    prev_scores.get("cold", 0),
                "total_lost":    prev_lost,
                "pipeline_value": prev_pval,
            },
            "deltas": {
                "total_leads_received": _metric_block(curr_total, prev_total),
                "hot_leads":   _metric_block(curr_scores.get("hot",  0), prev_scores.get("hot",  0)),
                "warm_leads":  _metric_block(curr_scores.get("warm", 0), prev_scores.get("warm", 0)),
                "cold_leads":  _metric_block(curr_scores.get("cold", 0), prev_scores.get("cold", 0)),
                "total_lost":  _metric_block(curr_lost, prev_lost, invert=True),
                "pipeline_value": _metric_block(curr_pval, prev_pval),
            },
            "funnel":           curr_funnel.get("stages",       []),
            "stage_labels":     curr_funnel.get("stage_labels", {}),
            "top_lost_reasons": (curr_wl.get("lost_reasons") or [])[:3],
            "leads_by_source":  leads_by_source,
        }
    except Exception as exc:
        logger.warning("get_lead_pipeline_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 3: Revenue Summary
# ---------------------------------------------------------------------------

def get_revenue_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    team: Optional[str] = None,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Revenue by source (pipeline deals and direct_sales), by team,
    weekly trend, average deal value, and total vs previous period.

    Revenue is recognised at converted_at (leads) or sale_date (direct_sales).
    Subscription renewals excluded — customers.renewed_at not in schema.

    S14: returns error dict on any failure — never raises.
    """
    try:
        def _rep_revenue_share(lead: dict, filter_rep_id: Optional[str]) -> float:
            """
            Return the portion of deal_value attributable to filter_rep_id.
            If no attribution data, full value goes to assigned_to (backwards compat).
            If no filter_rep_id, returns full deal_value (org-wide totals unchanged).
            """
            val = float(lead.get("deal_value") or 0)
            if not filter_rep_id:
                return val
            primary   = lead.get("attributed_to")
            secondary = lead.get("attributed_to_secondary")
            split_pct = lead.get("attribution_split_pct")
            # No attribution confirmed — fall back to assigned_to
            if not primary:
                return val if lead.get("assigned_to") == filter_rep_id else 0.0
            try:
                pct = int(split_pct) if split_pct is not None else 100
            except (TypeError, ValueError):
                pct = 100
            if filter_rep_id == primary:
                return round(val * pct / 100, 2)
            if secondary and filter_rep_id == secondary:
                return round(val * (100 - pct) / 100, 2)
            return 0.0

        def _compute(date_f: str, date_t: str) -> dict:
            leads  = _fetch_converted_leads_in_period(db, org_id, date_f, date_t, team=team)
            if rep_id:
                leads = [
                    l for l in leads
                    if l.get("attributed_to") == rep_id
                    or (not l.get("attributed_to") and l.get("assigned_to") == rep_id)
                    or l.get("attributed_to_secondary") == rep_id
                ]
            direct = _fetch_direct_sales_in_period(db, org_id, date_f, date_t)

            pipeline_rev = 0.0
            deal_values: list = []
            for l in leads:
                try:
                    val = _rep_revenue_share(l, rep_id) if rep_id else float(l.get("deal_value") or 0)
                    pipeline_rev += val
                    if val > 0:
                        deal_values.append(val)
                except (TypeError, ValueError):
                    pass

            direct_rev = 0.0
            for ds in direct:
                try:
                    direct_rev += float(ds.get("amount") or 0)
                except (TypeError, ValueError):
                    pass

            total_rev = round(pipeline_rev + direct_rev, 2)

            team_rev: dict = {}
            for l in leads:
                t = l.get("first_touch_team") or "Unattributed"
                try:
                    team_rev[t] = team_rev.get(t, 0.0) + float(l.get("deal_value") or 0)
                except (TypeError, ValueError):
                    pass
            for ds in direct:
                t = ds.get("source_team") or "Unattributed"
                try:
                    team_rev[t] = team_rev.get(t, 0.0) + float(ds.get("amount") or 0)
                except (TypeError, ValueError):
                    pass

            return {
                "total_revenue": total_rev,
                "by_source": {
                    "pipeline": round(pipeline_rev, 2),
                    "renewals": None,
                    "direct":   round(direct_rev, 2),
                },
                "by_team": [
                    {"team_name": t, "revenue": round(r, 2)}
                    for t, r in sorted(team_rev.items(), key=lambda x: x[1], reverse=True)
                ],
                "avg_deal_value": (
                    round(sum(deal_values) / len(deal_values), 2) if deal_values else 0.0
                ),
                "weekly_trend": _build_weekly_revenue_trend(leads, direct, date_f, date_t),
            }

        curr = _compute(date_from, date_to)
        prev = _compute(compare_date_from, compare_date_to)

        return {
            "current":   curr,
            "previous":  prev,
            "delta":     round(curr["total_revenue"] - prev["total_revenue"], 2),
            "delta_pct": _safe_delta_pct(curr["total_revenue"], prev["total_revenue"]),
            "direction": _direction(curr["total_revenue"], prev["total_revenue"]),
        }
    except Exception as exc:
        logger.warning("get_revenue_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 4: Response Time Analysis
# ---------------------------------------------------------------------------

def get_response_time_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Computes first-response time and average response time for the period.

    AI-sent messages are identified by sent_by IS NULL on outbound rows.
    Only human outbound replies (sent_by IS NOT NULL) are counted.

    First Response Time per thread:
      1. Find earliest inbound message in the thread within the period
      2. Find earliest human outbound message AFTER that inbound message
      3. first_response_mins = delta in minutes
      4. No human reply found → counted as no_response (excluded from avg)

    Average Response Time:
      For every inbound message in the period, find the next human outbound
      in the same thread. Average the deltas.

    SLA targets from organisations.sla_hot_hours (default 1h = 60 mins).

    direction for response time is INVERTED — lower time = improvement = "up".

    S14: returns empty structure with error flag on DB failure — never raises.
    """
    try:
        def _compute_rt(date_f: str, date_t: str) -> dict:
            # Fetch all messages for the org in the period
            try:
                msg_result = (
                    db.table("whatsapp_messages")
                    .select("id, lead_id, direction, sent_by, created_at")
                    .eq("org_id", org_id)
                    .execute()
                )
                all_msgs = msg_result.data or []
                if isinstance(all_msgs, dict):
                    all_msgs = [all_msgs]
            except Exception as exc:
                logger.warning("get_response_time_report: messages fetch failed: %s", exc)
                return {"error": "section unavailable"}

            # Filter to period — Pattern 33
            period_msgs = [
                m for m in all_msgs
                if _in_range(m.get("created_at"), date_f, date_t)
                and m.get("lead_id")
            ]

            if rep_id:
                # Scope to threads where this rep sent at least one message
                rep_lead_ids = {
                    m["lead_id"] for m in period_msgs
                    if m.get("direction") == "outbound" and m.get("sent_by") == rep_id
                }
                period_msgs = [m for m in period_msgs if m.get("lead_id") in rep_lead_ids]

            # Group all messages by lead_id (not just period messages — need
            # full thread context to find next outbound after an inbound)
            thread_map: dict = {}
            for m in all_msgs:
                lid = m.get("lead_id")
                if lid:
                    thread_map.setdefault(lid, []).append(m)
            # Sort each thread by created_at
            for lid in thread_map:
                thread_map[lid].sort(key=lambda x: x.get("created_at") or "")

            # Unique lead_ids that had an inbound message in the period
            inbound_period = [
                m for m in period_msgs if m.get("direction") == "inbound"
            ]
            period_lead_ids = {m["lead_id"] for m in inbound_period}

            first_response_mins_list: list = []
            no_response_threads = 0
            all_response_mins: list = []
            per_rep: dict = {}   # rep_id → list of response mins

            def _to_dt(ts: str) -> Optional[datetime]:
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    return None

            for lead_id in period_lead_ids:
                thread = thread_map.get(lead_id, [])
                inbound_in_period = [
                    m for m in thread
                    if m.get("direction") == "inbound"
                    and _in_range(m.get("created_at"), date_f, date_t)
                ]
                if not inbound_in_period:
                    continue

                # First response time — earliest inbound → earliest human outbound after it
                first_inbound = inbound_in_period[0]
                first_in_ts   = _to_dt(first_inbound.get("created_at") or "")

                first_human_out = None
                for m in thread:
                    if (
                        m.get("direction") == "outbound"
                        and m.get("sent_by") is not None  # human-sent
                        and _to_dt(m.get("created_at") or "") is not None
                        and first_in_ts is not None
                        and _to_dt(m.get("created_at")) > first_in_ts
                    ):
                        first_human_out = m
                        break

                if first_human_out and first_in_ts:
                    out_ts = _to_dt(first_human_out["created_at"])
                    if out_ts:
                        mins = (out_ts - first_in_ts).total_seconds() / 60
                        first_response_mins_list.append(mins)
                        rep = first_human_out.get("sent_by")
                        if rep:
                            per_rep.setdefault(rep, []).append(mins)
                else:
                    no_response_threads += 1

                # Average response time — every inbound → next human outbound
                for inb in inbound_in_period:
                    inb_ts = _to_dt(inb.get("created_at") or "")
                    if not inb_ts:
                        continue
                    for m in thread:
                        if (
                            m.get("direction") == "outbound"
                            and m.get("sent_by") is not None
                            and _to_dt(m.get("created_at") or "") is not None
                            and _to_dt(m.get("created_at")) > inb_ts
                        ):
                            resp_ts = _to_dt(m["created_at"])
                            if resp_ts:
                                all_response_mins.append(
                                    (resp_ts - inb_ts).total_seconds() / 60
                                )
                            break

            def _avg(lst: list) -> float:
                return round(sum(lst) / len(lst), 1) if lst else 0.0

            def _median(lst: list) -> float:
                if not lst:
                    return 0.0
                s = sorted(lst)
                n = len(s)
                mid = n // 2
                return round((s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2), 1)

            # SLA compliance — fetch org SLA target
            sla_mins = 60  # default: 60 minutes
            try:
                org_r = (
                    db.table("organisations")
                    .select("sla_hot_hours")
                    .eq("id", org_id)
                    .maybe_single()
                    .execute()
                )
                org_d = org_r.data
                if isinstance(org_d, list):
                    org_d = org_d[0] if org_d else None
                sla_hot_h = (org_d or {}).get("sla_hot_hours")
                if sla_hot_h:
                    sla_mins = int(sla_hot_h) * 60
            except Exception:
                pass

            sla_breaches = sum(1 for m in first_response_mins_list if m > sla_mins)
            sla_total    = len(first_response_mins_list) + no_response_threads
            sla_pct      = round(
                ((sla_total - sla_breaches) / sla_total * 100), 1
            ) if sla_total else 0.0

            # Daily trend — avg first response time per day
            daily: dict = {}
            for lead_id in period_lead_ids:
                thread = thread_map.get(lead_id, [])
                inbs = [
                    m for m in thread
                    if m.get("direction") == "inbound"
                    and _in_range(m.get("created_at"), date_f, date_t)
                ]
                if not inbs:
                    continue
                first_inb = inbs[0]
                first_in_ts = _to_dt(first_inb.get("created_at") or "")
                for m in thread:
                    if (
                        m.get("direction") == "outbound"
                        and m.get("sent_by") is not None
                        and first_in_ts
                        and _to_dt(m.get("created_at") or "") is not None
                        and _to_dt(m.get("created_at")) > first_in_ts
                    ):
                        out_ts = _to_dt(m["created_at"])
                        if out_ts:
                            day_key = out_ts.date().isoformat()
                            daily.setdefault(day_key, []).append(
                                (out_ts - first_in_ts).total_seconds() / 60
                            )
                        break

            daily_trend = [
                {"date": d, "avg_first_response_mins": _avg(mins)}
                for d, mins in sorted(daily.items())
            ]

            # Per-rep breakdown
            # Fetch user names
            rep_names: dict = {}
            try:
                users_r = (
                    db.table("users")
                    .select("id, full_name")
                    .eq("org_id", org_id)
                    .execute()
                )
                for u in (users_r.data or []):
                    rep_names[u["id"]] = u.get("full_name") or u["id"]
            except Exception:
                pass

            per_rep_list = []
            for rid, mins_list in per_rep.items():
                if rep_id and rid != rep_id:
                    continue
                rep_inbound_threads = sum(
                    1 for lid in period_lead_ids
                    if any(
                        m.get("sent_by") == rid and m.get("direction") == "outbound"
                        for m in thread_map.get(lid, [])
                    )
                )
                rep_breaches = sum(1 for m in mins_list if m > sla_mins)
                rep_sla_pct  = round(
                    ((len(mins_list) - rep_breaches) / len(mins_list) * 100), 1
                ) if mins_list else 0.0
                per_rep_list.append({
                    "rep_id":                  rid,
                    "rep_name":                rep_names.get(rid, rid),
                    "threads_handled":         rep_inbound_threads,
                    "avg_first_response_mins": _avg(mins_list),
                    "median_first_response_mins": _median(mins_list),
                    "sla_breaches":            rep_breaches,
                    "sla_compliance_pct":      rep_sla_pct,
                    "no_response_threads":     0,
                })

            return {
                "org_avg_first_response_mins":    _avg(first_response_mins_list),
                "org_median_first_response_mins": _median(first_response_mins_list),
                "org_avg_response_mins":          _avg(all_response_mins),
                "no_response_threads":            no_response_threads,
                "sla_compliance_pct":             sla_pct,
                "sla_breaches":                   sla_breaches,
                "daily_trend":                    daily_trend,
                "per_rep":                        per_rep_list,
            }

        curr = _compute_rt(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_rt(compare_date_from, compare_date_to)

        curr_avg = curr.get("org_avg_first_response_mins", 0.0)
        prev_avg = prev.get("org_avg_first_response_mins", 0.0) if not prev.get("error") else 0.0

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "delta_first_response_mins": round(curr_avg - prev_avg, 1),
            "delta_first_response_pct":  _safe_delta_pct(curr_avg, prev_avg),
            "direction": _direction(curr_avg, prev_avg, invert=True),
        }
    except Exception as exc:
        logger.warning("get_response_time_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 5: Sales Rep Performance
# ---------------------------------------------------------------------------

def get_rep_performance_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Per-rep breakdown. Calls get_sales_rep_metrics() for both periods.
    Merges with response time data from get_response_time_report().
    Adds tasks_completed, tasks_overdue, ai_mode_pct, human_mode_pct.

    ai_mode_pct: ratio of outbound messages where sent_by IS NULL
    (AI-sent) to total outbound for that rep's threads.

    tasks_completed: tasks.completed_at in period AND assigned_to = rep.
    tasks_overdue:   tasks.due_at < date_to AND status != 'completed'.

    Note: tasks.source_module is NOT used for AI task filtering —
    that metric is excluded from this build (not material per product owner).

    S14: returns error dict on any failure — never raises.
    """
    try:
        df  = _parse_date(date_from)
        dt  = _parse_date(date_to)
        cdf = _parse_date(compare_date_from)
        cdt = _parse_date(compare_date_to)

        curr_reps = get_sales_rep_metrics(
            db=db, org_id=org_id, date_from=df, date_to=dt,
            requesting_user_id=None, requesting_user_role="owner",
        )
        prev_reps = get_sales_rep_metrics(
            db=db, org_id=org_id, date_from=cdf, date_to=cdt,
            requesting_user_id=None, requesting_user_role="owner",
        )
        if rep_id:
            curr_reps = [r for r in curr_reps if r.get("rep_id") == rep_id]
            prev_reps = [r for r in prev_reps if r.get("rep_id") == rep_id]

        # Stage breakdown per rep — leads assigned in period grouped by outcome
        def _stage_breakdown_by_rep(date_f: str, date_t: str) -> dict:
            """
            Returns dict of rep_id → stage counts for leads assigned in period.
            Counts: leads_converted, leads_lost, leads_not_ready, leads_in_progress.
            leads_in_progress = assigned - converted - lost - not_ready.

            For converted leads: credit goes to attributed_to (primary) if confirmed,
            with a secondary credit also recorded for attributed_to_secondary.
            Falls back to assigned_to for un-attributed conversions.
            For lost/not_ready: still uses assigned_to (attribution is conversion-only).
            """
            all_leads = _fetch_leads_in_period(db, org_id, date_f, date_t)
            breakdown: dict = {}

            def _ensure(rep: str) -> None:
                if rep not in breakdown:
                    breakdown[rep] = {
                        "leads_converted":  0,
                        "leads_lost":       0,
                        "leads_not_ready":  0,
                    }

            for l in all_leads:
                aid   = l.get("assigned_to")
                stage = (l.get("stage") or "").lower()

                if stage == "converted":
                    primary   = l.get("attributed_to")
                    secondary = l.get("attributed_to_secondary")
                    if primary:
                        _ensure(primary)
                        breakdown[primary]["leads_converted"] += 1
                        if secondary:
                            _ensure(secondary)
                            breakdown[secondary]["leads_converted"] += 1
                    elif aid:
                        _ensure(aid)
                        breakdown[aid]["leads_converted"] += 1
                elif aid:
                    _ensure(aid)
                    if stage == "lost":
                        breakdown[aid]["leads_lost"] += 1
                    elif stage == "not_ready":
                        breakdown[aid]["leads_not_ready"] += 1

            return breakdown

        curr_stage_breakdown = _stage_breakdown_by_rep(date_from, date_to)
        prev_stage_breakdown = _stage_breakdown_by_rep(compare_date_from, compare_date_to)

        # Response time per rep for current period
        rt_report = get_response_time_report(
            db=db, org_id=org_id,
            date_from=date_from, date_to=date_to,
            compare_date_from=compare_date_from, compare_date_to=compare_date_to,
        )
        rt_by_rep: dict = {}
        for r in (rt_report.get("current") or {}).get("per_rep", []):
            rt_by_rep[r["rep_id"]] = r

        # Fetch tasks for the period — Pattern 33
        tasks_by_rep_completed: dict = {}
        tasks_by_rep_overdue: dict   = {}
        try:
            tasks_r = (
                db.table("tasks")
                .select("assigned_to, status, completed_at, due_at")
                .eq("org_id", org_id)
                .is_("deleted_at", None)
                .execute()
            )
            for t in (tasks_r.data or []):
                aid = t.get("assigned_to")
                if not aid:
                    continue
                if (
                    t.get("status") == "completed"
                    and _in_range(t.get("completed_at"), date_from, date_to)
                ):
                    tasks_by_rep_completed[aid] = tasks_by_rep_completed.get(aid, 0) + 1
                due = _parse_date(t.get("due_at"))
                dt_date = _parse_date(date_to)
                if (
                    t.get("status") != "completed"
                    and due and dt_date and due < dt_date
                ):
                    tasks_by_rep_overdue[aid] = tasks_by_rep_overdue.get(aid, 0) + 1
        except Exception as exc:
            logger.warning("get_rep_performance_report: tasks fetch failed: %s", exc)

        # Fetch outbound messages for ai_mode_pct computation — Pattern 33
        # ai_mode_pct per rep = AI outbound in rep's threads /
        #                       total outbound in rep's threads * 100
        lead_msg_counts: dict = {}   # lead_id → {"total": N, "ai": N}
        rep_lead_ids: dict    = {}   # rep_id  → set of lead_ids they've messaged
        try:
            msg_r = (
                db.table("whatsapp_messages")
                .select("sent_by, created_at, lead_id")
                .eq("org_id", org_id)
                .eq("direction", "outbound")
                .execute()
            )
            for m in (msg_r.data or []):
                if not _in_range(m.get("created_at"), date_from, date_to):
                    continue
                sb  = m.get("sent_by")
                lid = m.get("lead_id")
                if lid:
                    if lid not in lead_msg_counts:
                        lead_msg_counts[lid] = {"total": 0, "ai": 0}
                    lead_msg_counts[lid]["total"] += 1
                    if sb is None:
                        lead_msg_counts[lid]["ai"] += 1
                if sb and lid:
                    rep_lead_ids.setdefault(sb, set()).add(lid)
        except Exception as exc:
            logger.warning("get_rep_performance_report: messages fetch failed: %s", exc)

        def _enrich(reps: list, is_current: bool) -> list:
            stage_breakdown = curr_stage_breakdown if is_current else prev_stage_breakdown
            enriched = []
            for rep in reps:
                rid = rep.get("rep_id")
                rt  = rt_by_rep.get(rid, {}) if is_current else {}
                sb  = stage_breakdown.get(rid, {})
                leads_assigned   = int(rep.get("leads_assigned") or 0)
                leads_converted  = sb.get("leads_converted",  0)
                leads_lost       = sb.get("leads_lost",       0)
                leads_not_ready  = sb.get("leads_not_ready",  0)
                leads_in_progress = max(
                    leads_assigned - leads_converted - leads_lost - leads_not_ready, 0
                )
                if is_current:
                    rep_leads        = rep_lead_ids.get(rid, set())
                    total_in_threads = sum(lead_msg_counts.get(l, {}).get("total", 0) for l in rep_leads)
                    ai_in_threads    = sum(lead_msg_counts.get(l, {}).get("ai",    0) for l in rep_leads)
                    if total_in_threads > 0:
                        ai_mode_pct    = round(ai_in_threads / total_in_threads * 100, 1)
                        human_mode_pct = round(100 - ai_mode_pct, 1)
                    else:
                        ai_mode_pct    = 0.0
                        human_mode_pct = 100.0
                else:
                    ai_mode_pct    = 0.0
                    human_mode_pct = 100.0
                enriched.append({
                    **rep,
                    "leads_converted":    leads_converted,
                    "leads_lost":         leads_lost,
                    "leads_not_ready":    leads_not_ready,
                    "leads_in_progress":  leads_in_progress,
                    "avg_first_response_mins": rt.get("avg_first_response_mins"),
                    "sla_compliance_pct":      rt.get("sla_compliance_pct"),
                    "tasks_completed":  tasks_by_rep_completed.get(rid, 0) if is_current else None,
                    "tasks_overdue":    tasks_by_rep_overdue.get(rid,   0) if is_current else None,
                    "ai_mode_pct":      ai_mode_pct,
                    "human_mode_pct":   human_mode_pct,
                })
            return enriched

        curr_enriched = _enrich(curr_reps, is_current=True)
        prev_enriched = _enrich(prev_reps, is_current=False)

        # Build per-rep deltas
        prev_map = {r["rep_id"]: r for r in prev_enriched}
        per_rep_deltas = []
        for rep in curr_enriched:
            rid  = rep["rep_id"]
            prev = prev_map.get(rid, {})
            per_rep_deltas.append({
                "rep_id":   rid,
                "rep_name": rep.get("rep_name"),
                "leads_delta_pct": _safe_delta_pct(
                    float(rep.get("leads_assigned") or 0),
                    float(prev.get("leads_assigned") or 0),
                ),
                "conversion_rate_delta_pts": round(
                    float(rep.get("close_rate") or 0) - float(prev.get("close_rate") or 0), 1
                ),
                "revenue_delta_pct": _safe_delta_pct(
                    float(rep.get("revenue_closed") or 0),
                    float(prev.get("revenue_closed") or 0),
                ),
                "direction_leads":      _direction(
                    float(rep.get("leads_assigned") or 0),
                    float(prev.get("leads_assigned") or 0),
                ),
                "direction_conversion": _direction(
                    float(rep.get("close_rate") or 0),
                    float(prev.get("close_rate") or 0),
                ),
            })

        return {
            "current":       curr_enriched,
            "previous":      prev_enriched,
            "per_rep_deltas": per_rep_deltas,
        }
    except Exception as exc:
        logger.warning("get_rep_performance_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 6: Team Performance
# ---------------------------------------------------------------------------

def get_team_performance_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    team: Optional[str] = None,
) -> dict:
    """
    Team breakdown. Calls get_team_performance() for both periods.
    Adds deltas and marks best-performing team in current period.
    S14: returns error dict on any failure — never raises.
    """
    try:
        df  = _parse_date(date_from)
        dt  = _parse_date(date_to)
        cdf = _parse_date(compare_date_from)
        cdt = _parse_date(compare_date_to)

        curr_teams = get_team_performance(db=db, org_id=org_id, date_from=df, date_to=dt)
        prev_teams = get_team_performance(db=db, org_id=org_id, date_from=cdf, date_to=cdt)
        if team:
            curr_teams = [t for t in curr_teams if t.get("team_name") == team]
            prev_teams = [t for t in prev_teams if t.get("team_name") == team]

        # Mark best performer by revenue in current period
        max_rev = max(
            (float(t.get("revenue_generated") or 0) for t in curr_teams),
            default=0.0,
        )
        curr_enriched = [
            {
                **t,
                "is_best_performer": (
                    float(t.get("revenue_generated") or 0) == max_rev and max_rev > 0
                ),
            }
            for t in curr_teams
        ]

        prev_map = {t["team_name"]: t for t in prev_teams}
        team_deltas = []
        for team in curr_enriched:
            tn   = team["team_name"]
            prev = prev_map.get(tn, {})
            team_deltas.append({
                "team_name": tn,
                "leads_delta_pct": _safe_delta_pct(
                    float(team.get("leads_generated") or 0),
                    float(prev.get("leads_generated") or 0),
                ),
                "conversion_rate_delta_pts": round(
                    float(team.get("conversion_rate") or 0) -
                    float(prev.get("conversion_rate") or 0), 1
                ),
                "revenue_delta_pct": _safe_delta_pct(
                    float(team.get("revenue_generated") or 0),
                    float(prev.get("revenue_generated") or 0),
                ),
                "direction_leads":   _direction(
                    float(team.get("leads_generated") or 0),
                    float(prev.get("leads_generated") or 0),
                ),
                "direction_revenue": _direction(
                    float(team.get("revenue_generated") or 0),
                    float(prev.get("revenue_generated") or 0),
                ),
            })

        return {
            "current":     curr_enriched,
            "previous":    prev_teams,
            "team_deltas": team_deltas,
        }
    except Exception as exc:
        logger.warning("get_team_performance_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 7: WhatsApp Communication Intelligence
# ---------------------------------------------------------------------------

def get_whatsapp_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
) -> dict:
    """
    WhatsApp activity metrics for the period.

    AI-sent messages identified by: direction='outbound' AND sent_by IS NULL.
    Human-sent: direction='outbound' AND sent_by IS NOT NULL.
    window_breaches: uses window_open column (boolean) — no window_status column.

    S14: returns error dict on any failure — never raises.
    """
    try:
        def _compute_wa(date_f: str, date_t: str) -> dict:
            try:
                result = (
                    db.table("whatsapp_messages")
                    .select(
                        "id, direction, sent_by, created_at, lead_id, "
                        "status, window_open"
                    )
                    .eq("org_id", org_id)
                    .execute()
                )
                all_msgs = result.data or []
                if isinstance(all_msgs, dict):
                    all_msgs = [all_msgs]
            except Exception as exc:
                logger.warning("get_whatsapp_report: fetch failed: %s", exc)
                return {"error": "section unavailable"}

            msgs = [
                m for m in all_msgs
                if _in_range(m.get("created_at"), date_f, date_t)
            ]

            if rep_id:
                rep_lead_ids = {
                    m["lead_id"] for m in msgs
                    if m.get("sent_by") == rep_id and m.get("lead_id")
                }
                msgs = [m for m in msgs if m.get("lead_id") in rep_lead_ids]

            outbound = [m for m in msgs if m.get("direction") == "outbound"]
            inbound  = [m for m in msgs if m.get("direction") == "inbound"]

            ai_sent    = [m for m in outbound if m.get("sent_by") is None]
            human_sent = [m for m in outbound if m.get("sent_by") is not None]
            total_sent = len(outbound)

            ai_pct = round(len(ai_sent) / total_sent * 100, 1) if total_sent else 0.0

            # Reply rate: distinct leads who sent at least one inbound,
            # out of distinct leads who received at least one outbound
            leads_messaged   = {m["lead_id"] for m in outbound if m.get("lead_id")}
            leads_replied    = {m["lead_id"] for m in inbound  if m.get("lead_id")}
            reply_rate = round(
                len(leads_replied & leads_messaged) / len(leads_messaged) * 100, 1
            ) if leads_messaged else 0.0

            conversations_opened = len({m["lead_id"] for m in inbound if m.get("lead_id")})

            # Avg messages per conversation
            all_lead_ids = {m["lead_id"] for m in msgs if m.get("lead_id")}
            avg_msgs = round(len(msgs) / len(all_lead_ids), 1) if all_lead_ids else 0.0

            failed = sum(1 for m in outbound if m.get("status") == "failed")

            # window_breaches: outbound sent when window_open = False
            window_breaches = sum(
                1 for m in outbound
                if m.get("window_open") is False
            )

            return {
                "total_messages_sent":      total_sent,
                "ai_sent":                  len(ai_sent),
                "human_sent":               len(human_sent),
                "ai_pct":                   ai_pct,
                "total_inbound":            len(inbound),
                "reply_rate":               reply_rate,
                "conversations_opened":     conversations_opened,
                "avg_messages_per_conversation": avg_msgs,
                "failed_messages":          failed,
                "window_breaches":          window_breaches,
            }

        curr = _compute_wa(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_wa(compare_date_from, compare_date_to)

        def _d(key: str) -> dict:
            invert = key in ("failed_messages", "window_breaches")
            return _metric_block(
                float(curr.get(key) or 0),
                float(prev.get(key) or 0) if not prev.get("error") else 0.0,
                invert=invert,
            )

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "deltas": {
                "total_messages_sent":  _d("total_messages_sent"),
                "ai_pct":               _d("ai_pct"),
                "reply_rate":           _d("reply_rate"),
                "conversations_opened": _d("conversations_opened"),
            },
        }
    except Exception as exc:
        logger.warning("get_whatsapp_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 8: Support & Ticket Intelligence
# ---------------------------------------------------------------------------

def get_support_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Ticket metrics for the period.

    Uses urgency column (not priority — priority does not exist in schema).
    tickets_escalated = COUNT where urgency IN ('high', 'critical').
    reopened_tickets set to null — reopened_count column does not exist.

    S14: returns error dict on any failure — never raises.
    """
    try:
        def _compute_tickets(date_f: str, date_t: str) -> dict:
            try:
                result = (
                    db.table("tickets")
                    .select(
                        "id, status, urgency, created_at, resolved_at, "
                        "assigned_to, category, title"
                    )
                    .eq("org_id", org_id)
                    .is_("deleted_at", None)
                    .execute()
                )
                all_tickets = result.data or []
                if isinstance(all_tickets, dict):
                    all_tickets = [all_tickets]
            except Exception as exc:
                logger.warning("get_support_report: fetch failed: %s", exc)
                return {"error": "section unavailable"}

            opened   = [t for t in all_tickets if _in_range(t.get("created_at"), date_f, date_t)]
            resolved = [
                t for t in all_tickets
                if t.get("status") == "resolved"
                and _in_range(t.get("resolved_at"), date_f, date_t)
            ]

            if rep_id:
                opened   = [t for t in opened   if t.get("assigned_to") == rep_id]
                resolved = [t for t in resolved if t.get("assigned_to") == rep_id]

            escalated = [
                t for t in opened
                if (t.get("urgency") or "").lower() in ("high", "critical")
            ]

            resolution_rate = round(
                len(resolved) / len(opened) * 100, 1
            ) if opened else 0.0

            res_times = []
            for t in resolved:
                created  = _parse_date(t.get("created_at"))
                resolved_at = _parse_date(t.get("resolved_at"))
                if created and resolved_at and resolved_at >= created:
                    hours = (resolved_at - created).days * 24
                    res_times.append(float(hours))
            avg_res_hours = round(sum(res_times) / len(res_times), 1) if res_times else 0.0

            # Top 3 issue categories — Python-side grouping
            cat_counts: dict = {}
            for t in opened:
                cat = t.get("category") or "Uncategorised"
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            top_categories = [
                {"category": cat, "count": cnt}
                for cat, cnt in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            ]

            # Per-agent breakdown
            agent_map: dict = {}
            for t in opened:
                aid = t.get("assigned_to")
                if aid:
                    agent_map.setdefault(aid, {"tickets_handled": 0, "resolved": 0, "res_times": []})
                    agent_map[aid]["tickets_handled"] += 1
            for t in resolved:
                aid = t.get("assigned_to")
                if aid and aid in agent_map:
                    agent_map[aid]["resolved"] += 1
                    cr = _parse_date(t.get("created_at"))
                    ra = _parse_date(t.get("resolved_at"))
                    if cr and ra and ra >= cr:
                        agent_map[aid]["res_times"].append(float((ra - cr).days * 24))

            # Fetch agent names
            agent_names: dict = {}
            try:
                u_r = db.table("users").select("id, full_name").eq("org_id", org_id).execute()
                for u in (u_r.data or []):
                    agent_names[u["id"]] = u.get("full_name") or u["id"]
            except Exception:
                pass

            per_agent = [
                {
                    "agent_name": agent_names.get(aid, aid),
                    "tickets_handled": d["tickets_handled"],
                    "resolved": d["resolved"],
                    "avg_resolution_hours": round(
                        sum(d["res_times"]) / len(d["res_times"]), 1
                    ) if d["res_times"] else 0.0,
                }
                for aid, d in agent_map.items()
            ]

            return {
                "tickets_opened":          len(opened),
                "tickets_resolved":        len(resolved),
                "tickets_escalated":       len(escalated),
                "resolution_rate":         resolution_rate,
                "avg_resolution_time_hours": avg_res_hours,
                "reopened_tickets":        None,   # reopened_count column not in schema
                "top_issue_categories":    top_categories,
                "per_agent":               per_agent,
            }

        curr = _compute_tickets(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_tickets(compare_date_from, compare_date_to)

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "deltas": {
                "tickets_opened": _metric_block(
                    float(curr.get("tickets_opened") or 0),
                    float(prev.get("tickets_opened") or 0) if not prev.get("error") else 0.0,
                ),
                "resolution_rate": _metric_block(
                    float(curr.get("resolution_rate") or 0),
                    float(prev.get("resolution_rate") or 0) if not prev.get("error") else 0.0,
                ),
                "avg_resolution_time_hours": _metric_block(
                    float(curr.get("avg_resolution_time_hours") or 0),
                    float(prev.get("avg_resolution_time_hours") or 0) if not prev.get("error") else 0.0,
                    invert=True,
                ),
            },
        }
    except Exception as exc:
        logger.warning("get_support_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 9: Customer Health Snapshot
# ---------------------------------------------------------------------------

def get_customer_health_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
) -> dict:
    """
    Customer health metrics.

    Active customers = deleted_at IS NULL (no is_active column in schema).
    NPS via last_nps_score + last_nps_received_at.
    Renewals skipped — customers.renewed_at not in schema.
    last_active skipped — no equivalent column in schema.

    S14: returns error dict on any failure — never raises.
    """
    try:
        def _compute_health(date_f: str, date_t: str) -> dict:
            try:
                result = (
                    db.table("customers")
                    .select(
                        "id, created_at, churn_risk, deleted_at, "
                        "last_nps_score, last_nps_received_at, status"
                    )
                    .eq("org_id", org_id)
                    .execute()
                )
                all_customers = result.data or []
                if isinstance(all_customers, dict):
                    all_customers = [all_customers]
            except Exception as exc:
                logger.warning("get_customer_health_report: fetch failed: %s", exc)
                return {"error": "section unavailable"}

            # Active = not soft-deleted
            active = [c for c in all_customers if not c.get("deleted_at")]
            new    = [c for c in active if _in_range(c.get("created_at"), date_f, date_t)]

            # Churn risk distribution
            risk_dist: dict = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for c in active:
                risk = (c.get("churn_risk") or "low").lower()
                risk_dist[risk] = risk_dist.get(risk, 0) + 1

            churned_critical = risk_dist.get("critical", 0)

            # NPS for customers who received NPS in the period
            nps_scores = [
                int(c.get("last_nps_score") or 0)
                for c in active
                if _in_range(c.get("last_nps_received_at"), date_f, date_t)
                and c.get("last_nps_score") is not None
            ]
            nps_avg      = round(sum(nps_scores) / len(nps_scores), 1) if nps_scores else None
            nps_responses = len(nps_scores)

            return {
                "total_active_customers": len(active),
                "new_customers":          len(new),
                "churned_customers":      churned_critical,
                "churn_risk_distribution": risk_dist,
                "nps_avg":                nps_avg,
                "nps_responses":          nps_responses,
                "renewals_completed":     None,   # customers.renewed_at not in schema
            }

        curr = _compute_health(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_health(compare_date_from, compare_date_to)

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "deltas": {
                "new_customers": _metric_block(
                    float(curr.get("new_customers") or 0),
                    float(prev.get("new_customers") or 0) if not prev.get("error") else 0.0,
                ),
                "nps_avg": _metric_block(
                    float(curr.get("nps_avg") or 0),
                    float(prev.get("nps_avg") or 0) if not prev.get("error") else 0.0,
                ),
                "churned_critical": _metric_block(
                    float(curr.get("churned_customers") or 0),
                    float(prev.get("churned_customers") or 0) if not prev.get("error") else 0.0,
                    invert=True,
                ),
            },
        }
    except Exception as exc:
        logger.warning("get_customer_health_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 10: Task & Activity Analytics
# ---------------------------------------------------------------------------

def get_task_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
) -> dict:
    """
    Task metrics for the period.

    Uses tasks.completed_at, tasks.due_at, tasks.status, tasks.assigned_to.
    AI task metrics (source_module = 'ai_recommendation') excluded —
    not material per product owner.

    S14: returns error dict on any failure — never raises.
    """
    try:
        def _compute_tasks(date_f: str, date_t: str) -> dict:
            try:
                result = (
                    db.table("tasks")
                    .select("id, status, completed_at, due_at, created_at, assigned_to")
                    .eq("org_id", org_id)
                    .is_("deleted_at", None)
                    .execute()
                )
                all_tasks = result.data or []
                if isinstance(all_tasks, dict):
                    all_tasks = [all_tasks]
            except Exception as exc:
                logger.warning("get_task_report: fetch failed: %s", exc)
                return {"error": "section unavailable"}

            created   = [t for t in all_tasks if _in_range(t.get("created_at"),  date_f, date_t)]
            completed = [t for t in all_tasks if _in_range(t.get("completed_at"), date_f, date_t)
                         and t.get("status") == "completed"]

            dt_date = _parse_date(date_t)
            overdue = [
                t for t in all_tasks
                if t.get("status") != "completed"
                and _parse_date(t.get("due_at")) is not None
                and dt_date is not None
                and _parse_date(t.get("due_at")) < dt_date
            ]

            if rep_id:
                created   = [t for t in created   if t.get("assigned_to") == rep_id]
                completed = [t for t in completed if t.get("assigned_to") == rep_id]
                overdue   = [t for t in overdue   if t.get("assigned_to") == rep_id]

            completion_rate = round(
                len(completed) / len(created) * 100, 1
            ) if created else 0.0

            comp_times = []
            for t in completed:
                cr = _parse_date(t.get("created_at"))
                ca = _parse_date(t.get("completed_at"))
                if cr and ca and ca >= cr:
                    comp_times.append(float((ca - cr).days * 24))
            avg_completion_hours = (
                round(sum(comp_times) / len(comp_times), 1) if comp_times else 0.0
            )

            # Per-rep breakdown
            rep_map: dict = {}
            for t in created:
                aid = t.get("assigned_to")
                if aid:
                    rep_map.setdefault(aid, {"created": 0, "completed": 0, "overdue": 0})
                    rep_map[aid]["created"] += 1
            for t in completed:
                aid = t.get("assigned_to")
                if aid and aid in rep_map:
                    rep_map[aid]["completed"] += 1
            for t in overdue:
                aid = t.get("assigned_to")
                if aid and aid in rep_map:
                    rep_map[aid]["overdue"] += 1

            rep_names: dict = {}
            try:
                u_r = db.table("users").select("id, full_name").eq("org_id", org_id).execute()
                for u in (u_r.data or []):
                    rep_names[u["id"]] = u.get("full_name") or u["id"]
            except Exception:
                pass

            per_rep = [
                {
                    "rep_name":       rep_names.get(aid, aid),
                    "created":        d["created"],
                    "completed":      d["completed"],
                    "overdue":        d["overdue"],
                    "completion_rate": round(
                        d["completed"] / d["created"] * 100, 1
                    ) if d["created"] else 0.0,
                }
                for aid, d in rep_map.items()
            ]

            return {
                "tasks_created":          len(created),
                "tasks_completed":        len(completed),
                "completion_rate":        completion_rate,
                "overdue_tasks":          len(overdue),
                "avg_completion_time_hours": avg_completion_hours,
                "ai_recommended_actioned": None,  # excluded per product owner
                "ai_recommended_ignored":  None,
                "per_rep":                per_rep,
            }

        curr = _compute_tasks(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_tasks(compare_date_from, compare_date_to)

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "deltas": {
                "completion_rate": _metric_block(
                    float(curr.get("completion_rate") or 0),
                    float(prev.get("completion_rate") or 0) if not prev.get("error") else 0.0,
                ),
                "overdue_tasks": _metric_block(
                    float(curr.get("overdue_tasks") or 0),
                    float(prev.get("overdue_tasks") or 0) if not prev.get("error") else 0.0,
                    invert=True,
                ),
            },
        }
    except Exception as exc:
        logger.warning("get_task_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 11: Lost Lead Analysis
# ---------------------------------------------------------------------------

def get_lost_lead_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
    rep_id: Optional[str] = None,
    team: Optional[str] = None,
) -> dict:
    """
    Analysis of leads marked as lost within the period (updated_at in range).
    S14: returns error dict on any failure — never raises.
    """
    try:
        def _compute_lost(date_f: str, date_t: str) -> dict:
            try:
                result = (
                    db.table("leads")
                    .select(
                        "id, stage, lost_reason, updated_at, assigned_to, "
                        "first_touch_team, lost_at"
                    )
                    .eq("org_id", org_id)
                    .eq("stage", "lost")
                    .is_("deleted_at", None)
                    .execute()
                )
                all_lost = result.data or []
                if isinstance(all_lost, dict):
                    all_lost = [all_lost]
            except Exception as exc:
                logger.warning("get_lost_lead_report: fetch failed: %s", exc)
                return {"error": "section unavailable"}

            # Filter by lost_at in period
            lost = [l for l in all_lost if _in_range(l.get("lost_at"), date_f, date_t)]

            if rep_id:
                lost = [l for l in lost if l.get("assigned_to") == rep_id]
            if team:
                lost = [l for l in lost if (l.get("first_touch_team") or "") == team]

            # Lost by reason
            reason_counts: dict = {}
            for l in lost:
                r = l.get("lost_reason") or "No reason given"
                reason_counts[r] = reason_counts.get(r, 0) + 1
            lost_by_reason = dict(
                sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
            )

            # Lost by rep
            rep_counts: dict = {}
            for l in lost:
                aid = l.get("assigned_to")
                if aid:
                    rep_counts[aid] = rep_counts.get(aid, 0) + 1
            rep_names: dict = {}
            try:
                u_r = db.table("users").select("id, full_name").eq("org_id", org_id).execute()
                for u in (u_r.data or []):
                    rep_names[u["id"]] = u.get("full_name") or u["id"]
            except Exception:
                pass
            lost_by_rep = [
                {"rep_name": rep_names.get(rid, rid), "lost_count": cnt}
                for rid, cnt in sorted(rep_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            # Lost by team
            team_counts: dict = {}
            for l in lost:
                t = l.get("first_touch_team") or "Unattributed"
                team_counts[t] = team_counts.get(t, 0) + 1
            lost_by_team = [
                {"team_name": t, "lost_count": cnt}
                for t, cnt in sorted(team_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            top_lost_stage = (
                max(reason_counts.items(), key=lambda x: x[1])[0]
                if reason_counts else None
            )

            return {
                "total_lost":    len(lost),
                "lost_by_reason": lost_by_reason,
                "lost_by_rep":   lost_by_rep,
                "lost_by_team":  lost_by_team,
                "reactivated":   None,  # no re-entry tracking in current schema
                "top_lost_stage": top_lost_stage,
            }

        curr = _compute_lost(date_from, date_to)
        if curr.get("error"):
            return curr
        prev = _compute_lost(compare_date_from, compare_date_to)

        return {
            "current":  curr,
            "previous": prev if not prev.get("error") else {},
            "delta_total_lost": _metric_block(
                float(curr.get("total_lost") or 0),
                float(prev.get("total_lost") or 0) if not prev.get("error") else 0.0,
                invert=True,
            ),
        }
    except Exception as exc:
        logger.warning("get_lost_lead_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Section 12: Channel ROI
# ---------------------------------------------------------------------------

def get_channel_roi_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    compare_date_from: str,
    compare_date_to: str,
) -> dict:
    """
    Wraps get_channel_metrics() for both periods. Adds ROI computation.
    ROI per channel = revenue / total_spend * 100 (where spend > 0).
    Channels with no spend: ROI = null (not 0 — avoids misleading values).
    S14: returns error dict on any failure — never raises.
    """
    try:
        df  = _parse_date(date_from)
        dt  = _parse_date(date_to)
        cdf = _parse_date(compare_date_from)
        cdt = _parse_date(compare_date_to)

        curr_channels = get_channel_metrics(db=db, org_id=org_id, date_from=df, date_to=dt)
        prev_channels = get_channel_metrics(db=db, org_id=org_id, date_from=cdf, date_to=cdt)

        def _add_roi(channels: list) -> list:
            result = []
            for ch in channels:
                spend   = float(ch.get("total_spend") or 0)
                revenue = float(ch.get("revenue") or 0)
                roi_pct = round(revenue / spend * 100, 1) if spend > 0 else None
                result.append({**ch, "roi_pct": roi_pct})
            return result

        curr_enriched = _add_roi(curr_channels)
        prev_enriched = _add_roi(prev_channels)

        prev_map = {ch["utm_source"]: ch for ch in prev_enriched}
        channel_deltas = []
        for ch in curr_enriched:
            src  = ch["utm_source"]
            prev = prev_map.get(src, {})
            channel_deltas.append({
                "utm_source": src,
                "leads_delta_pct": _safe_delta_pct(
                    float(ch.get("total_leads") or 0),
                    float(prev.get("total_leads") or 0),
                ),
                "conversion_rate_delta_pts": round(
                    float(ch.get("conversion_rate") or 0) -
                    float(prev.get("conversion_rate") or 0), 1
                ),
                "roi_delta_pts": (
                    round(
                        float(ch.get("roi_pct") or 0) -
                        float(prev.get("roi_pct") or 0), 1
                    )
                    if ch.get("roi_pct") is not None and prev.get("roi_pct") is not None
                    else None
                ),
            })

        return {
            "current":        curr_enriched,
            "previous":       prev_enriched,
            "channel_deltas": channel_deltas,
        }
    except Exception as exc:
        logger.warning("get_channel_roi_report failed org=%s: %s", org_id, exc)
        return {"error": "section unavailable"}


# ---------------------------------------------------------------------------
# Master report assembler
# ---------------------------------------------------------------------------

_ALL_SECTIONS = [
    "executive_summary", "lead_pipeline", "revenue", "response_time",
    "rep_performance", "team_performance", "whatsapp", "support",
    "customer_health", "tasks", "lost_leads", "channel_roi",
]


def get_full_report(
    db: Any,
    org_id: str,
    date_from: str,
    date_to: str,
    sections: Optional[list] = None,
    team: Optional[str] = None,
    rep_id: Optional[str] = None,
    compare: str = "previous_period",
) -> dict:
    """
    Assembles all requested sections into a single report dict.

    sections: list of section keys to include. None → all sections.
    compare:
      "previous_period" → prior period of same length
      "year_on_year"    → same period 365 days ago
      "none"            → no comparison (previous values omitted)

    S14: each section is wrapped independently — one failure never blocks others.
    """
    active_sections = sections if sections else _ALL_SECTIONS[:]

    # Resolve comparison period
    if compare == "year_on_year":
        compare_date_from, compare_date_to = _compute_yoy_period(date_from, date_to)
    elif compare == "none":
        # Use same period as current so helpers don't choke — deltas will be 0
        compare_date_from, compare_date_to = date_from, date_to
    else:
        compare_date_from, compare_date_to = _compute_comparison_period(date_from, date_to)

    # Fetch org metadata for report_meta
    org_name = ""
    generated_by = ""
    try:
        org_r = (
            db.table("organisations")
            .select("name")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        org_d = org_r.data
        if isinstance(org_d, list):
            org_d = org_d[0] if org_d else None
        org_name = (org_d or {}).get("name") or ""
    except Exception:
        pass

    report: dict = {
        "report_meta": {
            "org_id":                   org_id,
            "org_name":                 org_name,
            "org_logo_url":             None,   # no logo_url column in schema
            "date_from":                date_from,
            "date_to":                  date_to,
            "period_label":             _format_period_label(date_from, date_to),
            "comparison_period_label":  (
                _format_period_label(compare_date_from, compare_date_to)
                if compare != "none" else None
            ),
            "compare_mode":             compare,
            "filters":                  {"team": team, "rep_id": rep_id},
            "sections_included":        active_sections,
            "generated_at":             datetime.now(timezone.utc).isoformat(),
        }
    }

    # Section dispatch map
    def _run(fn, **kwargs):
        try:
            return fn(
                db=db, org_id=org_id,
                date_from=date_from, date_to=date_to,
                compare_date_from=compare_date_from, compare_date_to=compare_date_to,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("get_full_report section failed: %s", exc)
            return {"error": "section unavailable"}

    if "executive_summary" in active_sections:
        report["executive_summary"] = _run(get_executive_summary, team=team)

    if "lead_pipeline" in active_sections:
        report["lead_pipeline"] = _run(get_lead_pipeline_report, team=team, rep_id=rep_id)

    if "revenue" in active_sections:
        report["revenue"] = _run(get_revenue_report, team=team, rep_id=rep_id)

    if "response_time" in active_sections:
        report["response_time"] = _run(get_response_time_report, rep_id=rep_id)

    if "rep_performance" in active_sections:
        report["rep_performance"] = _run(get_rep_performance_report, rep_id=rep_id)

    if "team_performance" in active_sections:
        report["team_performance"] = _run(get_team_performance_report, team=team)

    if "whatsapp" in active_sections:
        report["whatsapp"] = _run(get_whatsapp_report, rep_id=rep_id)

    if "support" in active_sections:
        report["support"] = _run(get_support_report, rep_id=rep_id)

    if "customer_health" in active_sections:
        report["customer_health"] = _run(get_customer_health_report)

    if "tasks" in active_sections:
        report["tasks"] = _run(get_task_report, rep_id=rep_id)

    if "lost_leads" in active_sections:
        report["lost_leads"] = _run(get_lost_lead_report, rep_id=rep_id, team=team)

    if "channel_roi" in active_sections:
        report["channel_roi"] = _run(get_channel_roi_report)

    return report


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def generate_report_pdf(report_data: dict) -> bytes:
    """
    Renders the report dict to a branded PDF via WeasyPrint.

    org_logo_url is not available in the current schema — Opsra wordmark
    text fallback is used instead.

    Charts are NOT rendered — replaced by data tables (WeasyPrint does not
    execute JS; SVG charts may be added in a later iteration).

    Layout:
      - Header:  org name + report period (logo fallback: "Opsra")
      - Footer:  "Generated by Opsra" + page number
      - One section per page (page-break-after: always)
      - KPI tables: This Period | Last Period | Change (coloured)
      - Zebra-striped tables with teal headers

    Raises ValueError if report_meta is missing.
    Returns raw PDF bytes.
    """
    if not report_data.get("report_meta"):
        raise ValueError("generate_report_pdf: report_data is missing report_meta")

    from weasyprint import HTML as _HTML

    meta       = report_data["report_meta"]
    org_name   = meta.get("org_name") or "Organisation"
    period     = meta.get("period_label") or ""
    compare_mode = meta.get("compare_mode") or "previous_period"
    comp_period = meta.get("comparison_period_label") or ""
    gen_at     = meta.get("generated_at") or ""

    # Teal accent colour consistent with frontend design system
    TEAL = "#0D9488"

    def _arrow(direction: Optional[str]) -> str:
        if direction == "up":   return "<span style='color:#16a34a'>▲</span>"
        if direction == "down": return "<span style='color:#dc2626'>▼</span>"
        return "<span style='color:#6b7280'>—</span>"

    def _fmt(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:,.1f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    def _metric_rows(metrics: dict) -> str:
        rows = ""
        labels = {
            "total_revenue":       "Total Revenue",
            "total_leads":         "Total Leads",
            "total_conversions":   "Conversions",
            "conversion_rate":     "Conversion Rate (%)",
            "avg_close_time_days": "Avg Close Time (days)",
            "cac":                 "CAC",
        }
        for key, m in metrics.items():
            label = labels.get(key, key.replace("_", " ").title())
            curr  = _fmt(m.get("current"))
            prev  = _fmt(m.get("previous"))
            delta = _fmt(m.get("delta"))
            pct   = _fmt(m.get("delta_pct"))
            arrow = _arrow(m.get("direction"))
            change_str = f"{arrow} {delta}"
            if m.get("delta_pct") is not None:
                change_str += f" ({pct}%)"
            if compare_mode == "none":
                rows += (
                    f"<tr>"
                    f"<td>{label}</td>"
                    f"<td style='text-align:right'>{curr}</td>"
                    f"</tr>"
                )
            else:
                rows += (
                    f"<tr>"
                    f"<td>{label}</td>"
                    f"<td style='text-align:right'>{curr}</td>"
                    f"<td style='text-align:right'>{prev}</td>"
                    f"<td style='text-align:right'>{change_str}</td>"
                    f"</tr>"
                )
        return rows

    def _section_table(title: str, rows_html: str) -> str:
        if compare_mode == "none":
            return f"""
        <div class='section'>
          <h2>{title}</h2>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>This Period</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """
        return f"""
        <div class='section'>
          <h2>{title}</h2>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>This Period</th>
                <th>Last Period</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """

    # Build section HTML
    sections_html = ""

    if report_data.get("executive_summary") and not report_data["executive_summary"].get("error"):
        es = report_data["executive_summary"]
        sections_html += _section_table(
            "Executive Summary",
            _metric_rows(es.get("metrics", {})),
        )

    def _simple_kv_section(title: str, current: dict, previous: dict, deltas: dict) -> str:
        rows = ""
        for key, val in (deltas or {}).items():
            if not isinstance(val, dict):
                continue
            label = key.replace("_", " ").title()
            curr  = _fmt((current or {}).get(key))
            prev  = _fmt((previous or {}).get(key))
            arrow = _arrow(val.get("direction"))
            d_pct = _fmt(val.get("delta_pct"))
            if compare_mode == "none":
                rows += (
                    f"<tr><td>{label}</td>"
                    f"<td style='text-align:right'>{curr}</td>"
                    f"</tr>"
                )
            else:
                rows += (
                    f"<tr><td>{label}</td>"
                    f"<td style='text-align:right'>{curr}</td>"
                    f"<td style='text-align:right'>{prev}</td>"
                    f"<td style='text-align:right'>{arrow} {d_pct}%</td></tr>"
                )
        return _section_table(title, rows) if rows else ""

    for sec_key, sec_title in [
        ("lead_pipeline",   "Lead & Pipeline Performance"),
        ("revenue",         "Revenue Summary"),
        ("whatsapp",        "WhatsApp Communication Intelligence"),
        ("support",         "Support & Ticket Intelligence"),
        ("customer_health", "Customer Health Snapshot"),
        ("tasks",           "Task & Activity Analytics"),
        ("lost_leads",      "Lost Lead Analysis"),
    ]:
        sec = report_data.get(sec_key)
        if sec and not sec.get("error"):
            sections_html += _simple_kv_section(
                sec_title,
                sec.get("current", {}),
                sec.get("previous", {}),
                sec.get("deltas", {}),
            )

    # Response time section
    rt = report_data.get("response_time")
    if rt and not rt.get("error"):
        curr_rt = rt.get("current", {})
        prev_rt = rt.get("previous", {})
        if compare_mode == "none":
            rt_rows = (
                f"<tr><td>Avg First Response (mins)</td>"
                f"<td style='text-align:right'>{_fmt(curr_rt.get('org_avg_first_response_mins'))}</td></tr>"
                f"<tr><td>SLA Compliance (%)</td>"
                f"<td style='text-align:right'>{_fmt(curr_rt.get('sla_compliance_pct'))}</td></tr>"
            )
        else:
            rt_rows = (
                f"<tr><td>Avg First Response (mins)</td>"
                f"<td style='text-align:right'>{_fmt(curr_rt.get('org_avg_first_response_mins'))}</td>"
                f"<td style='text-align:right'>{_fmt(prev_rt.get('org_avg_first_response_mins'))}</td>"
                f"<td style='text-align:right'>{_arrow(rt.get('direction'))} {_fmt(rt.get('delta_first_response_mins'))} mins</td></tr>"
                f"<tr><td>SLA Compliance (%)</td>"
                f"<td style='text-align:right'>{_fmt(curr_rt.get('sla_compliance_pct'))}</td>"
                f"<td style='text-align:right'>{_fmt(prev_rt.get('sla_compliance_pct'))}</td>"
                f"<td style='text-align:right'>—</td></tr>"
            )
        sections_html += _section_table("Response Time Analysis", rt_rows)

        per_rep_rt = curr_rt.get("per_rep") or []
        if per_rep_rt:
            rep_rt_rows = ""
            for r in per_rep_rt:
                rep_rt_rows += (
                    f"<tr>"
                    f"<td>{r.get('rep_name', '')}</td>"
                    f"<td style='text-align:right'>{_fmt(r.get('threads_handled'))}</td>"
                    f"<td style='text-align:right'>{_fmt(r.get('avg_first_response_mins'))} mins</td>"
                    f"<td style='text-align:right'>{_fmt(r.get('sla_compliance_pct'))}%</td>"
                    f"</tr>"
                )
            sections_html += f"""
            <div class='section'>
              <h2>Response Time — By Rep</h2>
              <table>
                <thead>
                  <tr><th>Rep</th><th>Threads</th><th>Avg First Response</th><th>SLA Compliance</th></tr>
                </thead>
                <tbody>{rep_rt_rows}</tbody>
              </table>
            </div>
            """

    # Rep performance section
    rp = report_data.get("rep_performance")
    if rp and not rp.get("error"):
        rep_rows = ""
        for rep in (rp.get("current") or []):
            rep_rows += (
                f"<tr>"
                f"<td>{rep.get('rep_name','')}</td>"
                f"<td style='text-align:right'>{_fmt(rep.get('leads_assigned'))}</td>"
                f"<td style='text-align:right'>{_fmt(rep.get('close_rate'))}%</td>"
                f"<td style='text-align:right'>{_fmt(rep.get('revenue_closed'))}</td>"
                f"</tr>"
            )
        if rep_rows:
            sections_html += f"""
            <div class='section'>
              <h2>Sales Rep Performance</h2>
              <table>
                <thead>
                  <tr><th>Rep</th><th>Leads</th><th>Close Rate</th><th>Revenue</th></tr>
                </thead>
                <tbody>{rep_rows}</tbody>
              </table>
            </div>
            """

    # Team performance section
    tp = report_data.get("team_performance")
    if tp and not tp.get("error"):
        team_rows = ""
        for t in (tp.get("current") or []):
            best = " ⭐" if t.get("is_best_performer") else ""
            team_rows += (
                f"<tr>"
                f"<td>{t.get('team_name','')}{best}</td>"
                f"<td style='text-align:right'>{_fmt(t.get('leads_generated'))}</td>"
                f"<td style='text-align:right'>{_fmt(t.get('conversion_rate'))}%</td>"
                f"<td style='text-align:right'>{_fmt(t.get('revenue_generated'))}</td>"
                f"</tr>"
            )
        if team_rows:
            sections_html += f"""
            <div class='section'>
              <h2>Team Performance</h2>
              <table>
                <thead>
                  <tr><th>Team</th><th>Leads</th><th>Conv. Rate</th><th>Revenue</th></tr>
                </thead>
                <tbody>{team_rows}</tbody>
              </table>
            </div>
            """

    # Channel ROI section
    cr = report_data.get("channel_roi")
    if cr and not cr.get("error"):
        ch_rows = ""
        for ch in (cr.get("current") or []):
            ch_rows += (
                f"<tr>"
                f"<td>{ch.get('utm_source','')}</td>"
                f"<td style='text-align:right'>{_fmt(ch.get('total_leads'))}</td>"
                f"<td style='text-align:right'>{_fmt(ch.get('conversion_rate'))}%</td>"
                f"<td style='text-align:right'>{_fmt(ch.get('revenue'))}</td>"
                f"<td style='text-align:right'>"
                f"{'—' if ch.get('roi_pct') is None else _fmt(ch.get('roi_pct')) + '%'}"
                f"</td>"
                f"</tr>"
            )
        if ch_rows:
            sections_html += f"""
            <div class='section'>
              <h2>Channel ROI</h2>
              <table>
                <thead>
                  <tr><th>Channel</th><th>Leads</th><th>Conv. Rate</th><th>Revenue</th><th>ROI</th></tr>
                </thead>
                <tbody>{ch_rows}</tbody>
              </table>
            </div>
            """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
      @page {{
        margin: 20mm 15mm;
        @bottom-center {{
          content: "Generated by Opsra  |  Page " counter(page) " of " counter(pages);
          font-size: 9px; color: #6b7280;
        }}
      }}
      body {{ font-family: Arial, sans-serif; font-size: 11px; color: #111827; margin: 0; }}
      .header {{ border-bottom: 2px solid {TEAL}; padding-bottom: 8px; margin-bottom: 16px;
                 display: flex; justify-content: space-between; align-items: center; }}
      .header-left h1 {{ margin: 0; font-size: 18px; color: {TEAL}; }}
      .header-left p  {{ margin: 2px 0; font-size: 10px; color: #6b7280; }}
      .header-right   {{ text-align: right; font-size: 10px; color: #6b7280; }}
      .section {{ page-break-inside: avoid; margin-bottom: 24px; border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; }}
      h2 {{ font-size: 14px; color: {TEAL}; border-bottom: 1px solid #e5e7eb;
            padding-bottom: 4px; margin-bottom: 8px; }}
      table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
      thead tr {{ background: {TEAL}; color: white; }}
      th {{ padding: 6px 8px; text-align: left; font-size: 10px; }}
      td {{ padding: 5px 8px; font-size: 10px; border-bottom: 1px solid #f3f4f6; }}
      tr:nth-child(even) td {{ background: #f9fafb; }}
    </style>
    </head>
    <body>
      <div class='header'>
        <div class='header-left'>
          <h1>Opsra</h1>
          <p>{org_name}</p>
          <p>Management Report — {period}</p>
        </div>
        <div class='header-right'>
          {f'Comparison period: {comp_period}<br>' if compare_mode != 'none' else ''}
          Generated: {gen_at[:10] if gen_at else ''}
        </div>
      </div>
      {sections_html}
    </body>
    </html>
    """

    return _HTML(string=html).write_pdf()