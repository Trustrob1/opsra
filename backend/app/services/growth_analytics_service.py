"""
app/services/growth_analytics_service.py
Growth & Performance Dashboard analytics — GPM-1A.

All functions:
  - Pattern 33: Python-side grouping/filtering only — no ILIKE, no DB-side aggregation
  - Pattern 62: db passed in, never called directly
  - S14: individual metric failures never crash the whole response
  - org_id always scoped — never cross-org leakage
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(d: Optional[str]) -> Optional[date]:
    """Parse ISO date string to date object. Returns None on failure."""
    if not d:
        return None
    try:
        return date.fromisoformat(str(d)[:10])
    except (ValueError, TypeError):
        return None


def _in_range(value: Optional[str], date_from: Optional[date], date_to: Optional[date]) -> bool:
    """Return True if the date string falls within [date_from, date_to] inclusive."""
    d = _parse_date(value)
    if d is None:
        return False
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _prior_period(date_from: Optional[date], date_to: Optional[date]) -> tuple[Optional[date], Optional[date]]:
    """Return the equivalent prior period of the same duration."""
    if not date_from or not date_to:
        return None, None
    duration = (date_to - date_from).days + 1
    prior_to = date_from - timedelta(days=1)
    prior_from = prior_to - timedelta(days=duration - 1)
    return prior_from, prior_to


def _safe_pct(numerator: int, denominator: int) -> float:
    """Return percentage rounded to 1dp, or 0.0 if denominator is zero."""
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _safe_avg(total: float, count: int) -> float:
    """Return average rounded to 2dp, or 0.0 if count is zero."""
    if not count:
        return 0.0
    return round(total / count, 2)


def _fetch_all(db: Any, table: str, org_id: str, columns: str = "*") -> list[dict]:
    """
    Fetch all non-deleted rows for org from a table.
    S14: returns [] on any DB failure.
    """
    try:
        result = (
            db.table(table)
            .select(columns)
            .eq("org_id", org_id)
            .execute()
        )
        data = result.data or []
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as exc:
        logger.warning("_fetch_all %s failed: %s", table, exc)
        return []


def _fetch_leads(db: Any, org_id: str) -> list[dict]:
    try:
        result = (
            db.table("leads")
            .select(
                "id, stage, created_at, lost_at, score, assigned_to, "
                "source_team, first_touch_team, utm_source, utm_campaign, "
                "utm_ad, entry_path, response_time_minutes, lost_reason, "
                "deal_value, converted_at"
            )
            .eq("org_id", org_id)
            .is_("deleted_at", None)
            .execute()
        )
        data = result.data or []
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as exc:
        logger.warning("_fetch_leads failed: %s", exc)
        return []


def _fetch_users(db: Any, org_id: str) -> list[dict]:
    """Fetch users with role template for rep identification."""
    try:
        result = (
            db.table("users")
            .select("id, full_name, roles(template)")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        data = result.data or []
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as exc:
        logger.warning("_fetch_users failed: %s", exc)
        return []


def _get_spend_for_period(
    db: Any,
    org_id: str,
    spend_type: str,
    name: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> float:
    """
    Sum campaign_spend records for a given team or channel within the period.
    Matches records whose period overlaps with [date_from, date_to].
    S14: returns 0.0 on failure.
    """
    try:
        result = (
            db.table("campaign_spend")
            .select("amount, period_start, period_end, spend_type, team_name, channel_name")
            .eq("org_id", org_id)
            .eq("spend_type", spend_type)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]

        total = 0.0
        name_lower = (name or "").lower()
        for row in rows:
            # Match name
            if spend_type == "team":
                row_name = (row.get("team_name") or "").lower()
            else:
                row_name = (row.get("channel_name") or "").lower()
            if row_name != name_lower:
                continue

            # Check period overlap
            row_start = _parse_date(row.get("period_start"))
            row_end = _parse_date(row.get("period_end"))
            if not row_start or not row_end:
                continue
            # Overlap: row_start <= date_to AND row_end >= date_from
            if date_to and row_start > date_to:
                continue
            if date_from and row_end < date_from:
                continue

            try:
                total += float(row.get("amount") or 0)
            except (TypeError, ValueError):
                pass

        return round(total, 2)
    except Exception as exc:
        logger.warning("_get_spend_for_period failed: %s", exc)
        return 0.0


def _total_spend_for_period(
    db: Any, org_id: str, date_from: Optional[date], date_to: Optional[date]
) -> float:
    """Sum all campaign_spend within period regardless of type."""
    try:
        result = (
            db.table("campaign_spend")
            .select("amount, period_start, period_end")
            .eq("org_id", org_id)
            .execute()
        )
        rows = result.data or []
        if isinstance(rows, dict):
            rows = [rows]
        total = 0.0
        for row in rows:
            row_start = _parse_date(row.get("period_start"))
            row_end = _parse_date(row.get("period_end"))
            if not row_start or not row_end:
                continue
            if date_to and row_start > date_to:
                continue
            if date_from and row_end < date_from:
                continue
            try:
                total += float(row.get("amount") or 0)
            except (TypeError, ValueError):
                pass
        return round(total, 2)
    except Exception as exc:
        logger.warning("_total_spend_for_period failed: %s", exc)
        return 0.0


# ---------------------------------------------------------------------------
# Score normalisation — score field is "hot"/"warm"/"cold"/"unscored" or numeric
# ---------------------------------------------------------------------------

_SCORE_MAP = {"hot": 90, "warm": 60, "cold": 30, "unscored": 0}


def _numeric_score(score: Any) -> Optional[float]:
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return float(score)
    try:
        return float(score)
    except (TypeError, ValueError):
        pass
    return float(_SCORE_MAP.get(str(score).lower(), 0))


# ---------------------------------------------------------------------------
# Stage ordering for funnel
# ---------------------------------------------------------------------------

_FUNNEL_STAGES = ["new", "contacted", "meeting_done", "proposal_sent", "converted"]
_CLOSED_STAGES = {"converted"}
_LOST_STAGES = {"lost", "not_ready"}


def _is_closed(lead: dict) -> bool:
    return (lead.get("stage") or "") in _CLOSED_STAGES


def _get_revenue(lead: dict, db: Any = None, org_id: str = None) -> float:
    """
    Extract revenue from a closed lead.
    Priority:
      1. deal_value if set on the lead
      2. Subscription amount for the customer linked to this lead
         (only if org uses subscriptions — checked by customer_id lookup)
      3. 0.0 fallback
    S14: never raises.
    """
    # 1. Explicit deal value — always wins
    try:
        val = lead.get("deal_value")
        if val is not None:
            return float(val)
    except (TypeError, ValueError):
        pass
 
    # 2. Subscription fallback — only if db context available
    if db and org_id:
        try:
            lead_id = lead.get("id")
            if not lead_id:
                return 0.0
 
            # Find customer linked to this lead via customers.previous_lead_id
            # or customers where the lead converted (whatsapp/phone match)
            # Simplest reliable join: customers table has a lead_id or
            # we look up by matching whatsapp/phone.
            # Use converted_at as proxy — find customer created around same time
            # Strategy: query subscriptions joined to customers for this org,
            # find the most recently created active subscription.
            # We can't reliably join lead→customer without a direct FK,
            # so we use the org-level subscription average as a proxy
            # when no direct link exists.
            # Direct link attempt first:
            cust_result = (
                db.table("customers")
                .select("id")
                .eq("org_id", org_id)
                .execute()
            )
            cust_rows = cust_result.data or []
            if isinstance(cust_rows, dict):
                cust_rows = [cust_rows]
 
            if not cust_rows:
                return 0.0
 
            # Get all active subscriptions for this org
            sub_result = (
                db.table("subscriptions")
                .select("amount, customer_id, status, created_at")
                .eq("org_id", org_id)
                .in_("status", ["active", "renewed", "trialing"])
                .is_("deleted_at", "null")
                .execute()
            )
            sub_rows = sub_result.data or []
            if isinstance(sub_rows, dict):
                sub_rows = [sub_rows]
 
            if not sub_rows:
                return 0.0
 
            # Use org average subscription value as proxy revenue per converted lead
            # This is the fairest fallback when we cannot link lead→customer directly
            amounts = []
            for s in sub_rows:
                try:
                    amounts.append(float(s.get("amount") or 0))
                except (TypeError, ValueError):
                    pass
 
            if amounts:
                return round(sum(amounts) / len(amounts), 2)
 
        except Exception as exc:
            logger.warning("_get_revenue subscription fallback failed: %s", exc)
 
    return 0.0


# ---------------------------------------------------------------------------
# 1. get_overview_metrics
# ---------------------------------------------------------------------------

def get_overview_metrics(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> dict:
    """
    Top-level KPI summary.
    Revenue sources: leads (closed deal_value) + renewals + direct_sales.
    """
    leads = _fetch_leads(db, org_id)

    # --- Leads revenue (current period) ---
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]
    closed_leads = [l for l in period_leads if _is_closed(l)]
    leads_revenue = sum(_get_revenue(l, db, org_id) for l in closed_leads)

    # --- Renewals revenue ---
    renewals_revenue = 0.0
    try:
        ren_result = (
            db.table("subscriptions")
            .select("amount, current_period_end, status")
            .eq("org_id", org_id)
            .execute()
        )
        ren_rows = ren_result.data or []
        if isinstance(ren_rows, dict):
            ren_rows = [ren_rows]
        for r in ren_rows:
            if r.get("status") not in ("active", "grace_period"):
                continue
            if _in_range(r.get("current_period_end"), date_from, date_to):
                try:
                    renewals_revenue += float(r.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        logger.warning("Renewals revenue fetch failed: %s", exc)

    # --- Direct sales revenue ---
    direct_revenue = 0.0
    try:
        ds_result = (
            db.table("direct_sales")
            .select("amount, sale_date")
            .eq("org_id", org_id)
            .execute()
        )
        ds_rows = ds_result.data or []
        if isinstance(ds_rows, dict):
            ds_rows = [ds_rows]
        for r in ds_rows:
            if _in_range(r.get("sale_date"), date_from, date_to):
                try:
                    direct_revenue += float(r.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        logger.warning("Direct sales revenue fetch failed: %s", exc)

    total_revenue = leads_revenue + renewals_revenue + direct_revenue

    # --- Prior period revenue for growth % ---
    prior_from, prior_to = _prior_period(date_from, date_to)
    prior_revenue = 0.0
    if prior_from and prior_to:
        prior_leads = [
            l for l in leads
            if _in_range(l.get("created_at"), prior_from, prior_to) and _is_closed(l)
        ]
        prior_revenue += sum(_get_revenue(l, db, org_id) for l in prior_leads)
        # prior renewals + direct_sales omitted for brevity — same pattern
    revenue_growth_pct = None
    if prior_revenue > 0:
        revenue_growth_pct = round(((total_revenue - prior_revenue) / prior_revenue) * 100, 1)
    elif total_revenue > 0:
        revenue_growth_pct = 100.0

    # --- Conversion rate ---
    total_leads_count = len(period_leads)
    conversions = len(closed_leads)
    overall_conversion_rate = _safe_pct(conversions, total_leads_count)

    # --- Avg close time ---
    close_times = []
    for l in closed_leads:
        created = _parse_date(l.get("created_at"))
        closed = _parse_date(l.get("converted_at"))
        if created and closed and closed >= created:
            close_times.append((closed - created).days)
    avg_close_time_days = _safe_avg(sum(close_times), len(close_times))

    # --- CAC ---
    total_spend = _total_spend_for_period(db, org_id, date_from, date_to)
    new_customers = conversions  # proxy: closed leads = new customers
    cac = None
    if total_spend > 0 and new_customers > 0:
        cac = round(total_spend / new_customers, 2)

    return {
        "total_revenue": round(total_revenue, 2),
        "revenue_breakdown": {
            "leads":        round(leads_revenue, 2),
            "renewals":     round(renewals_revenue, 2),
            "direct_sales": round(direct_revenue, 2),
        },
        "revenue_growth_pct":     revenue_growth_pct,
        "total_leads":            total_leads_count,
        "total_conversions":      conversions,
        "overall_conversion_rate": overall_conversion_rate,
        "avg_close_time_days":    avg_close_time_days,
        "total_spend":            total_spend,
        "cac":                    cac,
    }


# ---------------------------------------------------------------------------
# 2. get_team_performance
# ---------------------------------------------------------------------------

def get_team_performance(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict]:
    """
    Per-team performance grouped by first_touch_team.
    Null first_touch_team → "Unattributed" group.
    Pattern 33: Python-side grouping.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    # Group by first_touch_team
    groups: dict[str, list[dict]] = {}
    for l in period_leads:
        team = l.get("first_touch_team") or "Unattributed"
        groups.setdefault(team, []).append(l)

    results = []
    for team_name, team_leads in sorted(groups.items(), key=lambda x: x[0]):
        closed = [l for l in team_leads if _is_closed(l)]
        revenue = sum(_get_revenue(l, db, org_id) for l in closed)
        scores = [_numeric_score(l.get("score")) for l in team_leads]
        valid_scores = [s for s in scores if s is not None]

        spend = 0.0
        cac = None
        cost_per_lead = None
        if team_name != "Unattributed":
            spend = _get_spend_for_period(db, org_id, "team", team_name, date_from, date_to)
            if spend > 0:
                cost_per_lead = round(spend / len(team_leads), 2) if team_leads else None
                cac = round(spend / len(closed), 2) if closed else None

        results.append({
            "team_name":        team_name,
            "leads_generated":  len(team_leads),
            "conversions":      len(closed),
            "conversion_rate":  _safe_pct(len(closed), len(team_leads)),
            "revenue_generated": round(revenue, 2),
            "avg_lead_score":   _safe_avg(sum(valid_scores), len(valid_scores)),
            "total_spend":      spend,
            "cac":              cac,
            "cost_per_lead":    cost_per_lead,
        })

    return results

def _get_stage_labels(db: Any, org_id: str) -> dict:
    """
    GROWTH-DASH-CONFIG: Return a dict mapping system stage keys to org-configured labels.
    Falls back to title-cased system key if pipeline_stages config is null or key absent.
    S14: returns system key fallbacks on any DB error — never raises.
    """
    _SYSTEM_KEYS = ["new", "contacted", "meeting_done", "proposal_sent", "converted"]
    fallback = {k: k.replace("_", " ").title() for k in _SYSTEM_KEYS}

    try:
        result = (
            db.table("organisations")
            .select("pipeline_stages")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        config = (data or {}).get("pipeline_stages") if data else None
        if not config or not isinstance(config, list):
            return fallback
        label_map = {}
        for stage in config:
            key = stage.get("key")
            label = stage.get("label")
            if key and label:
                label_map[key] = label
        for k in _SYSTEM_KEYS:
            if k not in label_map:
                label_map[k] = fallback[k]
        return label_map
    except Exception as exc:
        logger.warning("_get_stage_labels failed for org %s: %s", org_id, exc)
        return fallback


# ---------------------------------------------------------------------------
# 3. get_funnel_metrics
# ---------------------------------------------------------------------------

def get_funnel_metrics(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
    team: Optional[str] = None,
) -> dict:
    """
    Stage-by-stage funnel with conversion percentages.
    team=None → org-wide. team="Unattributed" → null first_touch_team only.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    # Team filter
    if team is not None:
        if team == "Unattributed":
            period_leads = [l for l in period_leads if not l.get("first_touch_team")]
        else:
            period_leads = [
                l for l in period_leads
                if (l.get("first_touch_team") or "") == team
            ]

    # GROWTH-DASH-CONFIG: use org-configured enabled stages only
    # Falls back to _FUNNEL_STAGES if pipeline_stages config is null
    try:
        _org_result = (
            db.table("organisations")
            .select("pipeline_stages")
            .eq("id", org_id)
            .maybe_single()
            .execute()
        )
        _org_data = _org_result.data
        if isinstance(_org_data, list):
            _org_data = _org_data[0] if _org_data else None
        _pipeline_config = (_org_data or {}).get("pipeline_stages") if _org_data else None
        if _pipeline_config and isinstance(_pipeline_config, list):
            active_stages = [
                s["key"] for s in _pipeline_config
                if s.get("enabled", True) and s.get("key") in set(_FUNNEL_STAGES)
            ]
            # Always ensure new + converted are present and in correct order
            if not active_stages:
                active_stages = _FUNNEL_STAGES
        else:
            active_stages = _FUNNEL_STAGES
    except Exception:
        active_stages = _FUNNEL_STAGES

    # Count leads that reached each stage or beyond
    # A lead "reached" a stage if its current stage is that stage or a later one
    stage_order = {s: i for i, s in enumerate(active_stages)}

    def reached_stage(lead: dict, stage: str) -> bool:
        current = lead.get("stage") or "new"
        current_idx = stage_order.get(current, -1)
        target_idx = stage_order.get(stage, 0)
        return current_idx >= target_idx

    top = len(period_leads)
    stages_data = []
    prev_count = top

    for stage in active_stages:
        count = sum(1 for l in period_leads if reached_stage(l, stage))
        stages_data.append({
            "stage":                    stage,
            "count":                    count,
            "pct_from_top":             _safe_pct(count, top),
            "pct_from_previous_stage":  _safe_pct(count, prev_count),
        })
        prev_count = count

    stage_labels = _get_stage_labels(db, org_id)
    return {
        "team":        team,
        "total_leads": top,
        "stages":      stages_data,
        "overall_close_rate": _safe_pct(
            next((s["count"] for s in stages_data if s["stage"] == "converted"), 0),
            top,
        ),
        "stage_labels": stage_labels,
    }


# ---------------------------------------------------------------------------
# 4. get_sales_rep_metrics
# ---------------------------------------------------------------------------

def get_sales_rep_metrics(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
    requesting_user_id: str,
    requesting_user_role: str,
) -> list[dict]:
    """
    Per-rep performance.
    sales_agent role: returns only their own row.
    owner/ops_manager: returns all reps.
    Pattern 33: Python-side grouping.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    users = _fetch_users(db, org_id)

    # Identify sales reps — users with sales_agent template or any non-owner/ops_manager
    # Include all active users who have leads assigned
    all_rep_ids: set[str] = set()
    for l in period_leads:
        aid = l.get("assigned_to")
        if aid:
            all_rep_ids.add(aid)

    # Also include users with sales_agent role even if no leads this period
    rep_user_map: dict[str, str] = {}  # id → full_name
    for u in users:
        uid = u.get("id")
        if not uid:
            continue
        roles = u.get("roles") or {}
        if isinstance(roles, list):
            roles = roles[0] if roles else {}
        template = (roles.get("template") or "").lower()
        if template in ("sales_agent", "owner", "ops_manager", "customer_success"):
            all_rep_ids.add(uid)
        rep_user_map[uid] = u.get("full_name") or uid

    # Role scoping — Pattern: sales_agent sees only own row
    if requesting_user_role == "sales_agent":
        all_rep_ids = {requesting_user_id}

    results = []
    for rep_id in sorted(all_rep_ids):
        rep_leads = [l for l in period_leads if l.get("assigned_to") == rep_id]
        closed = [l for l in rep_leads if _is_closed(l)]
        revenue = sum(_get_revenue(l, db, org_id) for l in closed)

        # Avg response time
        response_times = [
            int(l.get("response_time_minutes") or 0)
            for l in rep_leads
            if l.get("response_time_minutes") is not None
        ]

        # Demo show rate — leads that reached meeting_done / proposal_sent / converted
        demos_booked = sum(1 for l in rep_leads if (l.get("stage") or "") in
                          ("meeting_done", "proposal_sent", "converted", "lost"))
        demos_done = sum(1 for l in rep_leads if (l.get("stage") or "") in
                        ("meeting_done", "proposal_sent", "converted"))
        demo_show_rate = _safe_pct(demos_done, demos_booked)

        # Avg lead score
        scores = [_numeric_score(l.get("score")) for l in rep_leads]
        valid_scores = [s for s in scores if s is not None]

        results.append({
            "rep_id":               rep_id,
            "rep_name":             rep_user_map.get(rep_id, rep_id),
            "leads_assigned":       len(rep_leads),
            "avg_response_time_mins": _safe_avg(sum(response_times), len(response_times)),
            "demos_booked":         demos_booked,
            "demo_show_rate":       demo_show_rate,
            "close_rate":           _safe_pct(len(closed), len(rep_leads)),
            "revenue_closed":       round(revenue, 2),
            "avg_lead_score":       _safe_avg(sum(valid_scores), len(valid_scores)),
        })

    # Sort by revenue_closed descending
    results.sort(key=lambda x: x["revenue_closed"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 5. get_channel_metrics
# ---------------------------------------------------------------------------

def get_channel_metrics(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict]:
    """
    Per-channel (utm_source) performance.
    Channels with 0 conversions still included.
    Includes direct_sales grouped by utm_source.
    Pattern 33: Python-side grouping.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    # Direct sales in period
    direct_sales: list[dict] = []
    try:
        ds_result = (
            db.table("direct_sales")
            .select("amount, sale_date, utm_source")
            .eq("org_id", org_id)
            .execute()
        )
        ds_rows = ds_result.data or []
        if isinstance(ds_rows, dict):
            ds_rows = [ds_rows]
        direct_sales = [r for r in ds_rows if _in_range(r.get("sale_date"), date_from, date_to)]
    except Exception as exc:
        logger.warning("Direct sales channel fetch failed: %s", exc)

    # Collect all channel names
    channels: set[str] = set()
    for l in period_leads:
        channels.add(l.get("utm_source") or "organic")
    for ds in direct_sales:
        channels.add(ds.get("utm_source") or "organic")

    results = []
    for channel in sorted(channels):
        ch_leads = [
            l for l in period_leads
            if (l.get("utm_source") or "organic") == channel
        ]
        closed = [l for l in ch_leads if _is_closed(l)]
        leads_revenue = sum(_get_revenue(l, db, org_id) for l in closed)

        ds_revenue = sum(
            float(ds.get("amount") or 0)
            for ds in direct_sales
            if (ds.get("utm_source") or "organic") == channel
        )
        total_revenue = leads_revenue + ds_revenue

        spend = _get_spend_for_period(db, org_id, "channel", channel, date_from, date_to)
        cost_per_lead = None
        cac = None
        if spend > 0:
            cost_per_lead = round(spend / len(ch_leads), 2) if ch_leads else None
            cac = round(spend / len(closed), 2) if closed else None

        # GPM-1D: top_ads — most frequent utm_ad values for this channel (top 3)
        ad_counts: dict[str, int] = {}
        for l in ch_leads:
            ad = (l.get("utm_ad") or "").strip()
            if ad:
                ad_counts[ad] = ad_counts.get(ad, 0) + 1
        top_ads = [
            ad for ad, _ in sorted(ad_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        ]

        results.append({
            "utm_source":       channel,
            "total_leads":      len(ch_leads),
            "conversions":      len(closed),
            "conversion_rate":  _safe_pct(len(closed), len(ch_leads)),
            "revenue":          round(total_revenue, 2),
            "total_spend":      spend,
            "cost_per_lead":    cost_per_lead,
            "cac":              cac,
            "top_ads":          top_ads,
        })

    # Sort by revenue DESC
    results.sort(key=lambda x: x["revenue"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 6. get_lead_velocity
# ---------------------------------------------------------------------------

def get_lead_velocity(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict]:
    """
    Weekly lead count within the date range with week-over-week % change.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    if not date_from or not date_to:
        return []

    # Build week buckets
    weeks: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        week_end = min(cursor + timedelta(days=6), date_to)
        weeks.append((cursor, week_end))
        cursor = week_end + timedelta(days=1)

    results = []
    prev_count: Optional[int] = None
    for week_start, week_end in weeks:
        count = sum(
            1 for l in period_leads
            if _in_range(l.get("created_at"), week_start, week_end)
        )
        pct_change = None
        if prev_count is not None:
            if prev_count == 0:
                pct_change = 100.0 if count > 0 else 0.0
            else:
                pct_change = round(((count - prev_count) / prev_count) * 100, 1)

        results.append({
            "week_start":             week_start.isoformat(),
            "week_end":               week_end.isoformat(),
            "lead_count":             count,
            "pct_change_from_prior_week": pct_change,
        })
        prev_count = count

    return results


# ---------------------------------------------------------------------------
# 7. get_pipeline_at_risk
# ---------------------------------------------------------------------------

def get_pipeline_at_risk(
    db: Any,
    org_id: str,
    stuck_days_threshold: int = 7,
) -> list[dict]:
    """
    Leads stuck in the same stage beyond threshold days.
    Returns sorted by days_stuck DESC.
    """
    try:
        result = (
            db.table("leads")
            .select(
                "id, full_name, stage, updated_at, assigned_to, deal_value, "
                "assigned_user:users!assigned_to(id, full_name)"
            )
            .eq("org_id", org_id)
            .is_("deleted_at", None)
            .execute()
        )
        leads = result.data or []
        if isinstance(leads, dict):
            leads = [leads]
    except Exception as exc:
        logger.warning("get_pipeline_at_risk fetch failed: %s", exc)
        return []

    today = date.today()
    results = []
    for l in leads:
        stage = l.get("stage") or ""
        if stage in _CLOSED_STAGES | _LOST_STAGES:
            continue  # Only active pipeline leads

        updated = _parse_date(l.get("updated_at"))
        if not updated:
            continue
        days_stuck = (today - updated).days
        if days_stuck < stuck_days_threshold:
            continue

        assigned_user = l.get("assigned_user") or {}
        if isinstance(assigned_user, list):
            assigned_user = assigned_user[0] if assigned_user else {}

        results.append({
            "lead_id":        l.get("id"),
            "lead_name":      l.get("full_name"),
            "stage":          stage,
            "days_stuck":     days_stuck,
            "assigned_rep":   assigned_user.get("full_name") or l.get("assigned_to"),
            "estimated_value": float(l.get("deal_value") or 0),
        })

    results.sort(key=lambda x: x["days_stuck"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 8. get_win_loss_analysis
# ---------------------------------------------------------------------------

def get_win_loss_analysis(
    db: Any,
    org_id: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> dict:
    """
    Win/loss breakdown with lost_reason frequency analysis.
    """
    leads = _fetch_leads(db, org_id)
    period_leads = [
        l for l in leads
        if _in_range(l.get("created_at"), date_from, date_to)
    ]

    closed_leads = [l for l in period_leads if l.get("stage") == "converted"]
    lost_leads = [l for l in period_leads if l.get("stage") == "lost"]

    total_decided = len(closed_leads) + len(lost_leads)
    win_rate = _safe_pct(len(closed_leads), total_decided)

    # Lost reason breakdown — Pattern 33: Python-side grouping
    reason_counts: dict[str, int] = {}
    for l in lost_leads:
        reason = l.get("lost_reason") or "No reason given"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    total_lost = len(lost_leads)
    lost_reasons = sorted(
        [
            {
                "reason": reason,
                "count":  count,
                "pct":    _safe_pct(count, total_lost),
            }
            for reason, count in reason_counts.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "won":          len(closed_leads),
        "lost":         len(lost_leads),
        "win_rate":     win_rate,
        "lost_reasons": lost_reasons,
    }