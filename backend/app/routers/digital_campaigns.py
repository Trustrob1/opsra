"""
app/routers/digital_campaigns.py
Digital Campaigns tab — REPORTS-DEPT-1 Phase 4d.

One row in digital_campaign_entries = one campaign, one week (manual
entry by the Digital Marketer — no ads-platform API integration, no
file upload; typed in by hand each week). Monthly views are a pure
client-computed rollup of whichever weeks fall in that calendar month —
there is no separate monthly storage, so there's no double-counting risk
between a "weekly" and a "monthly" row.

ROAS is calculated here by cross-referencing REAL revenue from
Sales Record (direct_sales), for the same date range being viewed — not
a manually-typed revenue figure. This mirrors the source reference
document exactly: it only ever computes ROAS as one blended, org-wide
figure (total spend vs. total revenue), NOT per-campaign, because
individual sales aren't attributable to individual ad campaigns in this
data model. Building per-campaign ROAS would be inventing false
precision the underlying data doesn't support.

CTR is stored per-row exactly as it appears in the source ads platform
(e.g. Meta Ads Manager), NOT as raw click counts — the marketer will be
copying this number directly off their platform's dashboard each week.
For a BLENDED CTR across multiple weeks/campaigns, raw clicks aren't
stored, so clicks are ESTIMATED as (ctr_pct / 100) * impressions per
row, summed, then re-divided by total impressions. This is an
approximation (small rounding error compounds across many rows) — it's
the best available approach without asking the marketer to also type in
raw click counts every week, and is flagged as "(estimated)" everywhere
it's surfaced (dashboard, PDF).

All aggregation (per-campaign totals, blended CTR/cost-per-conversion,
insights) happens CLIENT-SIDE from the raw entries the summary endpoint
returns — same pattern as Sales Record's own /direct-sales/summary route
— except for the PDF export, which needs the aggregation server-side to
render the document.

Owner/ops_manager only, matching Sales Record and Data Sources' existing
gate — no dedicated "digital marketer" role exists in this codebase yet.

Pattern 53: static routes before parameterised.
Pattern 62: db via Depends(get_supabase).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.routers.auth import get_current_org

logger = logging.getLogger(__name__)
router = APIRouter()

TEAL  = "#0D9488"
GREEN = "#16a34a"
RED   = "#dc2626"


# ---------------------------------------------------------------------------
# RBAC / helpers — self-contained per-router, matching the existing
# convention (growth_config.py and business_activities_report.py each
# define their own copy rather than sharing one).
# ---------------------------------------------------------------------------

def _require_owner_or_ops(org: dict) -> None:
    roles = org.get("roles") or {}
    if isinstance(roles, list):
        roles = roles[0] if roles else {}
    template = (roles.get("template") or "").lower()
    if template not in ("owner", "ops_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Owner or ops_manager access required"},
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _success(data: object, message: str = "OK") -> dict:
    return {"success": True, "data": data, "message": message, "error": None}


def _normalise_to_monday(date_str: str) -> str:
    """Any date within a week snaps to that week's Monday — so an entry
    always represents "the week containing this date", regardless of
    which day the marketer happened to pick in the date field."""
    d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _check_rate_limit(org_id: str) -> bool:
    """Same 10/hr pattern as the other PDF reports, own Redis key so the
    limits don't share a bucket. Fail open (S14) if Redis is unavailable."""
    try:
        import redis as _redis
        url = os.environ.get("REDIS_URL", "")
        if not url:
            return True
        r = _redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
        key = f"digital_campaigns_report_limit:{org_id}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, 3600)
        return count <= 10
    except Exception as exc:
        logger.warning("_check_rate_limit (digital campaigns report): Redis unavailable — allowing: %s", exc)
        return True


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DigitalCampaignEntryCreate(BaseModel):
    campaign_name: str   = Field(..., min_length=1, max_length=200)
    week_start:    str                       # any date within the target week
    daily_budget:  float = Field(0, ge=0)
    spend:         float = Field(0, ge=0)
    conversations: int   = Field(0, ge=0)
    ctr_pct:       float = Field(0, ge=0)
    impressions:   int   = Field(0, ge=0)
    notes:         Optional[str] = None


class DigitalCampaignEntryUpdate(BaseModel):
    campaign_name: Optional[str]   = Field(None, min_length=1, max_length=200)
    daily_budget:  Optional[float] = Field(None, ge=0)
    spend:         Optional[float] = Field(None, ge=0)
    conversations: Optional[int]   = Field(None, ge=0)
    ctr_pct:       Optional[float] = Field(None, ge=0)
    impressions:   Optional[int]   = Field(None, ge=0)
    notes:         Optional[str]   = None


# ---------------------------------------------------------------------------
# CRUD — weekly entries (Pattern 53: static routes before /{entry_id})
# ---------------------------------------------------------------------------

@router.post("/digital-campaigns", status_code=status.HTTP_201_CREATED)
def upsert_campaign_entry(
    payload: DigitalCampaignEntryCreate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Upsert on (org_id, campaign_name, week_start) — re-submitting the
    same campaign+week updates that row rather than creating a
    duplicate, so the marketer can correct a week's figures by just
    re-entering them.
    """
    _require_owner_or_ops(org)
    try:
        week_start = _normalise_to_monday(payload.week_start)
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "INVALID_DATE", "message": f"Invalid week_start: '{payload.week_start}'. Use YYYY-MM-DD."})

    row = {
        "org_id":         org["org_id"],
        "campaign_name":  payload.campaign_name.strip(),
        "week_start":     week_start,
        "daily_budget":   payload.daily_budget,
        "spend":          payload.spend,
        "conversations":  payload.conversations,
        "ctr_pct":        payload.ctr_pct,
        "impressions":    payload.impressions,
        "notes":          payload.notes,
        "created_by":     org["id"],
        "updated_at":     _now_iso(),
    }
    result = (
        db.table("digital_campaign_entries")
        .upsert(row, on_conflict="org_id,campaign_name,week_start")
        .execute()
    )
    return _success(result.data[0] if result.data else row, "Campaign entry saved")


@router.get("/digital-campaigns")
def list_campaign_entries(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    query = (
        db.table("digital_campaign_entries")
        .select("*")
        .eq("org_id", org["org_id"])
    )
    if date_from:
        query = query.gte("week_start", date_from)
    if date_to:
        query = query.lte("week_start", date_to)
    result = query.order("week_start", desc=True).execute()
    return _success({"items": result.data or []})


@router.get("/digital-campaigns/summary")
def get_campaign_summary(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    """
    Raw entries in range, PLUS total revenue from Sales Record
    (direct_sales) over the SAME range, for ROAS. All aggregation
    (per-campaign totals, blended CTR/cost-per-conversion, insights)
    happens client-side — same pattern as Sales Record's own
    /direct-sales/summary route.
    """
    _require_owner_or_ops(org)
    query = (
        db.table("digital_campaign_entries")
        .select("*")
        .eq("org_id", org["org_id"])
    )
    if date_from:
        query = query.gte("week_start", date_from)
    if date_to:
        query = query.lte("week_start", date_to)
    entries = query.order("week_start", desc=False).limit(5000).execute().data or []

    revenue = 0.0
    if date_from and date_to:
        sales_result = (
            db.table("direct_sales")
            .select("amount")
            .eq("org_id", org["org_id"])
            .gte("sale_date", date_from)
            .lte("sale_date", date_to)
            .limit(5000)
            .execute()
        )
        revenue = sum(float(s.get("amount") or 0) for s in (sales_result.data or []))

    return _success({"items": entries, "revenue": revenue})


@router.get("/digital-campaigns/report/download")
def download_digital_campaigns_report(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    org_id = org["org_id"]

    if not _check_rate_limit(org_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "You can download up to 10 reports per hour."},
        )

    now = datetime.now(timezone.utc)
    # Defaults to the trailing 30 days if no range given.
    if not date_from:
        date_from = (now - timedelta(days=30)).date().isoformat()
    if not date_to:
        date_to = now.date().isoformat()

    entries = (
        db.table("digital_campaign_entries")
        .select("*")
        .eq("org_id", org_id)
        .gte("week_start", date_from)
        .lte("week_start", date_to)
        .order("week_start", desc=False)
        .execute()
        .data or []
    )

    sales_result = (
        db.table("direct_sales")
        .select("amount")
        .eq("org_id", org_id)
        .gte("sale_date", date_from)
        .lte("sale_date", date_to)
        .execute()
    )
    revenue = sum(float(s.get("amount") or 0) for s in (sales_result.data or []))

    org_row = db.table("organisations").select("name").eq("id", org_id).maybe_single().execute()
    org_data = org_row.data
    if isinstance(org_data, list):
        org_data = org_data[0] if org_data else {}
    org_name = (org_data or {}).get("name") or "Organisation"

    pdf_bytes = _generate_digital_campaigns_pdf(org_name, date_from, date_to, entries, revenue, now)
    filename = f"Digital_Campaigns_Report_{date_from}_to_{date_to}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/digital-campaigns/{entry_id}")
def update_campaign_entry(
    entry_id: str,
    payload: DigitalCampaignEntryUpdate,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    existing = (
        db.table("digital_campaign_entries")
        .select("id")
        .eq("id", entry_id)
        .eq("org_id", org["org_id"])
        .maybe_single()
        .execute()
    )
    data = existing.data
    if isinstance(data, list):
        data = data[0] if data else None
    if not data:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Campaign entry not found"})

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = _now_iso()
    result = (
        db.table("digital_campaign_entries")
        .update(updates)
        .eq("id", entry_id)
        .eq("org_id", org["org_id"])
        .execute()
    )
    return _success(result.data[0] if result.data else {}, "Campaign entry updated")


@router.delete("/digital-campaigns/{entry_id}", status_code=status.HTTP_200_OK)
def delete_campaign_entry(
    entry_id: str,
    db=Depends(get_supabase),
    org: dict = Depends(get_current_org),
):
    _require_owner_or_ops(org)
    db.table("digital_campaign_entries").delete().eq("id", entry_id).eq("org_id", org["org_id"]).execute()
    return _success(None, "Campaign entry deleted")


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def _generate_digital_campaigns_pdf(
    org_name: str,
    date_from: str,
    date_to: str,
    entries: list,
    revenue: float,
    now: datetime,
) -> bytes:
    from weasyprint import HTML as _HTML

    def _fmt_naira(v: float) -> str:
        return f"₦{v:,.0f}"

    by_campaign: dict = {}
    for e in entries:
        name = e.get("campaign_name") or "Unnamed campaign"
        c = by_campaign.setdefault(name, {
            "daily_budget": 0.0, "spend": 0.0, "conversations": 0,
            "impressions": 0, "est_clicks": 0.0,
        })
        # Representative daily budget: the max seen across weeks for this
        # campaign (budgets are usually stable; max avoids under-reporting
        # if a week was entered with a temporarily lowered budget).
        c["daily_budget"] = max(c["daily_budget"], float(e.get("daily_budget") or 0))
        c["spend"] += float(e.get("spend") or 0)
        c["conversations"] += int(e.get("conversations") or 0)
        impressions = int(e.get("impressions") or 0)
        ctr = float(e.get("ctr_pct") or 0)
        c["impressions"] += impressions
        c["est_clicks"] += impressions * ctr / 100.0

    total_spend         = sum(c["spend"] for c in by_campaign.values())
    total_conversations  = sum(c["conversations"] for c in by_campaign.values())
    total_impressions   = sum(c["impressions"] for c in by_campaign.values())
    total_est_clicks    = sum(c["est_clicks"] for c in by_campaign.values())
    blended_ctr         = (total_est_clicks / total_impressions * 100) if total_impressions else 0.0
    blended_cost_conv   = (total_spend / total_conversations) if total_conversations else 0.0
    roas                = (revenue / total_spend) if total_spend else 0.0

    rows_html = ""
    for name, c in sorted(by_campaign.items(), key=lambda kv: kv[1]["spend"], reverse=True):
        cost_conv = (c["spend"] / c["conversations"]) if c["conversations"] else 0.0
        ctr = (c["est_clicks"] / c["impressions"] * 100) if c["impressions"] else 0.0
        rows_html += f"""
        <tr>
          <td>{name}</td>
          <td style='text-align:right'>{_fmt_naira(c['daily_budget'])}</td>
          <td style='text-align:right'>{_fmt_naira(c['spend'])}</td>
          <td style='text-align:right'>{c['conversations']:,}</td>
          <td style='text-align:right'>{_fmt_naira(cost_conv)}</td>
          <td style='text-align:right'>{ctr:.2f}%</td>
          <td style='text-align:right'>{c['impressions']:,}</td>
        </tr>
        """

    # Simple rule-based insights (no AI/model calls) — same spirit as
    # the source reference document's own callouts.
    ranked = [
        (name, (c["spend"] / c["conversations"]))
        for name, c in by_campaign.items() if c["conversations"] > 0
    ]
    insights = []
    if ranked:
        best = min(ranked, key=lambda x: x[1])
        worst = max(ranked, key=lambda x: x[1])
        insights.append(f"Lowest cost per conversation: <strong>{best[0]}</strong> at {_fmt_naira(best[1])} — a strong candidate for more budget.")
        if worst[0] != best[0]:
            insights.append(f"Highest cost per conversation: <strong>{worst[0]}</strong> at {_fmt_naira(worst[1])} — worth reviewing or pausing.")
    if total_spend > 0:
        if revenue > 0:
            insights.append(f"Blended return on ad spend: <strong>{roas:.1f}x</strong> — ₦{roas:.1f} in revenue for every ₦1 spent (revenue from Sales Record over the same period).")
        else:
            insights.append("No Sales Record revenue found for this period, so ROAS could not be calculated.")

    insights_html = "".join(f"<li style='margin-bottom:4px'>{i}</li>" for i in insights) or "<li>Not enough data yet for insights.</li>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8">
    <style>
      @page {{
        margin: 20mm 15mm;
        @bottom-center {{
          content: "Generated by Opsra  |  Page " counter(page) " of " counter(pages);
          font-size: 9px; color: #6b7280;
        }}
      }}
      body     {{ font-family: Arial, sans-serif; font-size: 10px; color: #111827; margin: 0; }}
      .header  {{ border-bottom: 2px solid {TEAL}; padding-bottom: 8px; margin-bottom: 16px;
                  display: flex; justify-content: space-between; align-items: flex-start; }}
      .header-left h1 {{ margin: 0; font-size: 18px; color: {TEAL}; }}
      .header-left p  {{ margin: 2px 0; font-size: 10px; color: #6b7280; }}
      .header-right   {{ text-align: right; font-size: 10px; color: #6b7280; }}
      .kpi-grid {{ display: flex; gap: 10px; margin-bottom: 18px; }}
      .kpi      {{ flex: 1; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; }}
      .kpi-label {{ font-size: 8px; color: #6b7280; text-transform: uppercase; margin: 0 0 4px; }}
      .kpi-value {{ font-size: 13px; font-weight: 700; color: #111827; margin: 0; }}
      h2       {{ font-size: 13px; color: {TEAL}; border-bottom: 1px solid #e5e7eb;
                  padding-bottom: 4px; margin-bottom: 8px; }}
      table    {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
      thead tr {{ background: {TEAL}; color: white; }}
      th       {{ padding: 6px 8px; text-align: left; font-size: 9px; }}
      td       {{ padding: 5px 8px; font-size: 9px; border-bottom: 1px solid #f3f4f6; }}
      tr:nth-child(even) td {{ background: #f9fafb; }}
      ul       {{ font-size: 9px; padding-left: 16px; margin: 0; }}
    </style>
    </head>
    <body>
      <div class='header'>
        <div class='header-left'>
          <h1>Opsra</h1>
          <p>{org_name}</p>
          <p>Digital Campaigns Report — {date_from} to {date_to}</p>
        </div>
        <div class='header-right'>Generated: {now.date().isoformat()}</div>
      </div>

      <div class='kpi-grid'>
        <div class='kpi'><p class='kpi-label'>Total Spend</p><p class='kpi-value'>{_fmt_naira(total_spend)}</p></div>
        <div class='kpi'><p class='kpi-label'>Conversations</p><p class='kpi-value'>{total_conversations:,}</p></div>
        <div class='kpi'><p class='kpi-label'>Cost/Conv (blended)</p><p class='kpi-value'>{_fmt_naira(blended_cost_conv)}</p></div>
        <div class='kpi'><p class='kpi-label'>CTR (blended, est.)</p><p class='kpi-value'>{blended_ctr:.2f}%</p></div>
        <div class='kpi'><p class='kpi-label'>ROAS</p><p class='kpi-value'>{roas:.1f}x</p></div>
      </div>

      <h2>Per-Campaign Breakdown</h2>
      <table>
        <thead><tr>
          <th>Campaign</th><th style='text-align:right'>Daily Budget</th>
          <th style='text-align:right'>Spent</th><th style='text-align:right'>Conversations</th>
          <th style='text-align:right'>Cost/Conv</th><th style='text-align:right'>CTR (est.)</th>
          <th style='text-align:right'>Impressions</th>
        </tr></thead>
        <tbody>{rows_html or "<tr><td colspan='7'>No campaign data for this period.</td></tr>"}</tbody>
      </table>

      <h2>Insights</h2>
      <ul>{insights_html}</ul>
    </body>
    </html>
    """
    return _HTML(string=html).write_pdf()
